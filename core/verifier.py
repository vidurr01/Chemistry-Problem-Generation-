"""
verifier.py — the two-tier verifier used by run_groundup_final.py (verify_problem).

History: this file was once a mock — verify_problem never called a model and returned
PASS at random — which is how two U-Pb dating questions with identical inputs
(1.00 g U-238, 0.100 g Pb-206, t1/2 = 4.468e9 yr) were both stamped PASS with ages of
6.44e9 and 2.08e9 years. The two tiers below exist to catch exactly that.

Tier 1 — deterministic: for numeric answers, the problem's numeric inputs + formula
  signature are hashed and compared with ACCEPTED questions; identical inputs with a
  different answer hard-FAIL, with no chemistry knowledge needed.
Tier 2 — answer-first LLM checks: blind-solve with the candidate withheld, compare the
  answers, then look for structural flaws and rate difficulty, one narrow call each;
  the PASS/FAIL verdict is assembled in code.

The verifier model (Gemini 3 Flash) is independent of the generator (Gemini 2.5 Flash):
a different model, so the generator never certifies its own output. An earlier choice,
"nvidia/nemotron-3-ultra-550b-a55b", echoed the request back instead of answering on
OpenRouter, so every call failed.
"""

import hashlib
import json
import math
import os
import re
import sys
import time
from pathlib import Path
from openai import OpenAI

if __package__ in (None, ""):   # run as a script (python core/verifier.py): make `core` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.llm import as_bool, is_transient, parse_json as _parse_json, write_json_atomic

VERIFIER_MODEL = "google/gemini-3-flash-preview"

_SEEN_PATH = Path(__file__).parent.parent / "outputs" / "verifier_seen_inputs.json"


def _client() -> OpenAI:
    """Lazy client — built at call time, not import time, so importing this
    module before .env is loaded into the environment doesn't crash."""
    key = os.environ.get("OPENROUTER_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_KEY not found in environment. Set it in .env.")
    return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")


def _call_with_retry(model: str, messages: list, temperature: float,
                      retries: int = 5, base_wait: float = 10.0) -> str:
    """One verifier call. Retries empty completions and transient API errors
    (core/llm.is_transient: 429, 5xx, timeouts, dropped connections)."""
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
            if is_transient(e) and attempt < retries - 1:
                time.sleep(base_wait * (2 ** attempt))
            else:
                raise
    raise RuntimeError(f"OpenRouter: max retries exceeded for model {model}")


def _call_json(model: str, messages: list, temperature: float, parse_retries: int = 2) -> dict:
    """_call_with_retry + _parse_json; an unparseable reply is asked for again."""
    for i in range(parse_retries + 1):
        content = _call_with_retry(model=model, messages=messages, temperature=temperature)
        try:
            return _parse_json(content)
        except (ValueError, json.JSONDecodeError):
            if i == parse_retries:
                raise


# ── Tier 1: deterministic duplicate-input check ─────────────────────────────

_NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*\s*(?:[eE][+-]?\d+|\s*[×xX]\s*10\^?[-−]?\d+)?")


def _normalize_number(token: str) -> str:
    """"1.00" and "1.0" are the same input; "4.468e9" and "4.468 × 10^9" too."""
    t = token.replace(" ", "").replace("−", "-")
    t = re.sub(r"[×xX]10\^?", "e", t)
    try:
        return f"{float(t):.6g}"
    except ValueError:
        return t


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
    cleaned = sorted(_normalize_number(n) for n in nums if n.strip())
    return "|".join(cleaned)


_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_NUMERIC_ANSWER = re.compile(r"""
    ^(?:[A-Za-z][A-Za-z0-9 ()\[\]_]{0,24}?\s*(?:=|≈|:)\s*)?       # optional label: "t =", "pH =", "Age:"
    (?P<num>[-+]?(?:\d+\.?\d*|\.\d+))
    (?:\s*(?:[eE](?P<e1>[-+]?\d+)
           |[×xX*·]\s*10\s*(?:\^|\*\*)?\s*\(?(?P<e2>[-+]?\d+)\)?))?
    (?P<unit>.*)$""", re.VERBOSE)
# One unit word: letters (with an optional exponent such as m^-3, s-1, CO2) or %, °, ‰.
_UNIT_WORD = re.compile(r"^(?:[%‰°]|[A-Za-zµμΩ°()/·]+(?:\^?[-+]?\d+)?)+$")


def parse_numeric_answer(text):
    """The value of a NUMERIC final answer, or None if the answer is not a number.

        "2.08 × 10^9 years" -> 2.08e9     "t = 6.44e9 years" -> 6.44e9
        "-0.76 V" -> -0.76                "3 isomers" -> 3.0
        "2-methylbut-2-ene" -> None       "propan-2-ol" -> None
        "x = 2, y = 3" -> None            "Option B" -> None
    """
    if text is None:
        return None
    s = str(text).translate(_SUPERSCRIPTS).replace("−", "-").replace("–", "-").strip().rstrip(".")
    if not s or "," in s or ";" in s:
        return None
    m = _NUMERIC_ANSWER.match(s)
    if not m:
        return None
    unit = m.group("unit")
    if unit and not (unit[0].isspace() or unit[0] in "%‰°/"):
        return None                       # "2-methyl...", "3a", "2,2-..." are names, not numbers
    words = unit.split()
    if len(unit.strip()) > 30 or any(not _UNIT_WORD.match(w) for w in words):
        return None
    exp = m.group("e1") or m.group("e2")
    try:
        return float(m.group("num")) * (10 ** int(exp) if exp else 1)
    except (ValueError, OverflowError):
        return None


def parse_numeric_answers(text):
    """All values of a numeric final answer as a list, or None if any part is not a
    number. Handles single answers and multi-part ones separated by commas,
    semicolons or "and":
        "t = 6.44e9 years"                         -> [6.44e9]
        "Ea = 293.95 kJ/mol, t = 10.395 seconds"   -> [293.95, 10.395]
        "2,2-dimethylpropane"                      -> None ("2-dimethylpropane" is not a number)
    """
    single = parse_numeric_answer(text)
    if single is not None:
        return [single]
    if text is None:
        return None
    parts = [x.strip() for x in re.split(r"[,;]|\band\b", str(text)) if x.strip()]
    if len(parts) < 2:
        return None
    values = [parse_numeric_answer(x) for x in parts]
    return values if all(v is not None for v in values) else None


def _same_values(a: list, b: list) -> bool:
    return len(a) == len(b) and all(math.isclose(x, y, rel_tol=0.01, abs_tol=1e-12) for x, y in zip(a, b))


def _stored_values(entry):
    """Stored final_answer as a list of numbers, or None for entries from older code."""
    v = entry.get("final_answer")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [float(v)]
    if isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
        return [float(x) for x in v]
    return None


def _inputs_key(problem: str, formula_signature: str) -> str:
    """Hash of the problem's numeric inputs + formula signature."""
    numeric_sig = _extract_numeric_signature(problem)
    return hashlib.sha256(f"{formula_signature}::{numeric_sig}".encode()).hexdigest()


def _load_seen(seen_path: Path) -> dict:
    if not seen_path.exists():
        return {}
    with open(seen_path, encoding="utf-8") as f:
        return json.load(f)


def check_duplicate_inputs(problem: str, answer_values: list, formula_signature: str,
                            seen_path: Path = None) -> dict:
    """
    Tier 1 gate, READ-ONLY, for NUMERIC answers. verify_problem calls it with the
    candidate's final answer (parse_numeric_answers of the extracted answer) and skips
    it when the answer is not numeric — Tier 1 exists to catch identical numeric
    inputs giving different numeric answers. Non-numeric answers (an organic product
    name) are judged by Tier 2 alone; taking "the last number in the solution" as
    their answer compared locants like the 2 in 2-methylbut-2-ene and failed
    unrelated questions.

    Compares against ACCEPTED questions only, stored by record_accepted_inputs as
    {input_hash: [{question_id, final_answer: [numbers]}, ...]}. Answers are the same
    if they have the same number of parts and each agrees within 1%. Entries without
    a question_id, or with a non-numeric final_answer, were written by older code and
    are ignored.

    Returns {"flagged": bool, "detail": str}. On flagged=True, verify_problem
    hard-fails regardless of the LLM tier — a disagreement with an accepted question
    means at least one of the two is wrong.
    """
    key = _inputs_key(problem, formula_signature)
    prior = [p for p in _load_seen(seen_path or _SEEN_PATH).get(key, [])
             if p.get("question_id") and _stored_values(p) is not None]
    conflict = next((p for p in prior if not _same_values(_stored_values(p), answer_values)), None)
    if conflict:
        return {
            "flagged": True,
            "detail": (
                f"Same numeric inputs and formula signature as accepted question "
                f"{conflict['question_id']}, whose final answer is "
                f"{conflict.get('answer_text') or conflict['final_answer']}; this attempt's "
                f"answer is {', '.join(f'{v:g}' for v in answer_values)}. At least one is wrong."
            ),
        }
    return {"flagged": False, "detail": ""}


def record_accepted_inputs(problem: str, final_answer: str, formula_signature: str, question_id: str,
                           archetype: str = "", seen_path: Path = None) -> bool:
    """Store an ACCEPTED question's inputs and numeric final answer for future Tier 1
    checks. `final_answer` is the extracted answer text (verify_problem's
    candidate_final_answer); non-numeric answers are not stored. Pass the same
    formula_signature / archetype that verify_problem was given. Returns True if stored."""
    values = parse_numeric_answers(final_answer)
    if values is None:
        return False
    seen_path = seen_path or _SEEN_PATH
    key = _inputs_key(problem, formula_signature or archetype)
    seen = _load_seen(seen_path)
    seen.setdefault(key, []).append({"question_id": question_id, "final_answer": values,
                                     "answer_text": str(final_answer)})
    write_json_atomic(seen_path, seen, ensure_ascii=False)
    return True


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
    obj = _call_json(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
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
    return _call_json(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": system + " Output JSON only."},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
    )


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
    return {"equivalent": as_bool(obj.get("equivalent")), "reason": str(obj.get("reason", "")).strip()}


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
    return {"blocking_flaw": as_bool(obj.get("blocking_flaw")),
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

    Tier 1 (deterministic comparison, numeric answers only): after one extraction
      call reads the candidate's final answer, reject if an accepted question with
      the same numeric inputs has a different numeric answer.
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
    # Step 1 — extract the candidate's final answer (own call, extraction only).
    candidate_answer = _extract_candidate_answer(solution)

    # Tier 1 — numeric answers only, before the expensive blind solve.
    answer_values = parse_numeric_answers(candidate_answer)
    if answer_values is not None:
        dup = check_duplicate_inputs(problem, answer_values, formula_signature or archetype)
        if dup["flagged"]:
            return {
                "independent_solution": "",
                "candidate_final_answer": candidate_answer,
                "semantic_flaws": dup["detail"],
                "verdict": "FAIL",
                "difficulty_rating": "N/A",
                "feedback_for_generator": (
                    "Duplicate-input conflict: " + dup["detail"] +
                    " Re-derive this problem from scratch and confirm the arithmetic "
                    "before resubmitting."
                ),
            }

    # Step 2 — solve the problem blind. Candidate solution is NOT in this prompt.
    independent = _blind_solve(problem, archetype, subject)

    # Step 3 — compare the two answers (own call, comparison only). With either answer
    # missing there is nothing to compare: two empty strings must not count as agreement.
    if not candidate_answer or not independent["final_answer"]:
        missing = "the candidate solution" if not candidate_answer else "the independent blind solve"
        eq = {"equivalent": False, "reason": f"No final answer could be read from {missing}."}
    else:
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
    # Offline Tier 1 demo (no API calls, temporary file — never the live one) on the
    # conflicting pair found in generated_questions_physical.json: identical inputs,
    # two different ages.
    import tempfile
    q = (
        "A zircon crystal contains uranium-238, which undergoes alpha decay to "
        "form lead-206 with a half-life of 4.468e9 years. A sample was found to "
        "contain 1.00 g of uranium-238 and 0.100 g of lead-206. Calculate the "
        "age of the zircon crystal."
    )
    with tempfile.TemporaryDirectory() as d:
        seen = Path(d) / "seen.json"
        record_accepted_inputs(q, "6.44 × 10^9 years", "upb_dating", "GEN_DEMO", seen_path=seen)
        for ans in ("6.44e9 years", "6.440 × 10⁹ years", "2.08e9 years"):
            print(f"{ans!r:24}", check_duplicate_inputs(q, parse_numeric_answers(ans), "upb_dating", seen))
