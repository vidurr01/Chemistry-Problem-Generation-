"""
Live single-question run using SambaNova API.
Uses real models instead of mocks. Run this to generate one augmented problem.
"""

import json
import os
import time
from datetime import datetime, timezone
from openai import OpenAI
from core.meta_tags import compute_meta_tags, archetype_code_from_label

# Load .env if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

SAMBANOVA_KEYS = [
    k for k in (
        os.environ.get("SAMBANOVA_KEY_1", ""),
        os.environ.get("SAMBANOVA_KEY_2", ""),
        os.environ.get("SAMBANOVA_KEY_3", ""),
        os.environ.get("SAMBANOVA_KEY_4", ""),
    ) if k
]
_key_idx = 0

def samba_client():
    return OpenAI(api_key=SAMBANOVA_KEYS[_key_idx], base_url="https://api.sambanova.ai/v1")

weak_client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")

STRONG_MODEL = "DeepSeek-V3.2"
WEAK_MODEL   = "llama3.2"


def sambanova_call(fn, retries=3, base_wait=65):
    """4-key rotation on 429; exponential backoff when all keys exhausted."""
    global _key_idx
    for attempt in range(retries * len(SAMBANOVA_KEYS)):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                next_idx = (_key_idx + 1) % len(SAMBANOVA_KEYS)
                if next_idx != _key_idx:
                    _key_idx = next_idx
                    print(f"    [rate limit] → rotating to key {_key_idx + 1}")
                    time.sleep(2)
                else:
                    wait = base_wait * (2 ** (attempt // len(SAMBANOVA_KEYS)))
                    print(f"    [rate limit] all keys exhausted → waiting {wait}s")
                    time.sleep(wait)
            else:
                raise
    raise RuntimeError("SambaNova rate limit: all keys exhausted after max retries")

# ── inline the pipeline components with real clients ──────────────────────────

from core.blackboard import Blackboard

def reason_over_concept_book_live(blackboard, concept_book):
    context = blackboard.context_summary()
    prompt = f"""You are an expert organic chemistry problem designer.

Task: select the best operators from the Concept Book to augment the seed problem
toward the target difficulty profile, given the full history of previous attempts.

Seed Problem: {blackboard.seed['question']}
Archetype: {blackboard.archetype}

Target Difficulty Profile:
{json.dumps(blackboard.target_profile, indent=2)}

Available Operators (Concept Book):
{json.dumps(concept_book, indent=2)}

Operators already used: {blackboard.operators_tried()}

Attempt History:
{context}

Select 1-3 operators. Return a JSON object with:
- "selected_operators": list of operator names
- "specific_constraints": dict mapping each operator to exact parameters
- "reasoning": string explaining the selection
"""
    resp = sambanova_call(lambda: samba_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    ))
    return json.loads(resp.choices[0].message.content.strip())


def generate_live(blackboard, constraints):
    last = blackboard.last_attempt()
    prior = ""
    if last:
        prior = f"""
--- REFINE IN PLACE ---
Previous Problem: {last['problem']}
Previous Solution: {last['solution']}
Verifier Feedback: {last['verifier_feedback']}
Weak Score: {last['weak_score']}%  Strong Score: {last['strong_score']}%
Fix only what was flagged. Keep everything else.
"""
    prompt = f"""You are an expert organic chemistry problem generator.

Seed Problem: {blackboard.seed['question']}
Original Solution: {blackboard.seed['answer']}
Archetype: {blackboard.archetype}

Target Difficulty Profile:
{json.dumps(blackboard.target_profile, indent=2)}

RLM-Selected Operators and Constraints:
{json.dumps(constraints, indent=2)}

{prior}

Rules:
- Use standard IUPAC nomenclature throughout.
- Apply ONLY the operators listed in the constraints.
- The problem must be chemically feasible and unambiguous.

Return a JSON object with:
- "augmented_problem": string
- "augmented_solution": string
- "operators_applied": list
- "reasoning": string
"""
    resp = sambanova_call(lambda: samba_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    ))
    return json.loads(resp.choices[0].message.content.strip())


def verify_live(problem, solution, archetype):
    prompt = f"""You are an expert organic chemistry verifier (Blind Solver).

1. Read the problem. Do NOT read the candidate solution yet.
2. Solve independently, step by step.
3. Compare to the candidate solution.
4. Check for semantic flaws: functional group incompatibilities, infeasible mechanisms,
   wrong stereochemistry, reagent conflicts.
5. Rate difficulty within the {archetype} archetype.

Candidate Problem:
{problem}

Candidate Solution:
{solution}

Return a JSON object with:
- "independent_solution": string
- "semantic_flaws": string ("None found" if clean)
- "verdict": "PASS" or "FAIL"
- "difficulty_rating": "Beginner", "Intermediate", or "Advanced" (if PASS, else "N/A")
- "feedback_for_generator": string (actionable if FAIL, else "")
"""
    resp = sambanova_call(lambda: samba_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry verifier. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return json.loads(resp.choices[0].message.content.strip())


def solve_weak_live(problem, solution, archetype):
    prompt = f"""You are a chemistry undergraduate student.
Solve this organic chemistry problem as best you can.
Then score yourself 0-100 against the reference solution.

Problem:
{problem}

Archetype: {archetype}

Reference Solution (for scoring only):
{solution}

Return JSON:
- "attempted_solution": string
- "score": integer 0-100
- "reasoning": string
"""
    resp = weak_client.chat.completions.create(
        model=WEAK_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    return json.loads(resp.choices[0].message.content.strip())


def solve_strong_live(problem, solution, archetype):
    prompt = f"""You are an expert organic chemist. Solve rigorously, showing full mechanism.
Then score yourself 0-100 against the reference solution.

Problem:
{problem}

Archetype: {archetype}

Reference Solution (for scoring only):
{solution}

Return JSON:
- "attempted_solution": string
- "score": integer 0-100
- "reasoning": string
"""
    resp = sambanova_call(lambda: samba_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return json.loads(resp.choices[0].message.content.strip())


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    WEAK_CEILING  = 60
    STRONG_FLOOR  = 85
    MAX_RETRIES   = 3

    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "seeds", "jeeadv_organic_seeds.json")) as f:
        seeds = json.load(f)
    with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge", "concept_book.json"), encoding="utf-8") as f:
        concept_book = json.load(f)

    OUTPUT_FILE = "generated_questions.json"
    accepted_questions = []
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE) as f:
            accepted_questions = json.load(f)

    seed = seeds[0]
    print(f"\nSeed: [{seed['question_index']}] {seed['question'][:80]}...")
    print(f"Archetype: {seed['archetype']}\n")

    target_profile = {
        "structural":   {"question_length_scope": "Advanced", "model_solution_length": "Advanced"},
        "interpretive": {"conceptual_fragility": "Advanced", "number_of_exceptions": "Intermediate",
                         "semantic_obfuscation": "Advanced", "distractor_plausibility": "Advanced"}
    }

    blackboard = Blackboard(seed, seed["archetype"], target_profile)
    failure_reason = ""

    for attempt in range(1, MAX_RETRIES + 2):
        print(f"── Attempt {attempt} ──────────────────────────")

        print("Concept reasoner...")
        constraints = reason_over_concept_book_live(blackboard, concept_book)
        print(f"  Operators: {constraints['selected_operators']}")
        print(f"  Reasoning: {constraints['reasoning'][:120]}...")

        print("Generator...")
        gen = generate_live(blackboard, constraints)

        print("Verifier...")
        verifier = verify_live(gen["augmented_problem"], gen["augmented_solution"], seed["archetype"])
        print(f"  Verdict: {verifier['verdict']} | Difficulty: {verifier['difficulty_rating']}")
        if verifier["verdict"] == "FAIL":
            print(f"  Feedback: {verifier['feedback_for_generator']}")

        print("Weak solver...")
        weak = solve_weak_live(gen["augmented_problem"], gen["augmented_solution"], seed["archetype"])
        print(f"  Score: {weak['score']}%")

        print("Strong solver...")
        strong = solve_strong_live(gen["augmented_problem"], gen["augmented_solution"], seed["archetype"])
        print(f"  Score: {strong['score']}%")

        blackboard.record_attempt(
            problem=gen["augmented_problem"],
            solution=gen["augmented_solution"],
            operators_used=gen.get("operators_applied", constraints["selected_operators"]),
            verifier_result=verifier,
            weak_score=weak["score"],
            strong_score=strong["score"],
        )

        accepted = (
            verifier["verdict"] == "PASS"
            and strong["score"] >= STRONG_FLOOR
            and weak["score"] <= WEAK_CEILING
        )

        if accepted:
            arch_code = archetype_code_from_label(seed["archetype"])
            solver_trace = strong.get("attempted_solution", "")
            meta = compute_meta_tags(
                question_text=gen["augmented_problem"],
                archetype_code=arch_code,
                solver_trace=solver_trace,
                fragility_weight=seed.get("fragility_weight"),
            )

            record = {
                "question_id":     f"GEN_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                "seed_id":         seed["question_index"],
                "year":            seed.get("year"),
                "paper":           seed.get("paper"),
                "topic":           seed.get("topic", "Organic Chemistry"),
                "sub_topic":       seed.get("sub_topic", ""),
                "archetype":       seed["archetype"],
                "archetype_code":  arch_code,
                "question":        gen["augmented_problem"],
                "solution":        gen["augmented_solution"],
                "operators_applied": gen.get("operators_applied", constraints["selected_operators"]),
                "loops_run":       attempt,
                "strong_score":    strong["score"],
                "weak_score":      weak["score"],
                "verifier_verdict": verifier["verdict"],
                "verifier_difficulty": verifier["difficulty_rating"],
                "meta_tags":       meta,
                "attempt_history": blackboard.history(),
                "generated_at":    datetime.now(timezone.utc).isoformat(),
            }

            accepted_questions.append(record)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(accepted_questions, f, indent=2)

            print(f"\n✓ ACCEPTED on attempt {attempt}")
            print(f"  Meta-tags: {meta}")
            print(f"  Weak: {weak['score']}% | Strong: {strong['score']}%")
            print(f"  Saved to {OUTPUT_FILE} (total: {len(accepted_questions)})")
            print("=" * 60)
            print(gen["augmented_problem"])
            print("=" * 60)
            print(gen["augmented_solution"])
            return

        if attempt > MAX_RETRIES:
            print(f"\n✗ Max retries reached.")
            break

        print("Refining in place...\n")

    print("Pipeline ended without acceptance.")


if __name__ == "__main__":
    main()
