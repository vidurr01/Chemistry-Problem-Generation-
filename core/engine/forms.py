"""
Question forms: the same audited engine steps used the way JEE Advanced uses formulas.

docs/advanced_formula_map.md: only about a third of real Advanced physical questions run the
formulas forward in chain order; the rest ask for an INPUT (inverse), use one formula in TWO
STATES (a ratio or difference), tie two unknowns together (SIMULTANEOUS), ask where two
quantities become equal (CONDITION), or merge two branches into one step (TREE).

Every form is built "forward, then hidden": the values are chosen first, the engine runs its
steps forward exactly as for a chain, and only then is something hidden or compared. So the
answer is always a value the engine computed forward. The numeric solving here only CHECKS
that the stated data determine the answer (exactly one root in the realistic range) and
computes what each trap gives in this form.

    f = Inverse(plan, hidden="s0.molarity")          # find an input from the output
    q = f.build(values)                              # -> FormQuestion
    q.stated, q.answer, q.traps, q.tolerance
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.engine.base import EngineError, _run_step, plan_chain, round_sig

# ── running a plan exactly ───────────────────────────────────────────────────


def run_outputs(plan, values: dict, trap=None) -> list:
    """Every step's output dict, unrounded. trap = (step index, Trap): that step's answer is
    replaced by the trap's wrong value and the later steps run on it."""
    outs, prev = [], {}
    for i in range(len(plan.steps)):
        v, out = _run_step(plan, i, prev, values)
        if trap is not None and trap[0] == i:
            wrong = trap[1].fn(dict(v))
            out = dict(out)
            if isinstance(wrong, dict):
                out.update(wrong)
            else:
                out[plan.steps[i].answer] = wrong
        outs.append(out)
        prev = out
    return outs


def final_field(plan) -> str:
    last = plan.steps[-1]
    return last.final[0] if last.final else last.answer


def value_of(plan, values: dict, where=None, trap=None) -> float:
    """The number at `where` = (step index, field); default the chain's final answer."""
    outs = run_outputs(plan, values, trap)
    i, f = where if where is not None else (len(plan.steps) - 1, final_field(plan))
    x = outs[i][f]
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise EngineError(f"{f} is not a finite number")
    return float(x)


# ── one-variable roots with a uniqueness check ───────────────────────────────


def _grid(lo, hi, n=240):
    if lo > 0 and hi / lo > 50:
        a, b = math.log(lo), math.log(hi)
        return [math.exp(a + (b - a) * k / (n - 1)) for k in range(n)]
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def roots(f, lo: float, hi: float, n: int = 240) -> list:
    """All roots of f in [lo, hi] found by a sign-change scan (refined by bisection); points
    where f cannot be evaluated are skipped."""
    xs = _grid(lo, hi, n)
    vals = []
    for x in xs:
        try:
            y = f(x)
            vals.append((x, y if math.isfinite(y) else None))
        except (EngineError, ArithmeticError, ValueError, TypeError):
            vals.append((x, None))
    found = []
    for (x1, y1), (x2, y2) in zip(vals, vals[1:]):
        if y1 is None or y2 is None:
            continue
        if y1 == 0:
            found.append(x1)
        elif y1 * y2 < 0:
            a, b, fa = x1, x2, y1
            for _ in range(200):
                m = (a + b) / 2
                try:
                    fm = f(m)
                except (EngineError, ArithmeticError, ValueError, TypeError):
                    break
                if fm == 0 or abs(b - a) <= 1e-13 * max(1.0, abs(m)):
                    break
                if fa * fm < 0:
                    b = m
                else:
                    a, fa = m, fm
            found.append((a + b) / 2)
    if vals and vals[-1][1] == 0:
        found.append(vals[-1][0])
    out = []
    for r in found:
        if not any(math.isclose(r, s, rel_tol=1e-6, abs_tol=1e-15) for s in out):
            out.append(r)
    return out


def _range_of(plan, qkey):
    g = plan.givens[qkey]
    lo, hi = g.param.lo, g.param.hi
    if lo is None or hi is None:
        raise EngineError(f"{qkey} has no realistic range to search")
    return float(lo), float(hi)


# ── the forms ────────────────────────────────────────────────────────────────


@dataclass
class FormQuestion:
    form: str
    stated: dict                 # what the question states: {qkey or label: value}
    hidden: list                 # givens the question does NOT state
    answer: Any
    asks: str
    unit: str
    traps: list = field(default_factory=list)      # {"id", "desc", "wrong_answer"}
    tolerance: float = 0.01
    detail: dict = field(default_factory=dict)     # form-specific facts for prompts and traces


def _trap_list(plan):
    return [(i, t) for i, st in enumerate(plan.steps) for t in st.traps]


def _add_trap(traps, t, wrong, answer, tol):
    if wrong is None or not math.isfinite(wrong) or math.isclose(wrong, answer, rel_tol=tol):
        return
    if any(x["id"] == t.id and math.isclose(x["wrong_answer"], wrong, rel_tol=1e-6) for x in traps):
        return
    traps.append({"id": t.id, "desc": t.desc, "wrong_answer": round_sig(wrong)})


class Forward:
    """The chain as now: givens -> steps -> asked quantity (kept for completeness)."""
    name = "forward"

    def __init__(self, plan):
        self.plan = plan

    def build(self, values):
        from core.engine.base import run_chain
        r = run_chain(self.plan, values)
        return FormQuestion("forward", dict(values), [], r.answer, r.asks, r.unit, r.traps, r.tolerance)


class Inverse:
    """Hide one input; state the chain's result instead; ask for the input. ('E_cell = 0.092 V
    when [M²⁺]/[M⁴⁺] = 10ˣ: find x.') The stated result is the forward value rounded to 4
    significant figures; the answer must be the ONLY input in its realistic range that gives it."""
    name = "inverse"

    def __init__(self, plan, hidden: str, observe=None):
        self.plan, self.hidden, self.observe = plan, hidden, observe

    def build(self, values):
        plan, h = self.plan, self.hidden
        if h not in plan.givens:
            raise EngineError(f"{h} is not an input of this chain")
        p = plan.givens[h].param
        if p.kind in ("text", "choice", "dict", "list"):
            raise EngineError(f"{h} is not a number")
        target = float(round_sig(value_of(plan, values, self.observe), 4))
        x0 = float(values[h])
        lo, hi = _range_of(plan, h)
        # the realistic range, stretched just enough to contain the value the chain ran on
        lo, hi = min(lo, x0 * 0.8 if x0 > 0 else x0 * 1.25), max(hi, x0 * 1.25 if x0 > 0 else x0 * 0.8)

        def f(x, trap=None):
            return value_of(plan, {**values, h: x}, self.observe, trap) - target

        rs = roots(f, lo, hi)
        if len(rs) != 1:
            raise EngineError(f"{len(rs)} values of {h} give this result in its range; the inverse is not unique")
        ans = rs[0]
        if not math.isclose(ans, x0, rel_tol=2e-3):
            raise EngineError("the recovered input differs from the one the chain ran on")
        # how much the 4-s.f. statement moves the answer (sets the grading tolerance)
        shifts = []
        for k in (1 - 5e-4, 1 + 5e-4):
            r2 = roots(lambda x: value_of(plan, {**values, h: x}, self.observe) - target * k, lo, hi)
            if len(r2) == 1:
                shifts.append(abs(r2[0] - ans) / abs(ans))
        tol = min(0.10, max(0.01, 1.5 * max(shifts or [0])))
        traps = []
        for i, t in _trap_list(plan):
            try:
                rt = roots(lambda x: f(x, (i, t)), lo, hi)
            except Exception:  # noqa: BLE001
                continue
            if len(rt) == 1:
                _add_trap(traps, t, rt[0], ans, tol)
        obs_i, obs_f = self.observe if self.observe else (len(plan.steps) - 1, final_field(plan))
        stated = {k: v for k, v in values.items() if k != h}
        stated[f"result:{obs_f}"] = target
        return FormQuestion("inverse", stated, [h], round_sig(ans), p.desc, p.unit, traps, tol,
                            {"observed": (obs_i, obs_f), "observed_value": target,
                             "observed_unit": plan.steps[obs_i].unit if obs_f == plan.steps[obs_i].answer else ""})


class TwoState:
    """Run the chain in two states that differ in one or more inputs; ask for the ratio (or
    difference) of the result. ('t(1/8)/t(1/10)', 'ΔT_b(X)/ΔT_b(Y)', 'pK_a(HX) − pK_a(HY)')"""
    name = "two_state"

    def __init__(self, plan, changes: dict, combine: str = "ratio", observe=None, transform=None):
        self.plan, self.changes, self.combine, self.observe = plan, changes, combine, observe
        self.transform = transform          # e.g. lambda k: -math.log10(k) to compare pK values

    def _value(self, values, trap=None):
        x = value_of(self.plan, values, self.observe, trap)
        return self.transform(x) if self.transform else x

    def build(self, values):
        state2 = {**values, **self.changes}
        a, b = self._value(values), self._value(state2)
        ans = self._combine(b, a)
        traps = []
        for i, t in _trap_list(self.plan):
            try:
                w = self._combine(self._value(state2, (i, t)), self._value(values, (i, t)))
            except Exception:  # noqa: BLE001
                continue
            _add_trap(traps, t, w, ans, 0.01)
        obs_f = self.observe[1] if self.observe else final_field(self.plan)
        asks = (f"ratio of {obs_f} in state 2 to state 1" if self.combine == "ratio"
                else f"difference of {obs_f}, state 2 minus state 1")
        return FormQuestion("two_state", {"state 1": dict(values), "state 2": state2}, [], round_sig(ans),
                            asks, "", traps, 0.01, {"combine": self.combine, "changes": dict(self.changes),
                                                    "state_values": (round_sig(a), round_sig(b))})

    def _combine(self, b, a):
        if self.combine == "ratio":
            if a == 0:
                raise EngineError("state 1 gives zero")
            return b / a
        return b - a


class Simultaneous:
    """The same chain in two states sharing unknown inputs; both results are stated; ask for one
    unknown. ('Two solutions of A and B: 0.3 bar at x_A = 0.25 and 0.4 bar at x_A = 0.50; find p°_B.')"""
    name = "simultaneous"

    def __init__(self, plan, hidden: list, state_changes: dict, ask: str, observe=None):
        if len(hidden) != 2:
            raise ValueError("two unknowns, two states")
        self.plan, self.hidden, self.changes, self.ask, self.observe = plan, hidden, state_changes, ask, observe

    def build(self, values):
        import numpy as np
        from scipy.optimize import fsolve
        plan, (h1, h2) = self.plan, self.hidden
        s2 = {**values, **self.changes}
        y1 = float(round_sig(value_of(plan, values, self.observe), 4))
        y2 = float(round_sig(value_of(plan, s2, self.observe), 4))

        def eqs(u, trap=None):
            a = {**values, h1: u[0], h2: u[1]}
            b = {**s2, h1: u[0], h2: u[1]}
            return [value_of(plan, a, self.observe, trap) / y1 - 1, value_of(plan, b, self.observe, trap) / y2 - 1]

        def span(h):                     # realistic range, widened to include the values used
            lo, hi = _range_of(plan, h)
            x = float(values[h])
            return min(lo, x * 0.8), max(hi, x * 1.25)

        (l1, u1), (l2, u2) = span(h1), span(h2)
        sols = []
        starts = [(values[h1], values[h2])] + [(l1 + f1 * (u1 - l1), l2 + f2 * (u2 - l2))
                                                for f1 in np.linspace(0.05, 0.95, 7) for f2 in np.linspace(0.05, 0.95, 7)]
        for s0 in starts:
            try:
                u, info, ok, _ = fsolve(eqs, list(s0), full_output=True)
            except Exception:  # noqa: BLE001
                continue
            if ok == 1 and max(abs(x) for x in eqs(u)) < 1e-9 and l1 <= u[0] <= u1 and l2 <= u[1] <= u2:
                if not any(np.allclose(u, s, rtol=1e-5) for s in sols):
                    sols.append(u)
        if len(sols) != 1:
            raise EngineError(f"{len(sols)} solutions for the two unknowns; not a unique question")
        sol = sols[0]
        # the two statements must be independent where they meet (else a line of solutions)
        jac = []
        for j in range(2):
            d = np.zeros(2)
            d[j] = 1e-6 * max(1.0, abs(sol[j]))
            jac.append((np.array(eqs(sol + d)) - np.array(eqs(sol - d))) / (2 * d[j]) * max(1e-300, abs(sol[j])))
        if np.linalg.cond(np.array(jac).T) > 1e6:
            raise EngineError("the two statements do not fix both unknowns (they are not independent)")
        if not (math.isclose(sol[0], values[h1], rel_tol=2e-3) and math.isclose(sol[1], values[h2], rel_tol=2e-3)):
            raise EngineError("the unknowns recovered differ from the chain's inputs")
        ans = float(sol[0] if self.ask == h1 else sol[1])
        p = plan.givens[self.ask].param
        stated = {"state 1": {k: v for k, v in values.items() if k not in self.hidden},
                  "state 2": {k: v for k, v in s2.items() if k not in self.hidden},
                  "results": (y1, y2)}
        return FormQuestion("simultaneous", stated, [h1, h2], round_sig(ans), p.desc, p.unit, [], 0.01,
                            {"changes": dict(self.changes)})


class Condition:
    """Find the input at which two chains give equal results (or one chain reaches a stated
    value). ('equal work in the adiabatic and the isothermal step', 'the pressure at which
    graphite and diamond coexist'). `link` maps the unknown into both chains' inputs."""
    name = "condition"

    def __init__(self, plan_a, plan_b, unknown: tuple, lo: float, hi: float, unit: str, asks: str):
        self.a, self.b, self.unknown, self.lo, self.hi, self.unit, self.asks = plan_a, plan_b, unknown, lo, hi, unit, asks

    def build(self, values_a, values_b):
        ka, kb = self.unknown            # the unknown's key in each chain (None: that chain does not use it)

        def f(x):
            a = value_of(self.a, {**values_a, ka: x} if ka else values_a)
            b = value_of(self.b, {**values_b, kb: x} if kb else values_b)
            return a - b

        rs = roots(f, self.lo, self.hi)
        if len(rs) != 1:
            raise EngineError(f"{len(rs)} values satisfy the condition in range; not unique")
        return FormQuestion("condition", {"A": values_a, "B": values_b}, [ka, kb], round_sig(rs[0]),
                            self.asks, self.unit, [], 0.01)


class Tree:
    """Two branches computed separately and merged into one final step. ('ΔH from ΔfH and ΔS
    from S°, then T = ΔH/ΔS'.) branches: {final-step input key: plan whose result feeds it}."""
    name = "tree"

    def __init__(self, final_step, branches: dict):
        self.final, self.branches = final_step, branches
        need = {p.key for p in final_step.needs}
        for key, plan in branches.items():
            if key not in need:
                raise EngineError(f"{final_step.tx} has no input {key!r}")
            if final_field(plan) != key and plan.steps[-1].answer != key:
                raise EngineError(f"branch for {key!r} ends in {final_field(plan)!r}")
        self.final_plan = plan_chain([final_step])

    def build(self, branch_values: dict, final_values: dict):
        from core.engine.base import check_kind
        fed = {}
        for key, plan in self.branches.items():
            fed[f"s0.{key}"] = value_of(plan, branch_values[key])
        values = {**final_values, **fed}
        for qk, g in self.final_plan.givens.items():
            if qk not in values:
                raise EngineError(f"missing {qk}")
        outs = run_outputs(self.final_plan, values)
        ans = outs[-1][self.final.answer]
        check_kind(self.final.kind, ans)
        traps = []
        for key, plan in self.branches.items():           # a mistake in either branch
            for i, t in _trap_list(plan):
                try:
                    wrong_in = value_of(plan, branch_values[key], trap=(i, t))
                    w = value_of(self.final_plan, {**values, f"s0.{key}": wrong_in})
                except Exception:  # noqa: BLE001
                    continue
                _add_trap(traps, t, w, ans, 0.01)
        for i, t in _trap_list(self.final_plan):
            try:
                w = value_of(self.final_plan, values, trap=(i, t))
            except Exception:  # noqa: BLE001
                continue
            _add_trap(traps, t, w, ans, 0.01)
        return FormQuestion("tree", {"branches": branch_values, "final": final_values}, [],
                            round_sig(ans), self.final.asks, self.final.unit, traps, 0.01,
                            {"branch_results": {k: round_sig(v) for k, v in fed.items()}})
