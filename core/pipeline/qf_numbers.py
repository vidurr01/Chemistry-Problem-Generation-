"""Question first, stage 5: NUMBERS (coder 1: code, not a model).

Values are drawn in the writer's ranges and run through coder 2's program until one set gives an
answer in the answer range that rounding barely moves, that at least MIN_TRAPS typical mistakes change,
and that uses every picked value (pick_numbers -> sandbox.search_numbers). Only then are they printed
in the question (filled_question). numbers_for runs stages 4 and 5 together."""

from __future__ import annotations

from core.engine import sandbox
from core.pipeline.qf_text import fill_template
from core.pipeline.qf_writer import blank_names, blank_spec
from core.pipeline.qf_checks import MIN_TRAPS
from core.pipeline.qf_coder import _probe_problem, solver_program


FRAGILE_TOL = 0.02       # an answer that rounding the steps to 3 figures moves by more is not asked (the
                         # iron allotrope question: r(γ) − r(α) = 2.03 pm from radii near 125 pm)


PICK_TRIES = 200         # value sets the number step tries


PICK_TIMEOUT = 90.0      # seconds the number step may take


def numbers_problem(out: dict, q: dict, drawn) -> str:
    """Why no value set in the writer's ranges makes a good question, in words the writer can act on."""
    kind, err, unit = out.get("kind"), str(out.get("error") or ""), q.get("unit") or ""
    msg = _numbers_problem(kind, err, unit, out, q, drawn)
    outside = (out.get("counts") or {}).get("answer_range", 0)
    if kind != "answer_range" and outside:
        lo, hi = out.get("answers_seen") or (None, None)
        msg += (f" (besides, {outside} of {out.get('tries')} value sets gave an answer outside your answer_range"
                + (f", between {lo:.3g} and {hi:.3g}" if lo is not None else "") + ")")
    return msg


def _numbers_problem(kind, err, unit, out, q, drawn) -> str:
    from core.engine import physical as ph
    if kind == "answer_range":
        lo, hi = out.get("answers_seen") or (None, None)
        seen = f"between {lo:.3g} and {hi:.3g}" if lo is not None else f"at {err}"
        ar = q.get("answer_range") or ("?", "?")
        return (f"with values in your ranges the answer comes out {seen}{(' ' + unit) if unit else ''}, never inside "
                f"your answer_range [{ar[0]}, {ar[1]}]: correct the answer_range, or the ranges if the answer should "
                f"lie there")
    if kind == "fragile":
        return (f"with values in your ranges the answer is too sensitive to rounding (rounding each step to 3 "
                f"significant figures moves it by {err}): it hangs on a small difference of nearly equal quantities "
                f"or a very steep function; ask for a quantity that does not, or choose ranges that keep the compared "
                f"quantities clearly apart")
    if kind == "traps":
        avail = list(dict.fromkeys(tr.desc for t in drawn for tr in ph.step(t).traps))
        return (f"with values in your ranges fewer than {MIN_TRAPS} typical mistakes change the answer (only: {err}); "
                f"choose the situation and the ranges so that at least {MIN_TRAPS} of these give a clearly different "
                f"answer: " + "; ".join(avail[:8]))
    if kind == "value_unused":
        names = ", ".join(f"[[{n.strip()}]]" for n in err.split(","))
        return f"the question states {names}, which the solution does not use: remove it, or make the question need it"
    if kind in ("code", "timeout"):
        return f"the solving program fails on values in your ranges: {err[:300]}"
    return (f"with values in your ranges the situation is physically impossible ({err[:240]}); choose ranges (and "
            f"values) in which every step of the situation is possible")


def pick_numbers(q: dict, code: str, drawn, seed: int = 0) -> dict:
    """Coder 1, the number step (code, not a model): value sets drawn from the writer's ranges are run through
    coder 2's program until one gives an answer in answer_range that is not fragile, that at least MIN_TRAPS
    typical mistakes change, and that uses every value it picks. Only the picked (range) values must matter: the
    writer's fixed values may be background the answer does not need, as "standard conditions, 1 bar and 298 K"
    in a real paper (real question 2020P1_Q15). {"ok", "values", "run", "tries"} or {"ok": False,
    "kind", "why" (for the writer), ...}."""
    names, ranges, fixed = blank_spec(q)
    ar = q.get("answer_range")
    ar = (float(ar[0]), float(ar[1])) if ar else None
    out = sandbox.search_numbers(code, drawn, ranges, fixed, ar, tries=PICK_TRIES if ranges else 1,
                                 fragile_tol=FRAGILE_TOL, min_traps=MIN_TRAPS, exempt=list(fixed), seed=seed,
                                 timeout=PICK_TIMEOUT)
    if not out.get("ok"):
        out["why"] = numbers_problem(out, q, drawn)
    return out


def filled_question(q: dict, values: dict):
    """(stem, givens): the question with the picked values printed in it (each exactly the value the program
    ran on), and the givens as the rest of the pipeline reads them."""
    stem = fill_template(q["stem"], values, {}, q.get("asked") or "")
    givens = [{"value": values[n], "quote": n} for n in blank_names(q) if n in values]
    return stem, givens


def numbers_for(q: dict, drawn, bb, seed: int = 0, design: dict | None = None):
    """The blank flow after the writer: coder 2 writes the program from the blanks, then the number step picks
    the values and prints them in the question. (stem, run, code, None) or (None, None, code, why)."""
    code, why = solver_program(q, drawn, bb, seed=seed, design=design)
    if code is None:
        return None, None, None, why
    picked = pick_numbers(q, code, drawn, seed)
    if not picked.get("ok") and picked.get("kind") in ("code", "timeout"):
        # it ran on the probe's values but breaks on others: the program's fault, one more try for the coder
        names = blank_names(q)
        print(f"    the program fails on other values: {str(picked.get('error'))[:160]}; back to the coder")
        new, why = solver_program(q, drawn, bb, previous=code, errors=[_probe_problem(picked, names)], tries=1,
                                  seed=seed, design=design)
        if new is None:
            return None, None, code, why
        code = new
        picked = pick_numbers(q, code, drawn, seed)
    bb.note("numbers", ok=bool(picked.get("ok")), values=picked.get("values"), tries=picked.get("tries"),
            kind=picked.get("kind"), counts=picked.get("counts"), problem=picked.get("why"))
    if not picked.get("ok"):
        print(f"    no good numbers in the writer's ranges ({picked.get('tries')} sets tried; "
              f"{picked.get('counts')}): {picked['why'][:200]}")
        return None, None, code, picked["why"]
    stem, givens = filled_question(q, picked["values"])
    run = {**picked["run"], "givens": givens}
    print(f"    numbers picked ({picked['tries']} set{'s' if picked['tries'] != 1 else ''} tried): "
          + ", ".join(f"{g['quote']} = {g['value']}" for g in givens)[:220])
    return stem, run, code, None
