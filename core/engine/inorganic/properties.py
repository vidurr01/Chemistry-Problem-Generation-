"""
Exact inorganic properties, computed by code (the answer key of inorganic questions; no model decides them).

    vsepr("XeF4")                    shape, hybridisation, lone pairs, polarity of a molecule or ion
    mo_diatomic("O2-")               MO configuration, bond order, unpaired electrons, magnetism
    complex_info("[Fe(CN)6]4-")      oxidation state, d electrons, spin, unpaired electrons, spin-only moment,
                                     CFSE, geometry, hybridisation of a coordination entity
    count_isomers("octahedral", ["a", "a", "b", "b", "c", "d"])  geometric and stereo isomers, by enumeration
    oxidation_state("K2Cr2O7", "Cr") average oxidation state of an element in a formula

Each function follows the JEE convention and says where a case falls outside what it can decide (EngineError):
an answer is computed or refused, never guessed. Checked against the concept book's own facts
(tests/test_engine_inorganic.py).
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from fractions import Fraction

from core.engine.base import EngineError
from core.engine.chem import Z_OF, parse_formula

# ── element data ─────────────────────────────────────────────────────────────

_PERIOD_STARTS = (1, 3, 11, 19, 37, 55, 87)


def group_of(symbol: str) -> int:
    """IUPAC group 1-18 (lanthanoids/actinoids: 3)."""
    z = Z_OF[symbol]
    if z == 1:
        return 1
    if z == 2:
        return 18
    start = max(s for s in _PERIOD_STARTS if s <= z)
    k = z - start
    if start in (3, 11):                       # periods 2-3: s block then p block
        return k + 1 if k < 2 else k + 11
    if start in (55, 87):                      # periods 6-7: La/Ac series inside group 3
        if k < 2:
            return k + 1
        if k < 17:
            return 3
        return k - 13                          # Hf (k = 17) is group 4 ... Rn (k = 31) group 18
    return k + 1                               # periods 4-5


def valence_electrons(symbol: str) -> int:
    g = group_of(symbol)
    return g if g <= 2 else (g - 10 if g >= 13 else g)


def is_transition(symbol: str) -> bool:
    return 3 <= group_of(symbol) <= 12 and Z_OF[symbol] > 20


def row_of(symbol: str) -> int:
    """Transition series: 3 (3d), 4 (4d), 5 (5d)."""
    z = Z_OF[symbol]
    return 3 if z <= 30 else (4 if z <= 48 else 5)


# ── VSEPR ────────────────────────────────────────────────────────────────────

# electrons a terminal atom takes from the central atom's valence shell (one bond pair per H/halogen,
# a double bond for O/S, a triple bond for N)
_TERMINAL_USE = {"H": 1, "F": 1, "Cl": 1, "Br": 1, "I": 1, "O": 2, "S": 2, "Se": 2, "N": 3}

# (steric number, lone pairs) -> molecular shape
_SHAPES = {
    (2, 0): "linear", (3, 0): "trigonal planar", (3, 1): "bent", (4, 0): "tetrahedral",
    (4, 1): "trigonal pyramidal", (4, 2): "bent", (5, 0): "trigonal bipyramidal", (5, 1): "see-saw",
    (5, 2): "T-shaped", (5, 3): "linear", (6, 0): "octahedral", (6, 1): "square pyramidal",
    (6, 2): "square planar", (7, 0): "pentagonal bipyramidal", (7, 1): "distorted octahedral",
}
_HYBRID = {2: "sp", 3: "sp2", 4: "sp3", 5: "sp3d", 6: "sp3d2", 7: "sp3d3"}
# shapes in which identical ligands cancel each other's dipoles
_SYMMETRIC = {"linear", "trigonal planar", "tetrahedral", "trigonal bipyramidal", "octahedral", "square planar",
              "pentagonal bipyramidal"}


def _formula_and_charge(text: str):
    """'SO4^2-', 'SO₄²⁻', 'SO4(2-)' or 'NH4+' -> (body, charge). A charge above 1 needs ^, superscripts or
    brackets: 'SO42-' would be read as SO42 with charge -1."""
    s = text.strip().replace(" ", "")
    mag, sign = "", None
    m = re.search(r"([⁰¹²³⁴⁵⁶⁷⁸⁹]*)([⁺⁻])$", s)
    if m:
        mag = m.group(1).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        sign = "+" if m.group(2) == "⁺" else "-"
        s = s[:m.start()]
    else:
        m = re.search(r"(?:\^(\d*)([+-])|\((\d*)([+-])\))$", s)
        if m:
            mag, sign = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
            s = s[:m.start()]
        elif s[-1:] in "+-":
            sign, s = s[-1], s[:-1]
    body = s.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    charge = 0 if not sign else (int(mag) if mag else 1) * (1 if sign == "+" else -1)
    return body, charge


def vsepr(species: str, central: str | None = None) -> dict:
    """Shape of a main-group MOLECULE or discrete ION with ONE central atom and terminal atoms (H, halogens, O, S,
    N); not for network or ionic solids (SiO2 as written would be read as a molecule like CO2).
    The central atom is the one present once (or the first atom of X3 such as I3⁻, O3, N3⁻), unless given."""
    body, charge = _formula_and_charge(species)
    counts = parse_formula(body)[0]
    if central is None:
        singles = [e for e, n in counts.items() if n == 1 and e != "H"]
        inner = [e for e in singles if e not in _TERMINAL_USE]      # XeOF4: Xe, not O
        if len(counts) == 1:                   # I3-, O3, N3-: one element
            central = next(iter(counts))
        elif len(singles) == 1:
            central = singles[0]
        elif len(inner) == 1:
            central = inner[0]
        else:
            raise EngineError(f"cannot tell the central atom of {species}; give central=...")
    if (group_of(central) in (1, 2) and central != "Be") or is_transition(central):
        # CaF2, TiO2 are ionic or network solids (fluorite, rutile): VSEPR describes molecules and discrete ions
        raise EngineError(f"{species}: VSEPR is for main-group molecules and discrete ions, not {central} compounds")
    ligands = Counter(counts)
    ligands[central] -= 1
    ligands = +ligands
    if any(e not in _TERMINAL_USE for e in ligands):
        raise EngineError(f"{species}: terminal atoms other than H, halogens, O, S, N are outside this model")
    n_lig = sum(ligands.values())
    used = sum(_TERMINAL_USE[e] * n for e, n in ligands.items())
    free = valence_electrons(central) - charge - used
    if free < 0:
        raise EngineError(f"{species}: the central atom has too few electrons for these bonds")
    lone_pairs, odd = divmod(free, 2)
    steric = n_lig + lone_pairs + odd          # a single unpaired electron occupies a domain (NO2, ClO2)
    shape = _SHAPES.get((steric, lone_pairs + odd))
    if shape is None:
        raise EngineError(f"{species}: steric number {steric} with {lone_pairs} lone pairs is outside this model")
    identical = len(ligands) == 1
    polar = None if not identical and shape in _SYMMETRIC else (not (identical and shape in _SYMMETRIC))
    if shape == "linear" and steric == 5 and identical:
        polar = False                          # XeF2, I3-: three equatorial lone pairs cancel
    if shape == "square planar" and identical:
        polar = False
    return {"species": species, "central": central, "ligands": dict(ligands), "steric_number": steric,
            "lone_pairs": lone_pairs, "unpaired_on_central": odd, "shape": shape,
            "electron_geometry": _SHAPES[(steric, 0)], "hybridisation": _HYBRID[steric], "polar": polar}


# ── MO theory for homonuclear and light heteronuclear diatomics ───────────────

_ORDER_MIXED = ["σ1s", "σ*1s", "σ2s", "σ*2s", "π2p", "σ2p", "π*2p", "σ*2p"]    # up to 14 electrons (B2, C2, N2)
_ORDER_PLAIN = ["σ1s", "σ*1s", "σ2s", "σ*2s", "σ2p", "π2p", "π*2p", "σ*2p"]    # beyond (O2, F2, Ne2)
_CAP = {"σ": 2, "π": 4}


def mo_diatomic(species: str) -> dict:
    """Molecular-orbital filling of a diatomic of H-Ne (homonuclear, or CO, NO, CN-, NO+ ...): bond order,
    unpaired electrons, magnetism. s-p mixing order for 14 electrons or fewer, the O2 order above (JEE)."""
    body, charge = _formula_and_charge(species)
    counts = parse_formula(body)[0]
    if sum(counts.values()) != 2 or any(Z_OF[e] > 10 for e in counts):
        raise EngineError(f"{species}: only diatomics of H to Ne")
    electrons = sum(Z_OF[e] * n for e, n in counts.items()) - charge
    if electrons <= 0:
        raise EngineError(f"{species}: no electrons")
    order = _ORDER_MIXED if electrons <= 14 else _ORDER_PLAIN
    fill, left, unpaired, config = {}, electrons, 0, []
    for orb in order:
        if left <= 0:
            break
        cap = _CAP[orb[0]]
        n = min(cap, left)
        fill[orb] = n
        left -= n
        if orb.startswith("π"):                # two degenerate orbitals, Hund's rule
            unpaired += n if n <= 2 else 4 - n
        else:
            unpaired += n % 2
        config.append(f"{orb}{n}")
    if left > 0:
        raise EngineError(f"{species}: more electrons than this model holds")
    bonding = sum(n for o, n in fill.items() if "*" not in o)
    anti = sum(n for o, n in fill.items() if "*" in o)
    bo = Fraction(bonding - anti, 2)
    return {"species": species, "electrons": electrons, "configuration": " ".join(config),
            "bond_order": float(bo), "bond_order_fraction": str(bo), "unpaired": unpaired,
            "magnetism": "paramagnetic" if unpaired else "diamagnetic", "exists": bo > 0}


# ── coordination entities ────────────────────────────────────────────────────

# ligand: (charge, denticity, field) with field "strong", "weak" or "nh3"/"h2o" (decided by the metal's charge)
LIGANDS = {
    "CN": (-1, 1, "strong"), "CO": (0, 1, "strong"), "NO2": (-1, 1, "strong"), "en": (0, 2, "strong"),
    "bpy": (0, 2, "strong"), "phen": (0, 2, "strong"), "PPh3": (0, 1, "strong"),
    "NH3": (0, 1, "nh3"), "H2O": (0, 1, "h2o"), "py": (0, 1, "nh3"),
    "F": (-1, 1, "weak"), "Cl": (-1, 1, "weak"), "Br": (-1, 1, "weak"), "I": (-1, 1, "weak"),
    "OH": (-1, 1, "weak"), "ONO": (-1, 1, "weak"), "SCN": (-1, 1, "weak"), "NCS": (-1, 1, "weak"),
    "ox": (-2, 2, "weak"), "C2O4": (-2, 2, "weak"), "gly": (-1, 2, "weak"), "edta": (-4, 6, "strong"),
}
_LIGAND_RX = re.compile(r"\(([^()]+)\)(\d*)|(" + "|".join(sorted(map(re.escape, LIGANDS), key=len, reverse=True))
                        + r")(\d*)")


def parse_complex(text: str):
    """'[Fe(CN)6]4-' -> ('Fe', {'CN': 6}, -4). Ligands from LIGANDS; the metal is written first."""
    s = text.strip().replace(" ", "")
    s = s.translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉", "0123456789+-0123456789"))
    m = re.fullmatch(r"\[([A-Z][a-z]?)(.*)\](?:(\d*)([+-]))?", s)
    if not m:
        raise EngineError(f"{text}: write a coordination entity as [M(L)n...]charge, e.g. [Fe(CN)6]4-")
    metal, rest, mag, sign = m.groups()
    charge = 0 if not sign else (int(mag) if mag else 1) * (1 if sign == "+" else -1)
    ligands, pos = Counter(), 0
    while pos < len(rest):
        lm = _LIGAND_RX.match(rest, pos)
        if not lm:
            raise EngineError(f"{text}: cannot read the ligands from {rest[pos:]!r}")
        name = lm.group(1) or lm.group(3)
        n = int(lm.group(2) or lm.group(4) or 1)
        if name not in LIGANDS:
            raise EngineError(f"{text}: unknown ligand {name!r} (known: {', '.join(LIGANDS)})")
        ligands[name] += n
        pos = lm.end()
    if metal not in Z_OF:
        raise EngineError(f"{text}: unknown element {metal}")
    return metal, dict(ligands), charge


def _strong(field: str, metal: str, ox: int) -> bool:
    if field == "strong":
        return True
    if field == "nh3":                          # NH3 pairs electrons on M3+ (Co3+), not on M2+
        return ox >= 3
    if field == "h2o":                          # [Co(H2O)6]3+ is low spin
        return ox >= 3 and metal == "Co"
    return False


def complex_info(text: str, geometry: str | None = None) -> dict:
    """Valence-bond and crystal-field description of a coordination entity, JEE conventions:
    octahedral low spin with a strong-field ligand, or always for 4d/5d metals, Co3+ low spin except with F-;
    tetrahedral always high spin; four-coordinate d8 with a strong-field ligand (or Pd2+, Pt2+, Au3+) square
    planar. Mixed ligands: low spin if any strong-field ligand (the JEE simplification)."""
    metal, ligands, charge = parse_complex(text)
    if not is_transition(metal):
        raise EngineError(f"{metal} is not a transition metal")
    ox = charge - sum(LIGANDS[l][0] * n for l, n in ligands.items())
    d = group_of(metal) - ox
    if not 0 <= d <= 10:
        raise EngineError(f"{text}: d{d} is impossible (oxidation state {ox:+d})")
    cn = sum(LIGANDS[l][1] * n for l, n in ligands.items())
    strong = (row_of(metal) > 3 or any(_strong(LIGANDS[l][2], metal, ox) for l in ligands)) and not (
        metal == "Co" and set(ligands) == {"F"})
    if metal == "Co" and ox == 3 and set(ligands) != {"F"}:
        strong = True
    if geometry is None:
        if cn == 6:
            geometry = "octahedral"
        elif cn == 4:
            planar = d == 8 and (strong or metal in ("Pd", "Pt") or (metal == "Au" and ox == 3))
            geometry = "square planar" if planar else "tetrahedral"
        elif cn == 2:
            geometry = "linear"
        else:
            raise EngineError(f"{text}: coordination number {cn} is outside this model")
    if geometry == "octahedral":
        if strong:
            t2g = min(d, 6)
            eg = d - t2g
            spin = "low" if 4 <= d <= 7 else "n/a"
        else:
            t2g = min(d, 3) + max(0, min(d - 5, 3))
            eg = d - t2g
            spin = "high" if 4 <= d <= 7 else "n/a"
        unpaired = _unpaired_levels([(t2g, 3), (eg, 2)])
        cfse = Fraction(-4, 10) * t2g + Fraction(6, 10) * eg
        pairs = _pairs(d, unpaired)
        # inner orbital needs two empty 3d: d<=3 always, d4-d7 when low spin ([Co(CN)6]4- d7: JEE d2sp3);
        # d8-d10 never ([Ni(en)3]2+ is sp3d2 though en is strong field; found 2026-11-24, no species used it)
        hybrid = "d2sp3" if (d <= 3 or (strong and d <= 7)) else "sp3d2"
        cfse_text = f"{float(cfse):+.1f} Δo"
    elif geometry == "tetrahedral":
        e = min(d, 2) + max(0, min(d - 5, 2))
        t2 = d - e
        unpaired = _unpaired_levels([(e, 2), (t2, 3)])
        spin = "high" if 3 <= d <= 6 else "n/a"
        cfse = Fraction(-6, 10) * e + Fraction(4, 10) * t2
        pairs = _pairs(d, unpaired)
        hybrid = "sp3"
        cfse_text = f"{float(cfse):+.1f} Δt"
    elif geometry == "square planar":
        unpaired = 0 if d == 8 else _unpaired_levels([(d, 5)])
        spin, cfse, pairs, hybrid, cfse_text = "low", None, None, "dsp2", None
    elif geometry == "linear":
        unpaired = _unpaired_levels([(d, 5)])
        spin, cfse, pairs, hybrid, cfse_text = "n/a", None, None, "sp", None
    else:
        raise EngineError(f"geometry {geometry!r} is outside this model")
    return {"entity": text, "metal": metal, "ligands": ligands, "charge": charge, "oxidation_state": ox,
            "d_electrons": d, "coordination_number": cn, "geometry": geometry, "spin": spin, "unpaired": unpaired,
            "spin_only_moment_BM": round(math.sqrt(unpaired * (unpaired + 2)), 2),
            "magnetism": "paramagnetic" if unpaired else "diamagnetic", "hybridisation": hybrid,
            "cfse": cfse_text, "pairing_energies": pairs}


def _unpaired_levels(levels) -> int:
    """Unpaired electrons when each level (electrons, degenerate orbitals) is filled by Hund's rule."""
    out = 0
    for n, orbs in levels:
        out += n if n <= orbs else 2 * orbs - n
    return out


def _pairs(d: int, unpaired: int) -> int:
    return (d - unpaired) // 2


# ── isomer counting by enumeration ───────────────────────────────────────────

_OCT = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
_SQ = [(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)]


def _matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _group(gens):
    ident = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    seen, frontier = {ident}, [ident]
    while frontier:
        new = []
        for g in frontier:
            for h in gens:
                m = _matmul(h, g)
                if m not in seen:
                    seen.add(m)
                    new.append(m)
        frontier = new
    return seen


_RX = ((1, 0, 0), (0, 0, -1), (0, 1, 0))
_RY = ((0, 0, 1), (0, 1, 0), (-1, 0, 0))
_RZ = ((0, -1, 0), (1, 0, 0), (0, 0, 1))
_INV = ((-1, 0, 0), (0, -1, 0), (0, 0, -1))
_MZ = ((1, 0, 0), (0, 1, 0), (0, 0, -1))                # the square's own plane is a mirror
_ROT_OCT = _group([_RX, _RY])                            # 24 proper rotations
_ALL_OCT = _group([_RX, _RY, _INV])                      # 48, with reflections
_ROT_SQ = _group([_RZ, ((1, 0, 0), (0, -1, 0), (0, 0, -1))])   # D4 proper rotations (8)
_ALL_SQ = _group([_RZ, ((1, 0, 0), (0, -1, 0), (0, 0, -1)), _MZ])


def _perms(points, group):
    idx = {p: i for i, p in enumerate(points)}
    out = []
    for g in group:
        out.append(tuple(idx[tuple(sum(g[i][k] * p[k] for k in range(3)) for i in range(3))] for p in points))
    return out


def count_isomers(geometry: str, ligands) -> dict:
    """Geometric isomers and stereoisomers (geometric with enantiomers counted separately) of a complex.
    ligands: one entry per ligand, a monodentate label ("a") or a bidentate pair ("AA" symmetric, "AB"
    unsymmetric), e.g. ["AA", "AA", "b", "b"] for [M(AA)2b2]. Exact: every arrangement is generated and the
    ones a rotation (stereo) or a rotation or reflection (geometric) carry into each other are counted once."""
    if geometry == "octahedral":
        points, rot, full = _OCT, _ROT_OCT, _ALL_OCT
    elif geometry == "square planar":
        points, rot, full = _SQ, _ROT_SQ, _ALL_SQ
    elif geometry == "tetrahedral":
        mono = [l for l in ligands if len(l) == 1]
        if len(mono) != 4:
            raise EngineError("tetrahedral: four monodentate ligands only")
        distinct = len(set(mono))
        return {"geometric": 1, "stereo": 2 if distinct == 4 else 1, "optical_pairs": 1 if distinct == 4 else 0}
    else:
        raise EngineError(f"geometry {geometry!r} is outside this model")
    n = len(points)
    if sum(2 if len(l) == 2 else 1 for l in ligands) != n:
        raise EngineError(f"{ligands}: the ligands do not fill {n} positions")
    trans = {i: next(j for j, q in enumerate(points) if q == tuple(-x for x in points[i])) for i in range(n)}
    perms_rot, perms_full = _perms(points, rot), _perms(points, full)
    bis = [l for l in ligands if len(l) == 2]
    monos = sorted(l for l in ligands if len(l) == 1)

    def arrangements():
        # chelates on cis pairs, monodentate labels on what is left
        def place(k, used, chel):
            if k == len(bis):
                free = [i for i in range(n) if i not in used]
                for labels in set(itertools.permutations(monos)):
                    pos = dict(chel_labels(chel))
                    pos.update(zip(free, labels))
                    yield tuple(pos[i] for i in range(n)), frozenset(chel)
                return
            for i in range(n):
                for j in range(n):
                    if i == j or i in used or j in used or trans[i] == j:
                        continue
                    if bis[k][0] == bis[k][1] and i > j:
                        continue
                    yield from place(k + 1, used | {i, j}, chel + [(i, j, bis[k])])

        def chel_labels(chel):
            for i, j, l in chel:
                yield i, l[0] + "*"
                yield j, l[1] + "*"
        yield from place(0, frozenset(), [])

    def canon(arr, perms):
        labels, chel = arr
        best = None
        for p in perms:
            new = [None] * n
            for i, lab in enumerate(labels):
                new[p[i]] = lab
            edges = tuple(sorted((min(p[i], p[j]), max(p[i], p[j]), l) if l[0] == l[1] else (p[i], p[j], l)
                                 for i, j, l in chel))
            key = (tuple(new), edges)
            if best is None or key < best:
                best = key
        return best

    arrs = list(arrangements())
    stereo = {canon(a, perms_rot) for a in arrs}
    geometric = {canon(a, perms_full) for a in arrs}
    return {"geometric": len(geometric), "stereo": len(stereo), "optical_pairs": len(stereo) - len(geometric)}


# ── oxidation state ──────────────────────────────────────────────────────────

_FIXED = {"F": -1}


def oxidation_state(formula: str, element: str, *, peroxide: bool = False, hydride: bool = False) -> Fraction:
    """Average oxidation state of `element` in a formula (charge as in 'Cr2O7^2-' or 'Cr₂O₇²⁻'), by the usual
    rules: group 1 +1, group 2 +2, F -1, O -2 (-1 with peroxide=True), H +1 (-1 with hydride=True); the
    element's state is what balances the charge. A fraction where it averages (Fe3O4: 8/3)."""
    body, charge = _formula_and_charge(formula)
    counts = parse_formula(body)[0]
    if element not in counts:
        raise EngineError(f"{element} is not in {formula}")
    if group_of(element) == 17 and any(group_of(e) == 17 and row_of(e) > row_of(element) for e in counts):
        return Fraction(-1)                        # interhalogen: the more electronegative halogen (Cl in ICl) is -1
    known = 0
    for e, n in counts.items():
        if e == element:
            continue
        if e == "O":
            v = -1 if peroxide else -2
        elif e == "H":
            v = -1 if hydride else 1
        elif e in _FIXED:
            v = _FIXED[e]
        elif group_of(e) in (1, 2) and e != "H":
            v = group_of(e)
        elif group_of(e) == 17:
            if group_of(element) == 17 and row_of(e) < row_of(element):
                v = -1                             # I in ICl: the lighter halogen is the negative one
            elif group_of(element) == 17:
                raise EngineError(f"{formula}: {e} is the positive halogen; give its state")
            else:
                v = -1
        else:
            raise EngineError(f"{formula}: the oxidation state of {e} is not fixed by the rules; give it")
        known += v * n
    return Fraction(charge - known, counts[element])
