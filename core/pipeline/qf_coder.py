"""Question first, stage 4: SOLVE (coder 2, Luna).

The program that solves the question from its blanks, before any number is chosen
(solver_program, write_blank_program). A probe runs it on values from the ranges first: a program
that breaks, assigns to a blank or ignores a picked value goes back to the coder.
program_for / write_program: the older path for a question that states its own numbers."""

from __future__ import annotations

import re

from core import models
from core.engine import sandbox
from core.pipeline.qf_text import PLACEHOLDER
from core.pipeline.qf_writer import blank_spec, constant_names
from core.pipeline.qf_checks import unneeded


CODE_TRIES = 3          # programs written per question (each retry gets the previous errors)


def write_program(stem: str, asks: str, unit: str, library: str, *, previous: str | None = None,
                  errors: list | None = None, model: str | None = None, txs=None) -> dict:
    """{"code": "..."} or {"cannot": "reason"} from the coder."""
    redo = ""
    if previous:
        redo = "\nYour previous program:\n" + previous + "\nwas rejected:\n" + \
               "\n".join(f"- {e}" for e in errors or []) + "\nFix it.\n"
    prompt = f"""Write a Python program that solves this chemistry question using ONLY the functions below.

QUESTION:
{stem}

Asked: {asks}{(' in ' + unit) if unit else ''}.

FUNCTIONS (the formulas the question is built on: chapter, formula, inputs, outputs and the
engine's own code; each checks its inputs and returns a dict). Call each of them at least once:
{library}

Also available: given(value, "quote"), find(step_N, "input", result=..., **other inputs),
solve_for(f, lo, hi), math (math.log, math.exp, math.sqrt ...),
calculate(expr) (exact arithmetic: calculate("2.5 * 6.022e23 / 1000") — use this instead of
typing intermediate numbers by hand to avoid arithmetic errors),
abs, min, max, sum, range, len (never round, int, floor or ceil a computed value).

EXACT CALLS (copy these; replace ... with your values):
{exact_calls(txs or [])}

HOW TO PROCEED: take every stated value with given(); then follow the formulas from them to the
asked quantity. For each formula: if you know all its inputs, use its forward line; if you know its
output and all inputs but one, use the backward line for that input. Two unknowns fixed only by two
formulas together: solve_for. Do not guess names: use the ones in EXACT CALLS.

{_MISTAKES}

How the functions work (the engine code above is for reference only):
- each step_<n>(...) returns a DICT: take the number you need with its key, e.g.
  step_100(...)["most_probable_speed"]; never multiply or compare the dict itself;
- inside solve() there is NO "C", no constants module and no imports: the steps hold their own
  constants (R, F, N_A ...); never write C.R_J or similar;
- take every given value first, at the top of solve(); define inner functions after that, and pass
  values to them as arguments.

Rules:
- call every step function with keyword arguments only, named exactly as listed (step_92(P_wet=...,
  aqueous_tension=...)), never positionally;
- define solve() that returns the answer as ONE number{(' in ' + unit) if unit else ''};
- every value taken from the question enters through given(value, "quote"): value exactly as the
  question writes it (25 for "25 °C"; convert afterwards), quote = the words of the question that
  state it, copied character for character; text values (an equation, a substance) too;
- use every value the solution needs; a value the question gives only to help hand arithmetic (log 2 = 0.30,
  ln 10 = 2.303) or a constant the functions hold is simply left out. NEVER put a value into the answer only
  to have used it (+ log 2 − log 2, × P / P): that changes a right answer into a wrong one (2022P1_Q3: the
  right pH 10.02 became 10.62). Call every function above at least once;
- never type in a value one of the functions computes (Z = 4 for fcc, an n-factor, 22.4 L): call it;
- never write a function's formula yourself: use the function's result in the calculation (a call
  whose result is thrown away does not count);
- the chemistry goes through these functions; besides them write only simple standard relations
  the question needs (n = m/M), unit conversions (× 1000, + 273.15 ...) and the arithmetic that
  combines results as the question asks (a ratio, a difference, an equality); never type a
  physical constant (R, F, N_A, h, k_w ...);
- to run ONE formula backwards (you know its result and need one of its inputs), use
  find(step_N, "input_name", result=value, **its other inputs), e.g.
  R = find(step_247, "resistance", result=kappa, cell_constant=G); it returns the input's value;
  "result" is the value of the function's OUTPUT (not one of its inputs);
- for an unknown that a later result fixes, use solve_for(f, lo, hi): f(x) is the mismatch for a
  trial x;
- NO import line at all: math (math.log, math.exp, math.sqrt ...) is already there; a program with
  "import math" or "from math import ..." is rejected before it runs (Qwen3 Coder wrote one in 5 of 8
  programs, 2026-11-17);
- no printing, nothing else.
If the question cannot be solved with these functions alone, is ambiguous, or lacks a value,
return instead {{"cannot": "<one sentence naming what is missing or ambiguous>"}}.
{redo}
Return JSON: {{"code": "def solve():\\n    ..."}}"""
    # a solve() program is 20-40 lines: 4000 tokens is ample, and caps what a runaway reply costs
    model = model or models.CODER
    out = models.ask_json("coder", model, "You write exact scientific Python. Output JSON only.", prompt,
                          max_tokens=models.coder_tokens(model), temperature=0.1,
                          fallbacks=models.CODER_FALLBACKS if model == models.CODER else ())
    return _code_reply(out)


def _code_reply(out: dict) -> dict:
    """{"code"} or {"cannot"} from a coder's JSON reply; ValueError for neither."""
    why = str(out.get("cannot") or "").strip()
    # a real reason only: a coder once copied the format's placeholder ("the reason") back
    if why and len(why) > 15 and why.lower() not in ("the reason", "<the reason>", "null", "none") \
            and not str(out.get("code") or "").strip():
        return {"cannot": why, **_thinking(out)}
    if why and not str(out.get("code") or "").strip():
        raise ValueError(f"the reply has neither code nor a reason (cannot = {why!r})")
    code = str(out.get("code") or "").strip()
    if not code:
        raise ValueError("the coder returned no code")
    return {"code": code, **_thinking(out)}


def _thinking(out: dict) -> dict:
    """The coder's thinking when the provider sent it (kept for the dataset), else nothing."""
    return {"reasoning": out["_reasoning"]} if out.get("_reasoning") else {}


def coder_for(attempt: int, escalate: bool, quiet: bool = False) -> str:
    """The coder (models.CODER); the last try (or the next one after the same failure twice) goes to
    models.CODER_STRONG when one is set, which says so. The numbers are no longer a coder's: code picks
    them (pick_numbers), so there is no number coder."""
    strong = models.CODER_STRONG
    if strong and strong != models.CODER and (escalate or attempt == CODE_TRIES - 1):
        if not quiet:
            print(f"    [coder] this try goes to the stronger coder {strong}")
        return strong
    return models.CODER


def _coder_hint(problem: str, free: dict | None) -> str:
    """A NameError said in words the coder can act on ("name 'C' is not defined": the
    coder wanted a constants module)."""
    m = re.match(r"NameError: name '(\w+)' is not defined", problem)
    if not m:
        return problem
    name = m.group(1)
    where = (f"the only predefined names are {', '.join(free)}" if free is not None
             else "nothing is predefined except the step_N functions, given, find, solve_for and math")
    extra = (" There is no constants module: take every constant the question states (R, F, N_A ...) with "
             "given(value, 'quote'), like any other value." if name in ("C", "const", "constants", "R", "F", "N_A",
                                                                        "h", "k", "c") else "")
    return f"{problem}: {where}; define {name} inside solve() before using it.{extra}"


def named_values(template: str, names, values: dict | None = None, asked: str = "", unit: str = "") -> str:
    """Each of the writer's names with what it IS: the words of the question around its placeholder
    (which carry its unit), e.g. 'P_aq = 0.031  ← "... an aqueous tension of [[P_aq]] atm at ..."'.
    The coder used to get a bare JSON {"P_aq": 0.031, ...} and guess what each name meant."""
    out = []
    for n in names:
        v = f" = {values[n]:g}" if values and isinstance(values.get(n), (int, float)) else ""
        m = re.search(r"\[\[" + re.escape(n) + r"\]\]", template)
        if m:
            a, b = max(0, m.start() - 70), min(len(template), m.end() + 40)
            ctx = PLACEHOLDER.sub(lambda x: "…" if x.group(1) != n else x.group(0), template[a:b])
            out.append(f"- {n}{v}  ← \"{'…' if a else ''}{' '.join(ctx.split())}{'…' if b < len(template) else ''}\"")
        elif n == asked:
            out.append(f"- {n}{v}  ← the quantity the question ASKS for{(' (in ' + unit + ')') if unit else ''}; "
                       f"not shown in the question")
        else:
            out.append(f"- {n}{v}  ← not shown in the question (a value you need to compute the others)")
    return "\n".join(out)


def exact_calls(txs) -> str:
    """For each formula: the exact call that runs it forward and, for each numeric input, the exact
    find() call that runs it backwards, with the engine's own names. A coder guessing names wrote
    find(step_160, ..., equilibrium_constant=Kp), passed outputs as inputs and used undefined names:
    with the call written out there is nothing to guess."""
    from core.engine import physical as ph
    out = []
    for t in txs:
        st = ph.step(t)
        args = []
        for p in st.needs:
            if p.kind == "choice" and p.choices:
                args.append(f"{p.key}={p.choices[0]!r}")
            elif p.kind == "text":
                args.append(f'{p.key}="..."')
            else:
                args.append(f"{p.key}=...")
        lines = [f"step_{t}: gives {st.answer!r} ({st.asks})",
                 f"  forward  (you know every input):  y = step_{t}({', '.join(args)})[{st.answer!r}]"]
        for p in st.needs:
            if p.kind in ("choice", "text"):
                continue
            rest = ", ".join(a for a in args if not a.startswith(p.key + "="))
            lines.append(f"  backward (you know {st.answer!r}, want {p.key!r}):  "
                         f"x = find(step_{t}, {p.key!r}, result=<{st.answer}>{', ' + rest if rest else ''})")
        out.append("\n".join(lines))
    return "\n".join(out)


_MISTAKES = """COMMON MISTAKES (each one gets the program rejected; all were made before):
- WRONG find(step_160, "gas_dissociation_degree", equilibrium_constant=Kp, total_pressure=P, ...)
  RIGHT find(step_160, "gas_dissociation_degree", result=Kp, total_pressure=P, ...): the known
  output is ALWAYS given as result=, never under its own name
- WRONG step_135(equilibrium_constant=K): an OUTPUT passed as an input. A function takes only the
  inputs listed for it; to get an input from a known output, use its backward line above
- WRONG using a name that was never defined (mass_Zn): only the names listed as available exist;
  every other quantity must be computed inside solve() before it is used
- WRONG typing a formula yourself, or calling a function and throwing its result away: every
  function's RESULT must be used in the calculation of the answer
- WRONG step_92(1.02, 0.03), C.R, import math: keyword arguments only; no constants module; no imports"""


def coder_library(drawn) -> str:
    """What a coder sees of each drawn formula: chapter, inputs, outputs, the engine's own code."""
    from core.engine import physical as ph
    return "\n\n".join(f"[chapter: {ph._domain(t)}]\n" + sandbox.library_doc([ph.step(t)], list(ph.STEPS.values()))
                       + "\n   code (the engine's own; call it as step_" + str(t) + "(...)):\n"
                       + "\n".join("      " + ln for ln in sandbox.step_source(t).splitlines())
                       for t in drawn)


PROBE_TRIES = 30         # value sets a new program is tried on before the search: does it run at all?


def blank_lines(template: str, names, consts=()) -> str:
    """Each blank with the words of the question around it (which carry its unit); constants marked."""
    lines = named_values(template, names).splitlines()
    return "\n".join(ln + ("   (a constant: the functions hold their own; use it only where none does)"
                           if n in consts else "") for n, ln in zip(names, lines))


def design_block(design: dict | None) -> str:
    """The designer's plan as the coder reads it: the route, the point a careful solver must notice and the
    typical mistake the program must NOT make. Empty without a design."""
    if not design:
        return ""
    parts = [("Situation", design.get("system") or design.get("situation")),
             ("Intended route", design.get("route") or design.get("links")),
             ("What a careful solver must notice", design.get("student_must_notice") or design.get("insight")),
             ("Typical mistake (your program must NOT make it)", design.get("trap"))]
    lines = [f"- {k}: {str(v).strip()}" for k, v in parts if v and str(v).strip()]
    if not lines:
        return ""
    return ("\nTHE QUESTION'S DESIGN (the author's plan: solve the question this way, including the point to "
            "notice, even where the text leaves it implicit):\n" + "\n".join(lines) + "\n")


def write_blank_program(template: str, asks: str, unit: str, names, consts, library: str, *,
                        previous: str | None = None, errors: list | None = None, model: str | None = None,
                        txs=None, design: dict | None = None) -> dict:
    """{"code"} or {"cannot"}: coder 2 solves the question from its blanks, before any number is chosen.
    The question's values are variables when the program runs, so one program serves every value set the
    number step tries. design: the designer's plan; its route and the point to notice are shown, because
    the question text alone may leave them implicit (run of 2026-11-18: the flask question's key took the
    gas volume as the whole flask, the very trap the design named)."""
    redo = ""
    if previous:
        redo = "\nYour previous program:\n" + previous + "\nwas rejected:\n" + \
               "\n".join(f"- {e}" for e in errors or []) + "\nFix it.\n"
    in_unit = (' in ' + unit) if unit else ''
    prompt = f"""Write a Python program that solves this chemistry question using ONLY the functions below.

QUESTION (every number is a blank [[name]]: the numbers are chosen later, so the program must work for any
sensible values):
{template}

Asked: {asks}{in_unit}.
{design_block(design)}
THE QUESTION'S VALUES: when solve() runs, each blank is already a variable with exactly its name, holding
the number in the unit written after it in the question:
{blank_lines(template, names, consts)}
Use them directly. Never assign to them, never redefine them, never type a number for them.

FUNCTIONS (the formulas the question is built on: chapter, formula, inputs, outputs and the
engine's own code; each checks its inputs and returns a dict). Call each of them at least once:
{library}

Also available: find(step_N, "input", result=..., **other inputs), solve_for(f, lo, hi),
math (math.log, math.exp, math.sqrt ...), abs, min, max, sum, range, len (never round, int, floor or ceil a computed value).

EXACT CALLS (copy these; replace ... with your values):
{exact_calls(txs or [])}

HOW TO PROCEED: start from the question's values; follow the formulas from them to the asked quantity.
For each formula: if you know all its inputs, use its forward line; if you know its output and all inputs
but one, use the backward line for that input. Two unknowns fixed only by two formulas together:
solve_for. Do not guess names: use the ones in EXACT CALLS.

{_MISTAKES}

How the functions work (the engine code above is for reference only):
- each step_<n>(...) returns a DICT: take the number you need with its key, e.g.
  step_100(...)["most_probable_speed"]; never multiply or compare the dict itself;
- inside solve() there is NO "C", no constants module and no imports: the steps hold their own
  constants (R, F, N_A ...); never write C.R_J or similar;
- define inner functions inside solve() and pass values to them as arguments.

Rules:
- call every step function with keyword arguments only, named exactly as listed (step_92(P_wet=...,
  aqueous_tension=...)), never positionally;
- define solve() that returns the answer as ONE number{in_unit};
- the question's values are the variables above: use those the solution needs (a constant only where no
  function holds it). NEVER put a value into the program only to have used it (P / P, T / T, × (V / V)): a
  stated value the answer does not need (background such as "standard conditions, 1 bar") is simply left
  out, and the check says so honestly;
- a number the question writes out itself (a coefficient of an equation) may be typed as written; convert
  units in the program (+ 273.15, / 1000 ...) where a function needs another unit;
- call every function above at least once;
- never type in a value one of the functions computes (Z = 4 for fcc, an n-factor, 22.4 L): call it;
- never write a function's formula yourself: use the function's result in the calculation (a call
  whose result is thrown away does not count);
- the chemistry goes through these functions; besides them write only simple standard relations
  the question needs (n = m/M), unit conversions and the arithmetic that combines results as the
  question asks (a ratio, a difference, an equality); never type a physical constant (R, F, N_A, h, k_w ...);
- to run ONE formula backwards (you know its result and need one of its inputs), use
  find(step_N, "input_name", result=value, **its other inputs), e.g.
  R = find(step_247, "resistance", result=kappa, cell_constant=G); it returns the input's value;
  "result" is the value of the function's OUTPUT (not one of its inputs);
- for an unknown that a later result fixes, use solve_for(f, lo, hi): f(x) is the mismatch for a
  trial x; give lo and hi wide enough for any sensible values of the question;
- NO import line at all: math is already there; a program with "import math" is rejected before it runs;
- no printing, nothing else.
If the question cannot be solved with these functions alone, is ambiguous, or lacks a value,
return instead {{"cannot": "<one sentence naming what is missing or ambiguous>"}}.
{redo}
Return JSON: {{"code": "def solve():\\n    ..."}}"""
    model = model or models.CODER
    out = models.ask_json("coder", model, "You write exact scientific Python. Output JSON only.", prompt,
                          max_tokens=models.coder_tokens(model), temperature=0.1,
                          fallbacks=models.CODER_FALLBACKS if model == models.CODER else ())
    return _code_reply(out)


def _probe_problem(pr: dict, names) -> str:
    """A failed probe or search in words the coder can act on."""
    err = str(pr.get("error") or "")
    kind = pr.get("kind")
    if kind == "value_unused":
        return (f"the program never uses {err}: data of the question (a value with a range), so the answer needs "
                f"it; use each where the question uses it (if the question truly has no use for one, reply cannot "
                f"and name it)")
    if kind == "timeout":
        return (f"{err}: make every solve_for bracket sensible for the question's values and do not loop; the "
                f"program must finish in well under a second")
    if kind == "engine":
        return (f"on values from the question's ranges every run fails inside a formula ({err[:300]}); check how "
                f"each value enters: its unit (°C or K, g or kg, mL or L, kJ or J) and which input of which "
                f"formula it is")
    m = re.match(r"NameError: name '(\w+)' is not defined", err)
    if m:
        return (f"{err}: the question's values are {', '.join(names) or '(none)'}; anything else must be computed "
                f"inside solve() before it is used")
    return err[:400]


def solver_program(q: dict, drawn, bb, *, previous: str | None = None, errors: list | None = None,
                   tries: int | None = None, seed: int = 0, design: dict | None = None):
    """Coder 2 (models.CODER): the program that solves the question from its blanks, before any number is
    chosen. Each program is first run on value sets from the question's ranges (a probe): one that does not
    run, assigns to or ignores a value of the question, or leaves out a drawn formula that cannot be dropped,
    goes back to the coder with the error. (code, None), or (None, why) said to the writer."""
    names, ranges, fixed = blank_spec(q)
    consts = constant_names(fixed)
    library = coder_library(drawn)
    tries = CODE_TRIES if tries is None else tries
    escalate, last_kind = False, None
    for attempt in range(tries):
        try:
            model = coder_for(attempt, escalate)
            out = write_blank_program(q["stem"], q["asks"], q.get("unit") or "", names, consts, library,
                                      previous=previous, errors=errors, model=model, txs=drawn,
                                      design=design)
        except Exception as e:                   # noqa: BLE001 - an unusable reply or a provider down
            if getattr(e, "status_code", None) == 402:
                raise                            # out of credits: the run stops and says so
            bb.note("program", attempt=attempt + 1, error=f"{type(e).__name__}: {str(e)[:300]}")
            print(f"    coder call failed ({type(e).__name__}); next attempt")
            errors = [f"unusable reply: {e}"] if isinstance(e, ValueError) else \
                [f"the coder could not be reached ({type(e).__name__}: {str(e)[:120]})"]
            continue
        if "cannot" in out:
            bb.note("program", attempt=attempt + 1, cannot=out["cannot"])
            print(f"    coder: cannot solve it with the formulas: {out['cannot'][:160]}")
            return None, f"a solver could not solve it with the formulas alone: {out['cannot']}"
        code = out["code"]
        pr = sandbox.search_numbers(code, drawn, ranges, fixed, tries=PROBE_TRIES, exempt=list(fixed), seed=seed,
                                    probe=True, timeout=60)
        kind = None if pr.get("ok") else pr.get("kind")
        if kind:
            probs = [_probe_problem(pr, names)]
        elif not pr["run"].get("ok"):
            kind, probs = "code", [str(pr["run"].get("error"))[:400]]
        else:
            run = pr["run"]
            unused = [t for t in run.get("unused_steps") or () if t in drawn]
            probs = [] if not unused or unneeded(drawn, run) else [
                f"the program never calls {', '.join(f'step_{t}' for t in unused)}; the question is built on every "
                f"function: use each where the question needs it (if the question truly does not need one, reply "
                f"cannot and say which)"]
        bb.note("program", attempt=attempt + 1, code=code, ok=not probs, problems=probs,
                probe_values=pr.get("values"), reasoning=out.get("reasoning"))
        if not probs:
            print(f"    program written (attempt {attempt + 1}); it runs on values from the question's ranges")
            return code, None
        print(f"    program rejected ({attempt + 1}/{tries}): {'; '.join(probs)[:200]}")
        if kind == "engine" and last_kind == "engine":
            # twice no value set the program could run on: the ranges, not the program
            return None, (f"with values in your ranges the situation is physically impossible ({str(pr.get('error'))[:240]}); "
                          f"choose ranges (and values) in which every step of the situation is possible")
        if probs == errors:
            if escalate or models.CODER_STRONG in (None, "", models.CODER):
                break                            # the same failure twice: no stronger coder to try
            escalate = True
        previous, errors, last_kind = code, probs, kind
    return None, "the question could not be solved reliably with the formulas: " + "; ".join(errors or [])


def program_for(stem, asks, unit, cand, bb, built=True):
    """(code, run, None) or (None, None, why the question could not be solved). built: the answer is
    known independently (the engine built the numbers, or an official answer), so the program only has
    to run; otherwise (an old question without placeholders) it is the answer key and must use every
    formula."""
    drawn = list(cand.get("drawn_txs") or cand["txs"])
    library = coder_library(drawn)
    previous, errors, escalate = None, None, False
    for attempt in range(CODE_TRIES):
        try:
            model = coder_for(attempt, escalate)
            out = write_program(stem, asks, unit, library, previous=previous, errors=errors, model=model,
                                txs=drawn)
        except Exception as e:                   # noqa: BLE001 - an unusable reply or a provider down
            if getattr(e, "status_code", None) == 402:
                raise                            # out of credits: the run stops and says so
            bb.note("program", attempt=attempt + 1, error=f"{type(e).__name__}: {str(e)[:300]}")
            print(f"    coder call failed ({type(e).__name__}); next attempt")
            errors = [f"unusable reply: {e}"] if isinstance(e, ValueError) else \
                [f"the coder could not be reached ({type(e).__name__}: {str(e)[:120]})"]
            continue
        if "cannot" in out:
            bb.note("program", attempt=attempt + 1, cannot=out["cannot"])
            print(f"    coder: cannot solve it with the formulas: {out['cannot'][:160]}")
            return None, None, f"a solver could not solve it with the formulas alone: {out['cannot']}"
        code = out["code"]
        run = sandbox.evaluate(code, drawn, any_step=True)
        # the program only has to run: whether its answer is the intended one is checked by the caller.
        # How it got there (exact quotes, every formula called) is not judged: those checks threw out
        # correct programs (ratios, ²³⁸₉₂U, "equimolar": 3 of 4 real JEE questions)
        probs = [run["error"]] if not run.get("ok") else []
        unused = [] if built or probs else [t for t in run["unused_steps"] if t not in unneeded(drawn, run)]
        if unused:
            probs = [f"the program never calls {', '.join(f'step_{t}' for t in unused)}; every function must "
                     f"be used (if the question does not need it, reply cannot)"]
        probs = [_coder_hint(p, free=None) for p in probs]
        bb.note("program", attempt=attempt + 1, code=code, ok=not probs, problems=probs,
                answer=run.get("answer"), reasoning=out.get("reasoning"))
        if not probs:
            print(f"    program solved it (attempt {attempt + 1}): {run['answer']} {unit}")
            return code, run, None
        print(f"    program rejected ({attempt + 1}/{CODE_TRIES}): {'; '.join(probs)[:200]}")
        if probs == errors:
            if escalate or models.CODER_STRONG in (None, "", models.CODER):
                break                            # the same failure from the strong coder too: the question
            escalate = True                      # the same failure twice: the last try goes to the strong coder
        previous, errors = code, probs
    return None, None, "the question could not be solved reliably with the formulas: " + "; ".join(errors or [])
