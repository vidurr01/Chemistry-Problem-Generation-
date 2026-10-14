"""
Checks on a written (readable) solution, in code, before the verifier reads it.

1. Arithmetic: every written calculation "<expression> = <number>" must be true. The
   expression may carry units ("0.025 mol × 46 g mol⁻¹ = 1.725 g" is false: 1.15). A line is
   only checked when its calculation can be read with certainty; anything else (equations,
   formulas, variables, functions written without brackets) is left to the verifier, so a
   correct solution is never failed by this check.
2. Trace: every intermediate result of the engine's computation and the final answer must
   appear in the solution, and the last line must give the final answer.
"""

from __future__ import annotations

import math
import re

from core import answers

_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_FUNC_NAMES = {"log", "log10", "ln", "sqrt", "exp"}
_NUM = r"(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_TOKEN = re.compile(
    rf"(?P<num>{_NUM})(?P<sup>[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?"
    r"|(?P<word>[A-Za-zα-ωΑ-ΩµμΩ°%_'][A-Za-z0-9α-ωΑ-ΩµμΩ°%_'⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺₀-₉]*)"
    r"|(?P<pow>[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)"
    r"|(?P<op>\*\*|[-+*/^×·÷−–])"
    r"|(?P<open>\()|(?P<close>\))"
    r"|(?P<space>\s+)"
    r"|(?P<other>.)")
# A formula-like word (a species, not a unit): two capitals (H2O, NaOH, KMnO4) or a capital
# followed by a digit (H2, O2, C6H12O6) or a subscript.
_FORMULA_WORD = re.compile(r"[A-Z][a-z]?[0-9₀-₉]|[A-Z][a-z]?\(?[A-Z]")
REL_TOL = 0.01               # a written result may be off by 1 % (rounded intermediates)


def _tokens(text: str):
    text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)          # 96,500 -> 96500
    text = re.sub(r"(?<=\d)\s*x\s*(?=\d)", " × ", text)               # 0.25 x 100
    out = []
    for m in _TOKEN.finditer(text):
        kind = m.lastgroup if m.lastgroup != "sup" else "num"
        if m.group("num") is not None:
            out.append(("num", m.group("num"), m.group("sup")))
        elif kind == "space":
            continue
        else:
            out.append((kind, m.group(kind), None))
    return _scientific(out)


def _scientific(toks):
    """'5.226 × 10⁻²' and '5.226 × 10^-2' are one number, as a reader takes them
    ('963.2 / 5.226 × 10⁻²' divides by 0.05226)."""
    def power_of_ten(j):
        """(exponent, index after it) for '10⁻²' / '10^-2' / '10^(-2)' starting at j, or None."""
        if j >= len(toks) or toks[j][0] != "num" or toks[j][1] != "10":
            return None
        if toks[j][2]:
            return int(toks[j][2].translate(_SUP)), j + 1
        k = j + 1
        if k >= len(toks) or toks[k][1] not in ("^", "**"):
            return None
        k, sign, paren = k + 1, 1, False
        if k < len(toks) and toks[k][0] == "open":
            k, paren = k + 1, True
        if k < len(toks) and toks[k][1] in ("-", "−", "–", "+"):
            sign, k = (1 if toks[k][1] == "+" else -1), k + 1
        if k < len(toks) and toks[k][0] == "num" and re.fullmatch(r"\d+", toks[k][1]) and \
                (not paren or k + 1 < len(toks) and toks[k + 1][0] == "close"):
            return sign * int(toks[k][1]), k + 1 + paren
        return None

    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t[0] == "num" and not t[2] and i + 1 < len(toks) and toks[i + 1][1] in ("×", "*", "·"):
            p = power_of_ten(i + 2)                                # 5.226 × 10⁻²
            if p:
                out.append(("num", f"({t[1]}e{p[0]})", None))
                i = p[1]
                continue
        p = power_of_ten(i) if not (out and out[-1][1] in ("×", "*", "·")) else None
        if p and toks[i][2] is None:                               # a bare 10^-3
            out.append(("num", f"(1e{p[0]})", None))
            i = p[1]
            continue
        out.append(t)
        i += 1
    return out


def _is_unit_word(w: str) -> bool:
    return not _FORMULA_WORD.search(w) and w.lower() not in _FUNC_NAMES


def _expression(tokens):
    """Python arithmetic for a token run, or None when the run is not plain arithmetic with
    units. Unit words may follow only a number, a closing bracket or another unit word."""
    parts, prev, depth = [], None, 0          # prev: num | close | unit | op | open | func | None
    i = 0
    has_op = False
    units = []
    while i < len(tokens):
        kind, val, sup = tokens[i]
        if kind == "num":
            if prev in ("num", "close", "unit"):
                return None                   # two numbers side by side: not one calculation
            parts.append(val + (f"**({sup.translate(_SUP)})" if sup else ""))
            prev = "num"
        elif kind == "word":
            if val.lower() in _FUNC_NAMES:
                if i + 1 < len(tokens) and tokens[i + 1][0] == "open" and prev in (None, "op", "open"):
                    parts.append(val.lower())
                    prev = "func"
                    has_op = True             # log(...) is a calculation
                else:
                    return None               # 'log 2' without brackets: cannot be read safely
            elif prev in ("num", "close", "unit") and _is_unit_word(val):
                prev = "unit"                 # a unit: dropped
                units.append(val)
            else:
                return None                   # prose, a variable or a species inside the calculation
        elif kind == "op":
            op = {"×": "*", "·": "*", "÷": "/", "−": "-", "–": "-", "^": "**"}.get(val, val)
            if prev == "unit" and op == "**":
                # 'day^-1', 'M^-1 s^-1': the unit's exponent
                k = i + 1
                if k < len(tokens) and tokens[k][1] in ("-", "−", "–", "+"):
                    k += 1
                if k < len(tokens) and tokens[k][0] == "num" and re.fullmatch(r"\d+", tokens[k][1]):
                    i = k + 1
                    continue
                return None
            if prev == "unit" and op == "/":
                # 'g / mol' or 'J/(mol K)': part of the unit, unless a number follows
                j = i + 1
                if j < len(tokens) and tokens[j][0] == "word" and _is_unit_word(tokens[j][1]):
                    units.append(tokens[j][1])
                    i += 2
                    prev = "unit"
                    continue
                if j < len(tokens) and tokens[j][0] == "open":
                    k = j + 1
                    while k < len(tokens) and (tokens[k][0] == "word" and _is_unit_word(tokens[k][1])
                                               or tokens[k][1] in ("·", "*")):
                        k += 1
                    if k > j + 1 and k < len(tokens) and tokens[k][0] == "close":
                        i = k + 1
                        prev = "unit"
                        continue
            if prev == "unit" and op in ("*",) and i + 1 < len(tokens) and tokens[i + 1][0] == "word":
                i += 1                         # 'mol·K'
                continue
            if op in ("+", "-") and prev in (None, "op", "open", "func"):
                parts.append(op)              # unary sign
            elif prev in ("num", "close", "unit"):
                parts.append(op)
                has_op = True
            else:
                return None
            prev = "op"
        elif kind == "open":
            if prev in ("num", "close", "unit"):
                return None                   # '2(0.5)' or 'mol (FeSO4)': not read
            parts.append("(")
            depth += 1
            prev = "open"
        elif kind == "close":
            if depth == 0 or prev not in ("num", "close", "unit"):
                return None
            parts.append(")")
            depth -= 1
            prev = "close"
        elif kind == "pow":                   # '(0.4)²'
            if prev != "close":
                return None
            parts.append(f"**({val.translate(_SUP)})")
            has_op = True
        else:
            return None
        i += 1
    if depth or prev not in ("num", "close", "unit"):
        return None
    return "".join(parts), has_op, units


def _value(expr: str):
    try:
        v = answers.safe_eval(expr)
    except (ValueError, ZeroDivisionError, OverflowError, SyntaxError, TypeError, RecursionError):
        return None
    return v if isinstance(v, float) and math.isfinite(v) else None


def _left_value(tokens):
    """The calculation that ends a segment ('… the mass is 0.025 mol × 46 g mol⁻¹'): the
    longest tail that is plain arithmetic with an operator, preceded by prose or nothing
    (never by a number or operator, which would mean the calculation is cut)."""
    for start in range(len(tokens)):
        kind = tokens[start][0]
        if kind not in ("num", "open") and not (kind == "op" and tokens[start][1] in "-−–") \
                and not (kind == "word" and tokens[start][1].lower() in _FUNC_NAMES):
            continue
        if start > 0 and tokens[start - 1][0] in ("num", "op", "open", "close"):
            continue
        if start > 0 and tokens[start - 1][0] == "word" and tokens[start - 1][1].lower() in _FUNC_NAMES:
            continue
        r = _expression(tokens[start:])
        if r is None:
            continue
        expr, has_op, units = r
        if not has_op and start > 0:
            return None               # 'Mass of 2 moles = …': a plain number only as a whole chain link
        v = _value(expr)
        return (expr, v, has_op, units) if v is not None else None
    return None


def _right_value(tokens):
    """The number (or calculation) that starts a segment ('1.725 g, which …'): the longest
    head that is plain arithmetic, and the number of significant decimals it was written with."""
    if not tokens or tokens[0][0] not in ("num", "open", "op") or \
            tokens[0][0] == "op" and tokens[0][1] not in "-−–":
        return None
    for end in range(len(tokens), 0, -1):
        r = _expression(tokens[:end])
        if r is None:
            continue
        rest = tokens[end:]
        # the head must end the calculation: no operator, number or bracket right after it,
        # and none after a following word ('0.5 × 2 mol H2 + 1' cannot be read)
        if rest and (rest[0][0] in ("op", "num", "open") or
                     rest[0][0] == "other" and rest[0][1] not in ".,;:!?'\"`)" or
                     rest[0][0] == "word" and len(rest) > 1 and rest[1][0] in ("op", "num", "open")):
            return None
        v = _value(r[0])
        return (r[0], v, r[1], r[2]) if v is not None else None
    return None


def _close(computed: float, stated: float, stated_text: str) -> bool:
    if computed == stated:
        return True
    # half a unit in the last written digit of the stated number
    m = re.match(r"^-?(\d*)\.?(\d*)(?:[eE]([-+]?\d+))?$", stated_text.strip("()").lstrip("+-"))
    half = 0.0
    if m and "**" not in stated_text and "*" not in stated_text and "/" not in stated_text:
        decimals = len(m.group(2) or "")
        half = 0.5 * 10 ** (-decimals + int(m.group(3) or 0))
    return abs(computed - stated) <= max(REL_TOL * abs(stated), half) * (1 + 1e-9)


# Factors by which a written result may differ from the bare arithmetic when the line changes
# units without saying so (J -> kJ, days -> s, cal -> J, atm -> Pa or torr, fraction -> %).
_UNIT_FACTORS = [f for b in (1e3, 1e6, 1e9, 60, 3600, 86400, 4.184, 101325, 760, 100) for f in (b, 1 / b)]


def _terms(expr: str) -> list:
    """Top-level additive terms of an expression ('-2*96.5+85*(450-298)' -> two terms)."""
    terms, depth, cur = [], 0, ""
    for i, ch in enumerate(expr):
        prev = expr[:i].rstrip()[-1:] if expr[:i].strip() else ""
        if ch in "+-" and depth == 0 and prev and (prev.isdigit() or prev == ")" or prev == ".") \
                and not re.search(r"\d[eE]$", expr[:i]):
            terms.append(cur)
            cur = ch
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    terms.append(cur)
    return [t for t in terms if t.strip()]


def _unit_explained(calc, computed: float, stated: float, stated_text: str) -> bool:
    """Could the difference be an unstated unit change? Only asked when the line has units."""
    if any(_close(computed * f, stated, stated_text) for f in _UNIT_FACTORS):
        return True
    terms = _terms(calc[0])
    if not 2 <= len(terms) <= 5:
        return False
    vals = [_value(t) for t in terms]
    if None in vals:
        return False
    import itertools
    for combo in itertools.product((1.0, 1e3, 1e-3), repeat=len(vals)):
        if any(c != 1.0 for c in combo) and _close(sum(v * c for v, c in zip(vals, combo)), stated, stated_text):
            return True
    return False


def _real_units(words) -> bool:
    from core import units as _units
    return all(_units.parse(w) is not None for w in words)


def arithmetic_errors(text: str) -> list:
    """[{"line": n, "text": line, "computed": x, "stated": y}] for every written calculation
    that is false. Lines with a reaction arrow are skipped."""
    errors = []
    for n, line in enumerate(str(text).splitlines(), 1):
        line = re.sub(r"^\s*(?:Step\s*)?\d+[.):]\s+", "", line)     # list numbering
        if re.search(r"→|->|⇌|⟶|<=>", line) or "\\" in line or "$" in line:
            continue                          # reactions; LaTeX cannot be read safely
        segs = re.split(r"=|≈|≅", line)
        if len(segs) < 2:
            continue
        toks = [_tokens(s) for s in segs]
        for idx, ((a, b), (sa, sb)) in enumerate(zip(zip(toks, toks[1:]), zip(segs, segs[1:]))):
            left = _left_value(a)
            if left and not left[2] and idx == 0:
                left = None                   # '0.1 mol = 0.1 × N_A': a quantity, not a chain link
            right = _right_value(b)
            if not left or not right or not (left[2] or right[2]):
                continue                      # '1 mol = 22.4 L': no calculation to check
            if left[2]:
                calc, plain = left, right
            else:
                calc, plain = right, left
            if plain is left and plain[0] == "1":
                continue                      # '1 L = 10^-3 × 1000 mL': a unit statement
            if not plain[2] and plain is left and not _real_units(plain[3]):
                continue                      # '2. This gives N = …': prose, not a quantity
            computed, stated = calc[1], plain[1]
            stated_text = plain[0] if not plain[2] else "*"
            if not _close(computed, stated, stated_text) and not (
                    (calc[3] or plain[3]) and _unit_explained(calc, computed, stated, stated_text)):
                claim = (sa[-90:].split(". ")[-1] + "=" + sb[:40].split(", ")[0]).strip()
                errors.append({"line": n, "text": line.strip(), "claim": claim, "computed": computed,
                               "stated": stated, "expression": calc[0]})
    return errors


def numbers_in(text: str) -> list:
    """Every number written in the text, reading '1.99 × 10²²', '1.99 x 10^22', '1.99e22'."""
    t = str(text).replace("−", "-").replace("–", "-")
    vals = []
    sci = re.compile(rf"(-?{_NUM})\s*[×x*·]\s*10\s*(?:\^|\*\*)?\s*\(?\s*([-+⁻⁺]?\s*[0-9⁰¹²³⁴⁵⁶⁷⁸⁹]+)\s*\)?")
    for m in sci.finditer(t):
        try:
            vals.append(float(m.group(1)) * 10 ** int(m.group(2).translate(_SUP).replace(" ", "")))
        except (ValueError, OverflowError):
            pass
    t2 = sci.sub(" ", t)
    t2 = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", t2)
    for m in re.finditer(rf"(?<![A-Za-z0-9₀-₉])-?{_NUM}", t2):
        try:
            vals.append(float(m.group(0)))
        except ValueError:
            pass
    return vals


def _appears(v: float, nums: list, rel: float = 0.006) -> bool:
    return any(x == v or (v != 0 and abs(x - v) <= rel * abs(v)) or (v == 0 and abs(x) < 1e-12) for x in nums)


def _scalars(x):
    if isinstance(x, bool):
        return []
    if isinstance(x, (int, float)):
        return [float(x)] if math.isfinite(x) else []
    if isinstance(x, (list, tuple)):
        return [v for e in x for v in _scalars(e)]
    if isinstance(x, dict):
        return [v for e in x.values() for v in _scalars(e)]
    return []


def trace_problems(text: str, trace: list, answer, kind: str = "real") -> list:
    """Problems with a solution against the engine's computation: a step's result or the final
    answer missing, or a last line that does not give the final answer."""
    probs = []
    nums = numbers_in(text)
    for i, t in enumerate(trace or [], 1):
        for k, v in (t.get("outputs") or {}).items():
            for x in _scalars(v):
                if not _appears(x, nums):
                    probs.append(f"Step {i}'s result ({k} = {x:.5g}) does not appear in the solution.")
    finals = _scalars(answer) if not isinstance(answer, str) else []
    lines = [ln for ln in str(text).splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    for x in finals:
        if not _appears(x, nums):
            probs.append(f"The final answer {x:.4g} does not appear in the solution.")
        elif not _appears(x, numbers_in(last)):
            probs.append(f"The last line must give the final answer ({x:.4g}).")
    if isinstance(answer, str) and answers.normalise_text(answer) not in answers.normalise_text(last)             and not answers.matches(answer, last.split(":", 1)[-1].strip(), kind):
        probs.append(f"The last line must give the final answer ({answer}).")
    return probs


def code_problems(text: str, trace: list, answer, kind: str = "real") -> list:
    """Every problem code can find, as sentences for the solution writer."""
    if not str(text or "").strip():
        return ["The solution is empty."]
    probs = [f"Line {e['line']}: '{e['claim']}' is false arithmetic: {e['expression']} = {e['computed']:.5g}, "
             f"not {e['stated']:.5g}." for e in arithmetic_errors(text)]
    return probs + trace_problems(text, trace, answer, kind)
