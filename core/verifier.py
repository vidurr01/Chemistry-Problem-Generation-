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
# Was "nvidia/nemotron-3-ultra-550b-a55b", which on OpenRouter does not return
# an answer at all — it echoes the request message array back as the content,
# so every verify_problem() call raised (bad JSON, missing key, None content).
# Now Gemini 3 Flash (preview): fast, returns clean json_object output, and its
# reasoning is strong enough to blind-solve JEE multi-step chemistry.
VERIFIER_MODEL = "google/gemini-3-flash-preview"

_SEEN_PATH = Path(__file__).parent.parent / "verifier_seen_inputs.json"


def _client() -> OpenAI:
    """Lazy client — built at call time, not import time, so importing this
    module before .env is loaded into the environment doesn't crash."""
    key = os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_KEY not found in environment. Set it in .env.")
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


def _first_json_object(text: str) -> str:
    """Return the first balanced {...} block in text, tracking string state so
    braces inside string values don't throw the count off. Used when a model
    appends prose or a second object after the JSON ("Extra data")."""
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return ""


def _parse_json(content: str) -> dict:
    """Tolerant JSON parse. Models wrap JSON in ```json fences even under
    response_format=json_object, sometimes append trailing prose or a second
    object, and sometimes wrap the object in a single-element list."""
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()

    obj = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        block = _first_json_object(text)
        if block:
            obj = json.loads(block)
        else:
            raise

    # Some models wrap the object in a single-element array.
    if isinstance(obj, list):
        obj = next((x for x in obj if isinstance(x, dict)), None)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a JSON object, got {type(obj).__name__}")
    return obj


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
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()
            # Empty completion: transient, back off briefly and retry.
            time.sleep(base_wait)
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

def _blind_solve(problem: str, archetype: str, subject: str) -> dict:
    """Phase 1: solve the problem cold. The candidate solution is NOT passed in
    here, so this answer is genuinely independent of what the generator wrote."""
    prompt = f"""
You are an expert {subject} chemist. Solve the problem below independently and
completely, showing every step. You have NOT been shown any candidate solution.
Solve it cold, exactly as a top JEE Advanced student would, and commit to a
final answer.

Problem:
{problem}

Archetype: {archetype}

Return ONLY a JSON object with these exact keys:
- "independent_solution": string (full derivation)
- "final_answer": string (your final answer only — the product name(s), the
  numeric value with units, or the reagent, stated concisely and unambiguously)
"""
    content = _call_with_retry(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    obj = _parse_json(content)
    sol = obj.get("independent_solution")
    if not sol:
        sol = next((v for k, v in obj.items()
                    if k != "final_answer" and isinstance(v, str) and v.strip()), "")
    return {
        "solution": sol or json.dumps(obj),
        "final_answer": str(obj.get("final_answer", "")).strip(),
    }


def _ask_json(system: str, user: str) -> dict:
    """One focused verifier call → one JSON object."""
    content = _call_with_retry(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": system + " Output JSON only."},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )
    return _parse_json(content)


# Each of the checks below is its own narrow call. Splitting them keeps every
# prompt short and single-purpose, which is where a small model hallucinates
# least — one call extracts an answer, one call compares two answers, one call
# looks for structural flaws, one call rates difficulty. The verdict is then
# assembled in code from those discrete results, not written by the model.

def _extract_candidate_answer(solution) -> str:
    """Read the candidate's reference solution and return only its final answer.
    No judgement — just extraction."""
    solution_text = json.dumps(solution, indent=2) if isinstance(solution, dict) else str(solution)
    obj = _ask_json(
        "You extract the single final answer from a worked chemistry solution.",
        f"""Solution:
{solution_text}

Return ONLY: {{"final_answer": "<the final answer this solution arrives at — product name(s),
numeric value with units, or reagent — stated concisely, nothing else>"}}""",
    )
    return str(obj.get("final_answer", "")).strip()


def _answers_equivalent(problem: str, answer_a: str, answer_b: str) -> dict:
    """Compare two final answers for chemical equivalence. Nothing else in the
    prompt, so the model is not tempted to re-solve or rationalise."""
    obj = _ask_json(
        "You judge whether two chemistry answers are the same answer.",
        f"""Problem (for context only, do not solve it):
{problem}

Answer A: {answer_a}
Answer B: {answer_b}

Are A and B the SAME answer? Same compound(s) (different IUPAC spelling of one
compound is still the same), all co-products present on both sides, numeric
values equal within rounding, same reagent. A missing co-product or a different
compound means NOT equivalent.

Return ONLY: {{"equivalent": true or false, "reason": "<one sentence>"}}""",
    )
    return {"equivalent": bool(obj.get("equivalent")), "reason": str(obj.get("reason", "")).strip()}


def _structural_check(problem: str, solution) -> dict:
    """Look for disqualifying flaws OTHER than a wrong final answer."""
    solution_text = json.dumps(solution, indent=2) if isinstance(solution, dict) else str(solution)
    obj = _ask_json(
        "You are a rigorous chemistry solution checker.",
        f"""Problem:
{problem}

Candidate solution:
{solution_text}

Check ONLY for these disqualifying problems:
- arithmetic or algebra errors in the worked steps
- a formula used outside the regime where it holds
- a physically impossible result (negative rate constant, age past cosmological
  bounds, activity on a stable nuclide, negative concentration)
- non-uniqueness: the problem implies one answer but several are equally valid
- circularity: the final product is the same compound as the starting material

Return ONLY: {{"blocking_flaw": true or false,
"flaws": "<specific, cite the step; or 'None found'>"}}""",
    )
    return {"blocking_flaw": bool(obj.get("blocking_flaw")),
            "flaws": str(obj.get("flaws", "") or "None found").strip()}


def _rate_difficulty(problem: str, independent_solution: str) -> str:
    obj = _ask_json(
        "You rate JEE Advanced chemistry problem difficulty.",
        f"""Problem:
{problem}

A correct solution:
{independent_solution}

Rate difficulty for a JEE Advanced candidate.
Return ONLY: {{"difficulty_rating": "Beginner" or "Intermediate" or "Advanced"}}""",
    )
    r = str(obj.get("difficulty_rating", "")).strip().capitalize()
    return r if r in ("Beginner", "Intermediate", "Advanced") else "Intermediate"


# ── Public entry point ───────────────────────────────────────────────────────

def verify_problem(problem: str, solution, archetype: str, subject: str = "chemistry",
                    formula_signature: str = "") -> dict:
    """
    Two-tier verifier.

    Tier 1 (deterministic, no LLM): reject on duplicate-input disagreement.
    Tier 2 (real LLM): two phases.
      Phase 1 solves the problem cold, with the candidate solution withheld,
      and commits to a final answer.
      Phase 2 reveals the candidate and FAILs it if its final answer disagrees
      with the phase-1 answer, or if it has arithmetic / regime / uniqueness /
      circularity problems. A candidate whose reasoning merely "looks" internally
      consistent does not pass unless its answer matches the blind solve.

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

    # Step 1 — solve the problem blind. Candidate solution is NOT in this prompt.
    independent = _blind_solve(problem, archetype, subject)

    # Step 2 — extract the candidate's final answer (own call, extraction only).
    candidate_answer = _extract_candidate_answer(solution)

    # Step 3 — compare the two answers (own call, comparison only).
    eq = _answers_equivalent(problem, independent["final_answer"], candidate_answer)
    answers_agree = eq["equivalent"]

    # Answer mismatch is decisive: the candidate's reference solution is not
    # trustworthy, no matter how tidy its own reasoning looks. Fail fast, and
    # skip the remaining calls.
    if not answers_agree:
        return {
            "independent_solution": independent["solution"],
            "independent_final_answer": independent["final_answer"],
            "candidate_final_answer": candidate_answer,
            "answers_agree": False,
            "semantic_flaws": f"Answer mismatch. {eq['reason']}".strip(),
            "verdict": "FAIL",
            "difficulty_rating": "N/A",
            "feedback_for_generator": (
                f"ANSWER MISMATCH. Independent blind solve gives: "
                f"{independent['final_answer'] or '(unstated)'}. Candidate solution concludes: "
                f"{candidate_answer or '(unstated)'}. {eq['reason']} "
                f"Re-derive the final answer from scratch and correct the reference solution."
            ).strip(),
        }

    # Step 4 — structural flaws other than a wrong answer (own call).
    struct = _structural_check(problem, solution)
    if struct["blocking_flaw"]:
        return {
            "independent_solution": independent["solution"],
            "independent_final_answer": independent["final_answer"],
            "candidate_final_answer": candidate_answer,
            "answers_agree": True,
            "semantic_flaws": struct["flaws"],
            "verdict": "FAIL",
            "difficulty_rating": "N/A",
            "feedback_for_generator": (
                "The final answer is right but the solution has a blocking flaw: "
                + struct["flaws"] + " Fix that step without changing the answer."
            ),
        }

    # Step 5 — difficulty rating (own call). Only reached on a clean PASS.
    difficulty = _rate_difficulty(problem, independent["solution"])

    return {
        "independent_solution": independent["solution"],
        "independent_final_answer": independent["final_answer"],
        "candidate_final_answer": candidate_answer,
        "answers_agree": True,
        "semantic_flaws": "None found",
        "verdict": "PASS",
        "difficulty_rating": difficulty,
        "feedback_for_generator": "",
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
