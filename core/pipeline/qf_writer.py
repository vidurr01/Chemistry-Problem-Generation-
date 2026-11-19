"""Question first, stage 3: WRITE.

The writer writes the question with every number as a blank [[name]] and a range for it, or a fixed
value for a value of the substance itself (write_question, BLANK_RULES). parse_values reads the
ranges; blank_problems sends a question with broken blanks back before any program is paid for."""

from __future__ import annotations

import json
import keyword
import math
import re

from core import models
from core.pipeline.qf_text import PLACEHOLDER, _fmt_number, _free_number, _sig_digits
from core.pipeline.qf_draw import TWISTS


# One draft per draw (2026-11-19, the author): over 21 draws that reached the writer, 9 passed on the first draft,
# 12 failed all three and none was rescued by a rewrite, so a failed draft means a new draw. (The too-easy
# refinement is separate and keeps its rounds.) Unreadable replies are retried without counting (qfirst).
WRITE_TRIES = 1


BLANK_RULES = """NUMBERS AS BLANKS. You do not choose the numbers: after a program has been written from your question, code
picks them inside the ranges you give and checks them with the formulas, so they always agree.
- Write EVERY number the question states as a placeholder [[name]] (letters, digits, _), with its unit
  after it as usual: "[[m_sample]] g of the ore", "an EMF of [[E_cell]] V".
- In "values", give for EACH placeholder EITHER {"range": [low, high]}: a realistic range, in the unit
  written after it, for every value that could be many things (amounts, masses, volumes, temperatures,
  concentrations, times, measured results such as an EMF, a titre or a density); choose a range in which
  the situation is physically real throughout (each substance in its stated phase, sensible conditions) -
  OR {"value": x} ONLY for a value that belongs to the substance or the situation itself: a molar mass, a
  standard potential, a tabulated ΔfH° or S°, the 8 corners of a cube.
- A COUNT (half-lives, electrons, ions per formula, atoms) is whole: {"range": [2, 5], "whole": true}
  or a whole value {"value": 8}. Every other range gives values to 3 significant figures, even when
  you write its ends as whole numbers ([250, 600] for a temperature).
- "answer_range": [low, high], a realistic range for the answer in "unit"; values that give an answer
  outside it are not used.
- The constants of the closing "(Given: ...)" line (R, F, N_A, h, c, k_B) are placeholders too, each with
  its standard value: "R = [[R]] J K^-1 mol^-1" and "R": {"value": 8.314}.
- POWERS OF TEN: never write "× 10^n" next to a placeholder or in "unit"; the code prints each number in
  full, with its own power of ten when it needs one. Ranges and values are plain JSON numbers: [1e-5, 5e-4],
  never strings, never with a unit inside.
- Write EVERY power as a^b: 2^6, e^12, (1/2)^3, cm^3, mol^-1 (no superscripts). Any number in a power
  that is data is a placeholder too: "after [[n]] half-lives".
- "unit": the plain unit of the answer ("Hz", "kJ mol⁻¹", "mol L⁻¹"), never with a factor or a power of
  ten in it.
- "asked": a name for the asked quantity. It must NOT appear as a placeholder in the question.
- Every value with a range must be needed to find the answer. A fixed value may be background the answer
  does not need ("under standard conditions, 1 bar and 298 K"), as in real papers; state nothing else the
  solver does not need.
"""   # how the writer states numbers: as blanks with ranges (also tools/step_by_step.py real)


def write_question(subject_name: str, formulas: str, library: str, constants: list, twist: str,
                   examples: list, traps: list, *, previous: str | None = None,
                   feedback: str | None = None, solved: str | None = None, used: list | None = None,
                   design: dict | None = None) -> dict:
    """{"stem", "asks", "unit", ...}: a new question that needs all the formulas, with the twist;
    or {"impossible": reason} when no sensible question can use all of them."""
    ex = "\n".join(f"{i + 1}. ({e['id']}) {e['text']}" for i, e in enumerate(examples)) or "(none)"
    const_lines = "\n".join(f"- {c}" for c in constants) or "- (none)"
    trap_lines = "\n".join(f"- {t}" for t in traps) or "- (none listed)"
    redo = ""
    if previous:
        redo = f"""
REWRITE your earlier question. Earlier version:
{previous}
What must change: {feedback}
"""
        if solved:
            redo += f"""
It was TOO EASY: strong students solved it like this. Remove what made it easy (an obvious
framing, a cue to the method, a direct route); make the reasoning genuinely harder, not the
numbers messier:
{solved}
"""
    used_block = ""
    if used:
        used_block = ("\nSITUATIONS ALREADY USED in our accepted questions on these chapters (do not reuse "
                      "their system, substances or set-up; find a different situation):\n"
                      + "\n".join(f"- {u}" for u in used) + "\n")
    if design:
        task = f"""You set papers for JEE Advanced {subject_name}. Write ONE new numerical question that
belongs among the hardest questions of a real paper, by WRITING UP the design below: it was planned by
a senior setter; your job is to turn it into the exact question text, faithfully.

THE DESIGN:
""" + "\n".join(f"- {k.replace('_', ' ')}: {design[k]}" for k in
                ("system", "hidden_link", "route", "student_must_notice", "trap", "given", "hidden", "asked")
                if design.get(k)) + f"""

How to write it up:
- state exactly the quantities under "given", and NOT those under "hidden": the hidden link and every
  intermediate stay unstated, so the student must find the connection;
- never state or hint at what the student must notice; never name a law, equation or method;
- do not give the data in the order the route uses them;
- nothing the solver should work out is given: no ratio ("1 mol reacts with 6 mol"), n-factor,
  equivalent mass or intermediate result that one of the formulas computes.

The formulas the design uses (their inputs, units and typical ranges):
{formulas}

{library}

Constants the formulas use; the question must state each of them in its closing "Given" line:
{const_lines}

HOW THE FORMULAS MUST BE USED (the twist): {TWISTS[twist]}
{used_block}
"""
    else:
        task = f"""You set papers for JEE Advanced {subject_name}. Write ONE new numerical question that
belongs among the hardest questions of a real paper.

These formulas were drawn AT RANDOM from the syllabus; they need not be related. Design one
coherent situation in which ALL of them are genuinely needed for the one answer (each result
must change the answer), and no other chemistry relation is needed (unit conversions and simple
arithmetic between results are fine). Connecting them in a natural, unexpected way is part of
what makes the question hard; joining unrelated parts by mere arithmetic is not acceptable:
{formulas}

A simple standard relation of the syllabus may be used alongside them where the situation needs
it (n = m/M, a unit conversion); the drawn formulas stay at the heart of the question.

What each formula takes and gives (units and typical ranges):
{library}

Constants the formulas use; the question must state each of them in its closing "Given" line:
{const_lines}

HOW THE FORMULAS MUST BE USED (the twist): {TWISTS[twist]}

Real JEE Advanced questions with this twist, to show its difficulty and style ONLY:
{ex}
Write a HARD, JEE Advanced style question of your own. Do NOT copy these examples, and do NOT
simply put one of them into a different scenario (other substances or numbers on the same
problem): your question must not reuse their chemical system, substances, numbers, sentence
structure or what they ask, and a teacher who knows these papers must not recognise it as a
variant of either. Build it from the drawn formulas, in a situation where they arise
naturally, and make the twist the heart of the problem.

{used_block}
"""
    prompt = task + f"""
NEVER INVENT A RELATION. Every equation the solution uses must be one of the formulas above or a
standard relation of the syllabus. Do not link quantities by a made-up rule (for example "ΔG° =
−(purity × number of peaks)"), and do not glue separate sub-problems together by arithmetic. A
question built that way is rejected. If the formulas cannot be joined by real chemistry in one
situation, return "impossible" instead.

Make it hard but fair:
- no intermediate result is given or asked; every formula's result must affect the answer, so
  no shortcut skips one;
- never name a law, equation or method; no hints; do not give data in the order it is used;
- choose the situation and the ranges so that these typical mistakes give clearly different, believable
  answers:
{trap_lines}
- complete and unambiguous: every value needed is stated once, exactly one reading, exactly one
  numerical answer; do not state anything a formula above computes;
- no giveaways: never state a ratio ("1 mol reacts with 6 mol"), an n-factor, an equivalent mass or
  any intermediate the solver should work out (the accepted bank had both: they made hard questions easy);
- one question, no parts, no options, text only (no graph or figure).

Write it as a human paper setter would: name substances directly with their formulas in
brackets ("potassium dichromate (K₂Cr₂O₇)"), plain text with Unicode subscripts and symbols, never
LaTeX or $...$ (write "(∂E°/∂T)ₚ", not "$(\\partial E^\\circ/\\partial T)_P$"), the unit right after
each number, short plain sentences, supporting data and the constants in one closing line
"(Given: ...)". Do not write the answer-format sentence (it is added automatically).

{BLANK_RULES}{redo}

If no sensible JEE question can genuinely need ALL of the drawn formulas, return only
{{"impossible": "why"}}. Otherwise return JSON (nothing else):
{{"asks": "the quantity asked, in words",
  "unit": "the plain unit of the answer, no power of ten (empty if dimensionless)",
  "asked": "name of the asked quantity",
  "values": {{"name": {{"range": [low, high]}}, "other_name": {{"value": x}}, ...}},
  "answer_range": [low, high],
  "links": ["Formula 1: takes [[a]], [[b]]; its result feeds Formula 3", "... one line for EVERY formula"],
  "stem": "the full question text, with every number as [[name]]"}}

Before the stem, plan "links": for EVERY formula above, which stated values it takes and where its
result goes. A question that does not need one of the formulas is rejected. A formula whose result a
student knows by heart (Z = 4 for fcc, 22.4 L) is not needed unless the question makes the solver
work it out (an unusual arrangement, a non-standard condition)."""
    role, model = "generator", models.GENERATOR       # the writer also does every rewrite (refine.py decides what)
    out = models.ask_json(role, model, "You set rigorous chemistry exam papers. Output JSON only.", prompt,
                          max_tokens=8000, temperature=0.8, reasoning_effort="low",
                          retry_cut_off=False)
    if out.get("impossible") and not str(out.get("stem") or "").strip():
        return {"impossible": str(out["impossible"])}
    if not str(out.get("stem") or "").strip() or not str(out.get("asks") or "").strip():
        raise ValueError("the writer returned no stem or no asked quantity")
    q = {k: (str(out.get(k)).strip() if out.get(k) is not None else "") for k in ("stem", "asks", "unit", "asked")}
    q.update(parse_values(out))
    return q


# Constants a question states in its Given line that the formulas hold themselves (R, F, N_A, h, c, k_B ...):
# a stated value equal to one of these need not be used by the program.
STANDARD_CONSTANTS = (8.314, 8.3145, 0.0821, 0.08206, 0.0831, 1.987, 96500, 96485, 6.022e23, 6.023e23, 6.02e23,
                      6.626e-34, 6.63e-34, 3e8, 2.998e8, 1.38e-23, 1.381e-23, 1.602e-19, 9.109e-31, 2.303, 101325,
                      760, 22.4, 22.7, 273.15, 0.0591, 0.059, 2.18e-18, 1.097e7)


def _reserved_names() -> set:
    """Every name the solving program already has (core/engine/sandbox.py): a blank named "list" hid the
    built-in, and one named "calculate" was skipped, so the program read the function instead of the value."""
    from core.engine import sandbox
    return ({"math", "given", "find", "solve_for", "solve", "calculate", "True", "False", "None"}
            | set(sandbox._SAFE_BUILTINS))


_RESERVED = _reserved_names()


def _num(v):
    from core.llm import as_number
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    n = as_number(v)
    return n if n is not None else _free_number(v)


def parse_values(out: dict) -> dict:
    """The writer's "values" (each placeholder: {"range": [lo, hi]} or {"value": x}) and "answer_range" as
    {"ranges": {name: (lo, hi, whole)}, "fixed": {name: value}, "answer_range": (lo, hi) or None,
    "free": the fixed values (shown in previews)}. A range is a count (whole numbers) only when marked
    "whole": true: a writer wrote [250, 600] for a temperature and [1, 8] for a volume ,
    and those must not come out as 329 K and 5 L only."""
    ranges, fixed, bad = {}, {}, []
    vals = out.get("values") if isinstance(out.get("values"), dict) else {}
    for k, spec in vals.items():
        k = str(k)
        if isinstance(spec, dict) and "range" in spec:
            r = spec.get("range")
            lo, hi = (_num(r[0]), _num(r[1])) if isinstance(r, (list, tuple)) and len(r) == 2 else (None, None)
            if lo is None or hi is None or not (math.isfinite(lo) and math.isfinite(hi)) or lo >= hi:
                bad.append(k)
                continue
            whole = spec.get("whole") is True or str(spec.get("whole")).lower() == "true"
            if whole and not (float(lo).is_integer() and float(hi).is_integer()):
                bad.append(k)                    # a count needs whole ends
                continue
            ranges[k] = (int(lo), int(hi), True) if whole else (float(lo), float(hi), False)
        else:
            v = _num(spec.get("value") if isinstance(spec, dict) else spec)
            if v is None or not math.isfinite(v):
                bad.append(k)
                continue
            fixed[k] = v
    for k, v in (out.get("free") or {}).items() if isinstance(out.get("free"), dict) else []:
        n = _num(v)                              # the earlier format: chosen values, taken as fixed
        if n is not None and str(k) not in ranges:
            fixed.setdefault(str(k), n)
    ar = out.get("answer_range")
    ans = None
    if isinstance(ar, (list, tuple)) and len(ar) == 2:
        lo, hi = _num(ar[0]), _num(ar[1])
        if lo is not None and hi is not None and lo < hi:
            ans = (float(lo), float(hi))
    return {"ranges": ranges, "fixed": fixed, "answer_range": ans, "free": dict(fixed), "bad_values": bad}


def blank_problems(q: dict) -> list:
    """What is wrong with the writer's blanks, in words it can act on (no program is paid for yet)."""
    template, asked = q.get("stem") or "", q.get("asked") or ""
    names = list(dict.fromkeys(PLACEHOLDER.findall(template)))
    ranges, fixed = q.get("ranges") or {}, q.get("fixed") or {}
    probs = []
    if not names:
        return ["the question states its numbers directly; write EVERY number as a placeholder [[name]] and "
                "give each one a range (or, for a value of the substance itself, a value) in \"values\""]
    if asked and asked in names:
        probs.append(f"the question shows the asked quantity [[{asked}]]; remove it from the text")
    power = re.search(r"\]\]\s*(?:[×x*]\s*)?10\s*(?:\^|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺])", template) or \
        re.search(r"10\s*(?:\^|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺])|[×x]\s*10\b", str(q.get("unit") or ""))
    if power:
        probs.append("a power of ten is written next to a placeholder or in the unit "
                     f"({power.group(0)!r}): write only '[[name]] unit' and give the range in full "
                     "([1e-5, 5e-4], not [1, 50] with × 10^-5); the unit carries no power of ten")
    if q.get("bad_values"):
        probs.append(f"unusable range or value for {', '.join(q['bad_values'])}: give [low, high] with low < high, "
                     f"or one plain number")
    missing = [n for n in names if n not in ranges and n not in fixed and n != asked]
    if missing:
        probs.append(f"no range or value for {', '.join('[[' + n + ']]' for n in missing)}: give each placeholder "
                     f"a range in \"values\" (or a value, if it belongs to the substance)")
    reserved = [n for n in names if n in _RESERVED or re.fullmatch(r"step_\d+", n) or keyword.iskeyword(n)
                or n.startswith("__")]                   # the sandbox refuses any name starting with "__"
    if reserved:
        probs.append(f"choose other names for {', '.join(reserved)} (they are reserved words of the program)")
    return probs


def constant_names(fixed: dict) -> list:
    """Fixed values that are standard constants (R, F, N_A ...): the steps hold their own, so a program need
    not use the stated ones."""
    return [k for k, v in fixed.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
            and any(c and abs(v - c) <= 2e-3 * abs(c) for c in STANDARD_CONSTANTS)]


def _typical(spec):
    """A typical value of a range blank: the middle (geometric for a wide positive range), 3 figures."""
    lo, hi, whole = (list(spec) + [False])[:3]
    if whole:
        return int(round((lo + hi) / 2))
    mid = math.sqrt(lo * hi) if lo > 0 and hi / lo >= 20 else (lo + hi) / 2
    return float(f"{mid:.3g}")


def preview_text(q: dict) -> str:
    """The written question as a reader sees it before its numbers are picked: the writer's fixed values in
    place, each range blank at a typical value of its range, anything else as '…'."""
    vals = dict(q.get("free") or {})
    vals.update(q.get("fixed") or {})
    for k, spec in (q.get("ranges") or {}).items():
        try:
            vals[k] = _typical(spec)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    def shown(m):                                # as fill_template prints it ("8 corners", not "8.00")
        v = vals.get(m.group(1))
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return "…"
        return str(v) if isinstance(v, int) else _fmt_number(float(v), max(3, min(_sig_digits(float(v)), 10)))
    return PLACEHOLDER.sub(shown, q.get("stem") or "")


def previous_text(q: dict) -> str:
    """The earlier question for a rewrite: its text with the blanks and the ranges and values it gave."""
    # a count keeps "whole": true (it was dropped, so the rewrite's count came back as a plain range)
    spec = {k: {"range": list(v[:2]), **({"whole": True} if len(v) > 2 and v[2] else {})}
            for k, v in (q.get("ranges") or {}).items()}
    spec.update({k: {"value": v} for k, v in (q.get("fixed") or {}).items() if k not in spec})
    out = q.get("stem") or ""
    if spec:
        out += "\nIts values: " + json.dumps(spec, ensure_ascii=False)
    if q.get("answer_range"):
        out += f"\nIts answer_range: {list(q['answer_range'])}"
    return out


def blank_names(q: dict) -> list:
    """The question's blanks in order of appearance (the asked quantity is never one)."""
    asked = q.get("asked") or ""
    return [n for n in dict.fromkeys(PLACEHOLDER.findall(q.get("stem") or "")) if n != asked]


def blank_spec(q: dict):
    """(names, ranges {name: (lo, hi, whole)}, fixed {name: value}) for the blanks the question shows; a
    range or value the writer gave for a name the question does not show is ignored."""
    names = blank_names(q)
    ranges = {k: tuple(v) for k, v in (q.get("ranges") or {}).items() if k in names}
    fixed = {k: v for k, v in (q.get("fixed") or {}).items() if k in names and k not in ranges}
    return names, ranges, fixed
