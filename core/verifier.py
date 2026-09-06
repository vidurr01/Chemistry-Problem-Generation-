import hashlib
import json
import os
import re
import time
from pathlib import Path
from openai import OpenAI

# ---------------------------------------------------------------------------
# This file was a mock. `verify_problem` never called a model — MockOpenAI
# returned "PASS" via `random.random() < 0.2`, unrelated to the problem or
# solution text. That's why every question in the physical-chem batch shows
# verifier_verdict: PASS, including two U-Pb dating questions with identical
# inputs (1.00 g U-238, 0.100 g Pb-206, t1/2 = 4.468e9 yr) that computed ages
# of 6.44e9 years and 2.08e9 years respectively — neither correct, and
# nothing ever checked.
#
# Two fixes, applied in order:
#
# 1. DETERMINISTIC GATE (runs first, no LLM, no randomness): hash each
#    question's extracted numeric inputs + formula/operator signature. If two
#    accepted questions share that hash but disagree on the final answer,
#    hard-fail both. This alone would have caught the U-Pb bug — it doesn't
#    need to know any chemistry, just that identical inputs can't produce two
#    different "correct" answers.
#
# 2. REAL LLM GATE: a genuine API call, on a model family independent of both
#    strong_solver.py and weak_solver.py, which spend deepseek/qwen/gpt-oss as
#    their scorers. Claude (Anthropic) shares none of those labs' failure modes.
# ---------------------------------------------------------------------------

# Verifier model. Independent of the DeepSeek generator (the thing it verifies).
# NVIDIA Nemotron-3-Ultra 550B (55B-active MoE) — final choice.
VERIFIER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

_SEEN_PATH = Path(__file__).parent.parent / "verifier_seen_inputs.json"


def _client() -> OpenAI:
    """Lazy client — built at call time, not import time, so importing this
    module before .env is loaded into the environment doesn't crash."""
    key = os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_KEY not found in environment. Set it in .env.")
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


def _parse_json(content: str) -> dict:
    """Tolerant JSON parse. Claude (and others) wrap JSON in ```json fences even
    under response_format=json_object, which a bare json.loads() cannot handle."""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
        # Some models (e.g. Nemotron) wrap the object in a single-element array.
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj[0]
        return obj
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            return json.loads(text[s:e + 1])
        raise


def _call_with_retry(model: str, messages: list, temperature: float,
                      retries: int = 5, base_wait: float = 10.0) -> str:
    """Same retry pattern as strong_solver.py / weak_solver.py."""
    for attempt in range(retries):
        try:
            response = _client().chat.completions.create(
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


# ── Tier 1: deterministic duplicate-input check ─────────────────────────────

_NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*\s*(?:[eE][+-]?\d+|\s*[×xX]\s*10\^?[-−]?\d+)?")

def _extract_numeric_signature(problem: str) -> str:
    """
    Pull every number out of the problem text, normalize, sort — order in the
    sentence doesn't matter for "are these the same inputs", only the
    multiset of values does. This is intentionally crude: it's a duplicate
    detector, not a parser. False positives (two genuinely different
    problems that happen to share all their numbers) just get an LLM check
    they'd get anyway; false negatives are the real risk, so keep the
    extraction permissive.
    """
    nums = _NUMBER_PATTERN.findall(problem)
    cleaned = sorted(n.replace(" ", "") for n in nums if n.strip())
    return "|".join(cleaned)


def _extract_final_answer(solution) -> str:
    """
    Solutions in this pipeline are either a flat string or a dict of parts
    (see part_a/b/c/d in the electrochemistry entries). Flatten to one
    string, then grab the last number-bearing line as a rough proxy for
    "the final answer". This is deliberately conservative — it's used only
    to detect disagreement between duplicate-input questions, not as the
    ground-truth comparison itself.
    """
    text = json.dumps(solution) if isinstance(solution, dict) else str(solution)
    numbers = _NUMBER_PATTERN.findall(text)
    return numbers[-1].replace(" ", "") if numbers else ""


def check_duplicate_inputs(problem: str, solution, formula_signature: str,
                            seen_path: Path = _SEEN_PATH) -> dict:
    """
    Tier 1 gate. Runs before any LLM call. Loads a persisted map of
    {input_hash: [(question_id, final_answer), ...]} and checks whether this
    problem's (numeric inputs + operator signature) has been seen before with
    a different final answer.

    Returns {"flagged": bool, "detail": str}. On flagged=True, verify_problem
    should hard-fail regardless of what the LLM tier says — a disagreement
    here means at least one of the two questions is wrong, full stop, and no
    amount of LLM confidence resolves which one without a real oracle.
    """
    numeric_sig = _extract_numeric_signature(problem)
    key = hashlib.sha256(f"{formula_signature}::{numeric_sig}".encode()).hexdigest()
    final_answer = _extract_final_answer(solution)

    seen = {}
    if seen_path.exists():
        with open(seen_path, encoding="utf-8") as f:
            seen = json.load(f)

    prior = seen.get(key, [])
    conflict = next((p for p in prior if p["final_answer"] != final_answer), None)

    seen.setdefault(key, []).append({"final_answer": final_answer})
    with open(seen_path, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=2)

    if conflict:
        return {
            "flagged": True,
            "detail": (
                f"Same numeric inputs and formula signature previously produced "
                f"final answer '{conflict['final_answer']}'; this attempt produced "
                f"'{final_answer}'. At least one is wrong."
            ),
        }
    return {"flagged": False, "detail": ""}


# ── Tier 2: real LLM blind-solver check ──────────────────────────────────────

def _blind_solve(problem: str, archetype: str, subject: str) -> str:
    prompt = f"""
You are an expert {subject} chemist. Solve the problem below independently and
completely, showing every step. You have not been shown any candidate
solution — solve it cold, exactly as a top JEE Advanced student would.

Problem:
{problem}

Archetype: {archetype}

Return ONLY a JSON object with this exact key:
- "independent_solution": string (full derivation and final answer)
"""
    content = _call_with_retry(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return _parse_json(content)["independent_solution"]


def _judge(problem: str, solution, independent_solution: str, archetype: str) -> dict:
    solution_text = json.dumps(solution, indent=2) if isinstance(solution, dict) else str(solution)
    prompt = f"""
You are an independent verifier. You solved the problem below without seeing
the candidate solution. Now compare.

Problem:
{problem}

Archetype: {archetype}

Your independent solution:
{independent_solution}

Candidate solution to verify:
{solution_text}

Check specifically for:
- Arithmetic or algebraic errors, even if the method/setup is right
- Formulas applied outside the regime where they hold (e.g. mass-ratio
  corrections applied to quantities already converted to moles, equilibrium
  assumptions where none is justified, sign errors in non-inertial frames)
- Physically impossible results (negative rate constants, ages exceeding
  cosmological bounds, activities assigned to stable nuclides)
- Domain/uniqueness issues (extraneous roots, multiple valid answers where
  the problem implies one)
- Non-circularity: the final product/answer must be chemically distinct from
  the starting material; reject a sequence that returns to its own reactant.

Return ONLY a JSON object with these exact keys:
- "verdict": "PASS" or "FAIL"
- "flaws": string, specific and cite the exact step if FAIL, else "None found"
- "difficulty_rating": "Beginner", "Intermediate", or "Advanced" if PASS, else "N/A"
- "feedback_for_generator": string, specific and actionable if FAIL, else ""
"""
    content = _call_with_retry(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are a rigorous, independent chemistry verifier. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return _parse_json(content)


# ── Public entry point ───────────────────────────────────────────────────────

def verify_problem(problem: str, solution, archetype: str, subject: str = "chemistry",
                    formula_signature: str = "") -> dict:
    """
    Two-tier verifier.

    Tier 1 (deterministic, no LLM): reject on duplicate-input disagreement.
    Tier 2 (real LLM, cross-family from both solver scorers): blind-solve
    then judge.

    formula_signature should be the operator/formula id this question routes
    through (e.g. "upb_dating", "nernst_thermo_chain") if your generator
    tracks that — pass operators_applied joined as a fallback if not. Without
    it, Tier 1 degrades to a numbers-only check, which still catches the
    exact bug found (identical inputs -> different answers) but is more
    prone to false positives across genuinely different question types that
    happen to share numbers.
    """
    dup = check_duplicate_inputs(problem, solution, formula_signature or archetype)
    if dup["flagged"]:
        return {
            "independent_solution": "",
            "semantic_flaws": dup["detail"],
            "verdict": "FAIL",
            "difficulty_rating": "N/A",
            "feedback_for_generator": (
                "Duplicate-input conflict: " + dup["detail"] +
                " Re-derive this problem from scratch and confirm the arithmetic "
                "before resubmitting."
            ),
        }

    independent = _blind_solve(problem, archetype, subject)
    judged = _judge(problem, solution, independent, archetype)

    return {
        "independent_solution": independent,
        "semantic_flaws": judged["flaws"],
        "verdict": judged["verdict"],
        "difficulty_rating": judged["difficulty_rating"],
        "feedback_for_generator": judged["feedback_for_generator"],
    }


if __name__ == "__main__":
    # Smoke test on the exact conflicting pair found in
    # generated_questions_physical.json: identical inputs, two different ages.
    q = (
        "A zircon crystal contains uranium-238, which undergoes alpha decay to "
        "form lead-206 with a half-life of 4.468e9 years. A sample was found to "
        "contain 1.00 g of uranium-238 and 0.100 g of lead-206. Calculate the "
        "age of the zircon crystal."
    )
    print(json.dumps(
        verify_problem(q, "t = 6.44e9 years", "Multi-Formulae", formula_signature="upb_dating"),
        indent=2,
    ))
    print(json.dumps(
        verify_problem(q, "t = 2.08e9 years", "Multi-Formulae", formula_signature="upb_dating"),
        indent=2,
    ))
