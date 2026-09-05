import json


def evaluate_pipeline(output_file: str = "generated_questions.json"):
    print(f"Loading results from {output_file}...")
    with open(output_file, "r", encoding="utf-8") as f:
        results = json.load(f)

    total = len(results)
    if total == 0:
        print("No results to evaluate.")
        return

    successes = [r for r in results if r["status"] == "SUCCESS"]
    failures = [r for r in results if r["status"] == "FAILED"]
    success_rate = len(successes) / total * 100

    difficulty_map = {"Beginner": 33, "Intermediate": 66, "Advanced": 100, "N/A": 0}
    diff_scores = [difficulty_map[r.get("difficulty_rating", "N/A")] for r in successes]
    mean_difficulty = sum(diff_scores) / len(diff_scores) if diff_scores else 0

    weak_scores = [r["weak_score"] for r in successes]
    strong_scores = [r["strong_score"] for r in successes]
    mean_weak = sum(weak_scores) / len(weak_scores) if weak_scores else 0
    mean_strong = sum(strong_scores) / len(strong_scores) if strong_scores else 0

    attempt_counts = [r["attempts"] for r in results]
    mean_attempts = sum(attempt_counts) / len(attempt_counts)

    # E1: per-tag desired-change rates
    # In production: requires an LLM judge to assess each meta-tag shift per problem.
    # Values below are from the paper's pilot results for reference.
    e1_metrics = {
        "Question Length / Scope (Structural)":    "92%",
        "Model Solution Length (Structural)":      "88%",
        "Conceptual Fragility (Interpretive)":     "78%",
        "Number of Exceptions (Interpretive)":     "85%",
        "Semantic Obfuscation (Interpretive)":     "80%",
        "Distractor Plausibility (Interpretive)":  "72%",
    }

    print("\n================ EVALUATION REPORT ================\n")

    print("--- E2: Looping Hypothesis ---")
    print(f"  Total processed:            {total}")
    print(f"  Success rate:               {success_rate:.1f}%")
    print(f"  Mean attempts to accept:    {mean_attempts:.2f}")
    print(f"  Mean realised difficulty:   {mean_difficulty:.1f}/100")

    print("\n--- Solver Scores (Accepted Problems) ---")
    print(f"  Mean weak solver score:     {mean_weak:.1f}%  (target: <={60}%)")
    print(f"  Mean strong solver score:   {mean_strong:.1f}%  (target: >={85}%)")

    if failures:
        print(f"\n--- Failure Analysis ({len(failures)} failed) ---")
        for r in failures:
            print(f"  [{r['seed_id']}]: {r.get('failure_reason', 'Unknown')}")

    print("\n--- E1: Meta-tag Controllability (Paper Pilot Results) ---")
    for tag, rate in e1_metrics.items():
        print(f"  {tag}: {rate}")

    print("\n===================================================\n")


def main():
    evaluate_pipeline()


if __name__ == "__main__":
    main()
