"""
generate_questions.py — batch driver for the ground-up question generator.

This is a thin wrapper around `run_groundup_final.py`. That script produces at
most ONE accepted question per invocation and appends it to
`generated_questions_<subject>.json`. This driver runs it repeatedly so you can
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

Output
------
Questions are appended to (created if absent):
    generated_questions_organic.json
    generated_questions_inorganic.json
    generated_questions_physical.json
Every attempt (accepted or not) is also logged to
    generated_questions_<subject>_attempts.jsonl
by the underlying script.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ENTRYPOINT = os.path.join(HERE, "run_groundup_final.py")

# Output file per subject, matching subject_config.py "output_file" values.
OUTPUT_FILES = {
    "organic":   os.path.join(HERE, "generated_questions_organic.json"),
    "inorganic": os.path.join(HERE, "generated_questions_inorganic.json"),
    "physical":  os.path.join(HERE, "generated_questions_physical.json"),
}

SUBJECTS = ("organic", "inorganic", "physical")


def stamp(msg):
    """Print a timestamped, flushed line so batch transitions are always visible,
    even while the child subprocess is quiet (loading, waiting on the API)."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_env_key():
    """Mirror the .env parsing in run_groundup_final.py so we can fail early
    with a clear message instead of after spinning up a subprocess."""
    env_path = os.path.join(HERE, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
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
    try:
        result = subprocess.run(cmd, cwd=HERE, env=env, timeout=child_timeout)
        rc = result.returncode
    except subprocess.TimeoutExpired:
        stamp(f"[warn] {subject}: run exceeded {child_timeout}s, killed. Continuing.")
        rc = None
    dt = time.time() - t0

    after = count_questions(out_file)
    produced = after > before
    stamp(f"{subject}: run finished in {dt:.0f}s "
          f"(exit={rc}, question saved: {'yes' if produced else 'no'})")
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
        ok = generate_one(subject, chapter, python_exe, child_timeout)

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

    p.add_argument("--organic-chapter", default=None, help="chapter override for organic")
    p.add_argument("--inorganic-chapter", default=None, help="chapter override for inorganic")
    p.add_argument("--physical-chapter", default=None, help="chapter override for physical")

    p.add_argument("--order", default="organic,inorganic,physical",
                   help="comma-separated order in which subjects are generated")
    p.add_argument("--max-consecutive-failures", type=int, default=6,
                   help="give up on a subject after this many runs in a row accept nothing")
    p.add_argument("--child-timeout", type=int, default=1800,
                   help="seconds before a single hung question run is killed and retried")
    p.add_argument("--python", default=sys.executable,
                   help="python executable used to run run_groundup_final.py")
    return p.parse_args()


def main():
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
    for subject in order:
        results[subject] = generate_subject(
            subject, targets[subject], chapters[subject],
            args.python, args.max_consecutive_failures, args.child_timeout,
        )

    elapsed = time.time() - start
    print("\n" + "=" * 70)
    print(" SUMMARY")
    print("=" * 70)
    any_short = False
    for subject in SUBJECTS:
        want = targets[subject]
        if want <= 0:
            continue
        got = results.get(subject, 0)
        flag = "" if got >= want else "  <-- short"
        if got < want:
            any_short = True
        print(f"  {subject:<10} {got}/{want}   -> {OUTPUT_FILES[subject]}{flag}")
    print(f"\n  elapsed: {elapsed/60:.1f} min")
    return 1 if any_short else 0


if __name__ == "__main__":
    sys.exit(main())
