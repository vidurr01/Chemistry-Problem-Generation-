"""
Shared machinery for the deterministic engines.

A Step implements one concept-book entry (one TX) as a computation from graph node
`src` to graph node `dst`. It declares the inputs it needs (Params), the output field
that answers it, and the traps a student typically falls into.

A chain is a list of steps. The output fields of step N are wired into step N+1
wherever the names match; every input that is not wired is a "given" the question
must state. plan_chain() refuses a chain in which a step uses nothing from the step
before it, so every chain the engine accepts really is one connected problem.

    plan = plan_chain([step_a, step_b])
    plan.givens            -> the inputs the question must supply (Given objects)
    result = run_chain(plan, {qkey: value, ...})
    result.answer, result.unit, result.trace, result.traps

Trap answers are computed by running the wrong value of one step through all the
later steps unchanged, so every trap is the final answer a student who made exactly
that mistake would write.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable


class EngineError(ValueError):
    """The inputs do not describe a valid problem (impossible values, no solution)."""


# ── Value checks ─────────────────────────────────────────────────────────────

_NUMERIC_KINDS = {"real", "positive", "nonneg", "negative", "fraction", "open_fraction",
                  "percent", "ph", "temperature", "integer", "count", "posint"}


def _num(x) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise EngineError(f"expected a number, got {x!r}")
    if not math.isfinite(x):
        raise EngineError(f"value is not finite: {x!r}")
    return float(x)


def check_kind(kind: str, value: Any, choices=None) -> None:
    """Raise EngineError if `value` is impossible for a quantity of this kind."""
    if kind == "any":
        return
    if kind == "choice":
        if value not in (choices or ()):
            raise EngineError(f"{value!r} is not one of {list(choices or ())}")
        return
    if kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise EngineError("expected a non-empty text value")
        return
    if kind == "dict":
        if not isinstance(value, dict) or not value:
            raise EngineError("expected a non-empty mapping")
        return
    if kind == "list":
        if not isinstance(value, (list, tuple)) or not value:
            raise EngineError("expected a non-empty list")
        return
    if kind not in _NUMERIC_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    x = _num(value)
    if kind == "positive" and x <= 0:
        raise EngineError(f"must be > 0, got {x}")
    if kind == "nonneg" and x < 0:
        raise EngineError(f"must be >= 0, got {x}")
    if kind == "negative" and x >= 0:
        raise EngineError(f"must be < 0, got {x}")
    if kind == "fraction" and not 0 <= x <= 1:
        raise EngineError(f"must be between 0 and 1, got {x}")
    if kind == "open_fraction" and not 0 < x < 1:
        raise EngineError(f"must be strictly between 0 and 1, got {x}")
    if kind == "percent" and not 0 <= x <= 100:
        raise EngineError(f"must be between 0 and 100, got {x}")
    if kind == "ph" and not -1 <= x <= 15:
        raise EngineError(f"pH out of range: {x}")
    if kind == "temperature" and x <= 0:
        raise EngineError(f"absolute temperature must be > 0 K, got {x}")
    if kind in ("integer", "count", "posint"):
        if abs(x - round(x)) > 1e-9:
            raise EngineError(f"must be a whole number, got {x}")
        if kind == "count" and x < 0:
            raise EngineError(f"count must be >= 0, got {x}")
        if kind == "posint" and x < 1:
            raise EngineError(f"must be >= 1, got {x}")


# ── Step description ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Param:
    """One input of a step.

    key      field name; matched against the previous step's output fields
    unit     unit the value is given in ("" when dimensionless)
    desc     what the value is, in words (shown to whoever proposes values)
    kind     value check (see check_kind)
    lo, hi   realistic range: a hint for whoever proposes values, not a hard limit
    context  steps that share a context name share one value (e.g. the temperature
             of the one system two steps describe)
    choices  allowed values when kind == "choice"
    role     what the value must belong to when it is wired from the previous step
             (e.g. "gas", "strong acid"); None accepts any (see links)
    """
    key: str
    unit: str
    desc: str
    kind: str = "positive"
    lo: float | None = None
    hi: float | None = None
    context: str | None = None
    choices: tuple | None = None
    role: str | None = None


@dataclass(frozen=True)
class Derive:
    """An input that is wired from the previous step when it can be, and otherwise
    computed from other givens (so the question never states two values that could
    contradict each other, e.g. an orbit energy AND the n and Z it follows from)."""
    key: str
    params: tuple
    fn: Callable[[dict], Any]


@dataclass(frozen=True)
class Trap:
    """A typical mistake at one step. fn takes the step's resolved inputs and returns
    the wrong value of the step's answer field (or a dict of wrong output fields)."""
    id: str
    desc: str
    fn: Callable[[dict], Any]


@dataclass(frozen=True)
class Step:
    """One concept-book entry as a computation from graph node src to node dst.

    tx          index of the entry in the subject's concept book
    src, dst    graph nodes the step connects
    needs       inputs; those the previous step outputs are wired automatically
    answer      the output field this step answers
    unit        unit of the answer field
    fn          resolved inputs -> dict of output fields (must contain `answer`)
    gives       further output fields later steps may use
    kind        value check for the answer field
    traps       typical mistakes at this step
    constants   constants the computation uses; the question must state them
    formula     the relation, for traces and prompts
    derive      inputs that are wired if possible, else computed from other givens
    asks        what the question asks for when this step ends the chain
    final       (field, unit, kind, asks) to report instead of `answer` when this
                step ends the chain (e.g. one coefficient of a balanced equation)
    roles       {output field: role} — what an output belongs to; a step whose input
                expects a different role cannot follow (untagged fits anything)
    domain      topic the step belongs to (set by the subject's registry); chains cross
                topics only along the subject's bridges
    keeps_role  the output is the same substance/system as the wired input (mass ->
                moles), so untagged outputs inherit the input's role along a chain
    """
    tx: int
    src: str
    dst: str
    needs: tuple
    answer: str
    unit: str
    fn: Callable[[dict], dict]
    gives: tuple = ()
    kind: str = "real"
    traps: tuple = ()
    constants: tuple = ()
    formula: str = ""
    derive: tuple = ()
    asks: str = ""
    final: tuple = ()
    roles: dict = field(default_factory=dict)
    domain: str | None = None
    keeps_role: bool = False

    @property
    def outputs(self) -> tuple:
        return tuple(dict.fromkeys((self.answer,) + tuple(self.gives)))


# ── Chains ───────────────────────────────────────────────────────────────────

@dataclass
class Given:
    """An input the question must state."""
    qkey: str
    param: Param
    steps: list = field(default_factory=list)   # indices of the steps that use it


@dataclass
class ChainPlan:
    steps: list
    wiring: list          # per step: {key: ("prev", field) | ("given", qkey) | ("derive", None)}
    givens: dict          # qkey -> Given
    constants: list


def qualify(i: int, p: Param) -> str:
    return f"ctx.{p.context}" if p.context else f"s{i}.{p.key}"


def plan_chain(steps: list) -> ChainPlan:
    """Work out which inputs come from the previous step and which must be given."""
    if not steps:
        raise EngineError("empty chain")
    wiring, givens, constants = [], {}, []
    prev_outputs: tuple = ()

    def add_given(i, p, w):
        qk = qualify(i, p)
        g = givens.setdefault(qk, Given(qk, p))
        if i not in g.steps:
            g.steps.append(i)
        w[p.key] = ("given", qk)

    for i, st in enumerate(steps):
        w: dict = {}
        for d in st.derive:
            if d.key in prev_outputs:
                w[d.key] = ("prev", d.key)
            else:
                w[d.key] = ("derive", None)
                for p in d.params:
                    if p.key in w:
                        continue
                    if p.key in prev_outputs:
                        w[p.key] = ("prev", p.key)
                    else:
                        add_given(i, p, w)
        for p in st.needs:
            if p.key in w:
                continue
            if p.key in prev_outputs:
                w[p.key] = ("prev", p.key)
            else:
                add_given(i, p, w)
        if i > 0 and not any(src == "prev" for src, _ in w.values()):
            raise EngineError(f"step {i} (tx {st.tx}) uses nothing from step {i - 1} (tx {steps[i - 1].tx})")
        wiring.append(w)
        for c in st.constants:
            if c not in constants:
                constants.append(c)
        prev_outputs = st.outputs
    return ChainPlan(steps, wiring, givens, constants)


def links(a: Step, b: Step, bridges=None) -> bool:
    """True if step b can follow step a: b uses at least one output of a, no wired value
    carries a role b's input rejects, and (when `bridges` is given) a and b share a topic
    or their two topics are bridged."""
    if bridges is not None and a.domain and b.domain and a.domain != b.domain \
            and frozenset((a.domain, b.domain)) not in bridges:
        return False
    params = {p.key: p for p in b.needs}
    for d in b.derive:
        params.setdefault(d.key, None)
        for p in d.params:
            params.setdefault(p.key, p)
    shared = set(params) & set(a.outputs)
    if not shared:
        return False
    for key in shared:
        want = params[key].role if params[key] is not None else None
        have = a.roles.get(key)
        if want and have and want != have:
            return False
    return True


def assign_steps(options: list, rng=None, bridges=None):
    """Pick one step per position so that every step can follow the one before it.

    options[k] is the list of candidate steps for position k (the TXs behind one graph
    edge). Returns a list of steps, chosen at random among the valid assignments, or
    None if no assignment links up."""
    import random as _random
    rng = rng or _random
    n = len(options)
    if n == 0:
        return None
    # ok[k] = steps at position k from which the rest of the chain can be completed
    ok = [None] * n
    ok[-1] = list(options[-1])
    for k in range(n - 2, -1, -1):
        ok[k] = [a for a in options[k] if any(links(a, b, bridges) for b in ok[k + 1])]
        if not ok[k]:
            return None
    for _ in range(25):
        chosen = [rng.choice(ok[0])]
        for k in range(1, n):
            nxt = [b for b in ok[k] if links(chosen[-1], b, bridges)]
            chosen.append(rng.choice(nxt))
        if roles_consistent(chosen):
            return chosen
    return None


def roles_consistent(steps: list) -> bool:
    """Follow roles along a chain: a keeps_role step passes its wired input's role on to
    its untagged outputs, so 'glycol mass -> moles' is still glycol when the next step
    asks for a weak acid. False if any wired value reaches an input expecting another role."""
    prev_roles: dict = {}
    for i, st in enumerate(steps):
        params = {p.key: p for p in st.needs}
        for d in st.derive:
            for p in d.params:
                params.setdefault(p.key, p)
        wired_role = None
        if i > 0:
            for key in set(params) & set(steps[i - 1].outputs):
                want, have = params[key].role, prev_roles.get(key)
                if want and have and want != have:
                    return False
                wired_role = wired_role or have or want
        roles = dict(st.roles)
        if st.keeps_role and wired_role:
            for f in st.outputs:
                roles.setdefault(f, wired_role)
        prev_roles = roles
    return True


@dataclass
class ChainResult:
    answer: Any
    unit: str
    kind: str
    asks: str
    trace: list           # per step: {"tx", "formula", "inputs", "outputs"}
    traps: list           # {"id", "desc", "step", "tx", "wrong_answer"}
    constants: list
    tolerance: float = 0.01   # relative; wider when rounding intermediates moves the answer


def _resolve(plan: ChainPlan, i: int, prev_out: dict, values: dict) -> dict:
    st = plan.steps[i]
    v = {}
    for key, (src, ref) in plan.wiring[i].items():
        if src == "prev":
            v[key] = prev_out[ref]
        elif src == "given":
            v[key] = values[ref]
    for d in st.derive:
        if plan.wiring[i][d.key][0] == "derive":
            v[d.key] = d.fn(dict(v))
    return v


def _run_step(plan: ChainPlan, i: int, prev_out: dict, values: dict):
    st = plan.steps[i]
    try:
        v = _resolve(plan, i, prev_out, values)
        out = st.fn(dict(v))
    except EngineError:
        raise
    except (ArithmeticError, ValueError, TypeError) as e:     # overflow, log of 0, bad types ...
        raise EngineError(f"tx {st.tx}: {type(e).__name__}: {e}") from None
    if not isinstance(out, dict) or st.answer not in out:
        raise EngineError(f"tx {st.tx} did not produce {st.answer!r}")
    check_kind(st.kind, out[st.answer])
    return v, out


def _run_from(plan: ChainPlan, start: int, prev_out: dict, values: dict) -> dict:
    out = prev_out
    for i in range(start, len(plan.steps)):
        _, out = _run_step(plan, i, out, values)
    return out


_TRAP_ERRORS = (EngineError, ZeroDivisionError, ValueError, OverflowError, KeyError, TypeError)


def run_chain(plan: ChainPlan, values: dict) -> ChainResult:
    """Compute the chain's answer, trace and traps for the given input values."""
    for qk, g in plan.givens.items():
        if qk not in values:
            raise EngineError(f"missing given {qk} ({g.param.desc})")
        check_kind(g.param.kind, values[qk], g.param.choices)

    trace, inputs, outs = [], [], []
    constants = list(plan.constants)
    out: dict = {}
    for i, st in enumerate(plan.steps):
        v, out = _run_step(plan, i, out, values)
        inputs.append(v)
        outs.append(out)
        for c in out.get("_constants", ()):       # data the step looked up, e.g. atomic masses
            if c not in constants:
                constants.append(c)
        trace.append({"tx": st.tx, "src": st.src, "dst": st.dst, "formula": st.formula,
                      "inputs": round_sig(v),
                      "outputs": round_sig({k: x for k, x in out.items() if k != "_constants"})})

    last = plan.steps[-1]
    a_field, a_unit, a_kind, a_asks = last.final or (last.answer, last.unit, last.kind, last.asks)
    answer = out[a_field]
    check_kind(a_kind, answer)
    tol = rounding_tolerance(plan, values, a_field, answer)

    traps, seen = [], set()
    for i, st in enumerate(plan.steps):
        for t in st.traps:
            try:
                wrong = t.fn(dict(inputs[i]))
                wrong_out = dict(outs[i])
                if isinstance(wrong, dict):
                    wrong_out.update(wrong)
                else:
                    wrong_out[st.answer] = wrong
                check_kind(st.kind, wrong_out[st.answer])
                final = _run_from(plan, i + 1, wrong_out, values)[a_field]
                check_kind(a_kind, final)
            except _TRAP_ERRORS:
                continue
            if answers_match(final, answer, rel_tol=tol):
                continue                   # this mistake does not change the answer beyond rounding
            key = (t.id, repr(round_sig(final)))
            if key in seen:
                continue
            seen.add(key)
            traps.append({"id": t.id, "desc": t.desc, "step": i, "tx": st.tx,
                          "wrong_answer": round_sig(final)})

    return ChainResult(answer=round_sig(answer), unit=a_unit, kind=a_kind,
                       asks=a_asks, trace=trace, traps=traps, constants=constants, tolerance=tol)


ROUNDING_SIG = 3          # a student carries about three significant figures between steps
MAX_TOLERANCE = 0.10


def rounding_tolerance(plan: ChainPlan, values: dict, a_field: str, answer) -> float:
    """Relative tolerance for a numeric answer. Re-run the chain the way a careful student
    would, rounding every intermediate result to ROUNDING_SIG significant figures; if that
    alone moves the answer by more than 1% (e.g. e^(-34.1), where rounding the exponent by
    0.03 shifts the answer 3%), widen the tolerance to 1.5x that shift, capped at 10%."""
    if isinstance(answer, bool) or not isinstance(answer, (int, float)) or answer == 0:
        return 0.01
    try:
        prev: dict = {}
        for i in range(len(plan.steps)):
            _, out = _run_step(plan, i, prev, values)
            prev = round_sig({k: x for k, x in out.items() if k != "_constants"}, ROUNDING_SIG)
        shifted = prev[a_field]
        dev = abs(float(shifted) - float(answer)) / abs(float(answer))
    except Exception:  # noqa: BLE001 - a rounded path that fails just keeps the default
        return 0.01
    return min(MAX_TOLERANCE, max(0.01, 1.5 * dev))


# ── Answers ──────────────────────────────────────────────────────────────────

def round_sig(x, sig: int = 4):
    """Round numbers (also inside lists/tuples/dicts) to `sig` significant figures."""
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        if x == 0 or not math.isfinite(x):
            return x
        r = round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))
        return int(r) if r.is_integer() and abs(r) < 1e15 else r
    if isinstance(x, (list, tuple)):
        return type(x)(round_sig(v, sig) for v in x)
    if isinstance(x, dict):
        return {k: round_sig(v, sig) for k, v in x.items()}
    return x


def answers_match(a, b, rel_tol: float = 0.01) -> bool:
    """True if two answers agree: numbers within rel_tol (1% by default), strings equal
    after whitespace/case normalisation, containers element by element."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        # purely relative: answers range from 10⁻³⁴ (J s) to 10²³ (particles), so any
        # absolute tolerance would make tiny answers always "match"
        return a == b or math.isclose(a, b, rel_tol=rel_tol, abs_tol=0.0)
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.lower().split()) == " ".join(b.lower().split())
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(answers_match(x, y, rel_tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(answers_match(a[k], b[k], rel_tol) for k in a)
    return a == b


# ── Numeric helpers ──────────────────────────────────────────────────────────

def solve_bisect(f: Callable[[float], float], lo: float, hi: float,
                 tol: float = 1e-13, max_iter: int = 400) -> float:
    """Root of f in [lo, hi]; f(lo) and f(hi) must differ in sign."""
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        raise EngineError("no root in the bracket")
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm == 0 or (hi - lo) / 2 < tol * max(1e-30, abs(mid)):
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def log10(x: float) -> float:
    if x <= 0:
        raise EngineError(f"log of non-positive value {x}")
    return math.log10(x)


def ln(x: float) -> float:
    if x <= 0:
        raise EngineError(f"ln of non-positive value {x}")
    return math.log(x)


def sqrt(x: float) -> float:
    if x < 0:
        raise EngineError(f"square root of negative value {x}")
    return math.sqrt(x)


def div(a: float, b: float) -> float:
    if b == 0:
        raise EngineError("division by zero")
    return a / b
