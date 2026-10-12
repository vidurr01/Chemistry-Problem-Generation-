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


def matches(engine_answer, member_answer, kind: str = "real") -> bool:
    """Does a council member's final answer match the engine's? Numbers within 1%;
    formulas/labels after normalisation; anything unreadable does not match."""
    if member_answer is None:
        return False
    if kind == "letters":
        from core.engine.facts import letters_of
        return bool(engine_answer) and letters_of(member_answer) == "".join(sorted(engine_answer))
    if isinstance(engine_answer, (int, float)) and not isinstance(engine_answer, bool):
        value = parse_numeric_answer(member_answer)
        return value is not None and answers_match(float(engine_answer), value)
    if isinstance(engine_answer, str):
        return normalise_text(engine_answer) == normalise_text(member_answer)
    return answers_match(engine_answer, member_answer)


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
