"""
Model-backed pipeline stages. Each function makes one narrow call and returns plain
data; every decision that follows (accept, retry, queue) is made in code by flow.py.

    propose_inputs      generator: concrete values for the chain's givens, or a veto
    write_stem          generator: the question text around fixed inputs
    gate_extract        extractor: the facts a stem states, read back into a form
    council_solve       council: closed-book solves in parallel (all members, or a named subset)
    verify_member       verifier: one member's attempt against the engine's trace
    clarification_hint  generator: a plain restatement of an unclear part
    solve_with_hint     council member: re-solve with a hint appended
    write_solution      solution writer: readable worked solution (accepted questions only)
"""

from __future__ import annotations

import json
import re
import queue
import threading

from core import models
from core.llm import as_bool, as_number

COUNCIL_MAX_TOKENS = 32000      # thinking models can reason past 16k on hard questions; empty replies otherwise


class CouncilMemberFailed(RuntimeError):
    """A council member's call failed after retries; the question is parked, not judged."""


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _fmt_value(v):
    """Values as an exam would print them: 4e-05 -> '4 × 10⁻⁵', 0.0591 stays."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float) and v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e5):
        mant, exp = f"{v:.4g}".split("e") if "e" in f"{v:.4g}" else (f"{v:.4g}", "0")
        return f"{mant} × 10{str(int(exp)).translate(_SUP)}"
    return str(v)


def _spec_lines(spec: list) -> str:
    out = []
    for s in spec:
        extra = []
        if s.get("unit"):
            extra.append(f"unit: {s['unit']}")
        if s.get("choices"):
            extra.append("one of: " + " | ".join(map(str, s["choices"])))
        elif s.get("range"):
            lo, hi = s["range"]
            extra.append(f"typical range {lo:g}–{hi:g}" if lo is not None and hi is not None else "")
        if s["kind"] in ("dict", "list", "text"):
            extra.append({"dict": "a JSON object", "list": "a JSON list", "text": "text"}[s["kind"]])
        if s["kind"] in ("posint", "count", "integer"):
            extra.append("whole number")
        out.append(f'- "{s["key"]}": {s["desc"]} ({"; ".join(x for x in extra if x)})')
    return "\n".join(out)


# ── 1. Inputs ────────────────────────────────────────────────────────────────

def propose_inputs(subject_name: str, chain_text: str, spec: list, *, refine: dict | None = None,
                   errors: list | None = None) -> dict:
    """{"coherent": bool, "reason": str, "scenario": str, "values": {key: value}}."""
    refine_block = ""
    if refine:
        refine_block = f"""
This chain was already used for a question the solvers found TOO EASY.
Previous values: {json.dumps(refine.get("values"), ensure_ascii=False)}
What to change: {refine.get("summary", "")}
How the solvers got it right:
{refine.get("working") or "(not available)"}
Find the shortcut or standard route they relied on, and choose NEW values or a new scenario
where that route gives the wrong answer (a trap that actually bites, a less obvious system),
not just bigger or messier numbers.
"""
    error_block = ""
    if errors:
        error_block = "\nYour previous values were rejected by the calculation engine:\n" + \
                      "\n".join(f"- {e}" for e in errors) + "\nPropose values that avoid these problems.\n"
    prompt = f"""You design JEE Advanced {subject_name} questions.

A calculation engine will compute the answer from these steps, in this order:
{chain_text}

The question needs a value for each of these inputs:
{_spec_lines(spec)}
{refine_block}{error_block}
First decide: can these steps form ONE coherent problem about one chemical system, where
each step's result really is the quantity the next step uses (same substance, same
sample)? If not, say so and stop.

If yes: invent a concrete, realistic scenario (name the substances) and give a value for
EVERY input. Use realistic JEE values with 2–4 significant figures; text inputs must be
exact strings in the format described (equations use '->'); JSON inputs must be JSON.

Return JSON:
{{"coherent": true or false,
  "reason": "why not, if not coherent",
  "scenario": "one sentence describing the system",
  "values": {{"<input key>": <value>, ...}}}}"""
    role, model = ("refiner", models.REFINER) if refine else ("generator", models.GENERATOR)
    out = models.ask_json(role, model,
                          "You design chemistry problems. Output JSON only.", prompt,
                          max_tokens=3000, temperature=0.8)
    out["coherent"] = as_bool(out.get("coherent"), default=False)
    return out


def coerce_values(spec: list, raw: dict) -> tuple:
    """Turn the generator's values into engine inputs. Returns (values, errors)."""
    values, errors = {}, []
    raw = raw or {}
    for s in spec:
        k = s["key"]
        if k not in raw:
            errors.append(f"no value for {k}")
            continue
        v = raw[k]
        if s["kind"] in ("dict", "list"):
            if isinstance(v, str):
                try:
                    v = json.loads(v)
                except ValueError:
                    errors.append(f"{k} must be JSON")
                    continue
            values[k] = v
        elif s["kind"] in ("text", "choice"):
            values[k] = str(v).strip()
        else:
            n = as_number(v)
            if n is None:
                errors.append(f"{k} must be a number")
                continue
            values[k] = int(round(n)) if s["kind"] in ("posint", "count", "integer") else n
    return values, errors


# ── 2. Stem ──────────────────────────────────────────────────────────────────

def write_stem(subject_name: str, scenario: str, chain_text: str, spec: list, values: dict,
               constants: list, asks: str, unit: str, traps: list, *, previous: str | None = None,
               feedback: str | None = None, solved: str | None = None,
               answer_format: str | None = None) -> str:
    """With `solved` (the council found the previous version too easy), the refiner rewrites
    it, seeing how the solvers got it right; otherwise the generator writes."""
    given_lines = "\n".join(
        f"- {s['desc']}: {_fmt_value(values[s['key']])}{(' ' + s['unit']) if s.get('unit') else ''}"
        for s in spec)
    const_lines = "\n".join(f"- {c}" for c in constants) or "- (none)"
    trap_lines = "\n".join(f"- {t}" for t in traps) or "- (none listed)"
    redo = ""
    if previous:
        redo = f"""
REWRITE this earlier version of the question. Keep every value exactly as listed above.
Earlier version:
{previous}
What must change: {feedback}
"""
        if solved:
            redo += f"""
How strong students solved the earlier version (remove what made this easy: a cue that names
the method, a spelled-out step, an obvious framing; keep it fair and unambiguous):
{solved}
"""
    answer_rule = (f"\nEnd the question with this sentence, copied exactly:\n{answer_format}"
                   if answer_format else "")
    prompt = f"""Write one JEE Advanced {subject_name} question.

Scenario: {scenario}
The intended solution path (do NOT reveal it):
{chain_text}

The question must state each of these values exactly (same number, same unit), in words a
student would read naturally:
{given_lines}

It must state these constants (copy them as written):
{const_lines}

It must ask for exactly one thing: {asks}{(' in ' + unit) if unit else ''}.{answer_rule}

Typical mistakes a strong student could make here (do not warn about them; just make sure
the question does not give them away):
{trap_lines}

Rules: no intermediate results, no hints, no answer; one question (no parts); text only;
no multiple-choice options; do not add data that is not listed. The descriptions above are
internal labels: write natural exam prose and never copy them or template symbols (A, B, x, y,
AxBy) into the question; a subscript is stated by writing the actual formula (AgCl states
x = 1, y = 1). Write powers of ten as × 10ⁿ.
{redo}
Return JSON: {{"stem": "the full question text"}}"""
    role, model = ("refiner", models.REFINER) if solved else ("generator", models.GENERATOR)
    out = models.ask_json(role, model,
                          "You write rigorous chemistry exam questions. Output JSON only.", prompt,
                          max_tokens=2500, temperature=0.6)
    stem = str(out.get("stem") or "").strip()
    if not stem:
        raise ValueError("generator returned an empty stem")
    return stem


def write_fact_stem(subject_name: str, title: str, lead: str, option_lines: list, *,
                    previous: str | None = None, feedback: str | None = None,
                    solved: str | None = None) -> str:
    """A fact (MCQ/MSQ) question: the generator may add one sentence of context; the
    question sentence and the four options must appear exactly as given."""
    opts = "\n".join(option_lines)
    redo = f"\nREWRITE this earlier version:\n{previous}\nWhat must change: {feedback}\n" if previous else ""
    if solved:
        redo += f"\nHow strong students solved it (remove the context cue that made it easy):\n{solved}\n"
    prompt = f"""Write one JEE Advanced {subject_name} multiple-choice question about {title}.

You may begin with at most one short sentence of context. Then copy this question sentence
EXACTLY:
{lead}

Then copy these four options EXACTLY, each on its own line, with their letters:
{opts}

Do not add, remove, reorder or reword any option. Do not reveal the answer.
{redo}
Return JSON: {{"stem": "the full question text"}}"""
    role, model = ("refiner", models.REFINER) if solved else ("generator", models.GENERATOR)
    out = models.ask_json(role, model,
                          "You write rigorous chemistry exam questions. Output JSON only.", prompt,
                          max_tokens=1500, temperature=0.4)
    stem = str(out.get("stem") or "").strip()
    if not stem:
        raise ValueError("generator returned an empty stem")
    return stem


# ── 3. Gate ──────────────────────────────────────────────────────────────────

def gate_extract(stem: str, spec: list, ask_options: list, constants: list) -> dict:
    """Read the stem's facts back into a form. Returns the raw extraction:
    {"values": {key: value|null}, "asked": option_number, "constants_stated": [bool]}."""
    fields = []
    for s in spec:
        how = "a number in the stated unit"
        if s["kind"] == "choice":
            how = "exactly one of: " + " | ".join(map(str, s["choices"]))
        elif s["kind"] == "dict":
            how = "a JSON object"
        elif s["kind"] == "list":
            how = "a JSON list"
        elif s["kind"] == "text":
            how = "the text exactly as written in the question"
        fields.append(f'- "{s["key"]}": {s["desc"]}{(" [" + s["unit"] + "]") if s.get("unit") else ""} — {how}')
    opts = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(ask_options))
    consts = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(constants)) or "(none)"
    prompt = f"""Read this chemistry question and copy facts out of it. Do not solve it.

QUESTION:
{stem}

1) For each field, give the value the question states for it, or null if the question does
not state it. Copy numbers as written (convert "×10^" notation to e-notation); do not
compute anything. A subscript or count that the question states by writing a formula counts
as stated (AgCl gives 1 and 1; Ca3(PO4)2 gives 3 and 2).
{chr(10).join(fields)}

2) What does the question ask for? Pick the number of the option:
{opts}

3) For each constant, does the question state it (true/false)?
{consts}

Return JSON: {{"values": {{"<field>": <value or null>, ...}}, "asked": <option number>,
"constants_stated": [true/false, ...]}}"""
    return models.ask_json("extractor", models.EXTRACTOR,
                           "You extract facts from text precisely. Output JSON only.", prompt,
                           max_tokens=2000, temperature=0.0)


# ── 4. Council ───────────────────────────────────────────────────────────────

_COUNCIL_SYSTEM = "You are a strong JEE Advanced chemistry student. Output JSON only."


def _council_prompt(stem: str, hint: str | None = None) -> str:
    hint_block = f"\nA teacher adds this hint:\n{hint}\n" if hint else ""
    return f"""Solve this problem. Work it out fully yourself.

PROBLEM:
{stem}
{hint_block}
If you believe the problem itself is flawed (impossible, contradictory, missing data, or
wrong chemistry), you may object — but still give your best answer.

Return JSON:
{{"working": "your full step-by-step solution",
  "final_answer": "only the final value (a number, formula or name), without the unit",
  "unit": "the unit of your final answer, or empty",
  "objection": null or {{"type": "chemistry" or "wording", "detail": "what is wrong"}}}}"""


BLANK_RETRIES = 2


_ANSWER_KEYS = ("final_answer", "answer", "final", "result", "value", "final_value")
_WORKING_KEYS = ("working", "solution", "steps", "reasoning", "explanation", "work")


def _first(out: dict, keys):
    for k in keys:
        v = out.get(k)
        if v not in (None, "") and not (isinstance(v, str) and not v.strip()):
            return v
    return None


def _solve(slug: str, stem: str, hint: str | None = None) -> dict:
    """One closed-book attempt. Some models answer {"answer": 100.1} instead of the requested
    keys, or put their working only in the reasoning trace; both are read. A reply with no
    answer and no working at all is a failed call, not a wrong answer: it is asked again,
    and still blank raises (the question parks)."""
    for attempt in range(BLANK_RETRIES + 1):
        out = models.ask_json("council", slug, _COUNCIL_SYSTEM, _council_prompt(stem, hint),
                              max_tokens=COUNCIL_MAX_TOKENS, temperature=0.2,
                              reasoning_effort=models.COUNCIL_REASONING_EFFORT)
        answer = _first(out, _ANSWER_KEYS)
        working = _first(out, _WORKING_KEYS)
        if isinstance(working, (dict, list)):
            working = json.dumps(working, ensure_ascii=False)
        if not working and out.get("_reasoning"):
            working = "(from the model's reasoning trace)\n" + out["_reasoning"]
        out = {**out, "final_answer": answer, "working": working or ""}
        blank = answer is None and not str(working or "").strip()
        if not blank:
            break
        print(f"    [council] {slug} sent a blank reply — asking again ({attempt + 1}/{BLANK_RETRIES})")
    else:
        raise ValueError(f"{slug} sent {BLANK_RETRIES + 1} blank replies")
    obj = out.get("objection")
    if isinstance(obj, dict) and obj.get("type") in ("chemistry", "wording"):
        objection = {"type": obj["type"], "detail": str(obj.get("detail", ""))[:1000]}
    else:
        objection = None
    return {"working": str(out.get("working", ""))[:20000], "final_answer": out.get("final_answer"),
            "unit": str(out.get("unit") or ""), "objection": objection}


def council_solve(stem: str, names=None) -> list:
    """The named members (default: all), in parallel, in roster order. Raises
    CouncilMemberFailed on the first failure: every member called must be measured, so a
    partial result is never judged."""
    roster = [(n, s) for n, s in models.COUNCIL if names is None or n in names]
    done = queue.Queue()

    def run(i, name, slug):
        try:
            done.put((i, {"name": name, "model": slug, **_solve(slug, stem)}, None))
        except Exception as e:                                   # noqa: BLE001
            done.put((i, None, f"{type(e).__name__}: {str(e)[:160]}"))

    for i, (name, slug) in enumerate(roster):
        threading.Thread(target=run, args=(i, name, slug), daemon=True).start()
    members = [None] * len(roster)
    for _ in roster:
        i, rec, err = done.get()
        if err:
            raise CouncilMemberFailed(f"{roster[i][0]}: {err}")
        members[i] = rec
    return members


def solve_with_hint(member: dict, stem: str, hint: str) -> dict:
    try:
        return {"name": member["name"], "model": member["model"], **_solve(member["model"], stem, hint)}
    except Exception as e:                                       # noqa: BLE001
        raise CouncilMemberFailed(f"{member['name']} (hint re-solve): {type(e).__name__}: {str(e)[:160]}")


# ── 5. Mismatch verifier ─────────────────────────────────────────────────────

VERDICTS = ("correct", "right_answer_wrong_reasoning", "wrong", "reference_wrong")
FAILURES = ("genuine_difficulty", "unclear_wording", "missing_knowledge", "slip")


def verify_member(stem: str, trace_text: str, answer_text: str, member: dict, after_hint: str | None = None) -> dict:
    obj = member.get("objection")
    objection = f"\nThe student objected ({obj['type']}): {obj['detail']}\n" if obj else ""
    hint = f"\nThe student was given this hint before this attempt: {after_hint}\n" if after_hint else ""
    prompt = f"""Compare a student's attempt with the reference solution of a chemistry problem.

PROBLEM:
{stem}

REFERENCE SOLUTION (computed exactly; the intended answer is {answer_text}):
{trace_text}
{hint}
STUDENT'S WORKING:
{member.get("working", "")}

STUDENT'S FINAL ANSWER: {member.get("final_answer")} {member.get("unit", "")}
{objection}
Judge:
- "answer_equivalent": true if the student's FINAL ANSWER states the same result as the
  intended answer, ignoring the working, wording, notation and formatting (e.g. "Yes" to
  "does a precipitate form?" equals "precipitate forms"; "shifts to the right" equals
  "forward"; "²³⁴₉₀Th" equals "Th-234"); false if it states a different result or none.
- "verdict": "correct" (right answer by sound reasoning), "right_answer_wrong_reasoning"
  (right answer reached by a wrong or lucky route), "wrong", or "reference_wrong" (the
  reference solution or the problem itself is actually wrong, so the student is not at fault).
- If "wrong", "failure_type": "genuine_difficulty" (a real chemistry/reasoning error, e.g.
  fell into the intended difficulty), "unclear_wording" (the wording reasonably supports the
  student's different reading), "missing_knowledge" (did not know a needed fact or formula),
  or "slip" (method and chemistry right; careless arithmetic, a miscopied number, or a
  format/unit error).
- "failed_step": the number of the reference step where the student first went wrong (or null).
- For a slip: "member_expression": the arithmetic the student set up for the final answer,
  with any miscopied number replaced by the value the problem gives, in the unit asked
  (numbers and + - * / ^ ( ) log ln sqrt exp only).
- For unclear wording: "ambiguous_text" (quote) and "clarification" (one plain sentence).
- For missing knowledge: "missing_fact".
- "objection_assessment": "valid", "invalid" or "unsure" if the student objected, else null.
- "reasoning": two or three sentences.

Return JSON with exactly these keys: answer_equivalent, verdict, failure_type, failed_step,
member_expression, ambiguous_text, clarification, missing_fact, objection_assessment, reasoning."""
    out = models.ask_json("verifier", models.VERIFIER,
                          "You are a meticulous chemistry examiner. Output JSON only.", prompt,
                          max_tokens=2000, temperature=0.0)
    verdict = out.get("verdict") if out.get("verdict") in VERDICTS else "wrong"
    failure = out.get("failure_type") if out.get("failure_type") in FAILURES else None
    if verdict == "wrong" and failure is None:
        failure = "genuine_difficulty"
    step = as_number(out.get("failed_step"))
    eq = out.get("answer_equivalent")
    return {"answer_equivalent": as_bool(eq, default=None) if eq is not None else None,
            "verdict": verdict, "failure_type": failure if verdict == "wrong" else None,
            "failed_step": int(step) if step is not None else None,
            "member_expression": out.get("member_expression"),
            "ambiguous_text": out.get("ambiguous_text"), "clarification": out.get("clarification"),
            "missing_fact": out.get("missing_fact"),
            "objection_assessment": out.get("objection_assessment") if obj else None,
            "reasoning": str(out.get("reasoning", ""))[:1500]}


# ── 5b. Refinement choice ────────────────────────────────────────────────────

def choose_refinement(stem: str, solved_summary: str, modes: tuple) -> dict:
    """Too easy: should the next round change the inputs or only the wording?
    {"mode": one of modes, "feedback": what to change}."""
    if len(modes) == 1:
        return {"mode": modes[0], "feedback": "Make the question harder to answer correctly without changing its facts."}
    prompt = f"""Two or more strong students solved this question correctly, so it is too easy.

QUESTION:
{stem}

How they solved it:
{solved_summary}

Decide what to change for the next version:
- "new_inputs": choose a different system or values so the chemistry itself is harder
  (for example, a case where the usual shortcut gives the wrong answer);
- "reword": keep the facts but remove what made it easy (a giveaway phrase, an obvious
  cue, a step spelled out).

Return JSON: {{"mode": "new_inputs" or "reword", "feedback": "one or two sentences on what to change"}}"""
    out = models.ask_json("refiner", models.REFINER,
                          "You design hard but fair chemistry questions. Output JSON only.", prompt,
                          max_tokens=1500, temperature=0.4)
    mode = out.get("mode") if out.get("mode") in modes else modes[0]
    return {"mode": mode, "feedback": str(out.get("feedback") or "")[:600]}


# ── 6. Hints ─────────────────────────────────────────────────────────────────

def clarification_hint(stem: str, ambiguous_text: str, clarification: str) -> str:
    prompt = f"""A student misread part of this question.

QUESTION:
{stem}

Unclear part: {ambiguous_text}
What it is meant to say: {clarification}

Write ONE sentence that restates only the unclear part plainly. Do not add any method,
formula, step or result.

Return JSON: {{"hint": "..."}}"""
    out = models.ask_json("generator", models.GENERATOR,
                          "You clarify exam questions without solving them. Output JSON only.", prompt,
                          max_tokens=400, temperature=0.2)
    return str(out.get("hint") or clarification or "").strip()


# ── 7. Readable solution ─────────────────────────────────────────────────────

def write_solution(stem: str, trace_text: str, answer_text: str) -> str:
    prompt = f"""Write a clear worked solution for this chemistry question, for a student.

QUESTION:
{stem}

EXACT COMPUTATION (follow it; do not change any number):
{trace_text}

FINAL ANSWER: {answer_text}

Explain each step in words, show the substitution, and end with the final answer.
The solution is ONE plain-text string: numbered steps separated by line breaks, no nested
JSON, no LaTeX. Return JSON: {{"solution": "1. ...\\n2. ...\\nFinal answer: ..."}}"""
    out = models.ask_json("solution_writer", models.SOLUTION_WRITER,
                          "You write clear chemistry solutions. Output JSON only.", prompt,
                          max_tokens=3000, temperature=0.3)
    return _solution_text(out.get("solution"))


def _solution_text(sol) -> str:
    """Readable text from whatever the writer returned: a string as is; a dict or list of
    steps (e.g. {"step1": {"description": ..., "calculation": ...}}) flattened into lines."""
    if isinstance(sol, str):
        return sol.strip()
    lines = []

    def walk(x, depth=0):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, (dict, list)):
                    if re.match(r"(?i)step\s*\d+|^\d+$", str(k)):
                        lines.append(f"Step {re.sub(r'(?i)step\s*', '', str(k))}:")
                    walk(v, depth + 1)
                elif v not in (None, ""):
                    label = "Final answer: " if str(k).lower().startswith("final") else ""
                    lines.append(f"{'  ' * depth}{label}{v}")
        elif isinstance(x, list):
            for v in x:
                walk(v, depth)
        elif x not in (None, ""):
            lines.append(f"{'  ' * depth}{x}")
    walk(sol)
    return "\n".join(lines).strip()
