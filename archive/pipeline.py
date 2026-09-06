import json
import os
from core.blackboard import Blackboard
from core.concept_reasoner import reason_over_concept_book
from core.generator import generate_augmented_problem
from core.verifier import verify_problem
from core.weak_solver import solve_weak, WEAK_SCORE_CEILING
from core.strong_solver import solve_strong, STRONG_FLOOR


def check_acceptance(verifier_result: dict, weak_result: dict, strong_result: dict):
    """
    Returns (accepted: bool, reason: str).
    Three independent gates — all must pass:
      1. Verifier: semantic validity (chemistry is correct)
      2. Strong solver: problem is solvable (not broken)
      3. Weak solver: problem is hard enough (not trivial)
    """
    if verifier_result["verdict"] == "FAIL":
        return False, f"VERIFIER_FAIL: {verifier_result['feedback_for_generator']}"
    if strong_result["score"] < STRONG_FLOOR:
        return False, (
            f"STRONG_TOO_LOW: {strong_result['score']}% (floor={STRONG_FLOOR}%) — "
            f"problem may be unsolvable or chemically broken"
        )
    if weak_result["score"] > WEAK_SCORE_CEILING:
        return False, (
            f"WEAK_TOO_HIGH: {weak_result['score']}% (ceiling={WEAK_SCORE_CEILING}%) — "
            f"problem not hard enough"
        )
    return True, "PASS"


def run_pipeline(seed: dict, concept_book: dict, target_profile: dict, max_retries: int = 3) -> dict:
    """
    Full stateful pipeline for one seed problem.
    The blackboard accumulates the complete trace across all attempts so that
    the concept reasoner and generator always have full context when refining.
    """
    blackboard = Blackboard(seed, seed["archetype"], target_profile)
    seed_id = seed["question_index"]
    failure_reason = ""

    print(f"\n[{seed_id}] Archetype: {seed['archetype']}")

    for attempt_num in range(1, max_retries + 2):
        print(f"[{seed_id}] Attempt {attempt_num}/{max_retries + 1}")

        # Step 1: RLM reasons over concept book given current blackboard state
        print(f"  → Concept reasoner running...")
        constraints = reason_over_concept_book(blackboard, concept_book)
        print(f"  → Operators selected: {constraints['selected_operators']}")

        # Step 2: Generator augments (or refines in place on retry)
        print(f"  → Generator running...")
        generation = generate_augmented_problem(blackboard, constraints)
        problem = generation["augmented_problem"]
        solution = generation["augmented_solution"]
        operators_used = generation.get("operators_applied", constraints["selected_operators"])

        # Step 3: Semantic verifier (blind solver)
        print(f"  → Verifier running...")
        verifier_result = verify_problem(problem, solution, seed["archetype"])

        # Step 4: Weak and strong solvers (independent difficulty calibration)
        print(f"  → Weak solver running...")
        weak_result = solve_weak(problem, solution, seed["archetype"])
        print(f"  → Strong solver running...")
        strong_result = solve_strong(problem, solution, seed["archetype"])

        # Record everything to blackboard
        blackboard.record_attempt(
            problem=problem,
            solution=solution,
            operators_used=operators_used,
            verifier_result=verifier_result,
            weak_score=weak_result["score"],
            strong_score=strong_result["score"],
        )

        accepted, failure_reason = check_acceptance(verifier_result, weak_result, strong_result)

        print(
            f"  → Verdict: {verifier_result['verdict']} | "
            f"Weak: {weak_result['score']}% | "
            f"Strong: {strong_result['score']}% | "
            f"{'ACCEPTED' if accepted else 'REJECTED: ' + failure_reason}"
        )

        if accepted:
            return {
                "seed_id": seed_id,
                "status": "SUCCESS",
                "attempts": attempt_num,
                "final_problem": problem,
                "final_solution": solution,
                "difficulty_rating": verifier_result["difficulty_rating"],
                "weak_score": weak_result["score"],
                "strong_score": strong_result["score"],
                "operators_used": operators_used,
                "blackboard": blackboard.to_dict(),
            }

        if attempt_num > max_retries:
            break

        print(f"  → Refining in place...")

    last = blackboard.last_attempt()
    return {
        "seed_id": seed_id,
        "status": "FAILED",
        "attempts": max_retries + 1,
        "final_problem": last["problem"] if last else "",
        "final_solution": last["solution"] if last else "",
        "difficulty_rating": "N/A",
        "weak_score": last["weak_score"] if last else 0,
        "strong_score": last["strong_score"] if last else 0,
        "failure_reason": failure_reason,
        "blackboard": blackboard.to_dict(),
    }


def main():
    print("Loading classified seeds...")
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "seeds", "classified_seeds.json"), "r", encoding="utf-8") as f:
        seeds = json.load(f)

    print("Loading concept book...")
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge", "concept_book.json"), "r", encoding="utf-8") as f:
        concept_book = json.load(f)

    target_profile = {
        "structural": {
            "question_length_scope": "Advanced",
            "model_solution_length": "Advanced"
        },
        "interpretive": {
            "conceptual_fragility": "Advanced",
            "number_of_exceptions": "Intermediate",
            "semantic_obfuscation": "Advanced",
            "distractor_plausibility": "Advanced"
        }
    }

    test_subset = seeds[:5]
    results = []

    print(f"\nRunning pipeline on {len(test_subset)} seeds...")
    for seed in test_subset:
        result = run_pipeline(seed, concept_book, target_profile)
        results.append(result)

    print("\nSaving results to pipeline_output.json...")
    with open("pipeline_output.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    successes = sum(1 for r in results if r["status"] == "SUCCESS")
    print(f"\nDone. Success rate: {successes}/{len(test_subset)} ({successes / len(test_subset) * 100:.1f}%)")


if __name__ == "__main__":
    main()
