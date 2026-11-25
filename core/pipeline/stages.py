"""
Model-backed pipeline stages. Each function makes one narrow call and returns plain
data; every decision that follows (accept, retry, queue) is made in code by flow.py.

    propose_inputs      generator: concrete values for the chain's givens, or a veto
    write_stem          generator: the question text around fixed inputs
    gate_extract        extractor: the facts a stem states, read back into a form
    council_solve       council: closed-book solves in parallel (all members, or a named subset)
    solve_with_hint     council member: re-solve with a hint appended
    write_solution      solution writer: readable worked solution (accepted questions only)
"""

from __future__ import annotations

import json
import math
import re
import queue
import threading

from core import answers, models
from core.llm import CutOffError, as_bool, as_number

COUNCIL_MAX_TOKENS = 32000      # thinking models can reason past 16k on hard questions; empty replies otherwise


class CouncilMemberFailed(RuntimeError):
    """A council member's call failed after retries; the question is parked, not judged."""


_SUP = str.maketrans("0123456789-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")


def _fmt_value(v):
    """Values as an exam would print them: 4e-05 -> '4 × 10⁻⁵', 0.0591 stays."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, float) and v != 0 and (abs(v) < 1e-3 or abs(v) >= 1e5):
        mant, exp = f"{v:.3e}".split("e")              # always scientific: 0.00035 -> 3.500e-04
        mant = mant.rstrip("0").rstrip(".")
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
                   errors: list | None = None, traps: list | None = None) -> dict:
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
    trap_block = ("Mistakes this chain is built to catch (never mention them in a question); pick values\n"
                  "where each gives a clearly different but believable answer:\n"
                  + "\n".join(f"- {t}" for t in traps) + "\n") if traps else ""
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
EVERY input. Aim for a JEE Advanced question, not a plug-in exercise:
- prefer a system where recognising which concept applies takes thought;
- choose values where the usual shortcut or approximation would mislead (e.g. a degree of
  dissociation that is not small, a limiting reagent that is not the obvious one);
- avoid round "textbook" numbers that make the path obvious.
{trap_block} Use realistic JEE values with 2–4 significant figures; text inputs must be
exact strings in the format described (equations use '->'); JSON inputs must be JSON.

Return JSON:
{{"coherent": true or false,
  "reason": "why not, if not coherent",
  "scenario": "one sentence describing the system",
  "values": {{"<input key>": <value>, ...}}}}"""
    role, model = ("refiner", models.REFINER) if refine else ("generator", models.GENERATOR)
    out = models.ask_json(role, model,
                          "You design chemistry problems. Output JSON only.", prompt,
                          max_tokens=16000, temperature=0.8)
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

The question must state each of these values exactly (same number, same unit). The labels are
generic internal names ("the substance", "the cation", "particles per unit"); in the question,
call each thing by its actual name from the scenario:
{given_lines}

It must state these constants (copy them as written):
{const_lines}

It must ask for exactly one thing: {asks}{(' in ' + unit) if unit else ''}.{answer_rule}

Typical mistakes a strong student could make here (do not warn about them; just make sure
the question does not give them away):
{trap_lines}

Make it as demanding as a JEE Advanced question, but fair:
- never name the law, equation or method needed, and never hint at the next step;
- do not list the data in the order the solution uses it; place each value where it belongs
  naturally in the description of the system or experiment;
- describe a concrete system or experiment, so the student has to recognise which concepts apply;
- ask only for the final quantity (no intermediate results, no "first find ...");
- it must stay complete and unambiguous: every value above stated, exactly one reading.
Before writing, list what would make this easy for a strong student (a cue word, a spelled-out
step, data in solution order) and avoid each one.

Rules: no intermediate results, no hints, no answer; one question (no parts); text only;
no multiple-choice options; do not add data that is not listed. The descriptions above are
internal labels: write natural exam prose and never copy them or template symbols (A, B, x, y,
AxBy) into the question; a subscript is stated by writing the actual formula (AgCl states
x = 1, y = 1). Write powers of ten as × 10ⁿ.

Write it the way a human JEE paper setter would:
- name substances directly, with the unit right after the number:
  BAD  "a mass of the substance equal to 2.719 g of pure sulfamic acid"
  GOOD "2.719 g of sulfamic acid"
  BAD  "a volume of the cation solution of 100.0 mL"   GOOD "100.0 mL of the Ag⁺ solution"
  BAD  "a concentration of the acid of 0.05"           GOOD "0.05 M acetic acid"
- data a real paper would give as supporting data (molar or equivalent masses, ionisation or
  dissociation behaviour, stoichiometric factors, physical constants) goes in one short
  closing line such as "(Given: equivalent mass of sulfamic acid = 97.09 g eq⁻¹; NaOH → Na⁺ +
  OH⁻)", never as an "Assuming that ..." sentence inside the story. That line holds only
  values and constants listed above: never a value you computed (a logarithm such as
  ln(13.25), a ratio, an intermediate result), which would give the method away;
- whenever an element, compound or ion is named in words, give its formula in brackets right
  after the name, as JEE papers do: "iron (Fe)", "potassium dichromate (K₂Cr₂O₇)",
  "aluminium sulfate (Al₂(SO₄)₃)"; a reaction is named by the formulas of its species;
- state each value once; no filler ("a certain amount of", "the said substance");
- short, plain sentences; no meta-talk about the question or the student.
Finally, re-read the question as an examiner and rewrite any phrase a human setter would not
write, without changing any value.
{redo}
Return JSON: {{"easy_cues_avoided": ["..."], "stem": "the full question text"}}"""
    role, model = ("refiner", models.REFINER) if solved else ("generator", models.GENERATOR)
    out = models.ask_json(role, model,
                          "You write rigorous chemistry exam questions. Output JSON only.", prompt,
                          max_tokens=16000, temperature=0.6)
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
                          max_tokens=8000, temperature=0.4)
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
            how = ("a species: the formula the question gives for it ('iron (Fe)' -> Fe), or null "
                   "if it gives none; a reaction: its equation, or for a reaction told in words "
                   "with formulas ('X is converted into Y') 'X -> Y' with only the coefficients the "
                   "question states; any other text as written")
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
                           max_tokens=8000, temperature=0.0)


# ── 4. Council ───────────────────────────────────────────────────────────────

_COUNCIL_SYSTEM = "You are a strong JEE Advanced chemistry student. Output JSON only."
# Added whenever the calculator is offered. Llama 3.x's chat template adds "Environment: ipython" when tools
# are passed, so Llama wrote Python programs instead of calling the calculator and then replied with nothing
# (it parked the flask question twice). Probe of 2026-11-19, 5 tries each on that question: with the tool
# 0/5 usable (4 programs, 1 loop of 12 calls); with this line 5/5 JSON.
NO_CODE = (" You have NO Python interpreter and no code runs: never write code. For arithmetic call the "
           "calculate function; then reply with only the JSON object.")


def _council_prompt(stem: str, hint: str | None = None, spec: dict | None = None) -> str:
    hint_block = f"\nA teacher adds this hint:\n{hint}\n" if hint else ""
    answer_lines = answers.spec_instruction(spec) if spec else (
        '"final_answer": "only the final value (a number, formula or name), without the unit",\n'
        '"unit": "the unit of your final answer, or empty"')
    return f"""Solve this problem. Work it out fully yourself.

PROBLEM:
{stem}
{hint_block}
If you believe the problem itself is flawed (impossible, contradictory, missing data, or
wrong chemistry), you may object — but still give your best answer.

Return JSON with exactly these keys:
"working": your full step-by-step solution,
{answer_lines},
"objection": null, or {{"type": "chemistry" or "wording", "detail": "what is wrong"}}."""


BLANK_RETRIES = 2


_ANSWER_KEYS = ("final_answer", "answer", "final", "result", "value", "final_value")
_WORKING_KEYS = ("working", "solution", "steps", "reasoning", "explanation", "work")


def _first(out: dict, keys):
    for k in keys:
        v = out.get(k)
        if v not in (None, "") and not (isinstance(v, str) and not v.strip()):
            return v
    return None


def _repair_line(slug: str, stem: str, out: dict, spec: dict, reason: str) -> dict | None:
    """The solver's answer line cannot be used (missing, not a plain number, an unreadable
    unit, ...). Ask it, cheaply, to restate the SAME answer as a correct line; it must not
    re-solve. Returns the completed answer, or None."""
    prompt = f"""You solved this problem:
{stem}

The end of your solution:
{str(out.get("working") or "")[-1500:]}

Your answer was: {json.dumps(out.get("answer") if out.get("answer") is not None else out.get("final_answer"), ensure_ascii=False)}
It cannot be used because: {reason}.

Restate the SAME answer. Do not solve again and do not change the value.
{answers.spec_instruction(spec)}
Return JSON with the single key "answer"."""
    try:
        r = models.ask_json("council", slug, "Output JSON only.", prompt, max_tokens=4000,
                            temperature=0.0, reasoning_effort="low")
    except Exception:                                            # noqa: BLE001 - grading falls back
        return None
    done = answers.complete_answer(answers.parse_answer_line(_first(r, ("answer",) + _ANSWER_KEYS)), spec)
    return done if done.get("ok") else None


def _solve(slug: str, stem: str, hint: str | None = None, spec: dict | None = None) -> dict:
    """One closed-book attempt. The solver writes its working and one answer line
    ([TYPE] [CALC_VALUE] [CALC_UNIT] [SUBSTANCE]); code fills TARGET_UNIT, FINAL_VALUE and
    RENDER. A line that cannot be used gets one restate request; a blank reply is asked
    again, and still blank raises (the question parks)."""
    for attempt in range(BLANK_RETRIES + 1):
        out = models.ask_json("council", slug, _COUNCIL_SYSTEM + NO_CODE, _council_prompt(stem, hint, spec),
                              max_tokens=COUNCIL_MAX_TOKENS, temperature=0.2,
                              reasoning_effort=models.COUNCIL_REASONING_EFFORT,
                              tools=models.CALC_TOOL)
        working = _first(out, _WORKING_KEYS)
        if isinstance(working, (dict, list)):
            working = json.dumps(working, ensure_ascii=False)
        if not working and out.get("_reasoning"):
            working = "(from the model's reasoning trace)\n" + out["_reasoning"]
        line = _first(out, ("answer",)) or _first(out, _ANSWER_KEYS)
        out = {**out, "working": working or "", "answer": line}
        if line is not None or str(working or "").strip():
            break
        print(f"    [council] {slug} sent a blank reply — asking again ({attempt + 1}/{BLANK_RETRIES})")
    else:
        raise ValueError(f"{slug} sent {BLANK_RETRIES + 1} blank replies")
    obj = out.get("objection")
    if isinstance(obj, dict) and obj.get("type") in ("chemistry", "wording"):
        objection = {"type": obj["type"], "detail": str(obj.get("detail", ""))[:1000]}
    else:
        objection = None
    rec = {"working": str(out.get("working", ""))[:20000], "objection": objection,
           "answer_line": None if line is None else str(line),
           # the model's own thinking and, with the calculator, every round (thinking, call, result): kept
           # for the dataset (supervised fine-tuning traces), never graded
           "reasoning": out.get("_reasoning"), "turns": out.get("_turns")}
    if not spec:                                                 # no spec: the raw answer is graded
        rec.update(final_answer=line, unit=str(out.get("unit") or ""))
        return rec
    done = answers.complete_answer(answers.parse_answer_line(line), spec)
    if not done.get("ok"):
        reason = done.get("reason", "")
        fixed = _repair_line(slug, stem, out, spec, reason)
        rec["format_repaired"] = fixed is not None
        print(f"    [council] {slug}: answer line unusable ({reason}); "
              + (f"restated as {fixed['render']!r}" if fixed else "restate failed"))
        done = fixed or {"ok": False, "reason": reason}
    if done.get("ok"):
        rec.update(final_answer=done["render"], unit="", answer_type=done.get("type"),
                   calc_value=done["calc_value"], calc_unit=done.get("calc_unit"),
                   target_unit=done.get("target_unit"), final_value=done["final_value"],
                   substance=done.get("substance"))
    else:                                                        # graded by the verifier's equivalence
        rec.update(final_answer=line, unit="", answer_unusable=done.get("reason"))
    return rec


def council_solve(stem: str, names=None, spec: dict | None = None) -> list:
    """The named members (default: all), in parallel, in roster order. Raises
    CouncilMemberFailed on the first failure: every member called must be measured, so a
    partial result is never judged."""
    roster = [(n, s) for n, s in models.COUNCIL if names is None or n in names]
    done = queue.Queue()

    def run(i, name, slug):
        try:
            done.put((i, {"name": name, "model": slug, **_solve(slug, stem, spec=spec)}, None))
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


def solve_with_hint(member: dict, stem: str, hint: str, spec: dict | None = None) -> dict:
    try:
        return {"name": member["name"], "model": member["model"], **_solve(member["model"], stem, hint, spec)}
    except Exception as e:                                       # noqa: BLE001
        raise CouncilMemberFailed(f"{member['name']} (hint re-solve): {type(e).__name__}: {str(e)[:160]}")


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
                          max_tokens=8000, temperature=0.4)
    mode = out.get("mode") if out.get("mode") in modes else modes[0]
    return {"mode": mode, "feedback": str(out.get("feedback") or "")[:600]}


# ── 7. Readable solution ─────────────────────────────────────────────────────

def write_solution(stem: str, trace_text: str, answer_text: str, *, previous: str | None = None,
                   problems: list | None = None) -> str:
    redo = ""
    if previous:
        found = "\n".join(f"- {p}" for p in problems or [])
        redo = f"""
Your earlier solution had these errors. Write the whole solution again with every one fixed:
{found}

Earlier solution:
{previous}
"""
    prompt = f"""Write a clear worked solution for this chemistry question, for a student.

QUESTION:
{stem}

EXACT COMPUTATION (follow it; do not change any number):
{trace_text}

FINAL ANSWER: {answer_text}

Explain each step in words, show the substitution, and end with the final answer.
- Each step must reach that step's result from the exact computation, with the arithmetic
  written out, e.g. "0.025 mol × 1.5 = 0.0375 mol"; every calculation you write must be true.
- Where a step's formula needs a ratio, n-factor or molar mass that the computation does not
  list, derive it from the formula shown and check that it gives the step's result.
- Never state a ratio, quantity or label that contradicts the computation; do not invent
  extra quantities.
The solution is ONE plain-text string: numbered steps separated by line breaks, no nested
JSON, no LaTeX. The last line is "Final answer: <answer>".
{redo}
Return JSON: {{"solution": "1. ...\\n2. ...\\nFinal answer: ..."}}"""
    system = "You write clear chemistry solutions. Output JSON only."
    try:
        out = models.ask_json("solution_writer", models.SOLUTION_WRITER, system, prompt,
                              max_tokens=8000, temperature=0.3, retry_cut_off=False)
    except CutOffError as e:
        out = finish_solution(prompt, system, e)
    return _solution_text(out.get("solution"))


SOLUTION_THOUGHT_CHARS = 12000      # how much of the cut-off reply's thinking the finish call is shown (its end)


def finish_solution(prompt: str, system: str, cut: CutOffError) -> dict:
    """The solution reply was cut off at the output limit after long thinking (3 physical replies, 2026-11-25:
    ~800 characters written). Asking the same prompt again pays for the same cut-off, so, as finish_design does
    for the designer, the writer finishes from what it wrote and its thinking so far. Its thinking level is
    left as it is (a low level wrote worse solutions). Raises ValueError if nothing was written or thought."""
    if not cut.partial.strip() and not cut.reasoning:
        raise ValueError(f"solution cut off before any text was written: {cut}")
    print("    [solution_writer] reply cut off at the output limit; finishing it from its thinking so far")
    thought = (f"\nYOUR THINKING SO FAR (end of it):\n{cut.reasoning[-SOLUTION_THOUGHT_CHARS:]}\n"
               if cut.reasoning else "")
    finish = f"""{prompt}

Your earlier reply to this was cut off at the output limit. This is what you had written of the JSON:
{cut.partial}
{thought}
Do not start over and do not redo the working: your thinking above already has it. Keep what you wrote,
complete the solution from where it stops, and return the COMPLETE JSON object and nothing else."""
    return models.ask_json("solution_writer", models.SOLUTION_WRITER, system, finish,
                           max_tokens=8000, temperature=0.3, retry_cut_off=False)


def check_solution(stem: str, trace_text: str, answer_text: str, solution: str) -> list:
    """The mismatch verifier reads a written solution against the exact computation and
    reports every step that is wrong. Returns [{"step", "quote", "problem"}] (empty: correct)."""
    numbered = "\n".join(f"[{i}] {ln}" for i, ln in enumerate(
        (ln for ln in str(solution).splitlines() if ln.strip()), 1))
    prompt = f"""A worked solution was written for a student from an exact reference computation.
Check it step by step and find every place where it is wrong.

QUESTION:
{stem}

EXACT REFERENCE COMPUTATION (correct; the final answer is {answer_text}):
{trace_text}

WRITTEN SOLUTION (lines numbered):
{numbered}

Report an error for every line that:
- states a ratio, n-factor, coefficient, molar mass or formula that is wrong or does not lead
  to the reference step's result;
- writes a calculation that is false (check every one), or reaches a step's result by
  arithmetic that does not give it;
- labels or explains a quantity wrongly (e.g. calls the amount used the amount left);
- contradicts itself or the reference computation;
- gives a final answer different from the reference.
Do not report wording, style, or extra correct explanation. If every line is correct,
return an empty list.

Return JSON: {{"errors": [{{"line": <line number>, "quote": "the exact wrong text, copied",
"problem": "what is wrong and what is right"}}]}}"""
    out = models.ask_json("solution_checker", models.SOLUTION_CHECKER,
                          "You are a meticulous chemistry examiner. Output JSON only.", prompt,
                          max_tokens=6000, temperature=0.0)
    errs = out.get("errors")
    if errs is None:
        raise ValueError("solution checker returned no 'errors' list")
    if isinstance(errs, dict):
        errs = [errs]
    if not isinstance(errs, list):
        raise ValueError("solution checker returned no 'errors' list")
    found = []
    for e in errs:
        if isinstance(e, str) and e.strip():
            found.append({"line": None, "quote": "", "problem": e.strip()})
        elif isinstance(e, dict) and (e.get("problem") or e.get("quote")):
            found.append({"line": as_number(e.get("line")), "quote": str(e.get("quote") or "").strip(),
                          "problem": str(e.get("problem") or "").strip()})
    return found


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
                        step_num = re.sub(r"(?i)step\s*", "", str(k))
                        lines.append(f"Step {step_num}:")
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
