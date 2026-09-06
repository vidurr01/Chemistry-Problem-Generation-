import json
import os
import time
from openai import OpenAI

WEAK_SCORE_CEILING = 60  # problem accepted only if weak solver scores <= this

# ---------------------------------------------------------------------------
# TWO PROVIDERS
# ---------------------------------------------------------------------------
# Solver:  llama3.2:3b            — local, via Ollama, genuinely weak/small
#          model. This is the role that SHOULD be easy to stump — a low
#          score here is what tells you the question is hard enough to keep.
# Scorer:  deepseek/deepseek-chat — DeepSeek-V3, via OpenRouter, same scorer
#          model used for the strong solver. Keeping one consistent grader
#          across both tiers means "hard for the weak solver" and "correct
#          per the strong gate" are judged by the same standard of correctness.
# ---------------------------------------------------------------------------

# --- Solver: local Ollama ---
solver_client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",  # literal string required by the SDK; Ollama ignores it
)
SOLVER_MODEL = "llama3.2:3b"

# --- Scorer: OpenRouter ---
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    raise RuntimeError("OPENROUTER_KEY not found in environment. Set it in .env.")

scorer_client = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")
SCORER_MODEL = "deepseek/deepseek-chat"


def _openrouter_call_with_retry(model: str, messages: list, temperature: float,
                                 retries: int = 5, base_wait: float = 10.0) -> str:
    """
    Retry wrapper matching the rest of the pipeline's OpenRouter usage
    (run_groundup*.py): exponential backoff on 429/503, single key, no rotation.
    """
    for attempt in range(retries):
        try:
            response = scorer_client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=messages,
                temperature=temperature,
                max_tokens=8192,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower() or "503" in msg:
                time.sleep(base_wait * (2 ** attempt))
            else:
                raise
    raise RuntimeError(f"OpenRouter: max retries exceeded for model {model}")


def attempt_weak(problem: str, archetype: str) -> dict:
    """
    Call 1 — BLIND ATTEMPT (llama3.2:3b, local via Ollama).
    No reference solution anywhere in this prompt or message list. No rate
    limits, no retry handler needed — it's local.
    """
    prompt = f"""
You are a chemistry undergraduate student solving an organic chemistry problem.
You have solid foundational knowledge but may miss edge cases, atypical reagent behaviour,
or subtle stereochemical distinctions.

Problem:
{problem}

Archetype: {archetype}

Attempt to solve the problem as best you can. Show your reasoning and give a final answer.
You do not have access to any reference solution — solve this independently.

Return ONLY a JSON object with this exact key:
- "attempted_solution": string (your full reasoning and final answer)
"""

    response = solver_client.chat.completions.create(
        model=SOLVER_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
    )
    return json.loads(response.choices[0].message.content.strip())


def score_weak_attempt(problem: str, attempted_solution: str, reference_solution: str, archetype: str) -> dict:
    """
    Call 2 — SCORING (DeepSeek-V3 via OpenRouter).
    Deliberately the same scorer model used for the strong solver, so a
    question's "too easy for the weak solver" verdict and its "correct per
    the strong gate" verdict are graded against the same notion of what's
    actually right — not two different, possibly disagreeing, standards.
    """
    prompt = f"""
You are grading a chemistry undergraduate's attempt at an organic chemistry problem.

Problem:
{problem}

Archetype: {archetype}

Student's attempted solution:
{attempted_solution}

Reference (correct) solution:
{reference_solution}

Compare the student's attempt to the reference solution and score it 0-100:
- 100: completely correct product, mechanism, and stereochemistry
- 0: completely wrong

Also flag if the reference solution itself appears wrong, impossible, or physically
implausible (e.g. an age or quantity outside sane bounds, a rule applied to a case it
doesn't apply to) — note this separately from the student's score.

Return ONLY a JSON object with these exact keys:
- "score": integer 0-100
- "reasoning": string explaining where the student lost points
- "reference_flagged": boolean (true if you suspect the reference solution itself is wrong)
- "reference_flag_reason": string (empty string if reference_flagged is false)
"""

    content = _openrouter_call_with_retry(
        model=SCORER_MODEL,
        messages=[
            {"role": "system", "content": "You are a strict, independent chemistry grader. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return json.loads(content)


def solve_weak(problem: str, solution: str, archetype: str) -> dict:
    """
    Orchestrates the two-call weak solver:
      1. llama3.2:3b (local) attempts the problem blind
      2. DeepSeek-V3 (OpenRouter) grades that attempt against the reference

    Score <= WEAK_SCORE_CEILING (60) means the problem is hard enough to accept.
    reference_flagged is a free byproduct: since the scorer here is the SAME
    model used to verify the strong solver's reference, any question flagged
    here is worth cross-checking against the strong solver's own
    reference_correct output.
    """
    attempt = attempt_weak(problem, archetype)
    scored = score_weak_attempt(
        problem=problem,
        attempted_solution=attempt["attempted_solution"],
        reference_solution=solution,
        archetype=archetype,
    )

    return {
        "attempted_solution": attempt["attempted_solution"],
        "score": scored["score"],
        "reasoning": scored["reasoning"],
        "reference_flagged": scored.get("reference_flagged", False),
        "reference_flag_reason": scored.get("reference_flag_reason", ""),
    }


if __name__ == "__main__":
    # smoke test — confirms Ollama + OpenRouter are both reachable and wired correctly
    result = solve_weak(
        problem="Calculate the age of a rock given U-238/Pb-206 ratio of 0.225, "
                "decay constant 1.55e-10 /yr.",
        solution="t = ln(5.444)/\u03bb = 6.44e9 years",
        archetype="Multi-Formulae",
    )
    print(json.dumps(result, indent=2))