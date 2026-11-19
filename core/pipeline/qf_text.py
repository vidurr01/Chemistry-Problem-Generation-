"""Question first, helpers: numbers in question text.

How a question prints its numbers (fill_template, _fmt_number), how numbers are read back out of a text
(stated_numbers), and the novelty check against past questions (too_close_to_past)."""

from __future__ import annotations

import math
import re

from core import answers


NGRAM = 4               # novelty: word 4-grams shared with one past question ...


MAX_SHARED_NGRAMS = 0.30    # ... at most this share of the new question's 4-grams


MAX_SHARED_VALUES = 3       # novelty: at most 2 distinctive values shared with one past question


_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


_NUM = re.compile(r"(?<![A-Za-z0-9_.])(-?\d+(?:\.\d+)?)"
                  r"(?:\s*(?:×|x|\*|·)\s*10\s*\^\s*\(?\s*([-+]?\d+)\s*\)?|[eE]([-+]?\d+))?")


def _num_text(v: float) -> str:
    return repr(float(v))


def _powers(t: str) -> str:
    """Powers written in the text, each turned into the ONE number it is: '10⁻³' -> 0.001, '2⁶' -> 64,
    'e¹²' -> 162754.79, '(1/2)³' -> 0.125, also with ^. A mantissa's power of ten ('3 × 10⁻³') is
    left for _NUM. Superscripts after a letter (Fe³⁺, cm³) are not powers of a number."""
    t = re.sub(r"(?:(?<=[0-9)])|(?<![A-Za-z]e)(?<=e))([⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)",
               lambda m: "^" + m.group(1).translate(_SUP), t)
    exp = r"\s*\^\s*\(?\s*(-?\d+(?:\.\d+)?)\s*\)?"

    def frac(m):
        try:
            return _num_text((float(m.group(1)) / float(m.group(2))) ** float(m.group(3)))
        except (ZeroDivisionError, OverflowError, ValueError):
            return m.group(0)
    t = re.sub(r"\(\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*\)" + exp, frac, t)

    def epow(m):
        try:
            return _num_text(math.e ** float(m.group(1)))
        except OverflowError:
            return m.group(0)
    t = re.sub(r"(?<![A-Za-z])e" + exp, epow, t)
    t = re.sub(r"(?<![A-Za-z])exp\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)", epow, t)

    def npow(m):
        before = t_now[:m.start()].rstrip()
        if m.group(1) == "10" and before[-1:] in ("×", "x", "*", "·"):
            return m.group(0)                    # '3 × 10^-3': the mantissa form, read by _NUM
        try:
            return _num_text(float(m.group(1)) ** float(m.group(2)))
        except (OverflowError, ValueError, ZeroDivisionError):
            return m.group(0)
    t_now = t
    return re.sub(r"(?<![\d.A-Za-z_])(\d+(?:\.\d+)?)" + exp, npow, t)


def stated_numbers(text) -> list:
    """The numbers a text states: '4.2 × 10⁻⁵' -> 4.2e-5, '−3.1' -> -3.1, '10⁻³' -> 0.001,
    '2⁶' -> 64, 'e¹²' -> 162754.79. Digits right after a letter (H2, CO2) are formula subscripts,
    not numbers."""
    t = str(text or "").replace("−", "-").replace("–", "-")
    t = _powers(t)
    out = []
    for m in _NUM.finditer(t):
        try:
            e = m.group(2) or m.group(3)
            out.append(float(f"{m.group(1)}e{int(e)}") if e else float(m.group(1)))
        except (ValueError, OverflowError):
            continue
    return out


def _scaled_equal(a: float, b: float, rel: float = 1e-6) -> bool:
    """a and b are the same number, up to a power of ten (a unit change: 25 % = 0.25)."""
    if a == b:
        return True
    if a == 0 or b == 0:
        return False
    k = math.log10(abs(b / a))
    return abs(k - round(k)) < 1e-9 + rel and (a > 0) == (b > 0)


def _trivial(v: float) -> bool:
    """Small whole numbers (1, 2, 3 ...) appear in every question; they say nothing."""
    return float(v).is_integer() and abs(v) <= 10


def _distinctive(v: float) -> bool:
    """A value with at least 3 significant digits (36.5, 0.0591, 1.25 × 10⁻³): sharing several
    of these with a past question means its data were copied; 300 K or 12.0 L mean nothing."""
    if v == 0 or not math.isfinite(v):
        return False
    digits = f"{abs(v):.6e}".split("e")[0].replace(".", "").rstrip("0")
    return len(digits) >= 3


def _words(text) -> list:
    return re.findall(r"[a-z0-9]+", answers.normalise_text(text))


def _profile(text) -> dict:
    w = _words(text)
    return {"grams": {tuple(w[i:i + NGRAM]) for i in range(len(w) - NGRAM + 1)},
            "values": [v for v in stated_numbers(text) if _distinctive(v)]}


def too_close_to_past(stem: str, values: list, examples: list) -> str | None:
    """Why the question is a variant of one of the example questions the writer was shown, or
    None: a large share of its wording, or MAX_SHARED_VALUES of its distinctive values, appear in
    that example."""
    mine = _profile(stem)
    own = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and _distinctive(v)]
    for ex in examples:
        q = _profile(ex["text"])
        if mine["grams"] and len(mine["grams"] & q["grams"]) / len(mine["grams"]) > MAX_SHARED_NGRAMS:
            return f"its wording follows example {ex['id']} too closely"
        shared = sum(1 for v in own if any(_scaled_equal(v, p) for p in q["values"]))
        if shared >= MAX_SHARED_VALUES:
            return f"it reuses {shared} values of example {ex['id']}"
    return None





_SCI = re.compile(r"^\s*([-+−]?\d+(?:\.\d*)?|[-+−]?\.\d+)\s*(?:[×xX*]\s*10\s*\^?\s*\(?\s*([-+]?\d+)\s*\)?)?")


def _free_number(v):
    """A free value the way a model writes it: '5.0 × 10⁻³', '1.2 x 10^-5', '300 K', '6.022 × 10²³'.
    None if no number leads the text. (core.llm.as_number dropped these, so the placeholder had no value.)"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    m = _SCI.match(v.translate(_SUP).replace("−", "-"))
    if not m:
        return None
    x = float(m.group(1).replace("−", "-"))
    return x * 10 ** int(m.group(2)) if m.group(2) else x


PLACEHOLDER = re.compile(r"\[\[(\w+)\]\]")


def _fmt_number(v: float, sig: int = 3) -> str:
    """As an exam prints it, keeping trailing zeros: 2 -> '2.00', 8.4941 -> '8.49', 96500 -> '96500',
    4.2e-5 -> '4.20 × 10^-5'. Never Python's '9.65e+04'."""
    import math
    v = float(v)
    if v == 0:
        return "0"
    e = math.floor(math.log10(abs(v)))
    if abs(v) < 1e-3 or abs(v) >= 1e6:
        mant = round(v / 10 ** e, sig - 1)
        if abs(mant) >= 10:
            mant, e = mant / 10, e + 1
        return f"{mant:.{sig - 1}f} × 10^{e}"           # powers as a^b: one plain form, read back by stated_numbers
    dec = max(0, sig - 1 - e)
    return f"{round(v, dec):.{dec}f}"


def _sig_digits(v: float) -> int:
    """Significant digits the writer gave: 96500 -> 3, 101325 -> 6, 8.314 -> 4, 2 -> 1."""
    m = f"{abs(float(v)):.10g}".split("e")[0]
    digits = m.replace(".", "").lstrip("0")
    return len(digits.rstrip("0") if "." not in m else digits) or 1


def fill_template(template: str, free: dict, computed: dict, asked: str) -> str:
    """The question with every placeholder replaced: free values as the writer chose them,
    computed ones rounded to 4 significant figures. Raises ValueError for a missing value or a
    placeholder of the asked quantity."""
    def sub(m):
        name = m.group(1)
        if name == asked:
            raise ValueError(f"the question shows the asked quantity [[{name}]]; remove it")
        if name in computed:
            # 4 figures: at 3, an EMF rounded to the millivolt moved a K or Ksp by ~2 %, past the check
            return _fmt_number(computed[name], 4)
        if name in free:
            if isinstance(free[name], int) and not isinstance(free[name], bool):
                return str(free[name])           # a count the writer gave as a whole number
            v = float(free[name])
            return _fmt_number(v, max(3, min(_sig_digits(v), 10)))   # 8.314 keeps 4 figures, 2 becomes 2.00
        raise ValueError(f"no value for [[{name}]]: put it in free or derived")
    return PLACEHOLDER.sub(sub, template)
