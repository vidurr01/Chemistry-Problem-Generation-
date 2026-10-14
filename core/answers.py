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


# ── Answer spec: the exact form a solver must give its final answer in ────────
# Fixing the format at the source removes whole classes of reading problems: a numeric
# answer is a JSON number in the asked unit, a categorical answer is one of the listed
# options, a fact answer is option letters. A reply that breaks the spec gets one short
# repair request (stages._repair_format); a format problem is never graded as wrong.

_STRICT_NUMBER = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")


def options_from_format(fmt):
    """Allowed answers named by an answer instruction, or None:
    'Answer yes or no.' -> ['yes', 'no'];
    'Answer with exactly one of: forward, backward, no shift.' -> ['forward', 'backward', 'no shift']."""
    if not fmt:
        return None
    f = str(fmt).strip().rstrip(".")
    if re.fullmatch(r"(?i)answer yes or no", f):
        return ["yes", "no"]
    m = re.search(r"(?i)exactly one of:\s*(.+)$", f)
    if m:
        return [o.strip() for o in m.group(1).split(",") if o.strip()]
    return None


def target_units(spec: dict) -> list:
    """One target unit per value: a spec unit may be one string for all values or a list."""
    u, n = spec.get("unit", ""), spec.get("count", 1)
    if isinstance(u, (list, tuple)):
        return [str(x or "") for x in u] if len(u) == n else [str(u[0] or "")] * n
    return [str(u or "")] * n


def numeric_values(engine_answer):
    """The engine's answer as a list of numbers (one or several), or None if it is not numeric."""
    if isinstance(engine_answer, bool):
        return None
    if isinstance(engine_answer, (int, float)):
        return [float(engine_answer)]
    if isinstance(engine_answer, (list, tuple)) and engine_answer and \
            all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in engine_answer):
        return [float(x) for x in engine_answer]
    return None


def _subst_key(s) -> str:
    """Comparable key of a substance label: 'N₂', 'N2', 'n2', 'N2(g)' -> the same key."""
    f = _formula(s)
    return repr(f) if f is not None else normalise_text(s)


def label_keys(engine_labels, member_labels):
    """(engine keys, member keys) for pairing values by label, or None when they cannot pair.
    Formulas compare by element counts (N₂ = N2 = N2(g)); other labels case-insensitively
    (Ethanol = ethanol) unless that makes the question's own labels collide (T and t,
    K and k), in which case case matters on both sides."""
    if not engine_labels or not member_labels or len(engine_labels) != len(member_labels):
        return None
    ek = [_subst_key(x) for x in engine_labels]
    mk = [_subst_key(x) for x in member_labels]
    if len(set(ek)) != len(ek):
        exact = lambda x: repr(_formula(x)) if _formula(x) is not None else " ".join(str(x).split())
        ek, mk = [exact(x) for x in engine_labels], [exact(x) for x in member_labels]
    if len(set(ek)) != len(ek) or len(set(mk)) != len(mk) or set(ek) != set(mk):
        return None
    return ek, mk


def value_ok(e: float, m, tol: float = 0.01) -> bool:
    """One value against the engine's: relative tolerance; an engine value of 0 needs |x| <= 1e-9."""
    try:
        m = float(m)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(m):
        return False
    return abs(m) <= 1e-9 if e == 0.0 else answers_match(e, m, tol)


def align_values(engine_vals, member_vals, engine_subst=None, member_subst=None):
    """[(engine value, member value)] in the ENGINE's order, or None when they cannot be paired
    (different count; substances named on both sides but not the same set, or repeated).
    Paired by substance when both sides name them, by position otherwise."""
    if member_vals is None or len(member_vals) != len(engine_vals):
        return None
    if engine_subst and member_subst and len(engine_subst) == len(engine_vals) == len(member_subst):
        keys = label_keys(engine_subst, member_subst)
        if keys is None:
            return None
        ek, mk = keys
        by = dict(zip(mk, member_vals))
        return [(e, by[k]) for e, k in zip(engine_vals, ek)]
    return list(zip(engine_vals, member_vals))


def values_match(engine_vals, member_vals, tol: float = 0.01, engine_subst=None, member_subst=None) -> bool:
    """Do several values match? Same count required. When both sides name their substances
    the values are paired by substance (so 'H2, N2' in swapped order still pairs correctly)
    and the member must name the same substances; otherwise they are paired by position.
    Each pair is compared with the relative tolerance; an engine value of exactly 0 needs
    |x| <= 1e-9."""
    pairs = align_values(engine_vals, member_vals, engine_subst, member_subst)
    return pairs is not None and all(value_ok(e, m, tol) for e, m in pairs)


def answer_spec(engine_answer, kind: str, unit: str = "", fmt: str | None = None, substances=None) -> dict:
    """What the solver's answer must look like for this question."""
    if kind == "letters":
        return {"type": "letters"}
    vals = numeric_values(engine_answer)
    if vals is not None:
        spec = {"type": "number", "unit": unit or "", "count": len(vals)}
        if substances:
            spec["substances"] = list(substances)
        return spec
    opts = options_from_format(fmt)
    if opts:
        return {"type": "choice", "options": opts}
    return {"type": "text", "format": fmt or ""}


SIG_FIGS = 3          # every numeric question asks for 3 significant figures


def spec_instruction(spec: dict) -> str:
    """How the solver must write its answer: one line of bracketed fields. The solver gives
    only TYPE, CALC_VALUE, CALC_UNIT and SUBSTANCE; code adds TARGET_UNIT (from the question),
    FINAL_VALUE (CALC_VALUE converted, core.units) and RENDER (complete_answer)."""
    t = spec.get("type")
    head = ('"answer": one line in exactly this form, nothing else in it:\n'
            '[TYPE: <topic in one word>] [CALC_VALUE: <value>] [CALC_UNIT: <unit>] [SUBSTANCE: <formula, or null>]\n')
    if t == "number":
        return head + (
            "Rules: CALC_VALUE is the number you calculated, as a plain decimal or e-notation number "
            "(e.g. -45200, 0.0005776, 1.5e-15) — no units, words, fractions, '×10' or thousands "
            "separators. CALC_UNIT is the unit of exactly that number, in plain text (e.g. J, kJ/mol, "
            "J/(K mol), mol/L, atm, torr, K, s^-1, g/mL); you do not need to convert it — conversion "
            "is done for you. " + (
                "Give exactly one value. " if spec.get("count", 1) == 1 else
                f"Give exactly {spec['count']} values, comma-separated, with one unit per value (or one "
                "unit for all), and name each value's substance or quantity in SUBSTANCE in the same order"
                + (f" ({', '.join(spec['substances'])})" if spec.get("substances") else "") + ". ")
            + "If the quantity has no unit, write none.\n"
            "Example: [TYPE: thermochemistry] [CALC_VALUE: -45200] [CALC_UNIT: J] [SUBSTANCE: null]"
            + ("" if spec.get("count", 1) == 1 else
               "\nExample with two values: [TYPE: equilibrium] [CALC_VALUE: 0.75, 570] [CALC_UNIT: atm, torr] "
               "[SUBSTANCE: N2, H2]"))
    if t == "choice":
        return head + ("Rules: CALC_VALUE is exactly one of: " + ", ".join(spec["options"])
                       + " (copied as written); CALC_UNIT: none.")
    if t == "letters":
        return head + "Rules: CALC_VALUE is the letter(s) of the correct option(s) only, e.g. B or AC; CALC_UNIT: none."
    fmt = spec.get("format") or "the final formula, name or label only"
    return head + f"Rules: CALC_VALUE is {fmt} (just the answer, no explanation, no commas); CALC_UNIT: none."


_LABEL = re.compile(r"\[\s*(TYPE|CALC[ _]?VALUES?|CALC[ _]?UNITS?|TARGET[ _]?UNITS?|FINAL[ _]?VALUES?|"
                    r"SUBSTANCES?|RENDER)\s*:", re.I)
_KEY = {"TYPE": "TYPE", "CALCVALUE": "CALC_VALUE", "CALCUNIT": "CALC_UNIT", "TARGETUNIT": "TARGET_UNIT",
        "FINALVALUE": "FINAL_VALUE", "SUBSTANCE": "SUBSTANCE", "RENDER": "RENDER"}
_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-", "＋": "+"})


def _label_key(label: str) -> str | None:
    k = re.sub(r"[\s_]", "", label.upper())
    k = k[:-1] if k.endswith("S") and k[:-1] in _KEY else k
    return _KEY.get(k)


def _line_fields(text) -> dict:
    """{FIELD: raw value} from an answer line. Values may contain brackets
    ([SUBSTANCE: K4[Fe(CN)6]]): a value runs to the next field label, and only its own
    closing bracket is dropped. A JSON object with the same keys is read too."""
    if isinstance(text, dict):
        out = {}
        for k, v in text.items():
            key = _label_key(str(k))
            if key:
                out[key] = ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else ("" if v is None else str(v))
        return out
    if isinstance(text, (list, tuple)):
        text = " ".join(map(str, text))
    s = str(text or "").replace("`", "")
    marks = list(_LABEL.finditer(s))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(s)
        val = s[m.end():end].strip()
        cut = val.rfind("]")
        if cut >= 0:
            val = val[:cut]                       # this field's closing bracket (and any text after it)
        key = _label_key(m.group(1))
        if key and key not in out:
            out[key] = val.strip()
    return out


def parse_answer_line(text) -> dict | None:
    """The solver's fields from '[TYPE: x] [CALC_VALUE: a, b] [CALC_UNIT: u, v] [SUBSTANCE: s, t]'
    (or a JSON object with those keys), or None if there is no CALC_VALUE. Numbers and units
    are split on commas; calc_value_raw keeps the unsplit value for text answers. Anything the
    solver put in TARGET_UNIT / FINAL_VALUE / RENDER is ignored (code computes those)."""
    found = _line_fields(text)
    if "CALC_VALUE" not in found or not found["CALC_VALUE"].strip():
        return None
    split = lambda v: [x.strip() for x in str(v).split(",") if x.strip()]
    raw = found["CALC_VALUE"].strip()
    subst = [x for x in split(found.get("SUBSTANCE", "")) if x.lower() not in ("null", "none", "-", "n/a")]
    return {"type": (found.get("TYPE") or "").strip() or None,
            "calc_value": split(raw.translate(_MINUS)), "calc_value_raw": raw,
            "calc_unit": split(found.get("CALC_UNIT", "")), "substance": subst}


def _fmt_number(x: float) -> str:
    return f"{x:.{SIG_FIGS + 1}g}"


def complete_answer(parsed: dict | None, spec: dict) -> dict:
    """Fill TARGET_UNIT, FINAL_VALUE and RENDER from the solver's fields. Returns a dict with
    ok=False and a reason when the line cannot be used (that triggers one restate request)."""
    from core import units
    if not parsed or not parsed["calc_value"]:
        return {"ok": False, "reason": "no [CALC_VALUE: ...] field"}
    t = spec.get("type")
    out = {**parsed, "target_unit": spec.get("unit", "") if t == "number" else ""}
    tus = target_units(spec) if t == "number" else []
    if t != "number":
        v = "".join(parsed["calc_value"]) if t == "letters" else parsed.get("calc_value_raw", parsed["calc_value"][0])
        if not format_ok(spec, v):
            return {"ok": False, "reason": f"CALC_VALUE {v!r} is not one of the allowed answers"}
        return {**out, "ok": True, "final_value": [v], "render": str(v)}
    values = []
    for v in parsed["calc_value"]:
        if not _STRICT_NUMBER.match(v):
            return {"ok": False, "reason": f"CALC_VALUE {v!r} is not a plain number"}
        values.append(float(v))
    if len(values) != spec.get("count", 1):
        return {"ok": False, "reason": f"expected {spec.get('count', 1)} value(s), got {len(values)}"}
    cu = parsed["calc_unit"] or ["none"]
    if len(cu) == 1 and len(values) > 1:
        cu = cu * len(values)
    if len(cu) != len(values):
        return {"ok": False, "reason": "CALC_UNIT does not give one unit per value"}
    # Put the values in the QUESTION's order before converting, so each value is converted to
    # the unit of the quantity it belongs to (a solver may list ΔG, ΔH, ΔS for ΔH, ΔS, ΔG).
    # Labels that do not name the asked substances are left in place; matching then fails them.
    subst = list(parsed.get("substance") or [])
    want = spec.get("substances")
    if want and len(subst) == len(values) == len(want):
        keys = label_keys(want, subst)
        if keys is not None:
            ek, mk = keys
            order = [mk.index(k) for k in ek]
            values = [values[i] for i in order]
            cu = [cu[i] for i in order]
            subst = [subst[i] for i in order]
    out["substance"] = subst
    finals = []
    for v, u, tu in zip(values, cu, tus):
        if units.parse(u) is None:
            return {"ok": False, "reason": f"unit {u!r} cannot be read"}
        f = units.convert(v, u, tu)
        if f is None:
            return {"ok": False, "reason": f"{u!r} cannot be converted to {tu!r}"}
        finals.append(f)
    render = ", ".join(f"{_fmt_number(f)}{(' ' + tu) if tu else ''}" for f, tu in zip(finals, tus))
    return {**out, "ok": True, "calc_value": values, "calc_unit": cu, "final_value": finals, "render": render,
            "target_unit": tus if len(tus) > 1 else tus[0]}


def format_ok(spec: dict, final_answer) -> bool:
    """Is a single final answer (a value, an option, letters) of the right kind?"""
    if final_answer is None or (isinstance(final_answer, str) and not final_answer.strip()):
        return False
    t = spec.get("type")
    if t == "number":
        if isinstance(final_answer, bool):
            return False
        if isinstance(final_answer, (int, float)):
            return math.isfinite(final_answer)
        return bool(_STRICT_NUMBER.match(str(final_answer).strip()))
    if t == "choice":
        a = normalise_text(final_answer).strip(" .'\"")
        return a in {normalise_text(o) for o in spec["options"]}
    if t == "letters":
        from core.engine.facts import letters_of
        return bool(letters_of(final_answer))
    return True


# ── Units ────────────────────────────────────────────────────────────────────
# Conversion lives in core/units.py (pint). This wrapper is kept for older callers.

def convert_unit(value, from_unit, to_unit):
    """value in from_unit expressed in to_unit, or None if they are not the same kind."""
    from core import units
    return units.convert(value, from_unit, to_unit)


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
