"""
Offline audit of organic chemoselectivity: the PCl5 bug class (live run 6, 2026-11-24).

An edge must not fire on one group while the molecule carries another group the same reagent attacks (as fast or
faster) and the edge's scope does not exclude it: the engine would draw the slow reaction and ignore the real one.

    python tools/audit_organic_selectivity.py           # every (edge, untouched attacked group) with an example

How: a pool of molecules with one or two functional groups (para on benzene and on a C4 chain) is run through
every ruled edge. Where an edge gives a product, each group in ATTACKS[reagent] that is still there unchanged in
the product is reported. Also reported: two edges with the same reagent that both fire on one molecule (two
different answers for one reagent). ATTACKS is a review aid written 2026-11-24, not an approved table: every
flag needs a chemist's look before any scope changes (the author approves scopes).
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rdkit import Chem, RDLogger  # noqa: E402

from core.engine.base import EngineError  # noqa: E402
from core.engine.organic import rules  # noqa: E402
from core.engine.organic.labels import REAGENT_LABEL  # noqa: E402
from core.engine.organic.scope import count  # noqa: E402

RDLogger.DisableLog("rdApp.*")

# reagent family: first matching regex on the edge's reagent label
FAMILY = [
    ("LiAlH4", r"LiAlH"), ("NaBH4", r"NaBH₄, C₂H₅OH"), ("DIBAL", r"DIBAL"), ("PCl5", r"PCl₅"),
    ("SOCl2", r"SOCl₂"), ("PI3", r"PI₃"), ("hot KMnO4", r"KMnO₄, H⁺, heat"), ("KMnO4", r"^KMnO₄$"),
    ("dichromate", r"Cr₂O₇"), ("mCPBA", r"mCPBA"), ("HBr/HI", r"^H(Br|I)\b"), ("Br2/CCl4", r"Br₂, CCl₄"),
    ("Br2/H2O", r"Br₂, H₂O"), ("Br2/FeBr3", r"FeBr₃"), ("Br2/hv", r"Br₂, hν"), ("H2 cat", r"^H₂, (Pd/C|Ni)"),
    ("Lindlar", r"BaSO₄"), ("O3", r"\(i\) O₃;"), ("Mg", r"^Mg"), ("RCOCl/py", r"CH₃COCl, pyridine"), ("PCC", r"PCC"),
    ("CHCl3/NaOH", r"CHCl₃, aq\. NaOH"), ("MeOH/HCl", r"CH₃OH \(excess\), dry HCl"), ("HCN", r"HCN"),
    ("soda lime", r"NaOH, CaO"), ("Clemmensen", r"Zn–Hg"), ("Wolff-Kishner", r"NH₂NH₂"),
    ("aq NaOH", r"^aq\. NaOH$"), ("alc KOH", r"alc\. KOH"), ("nitration", r"conc\. HNO₃, conc\. H₂SO₄"),
    ("NaNO2/HCl", r"NaNO₂"), ("H3O+ heat", r"^(H₃O⁺, heat|dil\. H₂SO₄, heat)$"), ("MeMgBr", r"CH₃MgBr"),
    ("I2/NaOH", r"I₂, NaOH"), ("Tollens", r"Tollens"), ("OsO4", r"OsO₄"), ("CH3ONa", r"^CH₃ONa$"),
    ("NH3 excess", r"^NH₃ \(excess\)$"), ("NaCN", r"NaCN"), ("Sn/HCl", r"Sn, conc"), ("Zn/H+", r"^Zn, H⁺$"),
    ("conc NaOH", r"conc\. NaOH"), ("dil NaOH", r"dil\. NaOH"), ("acid hydration", r"^dil\. H₂SO₄$"),
    ("HgSO4", r"HgSO₄"), ("TsCl", r"TsCl"), ("Wittig", r"Ph₃P"), ("CH2N2", r"CH₂N₂"), ("HIO4", r"HIO₄"),
    ("FC acylation", r"anhyd\. AlCl₃$"), ("conc H2SO4 heat", r"conc\. H₂SO₄, 443"),
    ("Cu 573K", r"^Cu, 573"), ("NaI", r"NaI"), ("SeO2", r"SeO₂"), ("Na then MeI", r"\(i\) Na; "),
]

# groups each reagent family also attacks under the edge's conditions (standard NCERT/JEE chemistry)
OX = ["alkene", "alkyne", "aldehyde", "alcohol_1", "alcohol_2", "benzylic_ch", "phenol", "aryl_nh2"]
ATTACKS = {
    "LiAlH4": ["aldehyde", "ketone", "carboxylic_acid", "ester", "acid_chloride", "anhydride", "amide", "nitrile",
               "epoxide", "nitro_aliphatic", "alkyl_halide"],
    "NaBH4": ["aldehyde", "ketone", "acid_chloride"],
    "DIBAL": ["aldehyde", "ketone", "ester", "nitrile", "acid_chloride"],
    "PCl5": ["alcohol", "carboxylic_acid", "aldehyde", "ketone", "phenol"],
    "SOCl2": ["alcohol", "carboxylic_acid"],
    "PI3": ["alcohol"],
    "hot KMnO4": OX, "KMnO4": OX, "dichromate": OX,
    "mCPBA": ["alkene", "ketone", "aldehyde", "amine_any"],
    "HBr/HI": ["alkene", "alkyne", "alcohol", "epoxide", "alkoxy_aryl"],
    "Br2/CCl4": ["alkene", "alkyne", "phenol", "aryl_nh2"],
    "Br2/H2O": ["alkene", "alkyne", "phenol", "aryl_nh2", "aldehyde"],
    "Br2/FeBr3": ["alkene", "alkyne", "phenol", "aryl_nh2"],
    "Br2/hv": ["alkene", "alkyne", "benzylic_ch"],
    "H2 cat": ["alkene", "alkyne", "nitro", "nitrile", "aldehyde"],
    "Lindlar": ["alkyne"],
    "O3": ["alkene", "alkyne"],
    "RCOCl/py": ["alcohol", "phenol", "amine_nh"],
    "PCC": ["alcohol_1", "alcohol_2"],
    "CHCl3/NaOH": ["phenol", "amine_aliphatic_nh2", "aryl_nh2", "ester", "acid_chloride", "anhydride"],
    "MeOH/HCl": ["aldehyde", "ketone", "carboxylic_acid", "acid_chloride", "anhydride", "epoxide"],
    "HCN": ["aldehyde", "ketone"],
    "soda lime": ["carboxylic_acid", "ester"],
    "Clemmensen": ["aldehyde", "ketone"],
    "Wolff-Kishner": ["aldehyde", "ketone", "ester", "acid_chloride", "anhydride"],
    "aq NaOH": ["alkyl_halide", "ester", "acid_chloride", "anhydride", "epoxide"],
    "alc KOH": ["alkyl_halide", "ester", "acid_chloride"],
    "nitration": ["aromatic_ring", "aryl_nh2", "alcohol", "aldehyde"],
    "NaNO2/HCl": ["aryl_nh2", "amine_aliphatic_nh2", "amine_nh", "phenol"],
    "H3O+ heat": ["ester", "nitrile", "amide", "acid_chloride", "anhydride", "epoxide"],
    "MeMgBr": ["protic", "aldehyde", "ketone", "ester", "acid_chloride", "anhydride", "nitrile", "epoxide"],
    "I2/NaOH": ["ester", "acid_chloride", "anhydride", "phenol"],
    "Tollens": ["aldehyde"],
    "OsO4": ["alkene"],
    "CH3ONa": ["alkyl_halide", "ester", "acid_chloride", "anhydride"],
    "NH3 excess": ["alkyl_halide", "ester", "acid_chloride", "anhydride", "epoxide", "aldehyde"],
    "NaCN": ["alkyl_halide"],
    "Sn/HCl": ["nitro"],
    "Zn/H+": ["alkyl_halide", "nitro"],
    "conc NaOH": ["aldehyde", "ester", "alkyl_halide", "acid_chloride", "anhydride"],
    "dil NaOH": ["aldehyde", "ester", "alkyl_halide", "acid_chloride", "anhydride"],
    "acid hydration": ["alkene", "epoxide"],
    "HgSO4": ["alkyne", "alkene"],
    "TsCl": ["alcohol", "phenol", "amine_nh"],
    "Wittig": ["aldehyde", "ketone", "protic"],
    "CH2N2": ["carboxylic_acid", "phenol", "alcohol"],
    "HIO4": [],
    "FC acylation": ["aromatic_ring", "phenol", "amine_any", "alcohol"],
    "conc H2SO4 heat": ["alcohol"],
    "Cu 573K": ["alcohol_1", "alcohol_2"],
    "NaI": ["alkyl_halide"],
    "SeO2": ["ketone", "aldehyde"],
    "Na then MeI": ["protic"],
}

# one or two groups on a benzene (para) or on a C4 chain; [*:n] marks the attachment
FRAGS = {
    "CHO": "[*]C=O", "ketone": "[*]C(C)=O", "COOH": "[*]C(=O)O", "ester": "[*]C(=O)OC", "ArOAc": "[*]OC(C)=O",
    "COCl": "[*]C(=O)Cl", "amide": "[*]C(N)=O", "CN": "[*]C#N", "NO2": "[*][N+](=O)[O-]", "allyl": "[*]CC=C",
    "propargyl": "[*]CC#C", "CH2OH": "[*]CO", "CHOHMe": "[*]C(C)O", "OH": "[*]O", "NH2": "[*]N",
    "CH2NH2": "[*]CN", "CH2Br": "[*]CBr", "CHBrMe": "[*]C(C)Br", "OMe": "[*]OC", "epoxide": "[*]CC1CO1",
    "Br": "[*]Br", "Me": "[*]C", "ethyl": "[*]CC", "NHMe": "[*]NC",
}
CORES = {"benzene": "c1ccc(cc1)", "chain": "CCCC"}


def zip_smiles(core: str, a: str, b: str | None) -> str | None:
    """core with fragment a at one end and b (or H) at the other."""
    fa = a.replace("[*]", "[*:1]")
    if core == "benzene":
        c = "[*:1]c1ccc([*:2])cc1"
    else:
        c = "[*:1]CCCC[*:2]"
    fb = b.replace("[*]", "[*:2]") if b else "[*:2][H]"
    m = Chem.MolFromSmiles(".".join([c, fa, fb]))
    if m is None:
        return None
    try:
        z = Chem.molzip(m)
        Chem.SanitizeMol(z)
        return Chem.MolToSmiles(Chem.RemoveHs(z))
    except Exception:
        return None


def pool() -> list:
    out = set()
    names = list(FRAGS)
    for core in CORES:
        for i, a in enumerate(names):
            if core == "chain" and a in ("OH", "NH2", "Br", "OMe", "NHMe", "ArOAc"):
                pass                                           # aliphatic OH/NH2/Br/OMe on a chain are fine too
            for b in [None] + names[i:]:
                s = zip_smiles(core, FRAGS[a], FRAGS[b] if b else None)
                if s:
                    out.add(s)
    return sorted(out)


def family(eid: str) -> str | None:
    lab = REAGENT_LABEL.get(eid, "")
    for name, rx in FAMILY:
        if re.search(rx, lab):
            return name
    return None


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    with open(os.path.join(ROOT, "knowledge", "reaction_graph.json"), encoding="utf-8") as f:
        edges = {e["id"]: e for e in json.load(f)["edges"]}
    mols = pool()
    print(f"{len(mols)} molecules x {len(rules.RULES)} ruled edges")
    flags = collections.defaultdict(list)          # (eid, group) -> examples
    fired = collections.defaultdict(dict)          # smiles -> {eid: product}
    nofam = sorted(e for e in rules.RULES if family(e) is None)
    for eid in sorted(rules.RULES):
        fam = family(eid)
        for s in mols:
            try:
                r = rules.apply(edges[eid], s)
            except EngineError:
                continue
            except Exception as ex:                # a crash is a finding too
                flags[(eid, f"CRASH {type(ex).__name__}")].append(s)
                continue
            fired[s][eid] = r.product
            for g in ATTACKS.get(fam, []):
                try:
                    if count(s, g) and count(r.product, g) >= count(s, g):
                        flags[(eid, g)].append(f"{s} -> {r.product}")
                except Exception:
                    pass
    print("\n== edge fires, the same reagent's other target is left untouched ==")
    for (eid, g), ex in sorted(flags.items()):
        print(f"{eid:48s} [{family(eid)}] leaves {g:20s} x{len(ex):3d}  e.g. {ex[0]}")
    print("\n== two edges with the same reagent both fire on one molecule ==")
    clash = collections.defaultdict(list)
    for s, d in fired.items():
        by = collections.defaultdict(list)
        for eid in d:
            by[family(eid) or REAGENT_LABEL.get(eid)].append(eid)
        for fam, es in by.items():
            if len(es) > 1 and len({d[e] for e in es}) > 1:
                clash[(fam, tuple(sorted(es)))].append(s)
    for (fam, es), ss in sorted(clash.items()):
        print(f"[{fam}] {' / '.join(es)}  x{len(ss)}  e.g. {ss[0]}")
    print(f"\nedges with no reagent family (not checked for untouched targets): {len(nofam)}")
    for e in nofam:
        print(f"  {e}  ({REAGENT_LABEL.get(e)})")


if __name__ == "__main__":
    main()
