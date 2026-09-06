"""
evaluate.py — audit pipeline output (generated_questions*.json).

Reads the current record schema produced by run_graph*.py / run_groundup*.py:

  question_id, seed_id, generation_mode, subject, chapter, archetype,
  archetype_code, question, solution, operators_applied, chain_description,
  loops_run, strong_score, weak_score, verifier_verdict, verifier_difficulty,
  meta_tags, attempt_history, generated_at

Usage:
    python -X utf8 tools/evaluate.py [generated_questions_<subject>.json]

Default input is generated_questions.json (the legacy archive output path).
"""

import json
import os
import statistics
import sys

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def mean(xs):
    return statistics.mean(xs) if xs else 0.0


def pct(x, total):
    return (x / total * 100.0) if total else 0.0


def evaluate_pipeline(output_file: str = "generated_questions.json"):
    path = output_file
    if not os.path.isabs(path):
        path = os.path.join(TARGET, path)
    if not os.path.exists(path):
        print(f"ERROR: {path} not found.")
        print("Run an entrypoint first (run_graph_final.py / run_groundup_final.py).")
        sys.exit(1)

    print(f"Loading results from {path}...")
    with open(path, "r", encoding="utf-8") as f:
        results = json.load(f)

    total = len(results)
    if total == 0:
        print("No results to evaluate.")
        return

    strong_scores = [r["strong_score"] for r in results]
    weak_scores   = [r["weak_score"]   for r in results]
    loops         = [r.get("loops_run", 1) for r in results]

    strong_pct = [s for s in strong_scores if s >= 85]
    weak_pct   = [w for w in weak_scores   if w <= 60]

    difficulty_hist = {}
    for r in results:
        d = r.get("verifier_difficulty", "?")
        difficulty_hist[d] = difficulty_hist.get(d, 0) + 1

    subjects = {}
    for r in results:
        s = r.get("subject", "organic")
        subjects[s] = subjects.get(s, 0) + 1

    archetypes = {}
    for r in results:
        a = r.get("archetype_code", "?")
        archetypes[a] = archetypes.get(a, 0) + 1

    meta_tag_totals = {}
    for r in results:
        for tag, val in (r.get("meta_tags") or {}).items():
            vals = meta_tag_totals.setdefault(tag, [])
            try:
                vals.append(int(val))
            except (TypeError, ValueError):
                pass

    print("\n================ EVALUATION REPORT ================\n")

    print(f"--- Records ---")
    print(f"  Total accepted questions: {total}")
    print(f"  Per subject: {subjects}")

    print("\n--- Acceptance Gates (accepted records should already pass) ---")
    print(f"  Mean weak score:   {mean(weak_scores):.1f}%   (gated ≤60%: {len(weak_pct)}/{total})")
    print(f"  Mean strong score: {mean(strong_scores):.1f}%   (gated ≥85%: {len(strong_pct)}/{total})")
    print(f"  Verifier PASS: {[r.get('verifier_verdict', '?') for r in results].count('PASS')}/{total}")

    print("\n--- Efficiency ---")
    print(f"  Mean loops to accept: {mean(loops):.2f}  (max {max(loops)})")

    print("\n--- Difficulty Labels (verifier_rating) ---")
    for d in sorted(difficulty_hist, key=lambda k: -difficulty_hist[k]):
        print(f"  {d:14s}: {difficulty_hist[d]} ({pct(difficulty_hist[d], total):.0f}%)")

    print("\n--- Archetype Distribution ---")
    for a in sorted(archetypes):
        print(f"  Archetype {a}: {archetypes[a]} ({pct(archetypes[a], total):.0f}%)")

    if meta_tag_totals:
        print("\n--- Meta-tag Means (1-5 scale) ---")
        for tag in sorted(meta_tag_totals):
            print(f"  {tag:28s}: {mean(meta_tag_totals[tag]):.2f}  (n={len(meta_tag_totals[tag])})")

    print("\n===================================================\n")


def main():
    if len(sys.argv) > 1:
        evaluate_pipeline(sys.argv[1])
    else:
        evaluate_pipeline()


if __name__ == "__main__":
    main()