"""
Properties of an organic compound, computed by code (RDKit), for statements in a question.

    askable("CC(O)CC")   {"molecular_formula": "C4H10O", "stereocentres": 1, "optically_active": True,
                          "iodoform_test": True, "lucas_test": "turbidity in about 5 minutes", ...}
    compare(prop, computed, claimed)   True / False, or None when the claimed value cannot be read

Structure-only rules, as JEE states them. A test is positive when the group is present (iodoform: CH3CO– or
CH3CH(OH)–, including ethanol and ethanal; Tollens: an aldehyde or HCOOH; Fehling: an aliphatic aldehyde).
Optical activity is not a property here: a product formed as a racemate makes "is optically active" ambiguous;
stereocentres and stereoisomers (meso counted once) are not.
"""

from __future__ import annotations

import re
from fractions import Fraction

from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.Chem.EnumerateStereoisomers import EnumerateStereoisomers, StereoEnumerationOptions
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

from core.engine.base import EngineError
from core.engine.organic.mol import canon, classes, mol

PROPERTIES = {
    "molecular_formula": "formula", "molar_mass": "number", "degree_of_unsaturation": "number",
    "pi_bonds": "number", "rings": "number", "sp2_carbons": "number", "sp3_carbons": "number", "sp_carbons": "number",
    "stereocentres": "number", "stereoisomers": "number", "geometrical_isomerism": "bool",
    "aromatic": "bool", "iodoform_test": "bool", "tollens_test": "bool", "fehling_test": "bool",
    "nahco3_effervescence": "bool", "fecl3_colour": "bool", "carbylamine_test": "bool", "dnp_test": "bool",
    "bromine_water_decolourised": "bool", "lucas_test": "text", "amine_class": "text",
    "functional_group": "group", "structure": "smiles",
}
DESCRIPTIONS = {
    "molecular_formula": "molecular formula", "molar_mass": "molar mass (g/mol, to 1 decimal)",
    "degree_of_unsaturation": "degree of unsaturation (DBE)", "pi_bonds": "number of π bonds",
    "rings": "number of rings", "sp2_carbons": "number of sp² carbons", "sp3_carbons": "number of sp³ carbons",
    "sp_carbons": "number of sp carbons", "stereocentres": "number of stereocentres (chiral carbons)",
    "stereoisomers": "total number of stereoisomers (meso counted once)",
    "geometrical_isomerism": "shows geometrical (cis/trans) isomerism", "aromatic": "aromatic",
    "iodoform_test": "positive iodoform test", "tollens_test": "positive Tollens' test",
    "fehling_test": "positive Fehling's test", "nahco3_effervescence": "effervescence with NaHCO₃",
    "fecl3_colour": "colour with neutral FeCl₃", "carbylamine_test": "positive carbylamine test",
    "dnp_test": "orange precipitate with 2,4-DNP", "bromine_water_decolourised": "decolourises bromine water",
    "lucas_test": "Lucas test result", "amine_class": "class of the amine (primary/secondary/tertiary)",
    "functional_group": "contains the functional group (graph node name, e.g. ketone)",
    "structure": "the compound's structure (SMILES; stereo ignored)",
}

_P = {k: Chem.MolFromSmarts(v) for k, v in {
    "iodo_co": "[CH3][CX3](=O)[#6]", "iodo_ald": "[CH3][CX3H1]=O", "iodo_oh": "[CH3][CX4H1]([OX2H1])[#6]",
    "iodo_etoh": "[CH3][CH2][OX2H1]",
    "ald": "[CX3H1](=O)[#6]", "hcho": "[CX3H2]=O", "hcooh": "[CX3H1](=O)[OX2H1]", "ar_ald": "c[CX3H1]=O",
    "cooh": "[CX3](=O)[OX2H1]", "so3h": "S(=O)(=O)[OX2H1]", "phenol": "c[OX2H1]", "enol": "[CX3]=[CX3][OX2H1]",
    "pri_amine": "[#6][NX3H2]", "carbonyl": "[#6][CX3](=O)[#6]", "cc_mult": "[CX3;!a]=[CX3;!a]",
    "cc_triple": "[CX2]#[CX2]", "aniline": "c[NX3H2]",
    "oh3": "[CX4H0]([#6])([#6])([#6])[OX2H1]", "oh2": "[CX4H1]([#6])([#6])[OX2H1]", "oh1": "[CX4H2]([#6])[OX2H1]",
    "allyl_benzyl_oh": "[CX4;H1,H2]([OX2H1])[$(C=C),$(c)]",
    "n_amine": "[NX3;!$(N-C=O);!$(N=*);!$(N-[N,O,S])]",
}.items()}


def _has(m, key) -> bool:
    return m.HasSubstructMatch(_P[key])


def _stereo(m):
    opts = StereoEnumerationOptions(onlyUnassigned=False, unique=True)
    base = Chem.Mol(m)
    Chem.RemoveStereochemistry(base)
    isomers = list(EnumerateStereoisomers(base, options=opts))
    smis = {Chem.MolToSmiles(x) for x in isomers}
    chiral = False
    for x in isomers:
        mirror = Chem.MolFromSmiles(Chem.MolToSmiles(x).replace("@@", "!").replace("@", "@@").replace("!", "@"))
        if mirror is not None and Chem.MolToSmiles(mirror) != Chem.MolToSmiles(x):
            chiral = True
            break
    centres = len(Chem.FindMolChiralCenters(base, includeUnassigned=True, useLegacyImplementation=False))
    return len(smis), chiral, centres


def askable(smiles: str) -> dict:
    """Every property code computes for the compound (one molecule; a mixture or ion pair: the organic part)."""
    parts = [p for p in canon(smiles).split(".") if Chem.MolFromSmiles(p) and Chem.MolFromSmiles(p).GetNumAtoms() > 1]
    if len(parts) != 1:
        raise EngineError(f"{smiles}: properties are computed for one compound")
    m = mol(parts[0])
    out = {"molecular_formula": CalcMolFormula(m), "molar_mass": round(Descriptors.MolWt(m), 1),
           "rings": m.GetRingInfo().NumRings(), "aromatic": any(a.GetIsAromatic() for a in m.GetAtoms())}
    hyb = [a.GetHybridization() for a in m.GetAtoms() if a.GetSymbol() == "C"]
    H = Chem.HybridizationType
    out["sp_carbons"] = sum(h == H.SP for h in hyb)
    out["sp2_carbons"] = sum(h == H.SP2 for h in hyb)
    out["sp3_carbons"] = sum(h == H.SP3 for h in hyb)
    pi = 0
    for b in m.GetBonds():
        bt = b.GetBondType()
        pi += {Chem.BondType.DOUBLE: 1, Chem.BondType.TRIPLE: 2}.get(bt, 0)
    pi += sum(1 for r in m.GetRingInfo().BondRings() if len(r) == 6
              and all(m.GetBondWithIdx(i).GetIsAromatic() for i in r)) * 3
    out["pi_bonds"] = pi
    counts = {}
    mh = Chem.AddHs(m)
    for a in mh.GetAtoms():
        counts[a.GetSymbol()] = counts.get(a.GetSymbol(), 0) + 1
    c, h, n = counts.get("C", 0), counts.get("H", 0), counts.get("N", 0)
    x = sum(counts.get(k, 0) for k in ("F", "Cl", "Br", "I"))
    if not set(counts) - {"C", "H", "N", "O", "S", "F", "Cl", "Br", "I"} and Chem.GetFormalCharge(m) == 0:
        dbe = Fraction(2 * c + 2 + n - h - x, 2)
        if dbe.denominator == 1:
            out["degree_of_unsaturation"] = int(dbe)
    n_iso, chiral, centres = _stereo(m)
    out["stereoisomers"] = n_iso
    out["stereocentres"] = centres
    out["geometrical_isomerism"] = any(b.GetStereo() != Chem.BondStereo.STEREONONE or _ez_possible(m, b)
                                       for b in m.GetBonds() if b.GetBondType() == Chem.BondType.DOUBLE
                                       and not b.IsInRing())
    out["iodoform_test"] = any(_has(m, k) for k in ("iodo_co", "iodo_ald", "iodo_oh", "iodo_etoh"))
    out["tollens_test"] = _has(m, "ald") or _has(m, "hcho") or _has(m, "hcooh")
    out["fehling_test"] = (_has(m, "ald") or _has(m, "hcho")) and not _has(m, "ar_ald")
    out["nahco3_effervescence"] = _has(m, "cooh") or _has(m, "so3h")
    out["fecl3_colour"] = _has(m, "phenol") or _has(m, "enol")
    out["carbylamine_test"] = _has(m, "pri_amine")
    out["dnp_test"] = _has(m, "carbonyl") or _has(m, "ald") or _has(m, "hcho")
    out["bromine_water_decolourised"] = _has(m, "cc_mult") or _has(m, "cc_triple") or _has(m, "phenol") \
        or _has(m, "aniline")
    alcohols = [k for k in ("oh3", "oh2", "oh1") if _has(m, k)]
    if len(alcohols) == 1 and len(m.GetSubstructMatches(Chem.MolFromSmarts("[CX4][OX2H1]"))) == 1:
        out["lucas_test"] = ("immediate turbidity" if alcohols[0] == "oh3" or _has(m, "allyl_benzyl_oh")
                             else "turbidity in about 5 minutes" if alcohols[0] == "oh2" else "no turbidity at room temperature")
    ns = [a for a in m.GetAtoms() if a.GetSymbol() == "N"]
    if len(ns) == 1 and _has(m, "n_amine") and ns[0].GetFormalCharge() == 0:
        k = sum(1 for nb in ns[0].GetNeighbors() if nb.GetSymbol() == "C")
        out["amine_class"] = {1: "primary", 2: "secondary", 3: "tertiary"}.get(k)
        if out["amine_class"] is None:
            del out["amine_class"]
    out["functional_group"] = sorted(classes(parts[0]))
    out["structure"] = canon(parts[0], stereo=False)
    return out


def _ez_possible(m, b) -> bool:
    """A non-ring C=C whose two ends each carry two different groups."""
    a1, a2 = b.GetBeginAtom(), b.GetEndAtom()
    if a1.GetSymbol() != "C" or a2.GetSymbol() != "C":
        return False
    ranks = list(Chem.CanonicalRankAtoms(m, breakTies=False))
    for a, other in ((a1, a2), (a2, a1)):
        subs = [nb for nb in a.GetNeighbors() if nb.GetIdx() != other.GetIdx()]
        n_h = a.GetTotalNumHs()
        if len(subs) + n_h != 2:
            return False
        if n_h == 2:
            return False
        if n_h == 0 and ranks[subs[0].GetIdx()] == ranks[subs[1].GetIdx()]:
            return False
    return True


_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")
_TRUE = {"true", "yes", "positive", "y", "1", "shows", "does", "is"}
_FALSE = {"false", "no", "negative", "n", "0", "does not", "doesn't", "not"}


def compare(prop: str, computed, claimed):
    kind = PROPERTIES.get(prop)
    if kind is None:
        return None
    s = str(claimed).strip().lower().translate(_SUP)
    if kind == "number":
        mm = re.match(r"^-?\d+(?:\.\d+)?", s)
        if not mm:
            return None
        v = float(mm.group(0))
        return abs(v - float(computed)) <= (0.051 if prop == "molar_mass" else 1e-9)
    if kind == "bool":
        if s in _TRUE or isinstance(claimed, bool) and claimed:
            return bool(computed) is True
        if s in _FALSE or isinstance(claimed, bool) and not claimed:
            return bool(computed) is False
        return None
    if kind == "formula":
        return s.replace(" ", "") == str(computed).lower()
    if kind == "smiles":
        try:
            return canon(str(claimed), stereo=False) == canon(str(computed), stereo=False)
        except EngineError:
            return None
    if kind == "group":
        return s.replace(" ", "_") in computed
    return re.sub(r"\s+", " ", s) == str(computed).lower()
