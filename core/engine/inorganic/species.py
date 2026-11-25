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
    "central_shape": "text", "central_hybridisation": "hybrid", "basicity": "number",
    "anion_shape": "text", "anion_hybridisation": "hybrid", "cation_shape": "text", "cation_hybridisation": "hybrid",
    "metal_ion_d_electrons": "number", "metal_ion_unpaired": "number", "metal_ion_magnetism": "text",
    "metal_ion_spin_only_moment": "number",
    # "oxidation_state:<El>" for any element of the species
}
DESCRIPTIONS = {
    "shape": "molecular shape (VSEPR)", "hybridisation": "hybridisation of the central atom",
    "polarity": "polar or non-polar", "bond_order": "MO bond order", "mo_magnetism": "magnetic behaviour (MO)",
    "mo_unpaired": "unpaired electrons (MO)", "complex_oxidation_state": "oxidation state of the metal",
    "complex_d_electrons": "d electrons of the metal", "complex_unpaired": "unpaired electrons",
    "complex_magnetism": "magnetic behaviour", "complex_geometry": "geometry",
    "complex_hybridisation": "hybridisation of the metal", "complex_spin_only_moment": "spin-only moment (BM)",
    "central_shape": "shape around the central atom of the oxoacid or oxoanion",
    "central_hybridisation": "hybridisation of the central atom of the oxoacid or oxoanion",
    "basicity": "basicity of the oxoacid (number of replaceable H)",
    "anion_shape": "shape of the salt's anion",
    "anion_hybridisation": "hybridisation of the central atom of the salt's anion",
    "cation_shape": "shape of the salt's polyatomic cation",
    "cation_hybridisation": "hybridisation of the central atom of the salt's polyatomic cation",
    "metal_ion_d_electrons": "d electrons of the metal ion", "metal_ion_unpaired": "unpaired electrons of the metal ion",
    "metal_ion_magnetism": "magnetic behaviour of the metal ion",
    "metal_ion_spin_only_moment": "spin-only moment of the metal ion (BM)",
}
_CATIONS = {"H": 1, "Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1, "NH4": 1, "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2}
# fixed-charge cations of salts whose anion is looked at (not H: an acid is not a salt)
_SALT_CATIONS = {**{k: v for k, v in _CATIONS.items() if k != "H"}, "Be": 2, "Al": 3, "Ag": 1, "Zn": 2}
# anions whose charge is fixed, for the metal's oxidation state in a simple salt (FeSO4, Cr2(SO4)3, CuCN)
_SALT_ANIONS = {"F": -1, "Cl": -1, "Br": -1, "I": -1, "O": -2, "S": -2, "OH": -1, "CN": -1, "SCN": -1,
                "NO3": -1, "NO2": -1, "SO4": -2, "SO3": -2, "S2O3": -2, "CO3": -2, "HCO3": -1, "C2O4": -2,
                "PO4": -3, "ClO3": -1, "ClO4": -1, "OCl": -1}
# elements less electronegative than H (Pauling): H is hydridic (-1) in their hydrides
_HYDRIDE_FORMERS = {"B", "Al", "Ga", "Si", "Ge", "Sn"}
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
    if re.fullmatch(r"[A-Z][a-z]?\(CO\)\d+", s):     # a neutral metal carbonyl written without brackets: Ni(CO)4
        return f"[{s}]"
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


def _charged(body: str, charge: int) -> str:
    return body + ("" if charge == 0 else f"^{abs(charge)}{'+' if charge > 0 else '-'}")


def _max_ox(el: str) -> int:
    g = P.group_of(el)
    return g - 10 if g >= 13 else g


def _oxo_text(body: str, charge: int):
    """An oxoacid or oxoanion with ONE central atom X (H2SO4, H3PO3, HNO2, H3BO3, HCO3-, ClO4-) as a VSEPR text
    about X: each O-H is a single-bonded group (written F, which bonds the same way), every other O a terminal
    O, and P's own P-H bonds stay H (P is 5-valent in its oxoacids: H3PO3 has one P-H, H3PO2 two).
    Returns (text, X, number of O-H), or None when the species is not of that kind (two centres, peroxo,
    organic, HOCl whose centre is O)."""
    counts = parse_formula(body)[0]
    others = [e for e in counts if e not in ("H", "O")]
    if len(others) != 1 or counts[others[0]] != 1 or "O" not in counts:
        return None
    x = others[0]
    if P.is_transition(x) or P.group_of(x) in (1, 2, 18):
        return None
    try:
        ox = P.oxidation_state(_charged(body, charge), x)
    except EngineError:
        return None
    if ox.denominator != 1 or ox > _max_ox(x) or (x == "C" and ox != 4):   # H2SO5 (+8 by the rules), HCOOH
        return None
    n_xh = (5 - int(ox)) // 2 if x == "P" and int(ox) in (1, 3) else 0
    n_oh = counts.get("H", 0) - n_xh
    n_oxo = counts["O"] - n_oh
    if n_oh < 0 or n_oxo < 0 or (n_oxo == 0 and P.group_of(x) == 17):
        return None
    text = x + (f"O{n_oxo}" if n_oxo else "") + (f"F{n_oh}" if n_oh else "") + (f"H{n_xh}" if n_xh else "")
    return _charged(text, charge), x, n_oh


def _split(body: str, head: str):
    """'Ca(HCO3)2' with head 'Ca' -> (1, 'HCO3', 2); 'K2Cr2O7' with 'K' -> (2, 'Cr2O7', 1); else None."""
    m = re.fullmatch(re.escape(head) + r"(\d*)(?:\((.+)\)(\d*)|(.+))", body)
    if not m:
        return None
    rest, n_rest = (m.group(2), int(m.group(3) or 1)) if m.group(2) else (m.group(4), 1)
    if re.search(r"[()\[\]·]", rest) or not rest[:1].isupper():
        return None
    return int(m.group(1) or 1), rest, n_rest


def _salt_parts(body: str):
    """'KClO3' -> ('K', 'ClO3', -1); 'Ca(HCO3)2' -> ('Ca', 'HCO3', -1). None when the cation's charge is not
    fixed or the rest is not one anion."""
    for cat in sorted(_SALT_CATIONS, key=len, reverse=True):
        sp = _split(body, cat)
        if not sp:
            continue
        n_cat, anion, n_an = sp
        q, r = divmod(-_SALT_CATIONS[cat] * n_cat, n_an)
        if r or q >= 0:
            return None
        return cat, anion, q
    return None


def _ion_props(body: str, charge: int, prefix: str) -> dict:
    """Shape and hybridisation of a polyatomic ion: oxoanions by _oxo_text, others (NH4+, BF4-, I3-) by VSEPR."""
    try:
        oxo = _oxo_text(body, charge)
        v = P.vsepr(oxo[0], central=oxo[1]) if oxo else P.vsepr(_charged(body, charge))
    except EngineError:
        return {}
    return {f"{prefix}_shape": v["shape"], f"{prefix}_hybridisation": v["hybridisation"]}


def _metal_ion(body: str, charge: int) -> dict:
    """d electrons, unpaired electrons (free ion, Hund's rule), magnetism and spin-only moment of the one 3d
    metal in a simple ion or salt (Fe2+, FeCl3, Cr2(SO4)3, K2MnO4, CuCl). Complexes go to complex_info;
    averaged states (Fe3O4) and 4d/5d metals (spin state not fixed by free-ion rules) are not computed."""
    counts = parse_formula(body)[0]
    metals = [e for e in counts if P.is_transition(e)]
    if len(metals) != 1 or P.row_of(metals[0]) != 3:
        return {}
    m = metals[0]
    if len(counts) == 1:
        ox = Fraction(charge) if charge > 0 else None
    else:
        try:
            ox = P.oxidation_state(_charged(body, charge), m)
        except EngineError:
            ox, sp = None, _split(body, m) if charge == 0 else None
            if sp and sp[1] in _SALT_ANIONS:
                ox = Fraction(-_SALT_ANIONS[sp[1]] * sp[2], sp[0])
    if ox is None or ox.denominator != 1 or ox < 1:
        return {}
    d = P.group_of(m) - int(ox)
    if not 0 <= d <= 10:
        return {}
    n = d if d <= 5 else 10 - d
    return {"metal_ion_d_electrons": d, "metal_ion_unpaired": n,
            "metal_ion_magnetism": "paramagnetic" if n else "diamagnetic",
            "metal_ion_spin_only_moment": round((n * (n + 2)) ** 0.5, 2)}


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
    oxo = None
    try:
        oxo = _oxo_text(body, charge)
        if oxo:
            for k in ("shape", "hybridisation", "polarity"):   # plain VSEPR put the H on X (HNO2 "trigonal planar")
                out.pop(k, None)
            v = P.vsepr(oxo[0], central=oxo[1])
            out.update({"central_shape": v["shape"], "central_hybridisation": v["hybridisation"]})
            if charge == 0:
                # boric acid is a Lewis acid (B(OH)3 + OH- -> B(OH)4-): monobasic whatever its O-H count
                out["basicity"] = 1 if P.group_of(oxo[1]) == 13 else oxo[2]
    except EngineError:
        pass
    try:
        parts = _salt_parts(body) if charge == 0 else None
    except EngineError:
        parts = None
    if not parts and charge == 0 and not oxo:
        sp = _split(body, "H")                     # HBF4, HPF6: H+ and a complex anion
        if sp and sp[2] == 1:
            parts = ("H", sp[1], -sp[0])
    if parts:
        cat, anion, q = parts
        out.update(_ion_props(anion, q, "anion"))
        if cat == "NH4":
            out.update(_ion_props("NH4", 1, "cation"))
    try:
        out.update(_metal_ion(body, charge))
    except EngineError:
        pass
    try:
        counts = parse_formula(body)[0]
    except EngineError:
        counts = {}
    if len(counts) >= 2:
        # B, Al, Si ... are less electronegative than H: in their hydrides H is -1 (B2H6, NaBH4, LiAlH4: +3, SiH4: +4)
        hydride = "H" in counts and all(e == "H" or e in _HYDRIDE_FORMERS or P.group_of(e) in (1, 2) for e in counts)
        for el in counts:
            if el in ("O", "H", "F") or P.group_of(el) in (1, 2):
                continue                           # K, Na, Ca are fixed by the rules: balancing them gives KClO3 K +7
            if parts and parts[0] == "NH4" and el == "N" and "N" in parse_formula(parts[1])[0]:
                continue                           # NH4NO3: N is -3 and +5; the average (+1) is not a fact to ask
            try:
                ox = P.oxidation_state(text, el, hydride=hydride and el in _HYDRIDE_FORMERS)
            except EngineError:
                continue
            if ox > _max_ox(el):                   # the rules missed a peroxide (CrO5 "+10" is +6): refused, not guessed
                continue
            if P.group_of(el) >= 13 and ox < P.group_of(el) - 18:
                continue                           # below the lowest state (graph node "NH4" gave N -4)
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
