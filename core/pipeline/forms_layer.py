"""
Pipeline layer for question forms (core/engine/forms.py).

After the generator has proposed values and the engine has run the chain forward, a form is
chosen and applied: it decides what the question STATES (the gate checks exactly that), what
it ASKS, the answer, the traps and the tolerance. The result is a ChainResult-compatible
FormResult, so grading, the ladder, the verifier and the answer key work unchanged; its trace
is the forward computation plus a note saying how the form uses it.

    picked = apply_form(adapter, cand, spec, values, result, rng, avoid={"forward"})
    # -> (form_spec, form_values, form_result) or None when no form fits these values
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.engine import forms
from core.engine.base import EngineError, round_sig, run_chain

NUMERIC = {"real", "positive", "nonneg", "negative", "fraction", "open_fraction", "percent", "ph",
           "temperature", "integer", "count", "posint"}
# How often each form is chosen when several fit (the forward chain stays possible but rare:
# about a third of real Advanced questions are forward, docs/advanced_formula_map.md).
FORM_WEIGHTS = {"inverse": 3, "two_state": 3, "simultaneous": 2, "forward": 1}
TWO_STATE_FACTORS = (2.0, 3.0, 4.0, 0.5, 0.25, 10.0, 0.1, 1.5)
SIMULTANEOUS_TRIES = 8        # (varied input, two unknowns) combinations tried per question
FRAGILE_TOL = 0.02


@dataclass
class FormResult:
    answer: object
    unit: str
    kind: str
    asks: str
    trace: list
    traps: list
    constants: list
    tolerance: float = 0.01
    form: str = "forward"
    form_note: str = ""            # for the verifier and the answer key (contains the answer)
    answer_substances: list | None = None
    stem_note: str = ""            # for the stem writer (never the answer)
    detail: dict = field(default_factory=dict)


def _numeric_givens(plan, spec):
    keys = {s["key"]: s for s in spec}
    out = []
    for qk, g in plan.givens.items():
        p = g.param
        if p.kind in NUMERIC and p.lo is not None and p.hi is not None and qk in keys:
            out.append(qk)
    return out


def _final(plan):
    last = plan.steps[-1]
    if last.final:
        f, unit, kind, asks = last.final
    else:
        f, unit, kind, asks = last.answer, last.unit, last.kind, last.asks
    return f, (unit if isinstance(unit, str) else ""), kind, asks


def _inverse(plan, spec, values, base, rng):
    f_field, f_unit, f_kind, f_asks = _final(plan)
    if f_kind not in NUMERIC:
        return None
    cands = _numeric_givens(plan, spec)
    rng.shuffle(cands)
    for h in cands:
        try:
            q = forms.Inverse(plan, h).build(values)
        except (EngineError, ArithmeticError, ValueError, TypeError):
            continue
        if q.tolerance > FRAGILE_TOL:
            continue
        p = plan.givens[h].param
        target = q.detail["observed_value"]
        f_unit = base.unit
        form_spec = [s for s in spec if s["key"] != h] + [{
            "key": "result", "desc": f"{f_asks}, as measured or given", "unit": f_unit, "kind": "real",
            "range": None, "choices": None, "step": len(plan.steps) - 1}]
        form_values = {k: v for k, v in values.items() if k != h} | {"result": target}
        note = (f"FORM inverse: the question states the result of the last step ({f_asks} = {target}"
                f"{(' ' + f_unit) if f_unit else ''}) and asks for an input of the chain, {p.desc}. "
                f"The steps above, run with {p.desc} = {q.answer}, reproduce the stated result; that "
                f"value is the only one in a realistic range that does.")
        stem_note = (f"QUESTION FORM (inverse): state the result of the last step, {f_asks} = {target}"
                     f"{(' ' + f_unit) if f_unit else ''}, as given data (a measurement or a known value), do "
                     f"NOT state {p.desc}, and ask for {p.desc}. The student must work the chain backwards.")
        return form_spec, form_values, FormResult(
            q.answer, p.unit, p.kind if p.kind in NUMERIC else "real", p.desc, base.trace, q.traps,
            base.constants, q.tolerance, "inverse", note, None, stem_note, {"hidden": h, "result": target})
    return None


def _two_state(plan, spec, values, base, rng):
    f_field, f_unit, f_kind, f_asks = _final(plan)
    if f_kind not in NUMERIC:
        return None
    cands = _numeric_givens(plan, spec)
    rng.shuffle(cands)
    for k in cands:
        p = plan.givens[k].param
        factors = list(TWO_STATE_FACTORS)
        rng.shuffle(factors)
        for fac in factors:
            v2 = float(round_sig(float(values[k]) * fac, 3))
            if p.kind in ("integer", "count", "posint"):
                v2 = int(round(v2))
            if v2 == values[k] or not (min(p.lo, values[k]) * 0.5 <= v2 <= max(p.hi, values[k]) * 2):
                continue
            try:
                q = forms.TwoState(plan, {k: v2}).build(values)
                s2 = run_chain(plan, {**values, k: v2})
            except (EngineError, ArithmeticError, ValueError, TypeError, ZeroDivisionError):
                continue
            if not math.isfinite(q.answer) or abs(q.answer - 1) < 0.02:
                continue
            spec2 = []
            for s in spec:
                if s["key"] == k:
                    spec2.append({**s, "desc": f"{s['desc']} in the first case"})
                    spec2.append({**s, "key": k + "@2", "desc": f"{s['desc']} in the second case"})
                else:
                    spec2.append(s)
            vals2 = dict(values) | {k + "@2": v2}
            asks = f"the ratio of the {f_asks} in the second case to that in the first"
            trace = ([{**t, "formula": f"[first case] {t['formula']}"} for t in base.trace]
                     + [{**t, "formula": f"[second case, {p.desc} = {v2}] {t['formula']}"} for t in s2.trace])
            note = (f"FORM two states: the same system in two cases that differ only in {p.desc} "
                    f"({values[k]} and {v2}{(' ' + p.unit) if p.unit else ''}); the question asks the ratio "
                    f"second : first of the {f_asks} = {s2.answer} / {base.answer} = {q.answer}.")
            stem_note = (f"QUESTION FORM (two states): describe the same system in two cases that differ only in "
                         f"{p.desc} (first case {values[k]}, second case {v2}{(' ' + p.unit) if p.unit else ''}); "
                         f"everything else is the same in both. Ask for the ratio of the {f_asks} in the second "
                         f"case to that in the first. Do not state either {f_asks}.")
            return spec2, vals2, FormResult(q.answer, "", "positive" if q.answer > 0 else "real", asks, trace,
                                            q.traps, base.constants, max(base.tolerance, s2.tolerance),
                                            "two_state", note, None, stem_note, {"varied": k, "values": (values[k], v2)})
    return None


def _simultaneous(plan, spec, values, base, rng):
    """Two cases differing in one input; both results stated; two other inputs unknown (shared
    by both cases); ask one of them."""
    f_field, f_unit, f_kind, f_asks = _final(plan)
    if f_kind not in NUMERIC:
        return None
    num = _numeric_givens(plan, spec)
    if len(num) < 3:
        return None
    order = list(num)
    rng.shuffle(order)
    combos = [(vary, a, b) for vary in order for a in order for b in order
              if a != vary and b != vary and a < b]
    rng.shuffle(combos)
    for vary, h1, h2 in combos[:SIMULTANEOUS_TRIES]:
        p = plan.givens[vary].param
        for fac in TWO_STATE_FACTORS[:3]:
            v2 = float(round_sig(float(values[vary]) * fac, 3))
            if p.kind in ("integer", "count", "posint"):
                v2 = int(round(v2))
            if v2 == values[vary] or not (min(p.lo, values[vary]) * 0.5 <= v2 <= max(p.hi, values[vary]) * 2):
                continue
            ask = rng.choice([h1, h2])
            try:
                q = forms.Simultaneous(plan, [h1, h2], {vary: v2}, ask=ask).build(values)
                s2 = run_chain(plan, {**values, vary: v2})
            except (EngineError, ArithmeticError, ValueError, TypeError, ZeroDivisionError):
                continue
            y1, y2 = q.stated["results"]
            pa = plan.givens[ask].param
            spec2, vals2 = [], {}
            for s in spec:
                if s["key"] in (h1, h2):
                    continue
                if s["key"] == vary:
                    spec2.append({**s, "desc": f"{s['desc']} in the first case"})
                    spec2.append({**s, "key": vary + "@2", "desc": f"{s['desc']} in the second case"})
                    vals2[s["key"]], vals2[vary + "@2"] = values[vary], v2
                else:
                    spec2.append(s)
                    vals2[s["key"]] = values[s["key"]]
            for n, y in (("result", y1), ("result@2", y2)):
                spec2.append({"key": n, "desc": f"{f_asks} measured in the {'first' if n == 'result' else 'second'} case",
                              "unit": base.unit, "kind": "real", "range": None, "choices": None,
                              "step": len(plan.steps) - 1})
                vals2[n] = y
            trace = ([{**t, "formula": f"[first case] {t['formula']}"} for t in base.trace]
                     + [{**t, "formula": f"[second case] {t['formula']}"} for t in s2.trace])
            note = (f"FORM simultaneous: two cases differing only in {p.desc}; the {f_asks} is stated "
                    f"for both ({y1} and {y2}); {plan.givens[h1].param.desc} and "
                    f"{plan.givens[h2].param.desc} are unknown and the same in both cases. The two "
                    f"statements fix both; the question asks {pa.desc} = {q.answer}.")
            stem_note = (f"QUESTION FORM (simultaneous): describe two cases that differ only in {p.desc}; "
                         f"state the {f_asks} measured in each case ({y1} and {y2}). Do NOT state "
                         f"{plan.givens[h1].param.desc} or {plan.givens[h2].param.desc}: they are unknown "
                         f"and the same in both cases. Ask for {pa.desc}.")
            return spec2, vals2, FormResult(q.answer, pa.unit, pa.kind if pa.kind in NUMERIC else "real",
                                            pa.desc, trace, [], base.constants, 0.01, "simultaneous",
                                            note, None, stem_note, {"unknowns": [h1, h2], "asked": ask})
    return None


BUILDERS = {"inverse": _inverse, "two_state": _two_state, "simultaneous": _simultaneous}


def apply_form(adapter, cand, spec, values, result, rng, avoid=()):
    """Choose a form (weighted, skipping `avoid`) that fits these values and apply it. Returns
    (spec, values, FormResult). Falls back to the forward chain when nothing else fits."""
    plan = cand["_plan"]
    kinds = [k for k in FORM_WEIGHTS if k not in avoid and k != "forward"]
    order = []
    while kinds:
        w = [FORM_WEIGHTS[k] for k in kinds]
        pick = rng.choices(kinds, weights=w)[0]
        order.append(pick)
        kinds.remove(pick)
    for kind in order:
        try:
            got = BUILDERS[kind](plan, spec, values, result, rng)
        except Exception:  # noqa: BLE001 - a form that cannot be built is just skipped
            got = None
        if got:
            return got
    return spec, values, FormResult(result.answer, result.unit, result.kind, result.asks, result.trace,
                                    result.traps, result.constants, result.tolerance, "forward", "",
                                    getattr(result, "answer_substances", None))
