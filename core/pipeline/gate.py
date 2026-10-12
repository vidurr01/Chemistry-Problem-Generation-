"""
Chemistry gate — the comparison half, in code.

The extractor (a model) only copies facts out of the stem into a form; this module
decides whether those facts are exactly the inputs the engine computed from:
every given stated with the same value, every constant stated, and the question
asking for the engine's final quantity. Anything else is a mismatch, and a form that
cannot be read at all is "unreadable".
"""

from __future__ import annotations

import math
import re

from core.answers import normalise_text
from core.engine.base import EngineError
from core.engine.chem import parse_equation
from core.llm import as_bool, as_number

NUM_TOL = 1e-3          # a stated number must equal the given to 0.1%


def _num_eq(a, b) -> bool:
    x, y = as_number(a), as_number(b)
    if x is None or y is None:
        return False
    return x == y or math.isclose(x, y, rel_tol=NUM_TOL, abs_tol=0.0)


def _eq_text(a, b) -> bool:
    sa, sb = str(a), str(b)
    if any(t in sa for t in ("->", "→", "⇌", "=")) and any(t in sb for t in ("->", "→", "⇌", "=")):
        try:
            ra, pa = parse_equation(sa)
            rb, pb = parse_equation(sb)
        except EngineError:
            pass
        else:
            key = lambda side: sorted((round(c, 6), re.sub(r"\s", "", f)) for c, f in side)
            return key(ra) == key(rb) and key(pa) == key(pb)
    return re.sub(r"\s", "", normalise_text(sa)) == re.sub(r"\s", "", normalise_text(sb))


def _same(kind: str, expected, got) -> bool:
    if got is None:
        return False
    if kind in ("dict",):
        if not isinstance(got, dict):
            return False
        e = {re.sub(r"\s", "", str(k)): v for k, v in expected.items()}
        g = {re.sub(r"\s", "", str(k)): v for k, v in got.items()}
        return e.keys() == g.keys() and all(
            _num_eq(e[k], g[k]) if as_number(e[k]) is not None else _eq_text(e[k], g[k]) for k in e)
    if kind == "list":
        if not isinstance(got, list) or len(got) != len(expected):
            return False
        for a, b in zip(expected, got):
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
                if not all(_num_eq(x, y) if as_number(x) is not None else _eq_text(x, y) for x, y in zip(a, b)):
                    return False
            elif not (_num_eq(a, b) if as_number(a) is not None else _eq_text(a, b)):
                return False
        return True
    if kind in ("text", "choice"):
        return _eq_text(expected, got)
    return _num_eq(expected, got)


def _squash(s: str) -> str:
    return " ".join(str(s).replace(" ", " ").split()).lower()


def compare_fact(stem: str, fq) -> dict:
    """A fact question passes when the stem contains the question sentence and every
    option exactly (whitespace and case aside). Checked in code; no extraction needed,
    because code wrote the options."""
    text = _squash(stem)
    mismatches = []
    if _squash(fq.lead) not in text:
        mismatches.append(f"the question sentence must appear exactly: {fq.lead}")
    for line in fq.option_lines:
        if _squash(line) not in text:
            mismatches.append(f"option missing or altered: {line}")
    if re.search(r"\b(answer|correct option)\s*(is|:)\s*\(?[A-D]\)?", stem, re.IGNORECASE):
        mismatches.append("the stem reveals the answer")
    return {"ok": not mismatches, "unreadable": False, "mismatches": mismatches}


def compare(spec: list, values: dict, extraction: dict, correct_option: int, constants: list) -> dict:
    """{"ok": bool, "unreadable": bool, "mismatches": [str, ...]}."""
    if not isinstance(extraction, dict) or not isinstance(extraction.get("values"), dict):
        return {"ok": False, "unreadable": True, "mismatches": ["extraction has no 'values' form"]}
    asked = as_number(extraction.get("asked"))
    stated = extraction.get("constants_stated")
    if asked is None or (constants and not isinstance(stated, list)):
        return {"ok": False, "unreadable": True, "mismatches": ["extraction is missing 'asked' or 'constants_stated'"]}

    mismatches = []
    got = extraction["values"]
    for s in spec:
        exp = values[s["key"]]
        val = got.get(s["key"])
        if val is None:
            mismatches.append(f"the question does not state {s['desc']} (should be {exp})")
        elif not _same(s["kind"], exp, val):
            mismatches.append(f"{s['desc']}: the question states {val!r}, it must be {exp!r}")
    if int(asked) != correct_option:
        mismatches.append("the question does not ask for the intended quantity")
    for i, c in enumerate(constants):
        if i >= len(stated or []) or not as_bool(stated[i]):
            mismatches.append(f"the question does not state: {c}")
    return {"ok": not mismatches, "unreadable": False, "mismatches": mismatches}
