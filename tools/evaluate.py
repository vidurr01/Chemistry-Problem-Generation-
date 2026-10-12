"""
evaluate.py — the paper report: what the pipeline accepted, what it rejected and why.

Reads outputs/generated_questions_<subject>.json (accepted questions) and
outputs/generated_questions_<subject>_attempts.jsonl (every event of every run).

    python tools/evaluate.py                       # all subjects with output
    python tools/evaluate.py --subject physical
    python tools/evaluate.py --json report.json    # also write the numbers as JSON

Sections: acceptance (chains tried, how each ended), council (answers matching the
engine vs counted as solved, per member), refinement rounds, knowledge tags (recall vs
closed book), trap-type spread, verifier labels, hint outcomes, spend. Questions saved
by the pre-engine pipeline are counted but left out of the engine statistics.
"""

import argparse
import json
import os
import statistics
import sys
from collections import Counter

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from subject_config import SUBJECT_CONFIGS  # noqa: E402


def _load(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _events(path):
    out = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    return out


def pct(a, b):
    return f"{(100.0 * a / b):.0f}%" if b else "—"


def report(subject: str) -> dict:
    cfg = SUBJECT_CONFIGS[subject]
    records = _load(cfg["output_file"], [])
    events = _events(os.path.splitext(cfg["output_file"])[0] + "_attempts.jsonl")
    new = [r for r in records if r.get("generation_mode") == "engine_council"]
    legacy = len(records) - len(new)
    ev = [e for e in events if "event" in e]

    ends = Counter(e["event"] for e in ev)
    judged = [e for e in ev if e["event"] in ("accept", "too_easy", "reword", "drop")]
    members = Counter()
    solved_by_member = Counter()
    for r in new:
        for m in r.get("council", []):
            members[m["name"]] += 1
            solved_by_member[m["name"]] += bool(m.get("counts_as_solved"))
    labels = Counter(m.get("failure_type") or m.get("verdict")
                     for r in new for m in r.get("council", []) if not m.get("counts_as_solved"))
    hints = Counter((h["hint"], h["solved"]) for r in new for h in r.get("hint_tests", []))
    traps = Counter(t for r in new for t in r.get("tags", {}).get("trap_types", []))
    rounds = Counter(r.get("rounds", 0) for r in new)
    tags = Counter(r.get("tags", {}).get("knowledge") for r in new)
    spend = [r.get("spend", {}).get("total_cost_usd") for r in new if r.get("spend")]
    by_round = {}
    for e in judged:
        rd = e.get("round", 0)
        b = by_round.setdefault(rd, {"judged": 0, "correct": 0, "members": 0})
        b["judged"] += 1
        for m in e.get("council") or []:
            b["members"] += 1
            b["correct"] += bool(m.get("answer_matches"))

    data = {
        "subject": subject, "accepted": len(new), "legacy_records": legacy,
        "run_events": dict(ends),
        "council_mean_correct": statistics.mean([r["council_n_correct"] for r in new]) if new else None,
        "council_mean_solved": statistics.mean([r["council_n_solved"] for r in new]) if new else None,
        "solved_vs_correct": dict(Counter((r["council_n_correct"], r["council_n_solved"]) for r in new)),
        "member_solve_rate": {k: solved_by_member[k] / members[k] for k in members},
        "rounds_to_accept": dict(rounds),
        "answers_matching_by_round": {rd: b["correct"] / b["members"] if b["members"] else None
                                      for rd, b in sorted(by_round.items())},
        "knowledge_tags": dict(tags),
        "trap_types": dict(traps.most_common()),
        "failure_labels": dict(labels),
        "hint_outcomes": {f"{h} {'solved' if s else 'not solved'}": n for (h, s), n in hints.items()},
        "spend_total_usd": round(sum(x for x in spend if x), 4),
        "spend_per_accepted_usd": round(statistics.mean([x for x in spend if x]), 4) if any(spend) else None,
    }

    print(f"\n================ {subject.upper()} ================")
    print(f"Accepted (engine pipeline): {len(new)}   older-format records: {legacy}")
    if ends:
        print("Run events:", ", ".join(f"{k} {v}" for k, v in ends.most_common()))
    if new:
        print(f"Council per accepted question: mean {data['council_mean_correct']:.2f}/3 answers match the engine, "
              f"{data['council_mean_solved']:.2f}/3 counted as solved")
        print("  (correct, solved) pairs:", data["solved_vs_correct"])
        print("  solve rate per member:", {k: f"{v:.0%}" for k, v in data["member_solve_rate"].items()})
        print("Refinement rounds before acceptance:", dict(sorted(rounds.items())))
        print("Knowledge tags:", dict(tags))
        top = traps.most_common(1)
        print(f"Trap types ({len(traps)} kinds):", dict(traps.most_common(8)),
              f"— largest share {pct(top[0][1], sum(traps.values()))}" if top else "")
        print("Why members failed:", dict(labels))
        print("Hint outcomes:", data["hint_outcomes"])
    if by_round:
        print("Council answers matching the engine, by round:",
              {rd: (f"{v:.0%}" if v is not None else "—") for rd, v in data["answers_matching_by_round"].items()})
    if spend:
        print(f"Spend: ${data['spend_total_usd']} total, ${data['spend_per_accepted_usd']} per accepted question")
    return data


def main():
    ap = argparse.ArgumentParser(description="Report on generated questions.")
    ap.add_argument("--subject", choices=sorted(SUBJECT_CONFIGS), default=None)
    ap.add_argument("--json", default=None, help="also write the report to this JSON file")
    args = ap.parse_args()
    subjects = [args.subject] if args.subject else [s for s in SUBJECT_CONFIGS
                                                    if os.path.exists(SUBJECT_CONFIGS[s]["output_file"])]
    if not subjects:
        print("No outputs yet. Run: python run_groundup_final.py --subject physical")
        return 1
    out = {s: report(s) for s in subjects}
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
