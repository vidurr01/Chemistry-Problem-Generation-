"""
sandbox.py — run a model-written solve() whose chemistry comes only from engine steps.

The question-first pipeline (core/pipeline/qfirst.py) has a model write the question and a
second model write a program that solves it. The program may use only:

    step_<tx>(**inputs)        one engine step of the chain: the concept-book formula, with its
                               input checks; returns the step's output fields (a dict)
    given(value, "quote")      every value taken from the question, with the words it comes
                               from (code checks the quote is in the question)
    solve_for(f, lo, hi)       the root of f(x) = 0 in [lo, hi]: for an unknown input
    math, abs, min, max, ...   arithmetic for unit conversions, ratios and differences

so every formula is one of the knowledge graph's; nothing else is importable. The code is
checked statically (no imports, no dunder access, no I/O names) and run in a separate process
with a time limit.

evaluate(code, txs) returns the answer, the trace of step calls (a solve_for loop records
only its final evaluation), the givens with their quotes, the traps (each step mistake
pushed through the whole program, as run_chain does), the rounding tolerance (the program
re-run with every step result rounded to 3 significant figures), and the dependency depth
(the longest run of distinct steps that feed each other's values), and the steps whose
results do not change the answer (each step's result scaled by 1.001 in turn).
"""

from __future__ import annotations

import ast
import builtins
import math
import re
import time
import multiprocessing as mp

TIMEOUT_S = 30
WHOLE_FIND_TOL = 6e-3      # find() on a whole-number input: the nearest whole number within 3-figure rounding
ROUND_SIG = 3
RELEVANCE_FACTORS = (1.001, 0.5, 2.0, 0.1, 10.0)   # a step's result is scaled by these in turn
MAX_TOLERANCE = 0.10

_FORBIDDEN_NAMES = {"eval", "exec", "open", "compile", "__import__", "getattr", "setattr", "delattr",
                    "globals", "locals", "vars", "input", "breakpoint", "type", "object", "super",
                    "memoryview", "bytearray", "help", "dir", "exit", "quit", "classmethod",
                    "staticmethod", "property"}
# Attributes that reach the interpreter's internals without a leading underscore: a generator's frame
# (g.gi_frame.f_back.f_globals) gave the module globals of _run_once and through them builtins.open and
# exec (found 2026-11-18). Frames, tracebacks, code objects and closure cells are blocked by prefix;
# str.format / format_map are blocked because their "{0.__globals__}" fields are never parsed as code.
_FORBIDDEN_ATTR_PREFIXES = ("_", "gi_", "cr_", "ag_", "f_", "tb_", "co_")
_FORBIDDEN_ATTRS = {"cell_contents", "format", "format_map"}
_FORBIDDEN_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef,
                    ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom, ast.With, ast.AsyncWith)
_SAFE_BUILTINS = {n: getattr(builtins, n)
                  for n in ("abs", "min", "max", "sum", "range", "len", "round", "float", "int", "pow",
                            "enumerate", "zip", "sorted", "list", "dict", "tuple", "bool", "str",
                            "isinstance", "any", "all", "reversed", "ValueError", "ZeroDivisionError",
                            "ArithmeticError", "Exception")}


class SolveError(Exception):
    """The program broke a rule or failed; the message goes back to the coder."""


# ── values the program computes itself ───────────────────────────────────────
# A step checks its own inputs and result (check_kind), but a value the program computes in plain Python between
# steps was never checked. Cu/Ag co-deposition (2026-11-25, another laptop): 3.05 A for 126 min is 23,058 C, so the
# deposit must weigh 7.59-25.8 g, yet 6.62 g was stated; the program split the charge in plain Python, Q_Ag came out
# -1,223 C, the energy came from Q_Cu alone and the question was accepted. Each name a program assigns is now checked
# by the kind its name implies. Only names that clearly denote an amount are checked; a name with a change/difference
# token (dH, delta_n, n_diff) or an unclear one (Q: charge or heat) is left alone.
_NAME_TOKEN = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_SIGNED_TOKENS = {"d", "delta", "change", "diff", "difference", "net", "shift", "dev", "deviation", "err", "error",
                  "log", "ln", "lg", "slope", "intercept", "coeff", "coef", "sign", "signed", "rel", "lhs", "rhs",
                  "residual", "mismatch", "f", "g", "res", "wrong", "trap", "excess"}
_NONNEG_TOKENS = {"charge", "charges", "mass", "masses", "mol", "mole", "moles", "nmol", "amount", "amounts",
                  "volume", "volumes", "vol", "pressure", "pressures", "press", "conc", "concentration", "molarity",
                  "molality", "current", "time", "density", "count", "particles", "atoms", "electrons", "faradays"}
_NONNEG_LETTERS = {"m", "n", "V", "P", "I", "t", "M"}          # case matters: T is temperature, v is not checked
_FRACTION_TOKENS = {"frac", "fraction", "fractions", "share", "degree"}
_FRACTION_FIRST = {"alpha"}           # alpha, alpha_1: degree of dissociation; density_alpha is the α phase (replay)
_TEMPERATURE_TOKENS = {"temp", "temperature", "kelvin"}
_TEMPERATURE_LETTERS = {"T"}
_SLACK = 1e-9                                                    # rounding noise around 0 and 1
# Q is charge or heat; tied to a two-letter element symbol (Q_Ag, q_Cu, charge share of a metal) it is a charge
_ELEMENTS_2 = set("He Li Be Ne Na Mg Al Si Cl Ar Ca Sc Ti Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Zr Nb Mo Tc "
                  "Ru Rh Pd Ag Cd In Sn Sb Te Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta Re Os Ir "
                  "Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa Np Pu".split())


def value_kind(name: str):
    """The kind a program variable's name implies ("nonneg", "fraction", "temperature") or None (not checked)."""
    raw = _NAME_TOKEN.findall(str(name))
    if not raw:
        return None
    low = [t.lower() for t in raw]
    if any(t in _SIGNED_TOKENS for t in low):
        return None
    if any(t in _FRACTION_TOKENS for t in low) or low[0] in _FRACTION_FIRST:
        return "fraction"
    if any(t in _TEMPERATURE_TOKENS for t in low) or raw[0] in _TEMPERATURE_LETTERS:
        return "temperature"
    if any(t in _NONNEG_TOKENS for t in low) or raw[0] in _NONNEG_LETTERS:
        return "nonneg"
    if low[0] == "q" and any(t in _ELEMENTS_2 for t in raw[1:]):
        return "nonneg"
    return None


def check_value(name: str, value) -> None:
    """Raise SolveError if a value the program computed is impossible for the kind its name implies."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return
    kind = value_kind(name)
    x = float(value)
    tol = _SLACK * max(1.0, abs(x))
    bad = ((kind == "nonneg" and x < -tol) or (kind == "temperature" and x <= 0)
           or (kind == "fraction" and not -tol <= x <= 1 + tol))
    if bad:
        want = {"nonneg": "must be >= 0", "temperature": "must be > 0 K", "fraction": "must be between 0 and 1"}[kind]
        raise SolveError(f"the program computed {name} = {x:.4g}, which is impossible ({name} {want}): "
                         f"the stated values contradict each other")


class _CheckAssigned(ast.NodeTransformer):
    """After each assignment to plain names inside a function, check every assigned name's value."""

    def _names(self, target):
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, (ast.Tuple, ast.List)):
            return [n for e in target.elts for n in self._names(e)]
        return []

    def _after(self, node, names):
        checks = [ast.Expr(ast.Call(ast.Name("_check_value_", ast.Load()),
                                    [ast.Constant(n), ast.Name(n, ast.Load())], []))
                  for n in dict.fromkeys(names)]
        return [node] + [ast.copy_location(c, node) for c in checks]

    def visit_Assign(self, node):
        return self._after(node, [n for t in node.targets for n in self._names(t)])

    def visit_AugAssign(self, node):
        return self._after(node, self._names(node.target))

    def visit_AnnAssign(self, node):
        return self._after(node, self._names(node.target)) if node.value is not None else node


def _instrumented(code: str):
    tree = _CheckAssigned().visit(ast.parse(code))
    ast.fix_missing_locations(tree)
    return compile(tree, "<solve>", "exec")


# ── static check ─────────────────────────────────────────────────────────────

def check_code(code: str, txs) -> list:
    """Problems found without running the code (empty list: may run)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error: {e}"]
    probs = []
    allowed_steps = {f"step_{t}" for t in txs}
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            probs.append(f"line {node.lineno}: {type(node).__name__} is not allowed")
        elif isinstance(node, ast.Attribute) and (node.attr.startswith(_FORBIDDEN_ATTR_PREFIXES)
                                                  or node.attr in _FORBIDDEN_ATTRS):
            probs.append(f"line {node.lineno}: attribute {node.attr!r} is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_NAMES or node.id.startswith("__"):
                probs.append(f"line {node.lineno}: {node.id!r} is not allowed")
            elif re.fullmatch(r"step_\d+", node.id) and node.id not in allowed_steps:   # step_100_result is a variable
                probs.append(f"line {node.lineno}: {node.id} is not a formula of the knowledge graph"
                             + (f" (allowed: {', '.join(sorted(allowed_steps))})" if len(allowed_steps) < 20 else ""))
        if isinstance(node, ast.Call) and _rounding_call(node):
            # a rounded value slips past the formulas' own checks (a whole n, a fraction in 0..1): run of 2026-11-19,
            # n = round(2.59) = 3 turned impossible stated data into a wrong key (88.61 for 85.4)
            probs.append(f"line {node.lineno}: do not round or truncate a computed value ({ast.unparse(node.func)}): "
                         f"pass it to the formula, which checks it (a whole number, a fraction) itself; to find a "
                         f"whole number use find() or solve_for(), which search whole numbers")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "solve" for n in tree.body):
        probs.append("define a function solve() that returns the answer")
    return probs


_ROUNDING_NAMES = {"round", "int"}
_ROUNDING_MATH = {"floor", "ceil", "trunc"}


def _rounding_call(node) -> bool:
    """round(x), int(x), math.floor/ceil/trunc(x) on anything but a plain number."""
    f = node.func
    hit = (isinstance(f, ast.Name) and f.id in _ROUNDING_NAMES) or (
        isinstance(f, ast.Attribute) and f.attr in _ROUNDING_MATH and isinstance(f.value, ast.Name)
        and f.value.id == "math")
    def literal(a):
        try:
            ast.literal_eval(a)                 # 3, -2.5, 1e-3: a written number, not a computed value
            return True
        except (ValueError, TypeError, SyntaxError):
            return False
    return hit and not all(literal(a) for a in node.args)


# ── library description for the coder ───────────────────────────────────────

def _unit_of_key(key, steps_all):
    for s in steps_all:
        for p in s.needs:
            if p.key == key and p.unit:
                return p.unit
        if s.answer == key and isinstance(s.unit, str) and s.unit:
            return s.unit
    return ""


def _param_line(p, optional=""):
    bits = [p.unit] if p.unit else []
    if p.kind == "choice":
        bits.append("one of " + " | ".join(map(str, p.choices or ())))
    elif p.kind in ("text", "dict", "list"):
        bits.append({"text": "text", "dict": "JSON object", "list": "JSON list"}[p.kind])
    elif p.lo is not None and p.hi is not None:
        # said as what it is, a usual value, not a limit: "typically 0.8–2" made a coder refuse a solution of
        # density 0.656 g/mL that the step computes correctly (2014P1_Q40, run of 2026-11-18)
        bits.append(f"usual values {p.lo:g}–{p.hi:g}, not a limit: any value the question gives is accepted")
    return f"      {p.key}: {p.desc}" + (f" [{'; '.join(bits)}]" if bits else "") + optional


def index_doc(steps) -> str:
    """Every step as one line: name, input keys, result and formula (the coder's index of the
    knowledge graph; a wrong input name is answered with the right ones)."""
    out = []
    for st in steps:
        keys = [p.key for p in st.needs]
        unit = st.unit if isinstance(st.unit, str) else "?"
        out.append(f"step_{st.tx}({', '.join(keys)}) -> {st.answer!r} [{unit}]: {st.asks} — {st.formula}")
    return "\n".join(out)


def library_doc(steps, steps_all=None) -> str:
    """The functions the coder may call, one block per step."""
    steps_all = steps_all or steps
    out = []
    for st in steps:
        lines = [f"step_{st.tx}(...)  — {st.asks}", f"   formula: {st.formula}", "   inputs:"]
        derived = {d.key: d for d in st.derive}
        for p in st.needs:
            if p.key in derived:
                d = derived[p.key]
                if d.params:
                    lines.append(_param_line(p, f"  (optional: if omitted it is computed from "
                                                f"{', '.join(q.key for q in d.params)})"))
                else:                           # a plain default (reactant_coefficient of step 208: 1)
                    try:
                        default = f"it is {d.fn({})!r}"
                    except Exception:           # noqa: BLE001
                        default = "it takes its default"
                    lines.append(_param_line(p, f"  (optional: if omitted {default})"))
            else:
                lines.append(_param_line(p))
        for d in st.derive:
            if d.key not in {p.key for p in st.needs} and d.params:
                # a hidden intermediate (electron_energy of steps 65/66): one of the two is REQUIRED
                lines.append(f"   - {d.key}: REQUIRED, either give {d.key}=... or give "
                             f"{', '.join(q.key + '=...' for q in d.params)} and it is computed")
            for q in d.params:
                if q.key not in {p.key for p in st.needs}:
                    lines.append(_param_line(q, f"  (only to compute {d.key})"))
        unit = st.unit if isinstance(st.unit, str) else "unit depends on the inputs"
        lines.append(f"   returns a dict: {st.answer!r} [{unit}] (the result)"
                     + (", also " + ", ".join(f"{k!r}" + (f" [{u}]" if (u := _unit_of_key(k, steps_all)) else "")
                                               for k in st.gives) if st.gives else "")
                     + (f"; passes on unchanged: {', '.join(st.carries)}" if st.carries else ""))
        out.append("\n".join(lines))
    return "\n\n".join(out)


def index_line(st) -> str:
    """One step as a one-line signature: for the other formulas the coder may also call."""
    unit = st.unit if isinstance(st.unit, str) else "varies"
    ins = ", ".join(f"{p.key}" + (f" [{p.unit}]" if p.unit else "") for p in st.needs)
    return f"step_{st.tx}({ins}) -> {st.answer!r}" + (f" [{unit}]" if unit else "") + f": {st.formula}"


_SRC: dict = {}


def step_source(tx: int) -> str:
    """The engine's own code for a step: its Step(...) definition and the module helpers its
    computation uses (not those of its traps), as written in core/engine/physical/*.py."""
    import inspect
    import textwrap
    from core.engine import physical as ph
    st = ph.step(tx)
    mod = inspect.getmodule(st.fn)
    path = inspect.getsourcefile(mod)
    if path not in _SRC:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        tree = ast.parse(text)
        steps, funcs = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Step":
                for kw in node.keywords:
                    if kw.arg == "tx" and isinstance(kw.value, ast.Constant):
                        steps[kw.value.value] = node
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                funcs[node.name] = node
        _SRC[path] = (text, steps, funcs)
    text, steps, funcs = _SRC[path]
    node = steps.get(tx)
    if node is None:
        return ""
    parts, seen = [], set()

    def helpers(n):
        for x in ast.walk(n):
            if isinstance(x, ast.Name) and x.id in funcs and x.id not in seen:
                seen.add(x.id)
                helpers(funcs[x.id]) if len(seen) < 6 else None
                parts.append(ast.get_source_segment(text, funcs[x.id]))
    for kw in node.keywords:
        if kw.arg != "traps":                   # the mistakes are not the coder's business
            helpers(kw.value)
    step_text = textwrap.dedent("    " + ast.get_source_segment(text, node))
    # lo= / hi= of an input only choose sample values; shown in the code they read as limits, and a coder refused
    # a density of 0.656 g/mL because the code said lo=0.8 (2014P1_Q40, 2026-11-18). Nothing enforces them.
    step_text = re.sub(r",\s*(?:lo|hi)=[-+]?[\w.]+(?:e[-+]?\d+)?", "", step_text)
    return "\n\n".join(parts + [step_text])


# ── running ──────────────────────────────────────────────────────────────────

class _Ctx:
    def __init__(self):
        self.calls, self.givens, self.constants = [], [], []
        self.recording = True
        self.patch = None              # (tx, Trap): that step returns the trap's wrong value
        self.scale = None              # (tx, factor, nth): that step's numeric results are scaled; nth None:
                                       # every call, else only its nth call (a ratio of two calls cancels)
        self.round = False


def _scalings(tx, calls) -> list:
    """How a step's results are perturbed to see whether they matter: every call at once, then (a step
    called more than once) each call on its own. t(1/8)/t(1/10) from one first-order law: scaling both
    calls cancels in the ratio, so the law looked unneeded (2012P1_Q36, run of 2026-11-17)."""
    n = sum(1 for c in calls if c["tx"] == tx)
    return [(tx, f, nth) for nth in [None] + (list(range(n)) if n > 1 else []) for f in RELEVANCE_FACTORS]


def _numbers_in(x):
    if isinstance(x, bool):
        return []
    if isinstance(x, (int, float)):
        return [float(x)] if math.isfinite(x) else []
    if isinstance(x, dict):
        return [n for v in x.values() for n in _numbers_in(v)]
    if isinstance(x, (list, tuple)):
        return [n for v in x for n in _numbers_in(v)]
    return []


def _make_step(st, ctx):
    from core.engine.base import EngineError, check_kind, round_sig
    need_keys = [p.key for p in st.needs]
    # a derived value (electron_energy of steps 65/66) may be given itself or computed from its params (Z):
    # both are inputs. The derived key was refused as "unknown" while the missing-input error asked for it,
    # and the coder went back and forth until the draw died (2 of 10 draws, fit A/B run of 2026-11-19)
    extra = {q.key for d in st.derive for q in d.params} | {d.key for d in st.derive} | set(st.carries)
    takes = need_keys + [f"{d.key} (or {', '.join(q.key for q in d.params)} to compute it)"
                         for d in st.derive if d.key not in need_keys and d.params]

    def f(*args, **kw):
        if args:
            raise SolveError(f"step_{st.tx} takes keyword arguments only, e.g. step_{st.tx}("
                             + ", ".join(f"{k}=..." for k in need_keys) + ")")
        v = dict(kw)
        unknown = set(v) - set(need_keys) - extra
        if unknown:
            raise SolveError(f"step_{st.tx}: unknown inputs {sorted(unknown)}; it takes {takes}")
        for d in st.derive:
            if d.key not in v:
                miss = [q.key for q in d.params if q.key not in v]
                if miss:
                    raise SolveError(f"step_{st.tx}: give {d.key!r}, or {miss} to compute it")
                v[d.key] = d.fn(dict(v))
        miss = [k for k in need_keys if k not in v]
        if miss:
            raise SolveError(f"step_{st.tx}: missing inputs {miss}")
        try:
            for p in st.needs:
                try:
                    check_kind(p.kind, v[p.key], p.choices)
                except EngineError as e:
                    # name the input: "must be a whole number, got 1e-07" alone sent the coder hunting
                    # for a unit error (run of 2026-11-16) when it had passed a concentration as n
                    raise SolveError(f"step_{st.tx}: input {p.key} ({p.desc}) {e}; you passed {v[p.key]!r}"
                                     ) from None
            out = st.fn(dict(v))
            if ctx.patch and ctx.patch[0] == st.tx:
                wrong = ctx.patch[1].fn(dict(v))
                out = {**out, **wrong} if isinstance(wrong, dict) else {**out, st.answer: wrong}
            check_kind(st.kind, out[st.answer])
        except EngineError as e:
            units = "; ".join(f"{p.key} in {p.unit}" for p in st.needs if p.unit)
            # the unit hint only for an out-of-range result: on a naming error ("does not appear in")
            # it misled the coder (run of 2026-11-16)
            ranged = re.search(r"negative|zero|must be|between|exceed|greater than|less than|more than|at most"
                               r"|at least|fraction|impossible", str(e))
            hint = (f" -- an impossible result usually means an input is in the wrong unit: give {units} "
                    f"(for example N × V in mL gives meq, not eq; mg is not g)") if units and ranged else ""
            raise SolveError(f"step_{st.tx}: {e}{hint}") from None
        except (ArithmeticError, ValueError, TypeError, KeyError) as e:
            raise SolveError(f"step_{st.tx}: {type(e).__name__}: {e}") from None
        for c in out.get("_constants", ()):
            if c not in ctx.constants:
                ctx.constants.append(c)
        out = {k: x for k, x in out.items() if k != "_constants"}
        for k in st.carries:
            if k in v and k not in out:
                out[k] = v[k]
        a = out.get(st.answer)
        if ctx.scale and ctx.scale[0] == st.tx and (
                ctx.scale[2] is None or ctx.scale[2] == sum(1 for c in ctx.calls if c["tx"] == st.tx)):
            # the result AND the other results it gives (formula 107 gives Tc and Pc beside its answer: a program
            # using out['Pc'] made 107 look irrelevant, stage run of 2026-11-16); inputs it hands on stay
            keys = [st.answer] + [k for k in st.gives if k not in v]
            out = {**out, **{k: out[k] * ctx.scale[1] for k in keys
                             if isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool)}}
        if ctx.round:
            out = round_sig(out, ROUND_SIG)
        if ctx.recording:
            ctx.calls.append({"tx": st.tx, "src": st.src, "dst": st.dst, "formula": st.formula,
                              "inputs": round_sig(v, 12), "outputs": round_sig(out, 5), "_raw_in": v,
                              "_raw_out": out})
        return dict(out)
    f._step = st                                        # for find(): which formula this function is
    return f


_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def clean_code(code: str) -> str:
    """Subscript digits outside string literals become ASCII ('CO₂ = ...' was a syntax error, run of
    2026-11-16); inside strings they stay, so quotes still match the question text."""
    if not any(ch in code for ch in "₀₁₂₃₄₅₆₇₈₉"):
        return code
    out, i, n, quote = [], 0, len(code), None
    while i < n:
        if quote:
            if code.startswith(quote, i):
                out.append(quote)
                i += len(quote)
                quote = None
                continue
            if code[i] == "\\" and i + 1 < n:
                out.append(code[i:i + 2])
                i += 2
                continue
            out.append(code[i])
            i += 1
            continue
        if code[i] == "#":
            j = code.find("\n", i)
            j = n if j < 0 else j
            out.append(code[i:j])
            i = j
            continue
        for q in ('"""', "'''", '"', "'"):
            if code.startswith(q, i):
                quote = q
                out.append(q)
                i += len(q)
                break
        else:
            out.append(code[i].translate(_SUBSCRIPTS))
            i += 1
    return "".join(out)


def _bracket(fn, lo, hi, points: int = 60, widen: int = 6):
    """A sub-range of [lo, hi] where f changes sign, scanning `points` points (log-spaced when
    both ends are positive); if none, the range is widened by 10× each side up to `widen` times.
    A wrong guess of range by the coder should not fail an otherwise correct program."""
    def f(x):
        try:
            v = float(fn(x))
            return v if math.isfinite(v) else None
        except Exception:                               # noqa: BLE001 - outside the step's domain
            return None
    if lo > hi:
        lo, hi = hi, lo
    for _ in range(widen + 1):
        if lo > 0:
            xs = [lo * (hi / lo) ** (i / points) for i in range(points + 1)]
        else:
            xs = [lo + (hi - lo) * i / points for i in range(points + 1)]
        prev = None
        for x in xs:
            v = f(x)
            if v is None:
                prev = None
                continue
            if v == 0:
                return x, x
            if prev is not None and (prev[1] < 0) != (v < 0):
                return prev[0], x
            prev = (x, v)
        lo, hi = (lo / 10, hi * 10) if lo > 0 else (lo - 10 * (hi - lo), hi + 10 * (hi - lo))
    return lo, hi                                       # no sign change: solve_bisect says so


WHOLE_SCAN = 200                                        # most whole numbers solve_for tries for one unknown


def _whole_root(fn, lo, hi, cause):
    """The whole number in [lo, hi] (at most WHOLE_SCAN + 1 of them) where f(n) is zero, or clearly nearest zero: |f| at most 1 % of the next best whole number's (the question's
    data are rounded, so the mismatch is seldom exactly 0). Raises SolveError otherwise."""
    start = max(int(math.floor(min(lo, hi))), -WHOLE_SCAN)
    stop = min(int(math.ceil(max(lo, hi))), start + WHOLE_SCAN)
    scores = []
    for n in range(start, stop + 1):
        try:
            v = float(fn(n))
        except Exception:                               # noqa: BLE001 - outside a step's domain
            continue
        if math.isfinite(v):
            scores.append((abs(v), n))
    scores.sort()
    if scores and (scores[0][0] == 0 or len(scores) == 1 and scores[0][0] < 1e-9
                   or len(scores) > 1 and scores[0][0] <= 0.01 * scores[1][0]):
        return scores[0][1]
    raise SolveError(f"solve_for: the unknown must be a whole number ({cause}), and no whole number from {start} "
                     f"to {stop} makes f zero; check the range and that f is the mismatch for the unknown")


def _run_once(code, steps, ctx, want="number", preset=None, entry="solve"):
    """Run the program's entry function (solve, or derive for derived values) on the preset values."""
    from core.engine.base import EngineError, solve_bisect

    def given(value, quote=""):
        if ctx.recording:
            ctx.givens.append({"value": value, "quote": str(quote)})
        return value

    def solve_for(fn, lo, hi):
        was = ctx.recording
        ctx.recording = False
        try:
            try:
                b_lo, b_hi = _bracket(fn, float(lo), float(hi))
                root = solve_bisect(lambda x: float(fn(x)), b_lo, b_hi)
            except (EngineError, ArithmeticError, ValueError, SolveError) as e:
                if "whole number" not in str(e):
                    raise
                # the unknown is a whole number (n, Z, l, a line count): bisection lands on 2.0000000000000004,
                # which the step refuses (run of 2026-11-15: an H-spectrum question failed 9 programs this way);
                # try the whole numbers instead, as find() does
                root = _whole_root(fn, lo, hi, e)
        except (EngineError, ArithmeticError, ValueError) as e:
            # an OverflowError at a far end of the widened range (10**pH, run of 2026-11-16) means no root
            # was found, not that the program is broken
            raise SolveError(f"solve_for: {e} (no sign change of f found in or around [lo, hi]; "
                             f"check that f is the mismatch for the unknown)") from None
        finally:
            ctx.recording = was
        fn(root)                                # the final evaluation goes into the trace
        return root

    def find(step_fn, unknown, result=None, **known):
        """The value of input `unknown` of one formula that makes its result equal `result`, the
        other inputs given: a formula worked backwards without writing the mismatch by hand. The
        result may also be given under the formula's own output name (equilibrium_constant=0.21),
        the way coders kept writing it (stage run of 2026-11-16: "missing argument 'result'" 5 times)."""
        st = getattr(step_fn, "_step", None)
        if st is None:
            raise SolveError("find: the first argument must be a formula function, e.g. "
                             "find(step_247, 'resistance', result=kappa, cell_constant=G)")
        ins = [q.key for q in st.needs]
        usage = (f"use find(step_{st.tx}, {unknown!r}, result=<value of {st.answer}>, "
                 + ", ".join(f"{k}=..." for k in ins if k != unknown) + ")")
        if result is None and st.answer in known:
            result = known.pop(st.answer)
        if result is None:
            raise SolveError(f"find(step_{st.tx}, {unknown!r}): give the known result as result=... "
                             f"(the value of {st.answer!r}); {usage}")
        par = next((q for q in st.needs if q.key == unknown), None)
        if par is None:
            raise SolveError(f"find: step_{st.tx} has no input {unknown!r}; its inputs are {ins}; {usage}")
        if unknown in known:
            raise SolveError(f"find: {unknown!r} is the unknown; do not also pass it; {usage}")
        allowed = set(ins) | {q.key for d in st.derive for q in d.params} | {d.key for d in st.derive} | set(st.carries)
        wrong = sorted(set(known) - allowed)
        if wrong:
            # said at once: every trial would fail on the name, and "no value gives ..." hid it
            raise SolveError(f"find(step_{st.tx}, {unknown!r}): unknown inputs {wrong}; step_{st.tx} takes {ins}; "
                             f"{usage}")
        missing = [k for k in ins if k != unknown and k not in known
                   and k not in {d.key for d in st.derive}]
        if missing:
            raise SolveError(f"find(step_{st.tx}, {unknown!r}): missing inputs {missing}; {usage}")
        target = float(result)
        if par.kind in ("integer", "count", "posint"):
            # a whole-number input (x in AxBy, a charge, a count): bisection lands on 1.0000000000000002,
            # which the step refuses (Codestral, 2022P2_Q3, 2026-11-17); try the whole numbers instead
            first = 1 if par.kind == "posint" else (0 if par.kind == "count" else -20)
            start = max(first, int(math.ceil(par.lo))) if par.lo is not None else first
            stop = min(int(par.hi), 200) if par.hi is not None else 200
            best, was = None, ctx.recording
            ctx.recording = False
            try:
                for n in range(start, stop + 1):
                    try:
                        got = float(step_fn(**known, **{unknown: n})[st.answer])
                    except (SolveError, ArithmeticError, ValueError, TypeError, KeyError):
                        continue
                    miss = abs(got - target)
                    if best is None or miss < best[1]:
                        best = (n, miss)
            finally:
                ctx.recording = was
            # 6e-3 (was 1e-3): a stated value printed to 3 significant figures is off by up to 0.5 %, and with derived
            # values (2026-11-26) the whole number is picked first and the printed value computed from it
            if best is None or best[1] > WHOLE_FIND_TOL * abs(target) + 1e-12:
                raise SolveError(f"find(step_{st.tx}, {unknown!r}): no whole number {unknown} from {start} to "
                                 f"{stop} gives {st.answer} = {target:g} with the other inputs")
            step_fn(**known, **{unknown: best[0]})       # the chosen value goes into the trace
            return best[0]
        lo = par.lo if par.lo is not None and par.lo > 0 else 1e-12
        hi = par.hi if par.hi is not None and par.hi > lo else 1e12
        if par.lo is not None and par.lo < 0:
            lo, hi = par.lo, (par.hi if par.hi is not None else -par.lo)
        try:
            return solve_for(lambda x: float(step_fn(**known, **{unknown: x})[st.answer]) - target, lo, hi)
        except SolveError as e:
            raise SolveError(f"find(step_{st.tx}, {unknown!r}): no value of {unknown} gives "
                             f"{st.answer} = {target:g} with the other inputs ({e})") from None

    # Calculator: sandboxed programs may call calculate("2.5 * 6.022e23 / 1000") to avoid
    # manual arithmetic errors; uses the same safe AST evaluator as the ladder's tool.
    from core.models import _eval_calc as _calc_impl
    def _sandbox_calculate(expr: str) -> float:
        """Evaluate an arithmetic expression and return a float. Raises ValueError on error."""
        result = _calc_impl(str(expr))
        if result.startswith("ERROR:"):
            raise ValueError(result[6:].strip())
        return float(result)

    env = {"__builtins__": dict(_SAFE_BUILTINS), "math": math, "given": given, "solve_for": solve_for,
           "find": find, "calculate": _sandbox_calculate,
           **{f"step_{st.tx}": _make_step(st, ctx) for st in steps}}
    # the question's values are variables of the program under their own names (its [[blanks]]); a whole
    # number stays whole (a count used in range())
    import keyword
    for k, val in (preset or {}).items():
        if str(k).isidentifier() and not keyword.iskeyword(k) and k not in env:
            env[k] = val if isinstance(val, int) and not isinstance(val, bool) else float(val)
    def _check_value_(name, value):
        # only the program's real run: not a solve_for trial value, not a trap or relevance perturbation
        if ctx.recording and ctx.patch is None and ctx.scale is None:
            check_value(name, value)

    env["_check_value_"] = _check_value_
    exec(_instrumented(code), env)                     # noqa: S102 - checked by check_code, own process
    if entry not in env:
        raise SolveError(f"define a function {entry}()")
    ans = env[entry]()
    if want == "dict":
        if not isinstance(ans, dict) or not ans:
            raise SolveError(f"{entry}() must return a dict of named numbers, got {ans!r}")
        out = {}
        for k, v in ans.items():
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise SolveError(f"{entry}() returned {k!r} = {v!r}: every value must be one finite number")
            out[str(k)] = float(v)
        return out
    if isinstance(ans, dict):
        ans = ans.get("answer")
    if isinstance(ans, bool) or not isinstance(ans, (int, float)) or not math.isfinite(ans):
        raise SolveError(f"solve() must return one finite number, got {ans!r}")
    return float(ans)


_SCALES = [10.0 ** k for k in range(-9, 10, 3)]


def _same(a, b):
    if a == 0 or b == 0:
        return False
    for s in _SCALES:
        for sign in (1, -1):
            if math.isclose(a * s * sign, b, rel_tol=1e-6):
                return True
    return False


def dependency_depth(calls) -> int:
    """Longest path of distinct steps along calls whose inputs reuse an earlier call's output
    (allowing a power-of-ten unit change or a sign change)."""
    n = len(calls)
    best = [None] * n                    # set of txs on the longest path ending at call i
    for j in range(n):
        ins = _numbers_in(calls[j]["_raw_in"])
        cand = {calls[j]["tx"]}
        for i in range(j):
            outs = _numbers_in(calls[i]["_raw_out"])
            if any(_same(o, x) for o in outs for x in ins):
                path = best[i] | {calls[j]["tx"]}
                if len(path) > len(cand):
                    cand = path
        best[j] = cand
    return max((len(b) for b in best), default=0)


def _allowed(txs, any_step):
    from core.engine import physical as ph
    return sorted(ph.STEPS) if any_step else list(txs)


def _evaluate(code, txs, any_step=False, preset=None, exempt=()):
    """preset: the question's values by name (its [[blanks]]), given to the program as variables.
    With preset, inputs_irrelevant lists the values the answer does not depend on (each value must
    matter, 2026-11-17); names in exempt (stated constants the steps hold themselves) are not tested."""
    from core.engine import physical as ph
    from core.engine.base import answers_match, round_sig
    steps = [ph.step(t) for t in _allowed(txs, any_step)]
    probs = check_code(code, _allowed(txs, any_step))
    if probs:
        return {"ok": False, "error": "; ".join(probs)}
    ctx = _Ctx()
    try:
        answer = _run_once(code, steps, ctx, preset=preset)
    except SolveError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:                              # noqa: BLE001 - the coder's bug
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    called = {c["tx"] for c in ctx.calls}
    unused = [t for t in txs if t not in called]
    called_txs = list(dict.fromkeys(c["tx"] for c in ctx.calls))
    used_steps = [ph.step(t) for t in called_txs]

    rc = _Ctx()
    rc.round = True
    try:
        shifted = _run_once(code, steps, rc, preset=preset)
        dev = abs(shifted - answer) / abs(answer) if answer else 0.0
        tol = min(MAX_TOLERANCE, max(0.01, 1.5 * dev))
    except Exception:                                   # noqa: BLE001
        tol = 0.01

    traps, seen = [], []
    for st in used_steps:
        for t in st.traps:
            tc = _Ctx()
            tc.patch = (st.tx, t)
            try:
                wrong = _run_once(code, steps, tc, preset=preset)
            except Exception:                           # noqa: BLE001 - this mistake breaks the program
                continue
            if answers_match(wrong, answer, rel_tol=tol) or any(answers_match(wrong, w, rel_tol=tol) for w in seen):
                continue
            seen.append(wrong)
            traps.append({"id": t.id, "desc": t.desc, "tx": st.tx, "step": called_txs.index(st.tx),
                          "wrong_answer": round_sig(wrong)})
    descs = [t["desc"] for t in traps]
    for t in traps:
        if descs.count(t["desc"]) > 1:
            t["desc"] = f"{t['desc']}, when finding the {ph.step(t['tx']).asks}"

    given_nums = [g["value"] for g in ctx.givens if isinstance(g["value"], (int, float))]
    given_nums += [float(v) for v in (preset or {}).values()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
    inter = []
    for c in ctx.calls:
        for x in _numbers_in(c["_raw_out"]):
            if not any(_same(x, gv) or x == gv for gv in given_nums) and x not in inter:
                inter.append(x)
    depth = dependency_depth(ctx.calls)
    irrelevant = []                      # steps whose results do not change the answer
    for tx in called_txs:
        res = [c["_raw_out"].get(ph.step(tx).answer) for c in ctx.calls if c["tx"] == tx]
        if not any(isinstance(x, (int, float)) and not isinstance(x, bool) for x in res):
            continue                     # a text result (an equation) cannot be scaled
        # a small change first; then large ones, because a discrete answer (a coordination number
        # from a radius ratio) only moves when a result crosses a boundary (run of 2026-11-16)
        matters = False
        for scale in _scalings(tx, ctx.calls):
            sc = _Ctx()
            sc.scale = scale
            try:
                moved = _run_once(code, steps, sc, preset=preset)
            except Exception:                           # noqa: BLE001 - it broke the program: it matters
                matters = True
                break
            if abs(moved - answer) > 1e-7 * abs(answer) + 1e-300:
                matters = True
                break
        if not matters:
            irrelevant.append(tx)
    roles = {k: _input_role(code, steps, preset, k, answer, ctx.calls) for k in (preset or {}) if k not in set(exempt)}
    inputs_unused = [k for k, r in roles.items() if r is None]           # feeds neither a formula nor the answer
    inputs_irrelevant = [k for k, r in roles.items() if r != "answer"]   # the answer does not depend on it
    constants = list(dict.fromkeys(c for st in used_steps for c in st.constants))
    constants += [c for c in ctx.constants if c not in constants]
    trace = [{k: v for k, v in c.items() if not k.startswith("_")} for c in ctx.calls]
    return {"ok": True, "answer": round_sig(answer, 4), "answer_exact": answer, "trace": trace,
            "givens": ctx.givens, "traps": traps, "tolerance": tol, "depth": depth, "unused_steps": unused,
            "irrelevant_steps": irrelevant, "called_txs": called_txs,
            "intermediates": inter, "constants": constants, "inputs_irrelevant": inputs_irrelevant,
            "inputs_unused": inputs_unused}


def _input_role(code, steps, preset, name, answer, base_calls):
    """What one value of the question does, found by changing it (a count, an int, by one; any other value by
    +2 %, -3 %, +0.1 % and -0.1 %): "answer" if the answer changes, "formula" if only the inputs of the
    formulas change (it cancels out, as T in a ratio of two isothermal steps), None if neither: the program
    does not use it. A change the program cannot take (a count of 0, a fraction above 1) proves nothing: only
    when no change at all can be made is the value taken as used. (2026-11-18: 1 bar was moved to 0, P / P
    failed, and the fake "use" of P counted as mattering.)"""
    v = preset[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "answer"
    if isinstance(v, int):
        tries = [v + 1, v - 1]
    else:
        tries = [v * 1.02, v * 0.97, v * 1.001, v * 0.999] if v else [1e-3, -1e-3]
    base = [c["_raw_in"] for c in base_calls]
    role, ran, refused = None, False, False
    for w in tries:
        c = _Ctx()
        try:
            moved = _run_once(code, steps, c, preset={**preset, name: w})
        except Exception:                               # noqa: BLE001 - this change is not possible
            refused = True
            continue
        ran = True
        if abs(moved - answer) > 1e-7 * abs(answer) + 1e-300:
            return "answer"
        if [x["_raw_in"] for x in c.calls] != base:
            role = "formula"
    # A non-whole value whose nudge the program refuses is read by it: a value it never reads cannot make it fail.
    # Live run of 2026-11-26: f_rev was the target of a whole-number search for n (find); ±0.1 % gave the same n and
    # ±2 % found no whole n, so f_rev was called unused and a right question was rejected twice. Whole numbers keep
    # the old rule (2026-11-18: a count moved from 1 to 0 broke a division, which proved nothing).
    if role is None and refused and not isinstance(v, int):
        role = "formula"
    return role if ran else "answer"


# ── the question's numbers: picked by code, checked by the engine ────────────────────────────────────
# (2026-11-17) The writer leaves the numbers as [[blanks]] with a realistic range each (or a value that
# belongs to the substance); the solving program is written from the question with its blanks; then code
# picks values in the ranges, runs the program and keeps the first set that gives a valid question.

CODE_ERRORS = re.compile(r"SyntaxError|syntax error|NameError|TypeError|AttributeError|KeyError|IndexError|"
                         r"UnboundLocalError|keyword arguments only|unknown inputs|missing inputs|has no input|"
                         r"must return one finite number|is not allowed|first argument must be|give the known "
                         r"result|is the unknown; do not also pass it")


def names_read(code: str) -> set:
    """The names a program reads (loads): a question value whose name the program never reads is not
    used by it."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def names_assigned(code: str) -> set:
    """The names a program assigns to (stores): a question value it assigns to is no longer the question's."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}


def _round3(x: float) -> float:
    return float(f"{x:.3g}")


def sample_values(ranges: dict, fixed: dict, rng) -> dict:
    """One set of the question's values: each range blank drawn at random (log-uniform over a wide positive
    range, else uniform; a whole-number range gives a whole number), rounded to 3 significant figures as
    the question prints it; the fixed values as they are."""
    out = dict(fixed)
    for name, (lo, hi, whole) in ranges.items():
        if whole:
            out[name] = rng.randint(int(math.ceil(lo)), int(math.floor(hi)))
        elif lo > 0 and hi / lo >= 20:
            out[name] = _round3(math.exp(rng.uniform(math.log(lo), math.log(hi))))
        else:
            out[name] = _round3(rng.uniform(lo, hi))
    return out


AIM_GRID = 9            # points scanned across a value's range when aiming the answer
AIM_BISECT = 40         # bisection steps once the answer is bracketed
AIM_VALUES = 2          # range values tried per out-of-range draw


def _aim(code, steps, values, ranges, answer_range, rng, deadline):
    """Answer first: a target drawn inside answer_range, then one range value solved so the program's answer hits
    it (scan the value's own range for a sign change, then bisect), the rest of the draw kept. A value set the
    program refuses (a step's input check, an impossible computed value) is simply not a solution, so the solved
    value also lands where the stated data are possible. (values, answer) or None. Draws whose answer fell outside
    answer_range were thrown away before (2026-11-25); with wide ranges most were."""
    lo_a, hi_a = float(answer_range[0]), float(answer_range[1])
    if lo_a > 0 and hi_a / lo_a >= 20:
        target = math.exp(rng.uniform(math.log(lo_a), math.log(hi_a)))
    else:
        target = rng.uniform(lo_a, hi_a)
    names = [k for k, (lo, hi, whole) in ranges.items() if not whole and hi > lo]
    rng.shuffle(names)
    for k in names[:AIM_VALUES]:
        lo, hi, _ = ranges[k]
        logscale = lo > 0 and hi / lo >= 20

        def g(x):
            try:
                return _run_once(code, steps, _Ctx(), preset={**values, k: x}) - target
            except Exception:                           # noqa: BLE001 - refused or broken here: no solution
                return None

        if logscale:
            grid = [math.exp(math.log(lo) + (math.log(hi) - math.log(lo)) * i / (AIM_GRID - 1)) for i in range(AIM_GRID)]
        else:
            grid = [lo + (hi - lo) * i / (AIM_GRID - 1) for i in range(AIM_GRID)]
        pts = []
        for x in grid:
            if time.time() > deadline:
                return None
            pts.append((x, g(x)))
        for (a, fa), (b, fb) in zip(pts, pts[1:]):
            if fa is None or fb is None or fa * fb > 0:
                continue
            for _ in range(AIM_BISECT):
                mid = math.sqrt(a * b) if logscale else (a + b) / 2
                fm = g(mid)
                if fm is None:
                    break
                if fa * fm <= 0:
                    b, fb = mid, fm
                else:
                    a, fa = mid, fm
            new = {**values, k: _round3((a + b) / 2)}
            try:
                ans = _run_once(code, steps, _Ctx(), preset=new)
            except Exception:                           # noqa: BLE001
                continue
            if lo_a <= ans <= hi_a:
                return new, ans
    return None


def _search(code, txs, ranges, fixed, answer_range=None, tries=200, fragile_tol=0.02, min_traps=2,
            exempt=(), seed=0, deadline_s=60.0, probe=False, hidden=None, derived=None):
    """Pick the question's values. probe=True: the first set the program runs on at all (does the program
    work?). Otherwise the first set that also gives an answer in answer_range, is not fragile (rounding the
    steps to 3 figures moves it by at most fragile_tol), has at least min_traps typical mistakes that change
    it, and where every value matters. {"ok", "values", "run", "tries"} or {"ok": False, "kind", "error",
    "counts"}; kind is "code" when every failure was the program's own error."""
    import random
    import time
    from core.engine import physical as ph
    rng = random.Random(seed)
    steps = [ph.step(t) for t in _allowed(txs, True)]
    probs = check_code(code, _allowed(txs, True))
    if probs:
        return {"ok": False, "kind": "code", "error": "; ".join(probs), "counts": {}}
    assigned = [k for k in list(ranges) + list(fixed) if k in names_assigned(code)]
    if assigned:
        msg = (f"the program assigns to {', '.join(assigned)}: these are the question's values, already defined "
               f"as variables; use them as they are, never assign to them")
        return {"ok": False, "kind": "code", "error": msg, "counts": {"code": 1}, "first": {"code": msg}, "tries": 0}
    # every value the question states must be used: a value the program never reads could contradict the
    # others unseen. A value it reads that cancels out (T in a ratio of two isothermal steps) is fine:
    # any value of it gives the same answer, so it cannot contradict anything.
    unread = [k for k in list(ranges) + list(fixed) if k not in set(exempt) and k not in names_read(code)]
    if unread:
        return {"ok": False, "kind": "value_unused", "error": ", ".join(unread), "counts": {"value_unused": 1},
                "first": {"value_unused": ", ".join(unread)}, "tries": 0}
    t0 = time.time()
    counts, first, seen = {}, {}, []

    def fail(kind, msg):
        counts[kind] = counts.get(kind, 0) + 1
        first.setdefault(kind, msg)

    n = 0
    for n in range(1, tries + 1):
        if time.time() - t0 > deadline_s:
            break
        values = sample_values(ranges, fixed, rng)
        if derived:
            # derived values (2026-11-26): the hidden free choices are drawn, derive() computes the stated values
            # from them with engine steps, and only the stated values (rounded as printed) go to solve()
            hv = sample_values(hidden or {}, {}, rng)
            try:
                dv = _run_once(code, steps, _Ctx(), want="dict", preset={**values, **hv}, entry="derive")
            except Exception as e:                      # noqa: BLE001
                msg = str(e) if isinstance(e, SolveError) else f"{type(e).__name__}: {e}"
                fail("code" if CODE_ERRORS.search(msg) or "derive" in msg else "engine", msg)
                continue
            gone = [d for d in derived if d not in dv]
            if gone:
                fail("code", f"derive() returned no value for {', '.join(gone)}")
                continue
            values = {**values, **{d: _round3(dv[d]) for d in derived}}
        try:
            ans = _run_once(code, steps, _Ctx(), preset=values)
        except Exception as e:                          # noqa: BLE001
            msg = str(e) if isinstance(e, SolveError) else f"{type(e).__name__}: {e}"
            fail("code" if CODE_ERRORS.search(msg) else "engine", msg)
            if "code" in counts and counts["code"] >= 3 and len(counts) == 1:
                break                                   # the program itself is broken: no values will help
            continue
        if probe:
            return {"ok": True, "values": values, "run": _evaluate(code, txs, True, values, exempt), "tries": n}
        if answer_range and not (answer_range[0] <= ans <= answer_range[1]):
            # no aiming with derived values: moving one stated value would break what derive() computed
            aimed = _aim(code, steps, values, ranges, answer_range, rng, t0 + deadline_s) \
                if ranges and not derived else None
            if aimed is None:
                fail("answer_range", f"{ans:.4g}")
                seen.append(ans)
                continue
            values, ans = aimed
        run = _evaluate(code, txs, True, values, exempt)
        if not run.get("ok"):
            fail("engine", run.get("error", "?"))
            continue
        if run["inputs_unused"]:
            fail("value_unused", ", ".join(run["inputs_unused"]))
            if counts["value_unused"] >= 3 and len(counts) == 1:
                break                                   # the same values are never used: no point going on
            continue
        if run["tolerance"] > fragile_tol:
            fail("fragile", f"{run['tolerance']:.1%}")
            continue
        if len(run["traps"]) < min_traps:
            fail("traps", ", ".join(t["desc"] for t in run["traps"]) or "none")
            continue
        return {"ok": True, "values": values, "run": run, "tries": n}
    # the failure of the sets that got furthest, not the most frequent one: 125 sets outside the answer range
    # and 75 inside it that failed the typical-mistake check were reported as "never inside your answer_range"
    # (2017P1_Q26, 2026-11-18)
    depth = {"code": 0, "engine": 0, "answer_range": 1, "value_unused": 2, "fragile": 3, "traps": 4}
    kind = max(counts, key=lambda k: (depth.get(k, 0), counts[k])) if counts else "engine"
    out = {"ok": False, "kind": kind, "error": first.get(kind, "no value set tried"), "counts": counts,
           "first": first, "tries": n}
    if seen:
        out["answers_seen"] = [min(seen), max(seen)]     # where the answers fell instead of answer_range
    return out


def _search_worker(q, args, kwargs):
    try:
        q.put(_search(*args, **kwargs))
    except Exception as e:                              # noqa: BLE001
        q.put({"ok": False, "kind": "code", "error": f"{type(e).__name__}: {e}", "counts": {}, "tries": 0})


def search_numbers(code: str, txs, ranges: dict, fixed: dict, answer_range=None, *, tries: int = 200,
                   fragile_tol: float = 0.02, min_traps: int = 2, exempt=(), seed: int = 0,
                   timeout: float = 90.0, probe: bool = False, hidden=None, derived=None) -> dict:
    """_search in its own process (the same isolation as evaluate). ranges: {name: (lo, hi, whole)};
    fixed: {name: value}; hidden: the free choices derived values are computed from ({name: (lo, hi, whole)});
    derived: the stated values derive() computes."""
    code = clean_code(code)
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    kwargs = {"answer_range": answer_range, "tries": tries, "fragile_tol": fragile_tol, "min_traps": min_traps,
              "exempt": tuple(exempt), "seed": seed, "deadline_s": max(5.0, timeout - 15), "probe": probe,
              "hidden": {k: tuple(v) for k, v in (hidden or {}).items()}, "derived": list(derived or ())}
    p = ctx.Process(target=_search_worker, args=(q, (code, list(txs), dict(ranges), dict(fixed)), kwargs),
                    daemon=True)
    p.start()
    try:
        out = q.get(timeout=timeout)
    except Exception:                                   # noqa: BLE001
        # no reply: the program hung (a solve_for that never ends) or the process died. Not the question's
        # ranges: kind "timeout", which goes back to the coder, never to the writer as "impossible"
        out = {"ok": False, "kind": "timeout", "error": f"the program did not finish within {timeout:g} s "
               f"(or its process stopped)", "counts": {"timeout": 1}, "tries": 0}
    p.join(1)
    if p.is_alive():
        p.terminate()
    return out


def _worker(code, txs, any_step, q, preset=None, exempt=()):
    try:
        q.put(_evaluate(code, txs, any_step, preset, exempt))
    except Exception as e:                              # noqa: BLE001
        q.put({"ok": False, "error": f"{type(e).__name__}: {e}"})


def evaluate(code: str, txs, timeout: float = TIMEOUT_S, any_step: bool = False, preset: dict | None = None,
             exempt=()) -> dict:
    """Run the program in its own process; {"ok": False, "error"} on any failure or timeout.
    txs: the steps it must call; any_step: it may also call every other step of the knowledge
    graph (called_txs in the result lists what it used)."""
    code = clean_code(code)
    probs = check_code(code, _allowed(txs, any_step))
    if probs:
        return {"ok": False, "error": "; ".join(probs)}
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(code, list(txs), any_step, q, dict(preset or {}), tuple(exempt)),
                    daemon=True)
    p.start()
    try:
        out = q.get(timeout=timeout)
    except Exception:                                   # noqa: BLE001 - queue.Empty: too slow
        out = {"ok": False, "error": f"solve() did not finish within {timeout:g} s"}
    p.join(1)
    if p.is_alive():
        p.terminate()
    return out
