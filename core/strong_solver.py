import json
import os
import time
from openai import OpenAI

STRONG_FLOOR = 85  # problem accepted only if strong solver scores >= this

# ---------------------------------------------------------------------------
# OPENROUTER — SINGLE PROVIDER, TWO DIFFERENT MODEL FAMILIES
# ---------------------------------------------------------------------------
# Solver:  openai/gpt-oss-120b        (OpenAI open-weight lineage)
# Scorer:  deepseek/deepseek-chat     (DeepSeek-V3 — different lab/architecture,
#                                      kept independent from the solver so
#                                      grading isn't blind to the same mistakes
#                                      the solver's own family tends to make)
#
# THIS is the gate that actually decides "is this question/reference correct."
# In the earlier single-call design, one model both solved AND self-scored
# against a reference it had every reason to agree with — that's how a
# physically impossible 6.44 Gyr rock age passed with strong_score=90.
#
# Verify exact slugs at https://openrouter.ai/models before running — OpenRouter
# renames/versions models over time (e.g. deepseek/deepseek-chat may become
# deepseek/deepseek-chat-v3.1 or similar).
# ---------------------------------------------------------------------------

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    raise RuntimeError("OPENROUTER_KEY not found in environment. Set it in .env.")

client = OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

SOLVER_MODEL = "openai/gpt-oss-120b"
SCORER_MODEL = "deepseek/deepseek-chat"


def _call_with_retry(model: str, messages: list, temperature: float,
                      retries: int = 5, base_wait: float = 10.0) -> str:
    """
    Retry wrapper matching the rest of the pipeline's OpenRouter usage
    (run_groundup*.py): exponential backoff on 429/503, single key, no rotation.
    """
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=messages,
                temperature=temperature,
                max_tokens=8192,  # required — unset reserves the model's full budget
                                   # and OpenRouter rejects low-balance accounts with 402
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower() or "503" in msg:
                time.sleep(base_wait * (2 ** attempt))
            else:
                raise
    raise RuntimeError(f"OpenRouter: max retries exceeded for model {model}")


def attempt_strong(problem: str, archetype: str) -> dict:
    """
    Call 1 — BLIND ATTEMPT (gpt-oss-120b via OpenRouter).
    No reference solution, no expected reaction chain, no operators_applied —
    nothing from the generator's internal state leaks into this call. The
    model sees exactly what a real JEE Advanced student would see.
    """
    prompt = f"""
You are an expert chemistry problem solver, capable of graduate-level analysis.

Problem:
{problem}

Archetype: {archetype}

Solve this problem rigorously and completely, showing every step of your reasoning.
Give a final numeric/structural answer where applicable.

Return ONLY a JSON object with this exact key:
- "attempted_solution": string (your full derivation and final answer)
"""

    content = _call_with_retry(
        model=SOLVER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,  # deterministic — this is a correctness check, not creative work
    )
    return json.loads(content)


def score_strong_attempt(problem: str, attempted_solution: str, reference_solution: str,
                          chain_description: str, archetype: str) -> dict:
    """
    Call 2 — SCORING (DeepSeek-V3 via OpenRouter).

    This call does three things at once, matching what the 4-gate check needs:
      1. Scores the independent attempt against the reference (0-100)
      2. Independently verifies the reference solution is itself chemically/
         numerically correct (reference_correct) — NOT just "consistent with
         itself," but actually right
      3. Runs an explicit plausibility check for physically impossible results
         (ages older than the solar system, negative rate constants, activities
         assigned to stable/terminal nuclides, etc.)

    Splitting solver and scorer across unrelated model families means an error
    both a generator and a same-family solver might independently agree on
    (e.g. a decay-equation slip) is much less likely to also fool the scorer.
    """
    prompt = f"""
You are an expert chemistry grader and independent verifier. You are NOT told what model
generated the reference solution — treat it with the same scrutiny you would treat a
student's submitted answer.

Problem:
{problem}

Archetype: {archetype}

Expected reasoning chain (for context only — verify independently, do not assume it is correct):
{chain_description}

Independent attempt (solved blind, with no access to the reference below):
{attempted_solution}

Reference solution (claimed correct answer):
{reference_solution}

Do the following, in order:
1. Verify the reference solution's chemistry and arithmetic from scratch. Do not assume it
   is correct just because it looks complete or well-formatted.
2. Check for physical/chemical impossibility in the reference: negative or supra-cosmological
   ages (e.g. an age greater than ~4.6 billion years for anything geological), decay/activity
   relationships applied to a stable or terminal nuclide, negative concentrations or rate
   constants, or a rule/formula applied outside the regime where it holds.
3. Compare the independent attempt to the (now-verified) correct answer and score the attempt
   0-100:
   - 100: completely correct product, mechanism, numeric result
   - 0: completely wrong
4. If the reference solution itself is wrong, the attempt's score should reflect how it
   compares to the TRUE correct answer, not to the flawed reference.

Return ONLY a JSON object with these exact keys:
- "score": integer 0-100 (independent attempt vs. the true correct answer)
- "reasoning": string, specific discrepancies found
- "reference_correct": boolean (false if the reference solution has any chemical, numeric,
  or physical-plausibility error)
- "reference_error_detail": string (empty string if reference_correct is true; otherwise a
  precise description of the error, e.g. "computed age of 6.44e9 years exceeds the age of
  the solar system")
"""

    content = _call_with_retry(
        model=SCORER_MODEL,
        messages=[
            {"role": "system", "content": "You are a rigorous, independent chemistry verifier. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return json.loads(content)


def solve_strong(problem: str, solution: str, chain_description: str, archetype: str) -> dict:
    """
    Orchestrates the two-call strong solver:
      1. gpt-oss-120b attempts the problem blind
      2. DeepSeek-V3 verifies the reference from scratch, checks plausibility,
         and scores the blind attempt against the true correct answer

    Gate usage (matches your existing 4-gate check):
        strong.score >= STRONG_FLOOR (85)   AND
        strong.reference_correct == True
    Both conditions now come from a model that never saw the reference while
    solving, and that was explicitly instructed to distrust the reference by
    default rather than assume it's right.
    """
    attempt = attempt_strong(problem, archetype)
    scored = score_strong_attempt(
        problem=problem,
        attempted_solution=attempt["attempted_solution"],
        reference_solution=solution,
        chain_description=chain_description,
        archetype=archetype,
    )

    return {
        "attempted_solution": attempt["attempted_solution"],
        "score": scored["score"],
        "reasoning": scored["reasoning"],
        "reference_correct": scored.get("reference_correct", True),
        "reference_error_detail": scored.get("reference_error_detail", ""),
    }


if __name__ == "__main__":
    # smoke test on the exact broken example found in generated_questions_physical.json
    result = solve_strong(
        problem=(
            "A zircon crystal contains uranium-238... calculate the age of the rock "
            "given 1.00 g U-238 and 0.100 g Pb-206, half-life 4.468e9 years."
        ),
        solution=(
            "w0 = 0.00476 mol, t = (4.468e9/0.693) * ln(0.00476/0.00420) = 6.44e9 years"
        ),
        chain_description="radioactive decay kinetics leading to rock dating via equilibrium and U-Pb ratio",
        archetype="Multi-Formulae",
    )
    print(json.dumps(result, indent=2))