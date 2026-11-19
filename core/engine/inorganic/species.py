"""
Graph species -> the properties code can compute for them, and claims checked against those values.

    askable("K4[Fe(CN)6]")        {"complex_unpaired": 0, "complex_magnetism": "diamagnetic", ..., "oxidation_state:Fe": 2}
    check_claim(species, "complex_unpaired", "0")   True / False (None: not computable, so not usable)

Species ids are the inorganic graph's (knowledge/reaction_graph_inorg.json). Charges there are written without a
marker: 'C2O42-' is C2O4 2-, 'Al3+' is Al 3+, but 'NO2-' is NO2 -1 (to_formula_charge says how).
"""

from __future__ import annotations

import re
from fractions import Fraction

from core.engine.base import EngineError
from core.engine.chem import parse_formula
from core.engine.inorganic import properties as P

# property keys a question may ask about, with how a claim's value is compared
PROPERTIES = {
    "shape": "text", "hybridisation": "hybrid", "polarity": "text",
    "bond_order": "number", "mo_magnetism": "text", "mo_unpaired": "number",
    "complex_oxidation_state": "number", "complex_d_electrons": "number", "complex_unpaired": "number",
    "complex_magnetism": "text", "complex_geometry": "text", "complex_hybridisation": "hybrid",
    "complex_spin_only_moment": "number",
    # "oxidation_state:<El>" for any element of the species
}
DESCRIPTIONS = {
    "shape": "molecular shape (VSEPR)", "hybridisation": "hybridisation of the central atom",
    "polarity": "polar or non-polar", "bond_order": "MO bond order", "mo_magnetism": "magnetic behaviour (MO)",
    "mo_unpaired": "unpaired electrons (MO)", "complex_oxidation_state": "oxidation state of the metal",
    "complex_d_electrons": "d electrons of the metal", "complex_unpaired": "unpaired electrons",
    "complex_magnetism": "magnetic behaviour", "complex_geometry": "geometry",
    "complex_hybridisation": "hybridisation of the metal", "complex_spin_only_moment": "spin-only moment (BM)",
}
_CATIONS = {"H": 1, "Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1, "NH4": 1, "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2}
_ANIONS = {"Cl": -1, "Br": -1, "I": -1, "F": -1, "NO3": -1, "OH": -1, "SO4": -2, "CO3": -2}


def to_formula_charge(sid: str):
    """'C2O42-' -> ('C2O4', -2); 'Al3+' -> ('Al', 3); 'NO2-' -> ('NO2', -1); 'K4[Fe(CN)6]' -> ('K4[Fe(CN)6]', 0)."""
    s = sid.split("·")[0].strip()
    if s[-1:] not in "+-":
        return s, 0
    sign = 1 if s[-1] == "+" else -1
    body = s[:-1]
    if body.endswith("]"):
        return body, sign
    m = re.fullmatch(r"(.*\])(\d+)", body)            # [BeCl4]2-
    if m:
        return m.group(1), sign * int(m.group(2))
    m = re.fullmatch(r"(.*?\D)(\d)(\d)", body)          # SO42-: SO4 and 2-
    if m:
        return m.group(1) + m.group(2), sign * int(m.group(3))
    m = re.fullmatch(r"([A-Z][a-z]?)(\d)", body)        # Al3+, S2-
    if m:
        return m.group(1), sign * int(m.group(2))
    return body, sign                                   # NO2-, NH4+: one charge


def _complex_text(sid: str):
    """The coordination entity of a species with its charge: '[Fe(CN)6]4-' from 'K4[Fe(CN)6]'."""
    s = sid.split("·")[0].strip()
    m = re.fullmatch(r"(.*?)(\[[^\]]+\])(\d*[+-]?)(.*)", s)
    if not m:
        return None
    before, entity, charge, after = m.groups()
    if charge:
        return entity + charge
    total = 0
    for part in (before, after):
        if not part:
            continue
        for ion, n in re.findall(r"(NH4|NO3|SO4|CO3|OH|[A-Z][a-z]?)(\d*)", part):
            n = int(n or 1)
            if ion in _CATIONS:
                total += _CATIONS[ion] * n
            elif ion in _ANIONS:
                total += _ANIONS[ion] * n
            else:
                return None                             # Fe4[Fe(CN)6]3: the outer ion's charge is not fixed
    q = -total
    return entity + ("" if q == 0 else f"{abs(q)}{'+' if q > 0 else '-'}")


def askable(sid: str) -> dict:
    """Every property code can compute for the species: {key: value}. Empty if none."""
    out = {}
    entity = _complex_text(sid)
    if entity:
        try:
            c = P.complex_info(entity)
            out.update({"complex_oxidation_state": c["oxidation_state"], "complex_d_electrons": c["d_electrons"],
                        "complex_unpaired": c["unpaired"], "complex_magnetism": c["magnetism"],
                        "complex_geometry": c["geometry"], "complex_hybridisation": c["hybridisation"],
                        "complex_spin_only_moment": c["spin_only_moment_BM"]})
        except EngineError:
            pass
        return out
    body, charge = to_formula_charge(sid)
    text = body + ("" if charge == 0 else f"^{abs(charge)}{'+' if charge > 0 else '-'}")
    try:
        v = P.vsepr(text)
        out.update({"shape": v["shape"], "hybridisation": v["hybridisation"]})
        if v["polar"] is not None:
            out["polarity"] = "polar" if v["polar"] else "non-polar"
    except EngineError:
        pass
    try:
        m = P.mo_diatomic(text)
        out.update({"bond_order": m["bond_order"], "mo_magnetism": m["magnetism"], "mo_unpaired": m["unpaired"]})
    except EngineError:
        pass
    try:
        counts = parse_formula(body)[0]
    except EngineError:
        counts = {}
    if len(counts) >= 2:
        for el in counts:
            if el in ("O", "H", "F"):
                continue
            try:
                ox = P.oxidation_state(text, el)
            except EngineError:
                continue
            out[f"oxidation_state:{el}"] = float(ox) if ox.denominator != 1 else int(ox)
    return out


_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")


def _norm_text(v) -> str:
    s = str(v).strip().lower().translate(_SUP).replace("_", " ").replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    return {"nonpolar": "non-polar", "seesaw": "see-saw", "t shaped": "t-shaped", "t-shape": "t-shaped",
            "pyramidal": "trigonal pyramidal", "angular": "bent", "v-shaped": "bent"}.get(s, s)


def _norm_number(v):
    s = str(v).strip().replace("+", "").translate(_SUP)
    m = re.match(r"^-?\d+(?:\.\d+)?(?:/\d+)?", s)
    if not m:
        return None
    t = m.group(0)
    return float(Fraction(t)) if "/" in t else float(t)


def compare(prop: str, computed, claimed):
    """True/False, or None when the claimed value cannot be read for this property."""
    kind = "number" if prop.startswith("oxidation_state:") else PROPERTIES.get(prop)
    if kind is None:
        return None
    if kind == "number":
        c = _norm_number(claimed)
        return None if c is None else abs(c - float(computed)) <= 0.011 * max(1.0, abs(float(computed)))
    return _norm_text(claimed) == _norm_text(computed)


def check_claim(sid: str, prop: str, value):
    """True / False if code can decide the claim; None if the property is not computable for this species."""
    props = askable(sid)
    if prop not in props:
        return None
    return compare(prop, props[prop], value)
