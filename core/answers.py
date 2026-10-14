"""
Reading and comparing final answers in code.

Council members return their final answer as text. This module turns that text into
something comparable with the engine's answer — a number, a formula, a label — and
decides "matches" without any model: numbers within 1%, text after normalisation.
"""

from __future__ import annotations

import ast
import math
import operator
import re

from core.engine.base import answers_match

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_NUMERIC_ANSWER = re.compile(r"""
    ^(?:[^\W\d][\w ()\[\]°]{0,24}?\s*(?:=|≈|:)\s*)?           # optional label: "t =", "ΔG =", "Age:"
    (?P<num>[-+]?(?:\d+\.?\d*|\.\d+))
    (?:\s*(?:[eE](?P<e1>[-+]?\d+)
           |[×xX*·]\s*10\s*(?:\^|\*\*)?\s*\(?(?P<e2>[-+]?\d+)\)?))?
    (?P<unit>.*)$""", re.VERBOSE)
# One unit word: letters (with an optional exponent such as m^-3, s-1, CO2) or %, °, ‰.
_UNIT_WORD = re.compile(r"^(?:[%‰°]|[A-Za-zµμΩ°()/·⁻¹²³]+(?:\^?[-+]?\d+)?)+$")


def parse_numeric_answer(text):
    """The value of a numeric final answer, or None if the answer is not a number.

        "2.08 × 10^9 years" -> 2.08e9     "t = 6.44e9 years" -> 6.44e9
        "-0.76 V" -> -0.76                "3 isomers" -> 3.0
        "2-methylbut-2-ene" -> None       "propan-2-ol" -> None
        "x = 2, y = 3" -> None            "Option B" -> None
    """
    if text is None:
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
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
    """All values of a numeric answer as a list, or None if any part is not a number
    ("Ea = 293.95 kJ/mol, t = 10.4 s" -> [293.95, 10.4])."""
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


def normalise_text(s) -> str:
    """Lower-case, single spaces, subscript/superscript digits as plain digits, no
    trailing full stop: 'C₆H₁₂O₆.' -> 'c6h12o6'."""
    t = str(s).translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")).translate(_SUPERSCRIPTS)
    return " ".join(t.strip().rstrip(".").lower().split())


def matches(engine_answer, member_answer, kind: str = "real", rel_tol: float = 0.01) -> bool:
    """Does a council member's final answer match the engine's? Numbers within 1%;
    formulas/labels after normalisation; anything unreadable does not match."""
    if member_answer is None:
        return False
    if kind == "letters":
        from core.engine.facts import letters_of
        return bool(engine_answer) and letters_of(member_answer) == "".join(sorted(engine_answer))
    if isinstance(engine_answer, (int, float)) and not isinstance(engine_answer, bool):
        value = numeric_value(member_answer)
        return value is not None and answers_match(float(engine_answer), value, rel_tol)
    if isinstance(engine_answer, str):
        return normalise_text(engine_answer) == normalise_text(member_answer) or \
            text_answers_match(engine_answer, member_answer) is True
    return answers_match(engine_answer, member_answer)


# ── Non-numeric answers ──────────────────────────────────────────────────────
# The engine's text answers come in a few shapes; each is compared exactly by code.
# text_answers_match returns True / False when code can decide, None when it cannot
# (then the verifier's answer_equivalent field decides; see flow._grade).

_SUBS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")

# category -> (patterns that mean it); checked in order, negations first
_CATEGORIES = {
    "direction": [
        ("no shift", r"\bno (net )?(shift|change|effect|reaction)\b|\bunaffected\b|\bunchanged\b|\bdoes(n't| not) shift\b|"
                     r"\bremains? (the same|unchanged)\b|\bneither\b|\bno direction\b|\b(at|in) equilibrium\b"),
        ("backward", r"\bbackward|\breverse|\bleft\b|\btowards? (the )?reactants?\b|\breactant side\b"),
        ("forward", r"\bforward|\bright\b|\btowards? (the )?products?\b|\bproduct side\b"),
    ],
    "precipitation": [
        ("no precipitate", r"^no\b|\bno precipitat|\bnot? (form|precipitat)|\bdoes(n't| not) (form|precipitat)|"
                           r"\bwill not\b|\bwon't\b|\bremains? (clear|in solution)\b|\bunsaturated\b"),
        ("precipitate forms", r"^yes\b|\bprecipitat(e|es|ion) (forms?|occurs?|will form)\b|\bprecipitates\b|"
                              r"\bwill precipitate\b|\bforms?\b"),
    ],
    "relation": [
        ("none of these", r"\bnone\b|\bno (such )?relation\b|\bneither\b"),
        ("isodiaphers", r"\bisodiapher"),
        ("isotones", r"\bisotone"),
        ("isobars", r"\bisobar"),
        ("isotopes", r"\bisotope"),
    ],
}
_CATEGORY_OF = {label: cat for cat, rules in _CATEGORIES.items() for label, _ in rules}
_CATEGORY_OF["at equilibrium"] = "direction"
_SAME = {"at equilibrium": "no shift"}       # engine labels that mean the same outcome


_FIRST_MATCH = {"precipitation"}     # negation patterns come first and win ("no precipitate forms")


def _category(cat: str, text: str):
    """The category an answer names. Precipitation: first rule that matches (negations first).
    Directions and relations: exactly one category must match, else None (ambiguous, e.g.
    'the system at equilibrium shifts forward')."""
    t = " ".join(str(text).lower().split())
    hits = [label for label, pattern in _CATEGORIES[cat] if re.search(pattern, t)]
    if cat in _FIRST_MATCH:
        return hits[0] if hits else None
    return hits[0] if len(hits) == 1 else None


def _formula(text: str):
    from core.engine.chem import parse_formula
    s = str(text).translate(_SUBS).translate(_SUPERSCRIPTS).strip().rstrip(".")
    s = re.sub(r"\((s|l|g|aq)\)", "", s)           # state labels
    s = s.replace("·", ".").replace(" ", "")
    m = re.match(r"^(.*?)([+-]\d*|\d*[+-])$", s)      # trailing charge: SO4^2- / SO42- / Fe3+
    try:
        if m and m.group(2) and not s.startswith(("+", "-")):
            counts, charge = parse_formula(m.group(1).rstrip("^") + "^" + m.group(2))
        else:
            counts, charge = parse_formula(s)
    except Exception:  # noqa: BLE001
        return None
    return (tuple(sorted(counts.items())), charge)


def _nuclide(text: str):
    """(symbol, A) from 'Th-234', '234Th', '²³⁴₉₀Th', 'thorium-234 (Th-234)'."""
    from core.engine.chem import SYMBOLS
    raw = str(text)
    sup = re.findall(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+", raw)
    t = raw.translate(_SUPERSCRIPTS).translate(_SUBS)
    syms = [s for s in re.findall(r"[A-Z][a-z]?", t) if s in SYMBOLS]
    if not syms:
        return None
    if sup:                                           # superscript = mass number
        return syms[-1], int(sup[-1].translate(_SUPERSCRIPTS))
    nums = [int(n) for n in re.findall(r"\d+", t)]
    return (syms[-1], max(nums)) if nums else None


def _config(text: str):
    t = str(text).translate(_SUPERSCRIPTS).translate(_SUBS)
    t = re.sub(r"[\s,]", "", t)
    return t if re.fullmatch(r"(\[[A-Z][a-z]?\])?(\d[spdf]\d+)+", t) else None


def _equation(text: str):
    from core.engine.chem import parse_equation
    try:
        r, p = parse_equation(str(text).translate(_SUBS).translate(_SUPERSCRIPTS))
    except Exception:  # noqa: BLE001
        return None
    coeffs = [c for c, _ in r + p]
    g = math.gcd(*[int(round(c)) for c in coeffs]) if all(float(c).is_integer() for c in coeffs) else 1
    norm = lambda side: tuple(sorted((_formula(f) or f, c / g) for c, f in side))
    return norm(r), norm(p)


def text_answers_match(engine_answer: str, member_answer):
    """True / False when code can compare these two non-numeric answers, else None."""
    e = str(engine_answer).strip()
    cat = _CATEGORY_OF.get(e)
    if cat:
        got = _category(cat, member_answer)
        return None if got is None else got == _SAME.get(e, e)
    if e == "not allowed":
        t = str(member_answer).lower()
        if re.search(r"not (allowed|possible|valid|exist)|\binvalid\b|\bimpossible\b|no such", t):
            return True
        return False if re.search(r"\b\d[spdfg]\b", t) else None
    if re.fullmatch(r"\d[spdfg]", e):                 # orbital label, e.g. '3d'
        found = re.findall(r"\b(\d)\s*([spdfg])\b", str(member_answer).lower())
        return None if not found else (e in {a + b for a, b in found} and len(set(found)) == 1)
    if re.fullmatch(r"[A-Z][a-z]?-\d+", e):           # nuclide, e.g. 'Th-234'
        sym, a = e.split("-")
        got = _nuclide(member_answer)
        return None if got is None else got == (sym, int(a))
    if "->" in e or "→" in e:
        a, b = _equation(e), _equation(member_answer)
        return None if a is None or b is None else a == b
    if _config(e):
        got = _config(member_answer)
        return None if got is None else got == _config(e)
    fe = _formula(e)
    if fe is not None:
        fm = _formula(member_answer)
        return None if fm is None else fm == fe
    return None


def numeric_value(text):
    """The number a final answer states, or None: '0.216', '11/51', 'ln(4)/2', 'P = 143',
    '143.3 K', '2.5 × 10⁻²⁰ m²'. Arithmetic is evaluated safely first (so a fraction is not
    misread as its denominator), then labelled or unit-bearing answers are parsed."""
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace("−", "-")
    # a superscript exponent is a power: 10⁻¹⁵ -> 10^(-15), never 10 - 15
    s = re.sub(r"([0-9)])\s*([⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)",
               lambda m: f"{m.group(1)}^({m.group(2).translate(_SUPERSCRIPTS)})", s)
    try:
        return float(safe_eval(s))
    except (ValueError, ZeroDivisionError, OverflowError, SyntaxError, TypeError):
        pass
    return parse_numeric_answer(s)


# ── Units ────────────────────────────────────────────────────────────────────
# A member may answer in another unit than the one asked (156100 J mol⁻¹ for 156.1 kJ mol⁻¹).
# The value is converted using the unit the member STATED, so a real "forgot to convert"
# mistake (156100 with unit kJ mol⁻¹) still does not match. Units that cannot be read, or
# differ in dimension, are not converted.

_U = {  # symbol: (dimension vector as dict, factor to the base unit)
    "m": ({"L": 1}, 1.0), "km": ({"L": 1}, 1e3), "cm": ({"L": 1}, 1e-2), "mm": ({"L": 1}, 1e-3),
    "µm": ({"L": 1}, 1e-6), "μm": ({"L": 1}, 1e-6), "nm": ({"L": 1}, 1e-9), "pm": ({"L": 1}, 1e-12),
    "Å": ({"L": 1}, 1e-10), "A°": ({"L": 1}, 1e-10),
    "L": ({"L": 3}, 1e-3), "l": ({"L": 3}, 1e-3), "mL": ({"L": 3}, 1e-6), "ml": ({"L": 3}, 1e-6),
    "dm": ({"L": 1}, 0.1),
    "kg": ({"M": 1}, 1.0), "g": ({"M": 1}, 1e-3), "mg": ({"M": 1}, 1e-6),
    "mol": ({"N": 1}, 1.0), "mmol": ({"N": 1}, 1e-3),
    "M": ({"N": 1, "L": -3}, 1e3), "mM": ({"N": 1, "L": -3}, 1.0),
    "s": ({"T": 1}, 1.0), "ms": ({"T": 1}, 1e-3), "min": ({"T": 1}, 60.0), "h": ({"T": 1}, 3600.0),
    "hr": ({"T": 1}, 3600.0), "day": ({"T": 1}, 86400.0), "days": ({"T": 1}, 86400.0),
    "year": ({"T": 1}, 3.15576e7), "years": ({"T": 1}, 3.15576e7), "yr": ({"T": 1}, 3.15576e7),
    "J": ({"E": 1}, 1.0), "kJ": ({"E": 1}, 1e3), "MJ": ({"E": 1}, 1e6), "cal": ({"E": 1}, 4.184),
    "kcal": ({"E": 1}, 4184.0), "eV": ({"E": 1}, 1.602176634e-19),
    "Pa": ({"P": 1}, 1.0), "kPa": ({"P": 1}, 1e3), "bar": ({"P": 1}, 1e5), "atm": ({"P": 1}, 101325.0),
    "mmHg": ({"P": 1}, 133.322), "torr": ({"P": 1}, 133.322), "Torr": ({"P": 1}, 133.322),
    "K": ({"K": 1}, 1.0), "V": ({"V": 1}, 1.0), "mV": ({"V": 1}, 1e-3),
    "C": ({"Q": 1}, 1.0), "A": ({"I": 1}, 1.0), "S": ({"G": 1}, 1.0), "mS": ({"G": 1}, 1e-3),
}
_UNIT_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


def _unit(u):
    """(dimension dict, factor) of a unit string such as 'kJ mol⁻¹', 'J/mol', 'mol L^-1',
    'L mol-1 s-1', 'dm³'; None if any part is unknown. '' is dimensionless."""
    s = str(u or "").strip().translate(_UNIT_SUP).replace("·", " ").replace("*", " ")
    s = s.replace("mm Hg", "mmHg").replace("^", "")
    if not s:
        return {}, 1.0
    dims, factor, sign = {}, 1.0, 1
    for tok in re.findall(r"/|[A-Za-zµμÅ°]+-?\d*", s):
        if tok == "/":
            sign = -1
            continue
        m = re.fullmatch(r"([A-Za-zµμÅ°]+?)(-?\d+)?", tok)
        sym, exp = m.group(1), int(m.group(2) or 1)
        if sym not in _U:
            return None
        d, f = _U[sym]
        for k, v in d.items():
            dims[k] = dims.get(k, 0) + v * exp * sign
        factor *= f ** (exp * sign)
    return {k: v for k, v in dims.items() if v}, factor


def convert_unit(value, from_unit, to_unit):
    """value in from_unit expressed in to_unit, or None if they are not the same kind."""
    a, b = _unit(from_unit), _unit(to_unit)
    if a is None or b is None or a[0] != b[0]:
        return None
    return value * a[1] / b[1]


# ── Safe arithmetic for confirming slips ─────────────────────────────────────

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.UAdd: operator.pos}
_FUNCS = {"log": math.log10, "log10": math.log10, "ln": math.log, "sqrt": math.sqrt,
          "exp": math.exp, "pi": math.pi, "e": math.e}


def safe_eval(expr: str) -> float:
    """Evaluate a plain arithmetic expression ('0.693 / 0.0231', '2*96500*1.1/1000',
    'ln(4)/100', '10^-3') without executing code. Raises ValueError if it is anything else."""
    s = str(expr).replace("×", "*").replace("^", "**").replace("−", "-").replace("÷", "/")
    s = re.sub(r"(\d)\s*[eE]\s*([-+]?\d)", r"\1e\2", s)
    tree = ast.parse(s, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _FUNCS and not callable(_FUNCS[node.id]):
            return _FUNCS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and callable(_FUNCS.get(node.func.id)) \
                and len(node.args) == 1 and not node.keywords:
            return _FUNCS[node.func.id](ev(node.args[0]))
        raise ValueError(f"not plain arithmetic: {ast.dump(node)[:80]}")

    return ev(tree)
