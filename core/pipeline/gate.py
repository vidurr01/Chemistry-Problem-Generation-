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


_ARROWS = ("->", "→", "⇌", "⟶", "<=>", "=")


def _species_key(text):
    """Key of one species written as a formula ('Fe', 'Fe²⁺', 'Cr2O7^2-', 'Ca₃(PO₄)₂',
    'H2O(l)'), also when the stem's name comes with it ('iron (Fe)', 'Fe (iron)'). Names
    alone are not read: the generator writes the formula next to every named species.
    None when it is not one readable formula."""
    from core.answers import _formula
    t = str(text).strip().rstrip(".")
    m = re.match(r"^(.*\S)\s+\(([^()]*(?:\([^()]*\)[^()]*)*)\)$", t)   # 'name (formula)' or 'formula (name)'
    if m:
        inner, outer = m.group(2).strip(), m.group(1).strip()
        if re.search(r"[A-Z]", inner) and _formula(inner) is not None:
            t = inner
        elif re.search(r"[A-Z]", outer) and _formula(outer) is not None:
            t = outer
    if not re.search(r"[A-Z]", t) or _formula(t) is None:
        return None
    return _notation(t)


def _notation(t: str) -> str:
    """The formula as written, minus notation: subscripts, superscripts, '^', state labels,
    spaces, '·' for '.', and the charge written sign last ('SO₄²⁻' = 'SO4^2-' = 'SO42-').
    Isomers stay different (C2H5OH is not CH3OCH3)."""
    from core.answers import _SUBS, _SUPERSCRIPTS
    s = str(t).translate(_SUBS).translate(_SUPERSCRIPTS)
    s = re.sub(r"\((s|l|g|aq)\)", "", s).replace("·", ".").replace("^", "")
    s = re.sub(r"[\s{}]", "", s).rstrip(".")
    return re.sub(r"([+-])(\d+)$", r"\2\1", s)


def _equation_key(text):
    """((reactant keys), (product keys)) of an equation, coefficients included; None if any
    species cannot be read."""
    try:
        r, p = parse_equation(str(text))
    except EngineError:
        return None
    side = []
    for part in (r, p):
        keys = []
        for c, f in part:
            k = _species_key(f)
            if k is None:
                return None
            keys.append((round(float(c), 6), k))
        side.append(tuple(sorted(keys, key=repr)))
    return tuple(side)


def _reaction_in_words(expected: str, got: str) -> bool:
    """A reaction stated in words ('Fe3O4 is dissolved and converted into Fe2(SO4)3') states
    the expected equation when every species of it appears by formula, each reactant before
    each product, and the equation has no coefficient other than 1 (a coefficient cannot be
    read from words)."""
    key = _equation_key(expected)
    if key is None or any(c != 1 for side in key for c, _ in side):
        return False
    found = []                                                      # (position, key) of each formula
    for m in re.finditer(r"[A-Z][A-Za-z0-9₀-₉()\[\]⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻^+\-]*", str(got)):
        k = _species_key(m.group(0).rstrip("+-^").rstrip(",;:") or m.group(0))
        if k is None:
            k = _species_key(m.group(0).rstrip(",;:."))
        if k is not None:
            found.append((m.start(), k))
    pos = {}
    for p, k in found:
        pos.setdefault(k, []).append(p)
    reactants = [k for _, k in key[0]]
    products = [k for _, k in key[1]]
    if not reactants or not products or not all(k in pos for k in reactants + products):
        return False
    return max(min(pos[k]) for k in reactants) < min(max(pos[k]) for k in products)


def _eq_text(a, b) -> bool:
    sa, sb = str(a), str(b)
    if any(t in sa for t in _ARROWS):
        ka = _equation_key(sa)
        if any(t in sb for t in _ARROWS):
            kb = _equation_key(sb)
            if ka is not None and kb is not None:
                return ka == kb
        elif ka is not None and _reaction_in_words(sa, sb):
            return True
    if "," in sa and "," in sb:                                     # species lists, any order
        la = [_species_key(x) for x in sa.split(",")]
        lb = [_species_key(x) for x in sb.split(",")]
        if None not in la and None not in lb:
            return sorted(la, key=repr) == sorted(lb, key=repr)
    ka, kb = _species_key(sa), _species_key(sb)
    if ka is not None and kb is not None:
        return ka == kb
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
