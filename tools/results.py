"""
results.py — manage the final question sets in results/.

outputs/generated_questions_<subject>.json is the raw run output: every question the
pipeline accepts is appended there. results/generated_questions_<subject>_final.json is
the review set: the same questions, each with slots for a human evaluation.

Commands
--------
    python tools/results.py promote [--subject S] [--dry-run]
        Copy accepted questions from outputs/ into results/ with empty human-eval
        slots. Questions already in results/ (and their scores) are never touched;
        questions listed in results/rejected.json are skipped.
        run_groundup_final.py calls this automatically after each acceptance.

    python tools/results.py pending [--subject S]
        List questions in results/ that have no human score yet.

    python tools/results.py score <question_id> <0-3> --rationale "..."
        Record a human evaluation. The level label is derived from the score:
          0 Wrong · 1 JEE Mains · 2 between JEE Mains and JEE Advanced · 3 JEE Advanced

    python tools/results.py reject <question_id> --reason "..."
        Remove a question from results/ and record it in results/rejected.json so
        `promote` never re-adds it.

    python tools/results.py queue [--subject S] [--reason R]
        List the review queues (engine_unknown, gate_unreadable, engine_wrong,
        objection_unresolved): items the pipeline could not settle in code.

    python tools/results.py dismiss <reason> <subject> <item_id> --note "..."
        Remove one queue item after reviewing it (the note is printed for the log).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from subject_config import SUBJECT_CONFIGS  # noqa: E402

RESULTS_DIR = os.path.join(_ROOT, "results")
REJECTED_FILE = os.path.join(RESULTS_DIR, "rejected.json")
SUBJECTS = tuple(SUBJECT_CONFIGS)

HUMAN_EVAL_LEVELS = {
    0: "Wrong",
    1: "JEE Mains",
    2: "between JEE Mains and JEE Advanced",
    3: "JEE Advanced",
}


def results_path(subject):
    return os.path.join(RESULTS_DIR, f"generated_questions_{subject}_final.json")


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    """Write via a temp file so an interrupted write never corrupts the set."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def _set_human_eval(record, score, level, rationale):
    # Stored twice (flat + nested) to match the existing result files.
    record["human_eval_score"] = score
    record["human_eval_level"] = level
    record["human_eval_rationale"] = rationale
    record["human_eval"] = {"score": score, "level": level, "rationale": rationale}


def _find(question_id):
    """Return (subject, records, index) for a question in results/, or None."""
    for subject in SUBJECTS:
        records = _load(results_path(subject), [])
        for i, r in enumerate(records):
            if r.get("question_id") == question_id:
                return subject, records, i
    return None


def promote(subjects=SUBJECTS, dry_run=False, quiet=False):
    """Copy new accepted questions from outputs/ into results/. Returns count added."""
    rejected = _load(REJECTED_FILE, {})
    total = 0
    for subject in subjects:
        raw = _load(SUBJECT_CONFIGS[subject]["output_file"], [])
        final = _load(results_path(subject), [])
        have = {r.get("question_id") for r in final}
        new = [r for r in raw
               if r.get("question_id") not in have and r.get("question_id") not in rejected]
        for r in new:
            record = dict(r)
            _set_human_eval(record, None, None, None)
            final.append(record)
            if not quiet:
                print(f"  {'would add' if dry_run else 'added'} {subject}: {r.get('question_id')}")
        if new and not dry_run:
            _save(results_path(subject), final)
        total += len(new)
    if not quiet:
        print(f"{total} question(s) {'would be ' if dry_run else ''}promoted to results/.")
    return total


def pending(subjects=SUBJECTS):
    n = 0
    for subject in subjects:
        for r in _load(results_path(subject), []):
            if r.get("human_eval_score") is None:
                n += 1
                q = " ".join(str(r.get("question", "")).split())
                print(f"  {subject:<10} {r.get('question_id')}  {q[:90]}")
    print(f"{n} question(s) awaiting human evaluation.")


def score(question_id, value, rationale):
    found = _find(question_id)
    if not found:
        sys.exit(f"ERROR: {question_id} not found in results/. Run `promote` first?")
    subject, records, i = found
    _set_human_eval(records[i], value, HUMAN_EVAL_LEVELS[value], rationale)
    _save(results_path(subject), records)
    print(f"Scored {question_id} ({subject}): {value} = {HUMAN_EVAL_LEVELS[value]}")


def reject(question_id, reason):
    rejected = _load(REJECTED_FILE, {})
    found = _find(question_id)
    subject = None
    if found:
        subject, records, i = found
        del records[i]
        _save(results_path(subject), records)
    rejected[question_id] = {
        "subject": subject, "reason": reason,
        "rejected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _save(REJECTED_FILE, rejected)
    print(f"Rejected {question_id}" + (f" (removed from {subject} results)" if found else ""))


def queue_list(subjects, reasons):
    from core.pipeline import queues
    n = 0
    for reason in reasons:
        for subject in subjects:
            for item in queues.load(reason, subject):
                n += 1
                what = item.get("stem") or item.get("error") or item.get("objection") or ""
                print(f"  {reason:<21} {subject:<10} {item['id']}  {' '.join(str(what).split())[:90]}")
    print(f"{n} item(s) in the review queues.")


def queue_dismiss(reason, subject, item_id, note):
    from core.pipeline import queues
    if not queues.remove(reason, subject, item_id):
        sys.exit(f"ERROR: {item_id} not found in queue {reason} ({subject}).")
    print(f"Dismissed {item_id} from {reason} ({subject}): {note}")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="Manage the final question sets in results/.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("promote", help="copy new accepted questions from outputs/ into results/")
    p.add_argument("--subject", choices=SUBJECTS)
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("pending", help="list questions without a human score")
    p.add_argument("--subject", choices=SUBJECTS)

    p = sub.add_parser("score", help="record a human evaluation")
    p.add_argument("question_id")
    p.add_argument("value", type=int, choices=sorted(HUMAN_EVAL_LEVELS))
    p.add_argument("--rationale", required=True)

    p = sub.add_parser("reject", help="remove a question and never re-promote it")
    p.add_argument("question_id")
    p.add_argument("--reason", required=True)

    from core.pipeline.queues import REASONS
    p = sub.add_parser("queue", help="list the review queues")
    p.add_argument("--subject", choices=SUBJECTS)
    p.add_argument("--reason", choices=REASONS)

    p = sub.add_parser("dismiss", help="remove one reviewed item from a queue")
    p.add_argument("reason", choices=REASONS)
    p.add_argument("subject", choices=SUBJECTS)
    p.add_argument("item_id")
    p.add_argument("--note", required=True)

    args = ap.parse_args()
    subjects = (args.subject,) if getattr(args, "subject", None) else SUBJECTS
    if args.cmd == "promote":
        promote(subjects, dry_run=args.dry_run)
    elif args.cmd == "pending":
        pending(subjects)
    elif args.cmd == "score":
        score(args.question_id, args.value, args.rationale)
    elif args.cmd == "reject":
        reject(args.question_id, args.reason)
    elif args.cmd == "queue":
        queue_list(subjects, (args.reason,) if args.reason else REASONS)
    elif args.cmd == "dismiss":
        queue_dismiss(args.reason, args.subject, args.item_id, args.note)


if __name__ == "__main__":
    main()
