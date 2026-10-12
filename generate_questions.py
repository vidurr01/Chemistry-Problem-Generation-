"""
generate_questions.py — batch driver for the ground-up question generator.

This is a thin wrapper around `run_groundup_final.py`. That script produces at
most ONE accepted question per invocation and appends it to
`outputs/generated_questions_<subject>.json`. This driver runs it repeatedly so you can
ask for a set number of physical, inorganic, and organic questions in one call.

Each subject's questions are produced in separate fresh subprocesses. That keeps
per-question state (blackboard, coverage, verifier dedup) isolated exactly as a
manual run would, and means one crashed attempt cannot take the batch down.

Usage
-----
    python generate_questions.py --organic 5 --inorganic 3 --physical 2

    # override the chapter used for a subject (must match a chapter in that
    # subject's concept book; see subject_config.py for the defaults)
    python generate_questions.py --physical 4 --physical-chapter "Chemical Kinetics"

    # keep going even if a subject produces no accepted question for a while
    python generate_questions.py --organic 10 --max-consecutive-failures 5

Launch it WITHOUT shell redirection to the log — the driver writes that log
itself, in APPEND mode, so relaunching never overwrites an earlier run. Each run
starts with a "RUN <timestamp> :: <args>" separator. Use --log to change the path
or --log "" to disable. Console output still streams live as well.

Output
------
Questions are appended to (created if absent):
    outputs/generated_questions_organic.json
    outputs/generated_questions_inorganic.json
    outputs/generated_questions_physical.json
Every attempt (accepted or not) is also logged to
    outputs/generated_questions_<subject>_attempts.jsonl
by the underlying script, and the full run console is appended to
    outputs/batch_run.log
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

# The child prints box-drawing / arrow characters; make sure our console can too
# (Windows consoles default to cp1252, which raises UnicodeEncodeError on them).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT = os.path.join(HERE, "run_groundup_final.py")

from subject_config import OUTPUT_DIR, SUBJECT_CONFIGS
from core.llm import load_env

SUBJECTS = ("organic", "inorganic", "physical")

# Exit code run_groundup_final.py returns for a setup problem with this subject (missing
# concept book / graph, or a --chapter with no chains): retrying cannot help, so the
# driver moves on to the next subject. (Its EXIT_CONFIG_ERROR.)
CONFIG_ERROR_EXIT_CODE = 2

# Exit codes on which run_groundup_final.py stops for a reason that is not the question's
# (its EXIT_COUNCIL_FAILED / EXIT_SAVE_FAILED). The whole batch stops then: the next run
# would hit the same failure. The question is parked and rechecked on the next run.
STOP_EXIT_CODES = {
    3: "a council member failed (check OpenRouter / the API key)",
    4: "an accepted question could not be saved (check the output file / disk)",
}


class SubjectSkip(Exception):
    """A run hit a configuration error for this subject; move on to the next subject."""


class BatchStop(Exception):
    """A run stopped on a systemic failure; carries the subject's accepted count so far."""
    def __init__(self, reason, accepted=0):
        super().__init__(reason)
        self.reason = reason
        self.accepted = accepted

# Output file per subject, read from subject_config.py so the two never drift.
OUTPUT_FILES = {s: SUBJECT_CONFIGS[s]["output_file"] for s in SUBJECTS}

# Append-only run log. Opened in main(); every run adds a separator header and its
# lines to the end, so relaunching never clobbers an earlier run's output. The
# child subprocess's stdout is tee'd here line by line as well (see generate_one).
_LOG = None


def emit(text, end="\n"):
    """Write to the real console AND append to the run log. Never let an encoding
    or I/O hiccup on one sink kill the run."""
    for sink in (sys.stdout, _LOG):
        if sink is None:
            continue
        try:
            sink.write(text + end)
            sink.flush()
        except Exception:
            pass


def stamp(msg):
    """Print a timestamped, flushed line so batch transitions are always visible,
    even while the child subprocess is quiet (loading, waiting on the API)."""
    emit(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_env_key():
    """Read .env the same way run_groundup_final.py does, so a missing key fails
    here instead of after spinning up a subprocess."""
    load_env()
    return os.environ.get("OPENROUTER_KEY", "")


def count_questions(path):
    """Number of accepted questions currently in a subject output file."""
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except (json.JSONDecodeError, OSError):
        return 0


def generate_one(subject, chapter, python_exe, child_timeout):
    """Run the entrypoint once. Returns True if it appended a new question."""
    out_file = OUTPUT_FILES[subject]
    before = count_questions(out_file)

    cmd = [python_exe, "-X", "utf8", ENTRYPOINT, "--subject", subject]
    if chapter:
        cmd += ["--chapter", chapter]

    # PYTHONUNBUFFERED so the child's stage-by-stage prints reach the log/console
    # live instead of sitting in a block buffer until the process exits.
    env = dict(os.environ, PYTHONUNBUFFERED="1")

    # Stream the child's output straight through so progress is visible. A single
    # question that hangs (stalled HTTP call, rate-limit backoff storm) is killed
    # after child_timeout and counted as a non-acceptance, so the batch continues.
    stamp(f"{subject}: launching run_groundup_final.py (timeout {child_timeout}s)")
    t0 = time.time()
    rc = None
    try:
        # Capture the child's output so we can tee it to both the console and the
        # append log, line by line. PYTHONUNBUFFERED on the child keeps it live.
        proc = subprocess.Popen(cmd, cwd=HERE, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1,
                                encoding="utf-8", errors="replace")
        # Read the output on a separate thread: iterating proc.stdout here would block
        # until the child exits, so the timeout below could never fire on a hung run.
        def pump():
            for line in proc.stdout:
                emit(line.rstrip("\n"))
        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            rc = proc.wait(timeout=child_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            stamp(f"[warn] {subject}: run exceeded {child_timeout}s, killed. Continuing.")
        reader.join(timeout=5)   # the pipe closes when the child exits; drain what is left
    except Exception as e:
        stamp(f"[warn] {subject}: run failed to launch: {e}")
    dt = time.time() - t0

    after = count_questions(out_file)
    produced = after > before
    stamp(f"{subject}: run finished in {dt:.0f}s "
          f"(exit={rc}, question saved: {'yes' if produced else 'no'})")
    if rc in STOP_EXIT_CODES:
        stamp(f"[stop] {subject}: {STOP_EXIT_CODES[rc]}; the question is parked for the next run. "
              f"Stopping the batch.")
        raise BatchStop(STOP_EXIT_CODES[rc])
    if rc == CONFIG_ERROR_EXIT_CODE:
        stamp(f"[skip] {subject}: configuration error (see the run output above); "
              f"retrying cannot help, moving on to the next subject.")
        raise SubjectSkip()
    if rc not in (0, None) and not produced:
        stamp(f"[warn] {subject}: exit code {rc} and no question was saved.")
    return produced


def generate_subject(subject, target, chapter, python_exe, max_consecutive_failures, child_timeout):
    """Loop until `target` new questions are accepted for one subject."""
    if target <= 0:
        return 0

    print("\n" + "=" * 70, flush=True)
    stamp(f"{subject.upper()}: requesting {target} question(s)"
          + (f"  (chapter: {chapter})" if chapter else ""))
    print("=" * 70, flush=True)

    accepted = 0
    consecutive_failures = 0
    attempt = 0

    while accepted < target:
        attempt += 1
        stamp(f"--- {subject} | attempt {attempt} | accepted {accepted}/{target} ---")
        try:
            ok = generate_one(subject, chapter, python_exe, child_timeout)
        except BatchStop as stop:
            stop.accepted = accepted
            raise
        except SubjectSkip:
            break

        if ok:
            accepted += 1
            consecutive_failures = 0
            stamp(f"[ok] {subject}: {accepted}/{target} accepted.")
        else:
            consecutive_failures += 1
            stamp(f"[no accept] {subject}: {consecutive_failures} consecutive failure(s).")
            if consecutive_failures >= max_consecutive_failures:
                stamp(f"[stop] {subject}: hit {max_consecutive_failures} consecutive "
                      f"failures, moving on with {accepted}/{target}.")
                break
            time.sleep(2)  # small breather before retrying

    return accepted


def parse_args():
    p = argparse.ArgumentParser(
        description="Batch-generate JEE Advanced chemistry questions across subjects.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--organic", type=int, default=0, help="number of organic questions to generate")
    p.add_argument("--inorganic", type=int, default=0, help="number of inorganic questions to generate")
    p.add_argument("--physical", type=int, default=0, help="number of physical questions to generate")

    p.add_argument("--organic-chapter", default=None,
                   help="fix organic to one chapter (default: each run picks a chapter by coverage)")
    p.add_argument("--inorganic-chapter", default=None,
                   help="fix inorganic to one chapter (default: each run picks a chapter by coverage)")
    p.add_argument("--physical-chapter", default=None,
                   help="fix physical to one chapter (default: each run picks a chapter by coverage)")

    p.add_argument("--order", default="organic,inorganic,physical",
                   help="comma-separated order in which subjects are generated")
    p.add_argument("--max-consecutive-failures", type=int, default=6,
                   help="give up on a subject after this many runs in a row accept nothing")
    p.add_argument("--child-timeout", type=int, default=1800,
                   help="seconds before a single hung question run is killed and retried")
    p.add_argument("--python", default=sys.executable,
                   help="python executable used to run run_groundup_final.py")
    p.add_argument("--log", default=os.path.join(OUTPUT_DIR, "batch_run.log"),
                   help="run log, APPENDED to (never overwritten). Empty string disables.")
    return p.parse_args()


def main():
    global _LOG
    args = parse_args()

    targets = {
        "organic":   args.organic,
        "inorganic": args.inorganic,
        "physical":  args.physical,
    }
    chapters = {
        "organic":   args.organic_chapter,
        "inorganic": args.inorganic_chapter,
        "physical":  args.physical_chapter,
    }

    if sum(targets.values()) <= 0:
        print("Nothing to do. Pass at least one of --organic/--inorganic/--physical with a positive count.")
        print("Example:  python generate_questions.py --organic 5 --inorganic 3 --physical 2")
        return 1

    if not os.path.exists(ENTRYPOINT):
        print(f"ERROR: entrypoint not found: {ENTRYPOINT}")
        return 1

    key = load_env_key()
    if not key or "your-openrouter-key-here" in key:
        print("ERROR: OPENROUTER_KEY is not set.")
        print("  Put your key in a .env file next to this script:  OPENROUTER_KEY=sk-or-...")
        return 1

    if args.log:
        log_path = args.log if os.path.isabs(args.log) else os.path.join(HERE, args.log)
        _LOG = open(log_path, "a", encoding="utf-8")
        _LOG.write("\n\n" + "=" * 78 + "\n")
        _LOG.write(f"RUN {datetime.now().isoformat(timespec='seconds')}  ::  "
                   f"{' '.join(sys.argv[1:])}\n")
        _LOG.write("=" * 78 + "\n")
        _LOG.flush()

    order = [s.strip() for s in args.order.split(",") if s.strip()]
    for s in order:
        if s not in SUBJECTS:
            print(f"ERROR: unknown subject in --order: {s!r} (expected any of {SUBJECTS})")
            return 1
    # Append any subject missing from --order so a typo cannot silently drop work.
    for s in SUBJECTS:
        if s not in order:
            order.append(s)

    start = time.time()
    results = {}
    stopped = None
    for subject in order:
        try:
            results[subject] = generate_subject(
                subject, targets[subject], chapters[subject],
                args.python, args.max_consecutive_failures, args.child_timeout,
            )
        except BatchStop as stop:
            results[subject] = stop.accepted
            stopped = stop.reason
            break

    elapsed = time.time() - start
    emit("\n" + "=" * 70)
    emit(" SUMMARY")
    emit("=" * 70)
    any_short = False
    for subject in SUBJECTS:
        want = targets[subject]
        if want <= 0:
            continue
        got = results.get(subject, 0)
        flag = "" if got >= want else "  <-- short"
        if got < want:
            any_short = True
        emit(f"  {subject:<10} {got}/{want}   -> {OUTPUT_FILES[subject]}{flag}")
    emit(f"\n  elapsed: {elapsed/60:.1f} min")
    if stopped:
        emit(f"  batch STOPPED early: {stopped} (see the log above).")
    if _LOG is not None:
        _LOG.close()
    return 1 if (any_short or stopped) else 0


if __name__ == "__main__":
    sys.exit(main())
