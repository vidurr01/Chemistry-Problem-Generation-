"""
Substrate scope of the organic edges (docs/organic_rule_scope.md, approved by the user 2026-11-22).

The scope lives in the graph (knowledge/reaction_graph.json), per edge:
    chemoselectivity.requires_absent : ["ketone", "protic", ...]   group names from GROUPS: none may be present
    firing_condition                 : {"only_smiles": [...]}        the edge is modelled for these molecules only
                                       {"requires": [names]}         every named group must be present
                                       {"at_most_one": [names]}      each named group at most once
                                       {"note": "..."}               why (free text, not checked)
check(edge, smiles) raises EngineError when the molecule is outside the edge's scope; rules.apply() calls it
before the rule, so every walk and audit sees the same scope.
"""

from __future__ import annotations

from functools import lru_cache

from rdkit import Chem

from core.engine.base import EngineError
from core.engine.organic.mol import canon, mol

# name -> (SMARTS, what it is). The SMARTS of one group must not match another group's characteristic atoms
# (an anhydride is not an "ester", a COOH is not an "aldehyde").
GROUPS: dict = {
    "aldehyde":          ("[$([CX3H1](=O)[#6]),$([CX3H2]=O)]", "CHO"),
    "ketone":            ("[#6][CX3](=O)[#6]", "ketone C=O"),
    "carboxylic_acid":   ("[CX3](=O)[OX2H1]", "COOH"),
    "ester":             ("[CX3](=O)[OX2][#6;!$(C=O)]", "ester"),
    "acid_chloride":     ("[CX3](=O)[Cl,Br]", "COCl"),
    "anhydride":         ("[CX3](=O)[OX2][CX3]=O", "anhydride"),
    "amide":             ("[CX3](=O)[NX3]", "amide"),
    "nitrile":           ("[CX2]#[NX1]", "C≡N"),
    # 2026-11-26 (live run of the new edges): the blind step check held an acid step on an isocyanide and an SN2 step
    # next to a benzylic NMe3⁺ (a second SN2 site)
    "isocyanide":        ("[N+]#[C-]", "isocyanide N≡C"),
    "quaternary_ammonium": ("[NX4+;!$([N+][O-])]", "quaternary ammonium N⁺"),
    "epoxide":           ("C1OC1", "epoxide"),
    "nitro_aliphatic":   ("[CX4][N+](=O)[O-]", "aliphatic NO2"),
    "nitro":             ("[#6][N+](=O)[O-]", "NO2"),
    "nitroso_aryl":      ("c[NX2]=O", "Ar–N=O"),
    "alkene":            ("[CX3;!a]=[CX3;!a]", "C=C"),
    "alkyne":            ("[CX2]#[CX2]", "C≡C"),
    "terminal_alkyne":   ("[CX2H1]#[CX2]", "≡C–H"),
    "alcohol":           ("[CX4][OX2H1]", "alcohol OH"),
    "alcohol_1":         ("[CX4;H2,H3][OX2H1]", "1° OH"),
    "alcohol_2":         ("[CX4H1]([#6])([#6])[OX2H1]", "2° OH"),
    "phenol":            ("c[OX2H1]", "phenol OH"),
    "amine_nh":          ("[NX3;H2,H1;!$(NC=O);!$(N=*);!$(N#*)]", "N–H of an amine"),
    "amine_aliphatic_nh2": ("[CX4][NX3H2]", "aliphatic NH2"),
    "aryl_nh2":          ("c[NX3H2]", "ArNH2"),
    "amine_any":         ("[NX3;!$(NC=O);!$(N=*);!$(N-[N+,O]);!$([N+])]", "amine N"),
    "protic":            ("[$([O,N,S;!H0]),$([CX2H1]#C)]", "acidic H (O–H, N–H, S–H, ≡C–H)"),
    "benzylic_ch":       ("[CX4;!H0;!$([CX4][OX2H1])]c", "benzylic C–H (not a CH–OH)"),
    "alkyl_halide":      ("[CX4][Cl,Br,I]", "C–X"),
    "halide_2":          ("[CX4H1]([#6])([#6])[Cl,Br,I]", "2° C–X"),
    "halide_3":          ("[CX4]([#6])([#6])([#6])[Cl,Br,I]", "3° C–X"),
    "vicinal_dihalide":  ("[Cl,Br,I][CX4][CX4][Cl,Br,I]", "vicinal dihalide"),
    "aromatic_ring":     ("a", "aromatic ring"),
    "meta_director":     ("c[$([N+](=O)[O-]),$(C=O),$(C#N),$(S(=O)=O),$([N+]([#6])([#6])[#6])]", "meta-directing group on the ring"),
    "alkoxy_aryl":       ("c[OX2][#6]", "Ar–O–R"),
    "benzylic_allylic_ether": ("[$([CX4](c)[OX2][#6]),$([CX4]([CX3]=[CX3])[OX2][#6])]", "benzylic or allylic C–O ether"),
    "ortho_substituted_phenol": ("[OX2H1]c:c-[!#1]", "phenol with an ortho substituent"),
    "hindered_archo":    ("[CX3H1](=O)c(:c-[!#1]):c-[!#1]", "2,6-disubstituted ArCHO"),
    "di_tert_ketone":    ("[CX4]([#6])([#6])([#6])[CX3](=O)[CX4]([#6])([#6])[#6]", "di-tert-alkyl ketone"),
    "alpha_ch_ch2_ketone": ("[CX4;H1,H2]([#6])[CX3](=O)[#6]", "α-CH or α-CH2 next to the ketone"),
    "ester_o_not_primary": ("[CX3](=O)[OX2][$([CX4H1]),$([CX4H0]),$(c)]", "ester O on a 2°, 3° or aryl carbon"),
    "vicinal_triol":     ("[OX2H1][CX4][CX4]([OX2H1])[CX4][OX2H1]", "three adjacent OH"),
    "nh2_can_shift":     ("[NX3H2][CX4;!$([CH3]);!$([CH2][CH3]);!$([CH2]c)]",
                          "NH2 whose carbocation could rearrange (not CH3, CH3CH2 or ArCH2)"),
    "enal":              ("[CX3]=[CX3][CX3H1]=O", "α,β-unsaturated CHO"),
    # an electron-poor C=C / C≡C (Michael acceptor): electrophiles do not add Markovnikov to it, nucleophiles add at
    # the β-carbon (live run 8, 2026-11-24: acid hydration of a 2-formylcyclohexenone put OH on the α-carbon)
    "conj_cc":           ("[$([CX3;!a]=[CX3;!a][CX3]=O),$([CX3;!a]=[CX3;!a]C#N),$([CX3;!a]=[CX3;!a][N+](=O)[O-])]",
                          "C=C conjugated with C=O, C≡N or NO2"),
    "conj_alkyne":       ("[$([CX2]#[CX2][CX3]=O),$([CX2]#[CX2]C#N)]", "C≡C conjugated with C=O or C≡N"),
    "vinyl_halide":      ("[CX3]=[CX3][Cl,Br,I]", "vinyl halide (adding OH next to the C–X collapses to a C=O)"),
    "dialkyl_ether":     ("[CX4][OX2][CX4]", "dialkyl ether"),
    "alcohol_3":         ("[CX4H0]([#6])([#6])([#6])[OX2H1]", "3° OH"),
    "acetal":            ("[CX4]([OX2][#6])[OX2][#6]", "acetal / ketal (opened by aqueous acid)"),
    "oxime":             ("[CX3]=N[OX2H1]", "oxime (Beckmann / hydrolysis in acid)"),
    "sulfonate_ester":   ("[CX4]OS(=O)(=O)[#6]", "alkyl tosylate / sulfonate ester (a leaving group)"),
    "methyl_carbinol":   ("[CH3][CX4;H1,H2][OX2H1]", "CH3CH(OH)– (gives the haloform test)"),
    # reagent × group table (2026-11-25, tools/apply_rule_scope.py LAYER2): groups that hydrolyse, solvolyse,
    # cyclise or fall apart under conditions aimed at another group
    "gem_dihalide":      ("[CX4]([Cl,Br,I])[Cl,Br,I]", "gem-dihalide (hydrolyses to C=O)"),
    "imine":             ("[C]=[NX2;!$(N~[O,N])]", "imine C=N (hydrolysed, reduced, protonated)"),
    "cyanohydrin":       ("[CX4]([OX2H1])C#N", "cyanohydrin (reverts to C=O + CN⁻ in acid or base)"),
    "halohydrin":        ("[OX2H1][CX4][CX4][Cl,Br,I]", "halohydrin (closes to an epoxide in base)"),
    "alpha_halo_carbonyl": ("[Cl,Br,I][CX4][CX3]=O", "α-halo carbonyl"),
    "activated_cx":      ("[$([CX4]([Cl,Br,I])c),$([CX4]([Cl,Br,I])[CX3]=[CX3]),$([CX4]([#6])([#6])([#6])[Cl,Br,I]),"
                          "$([CX4;!H2;!H3]OS(=O)=O),$([CX4](c)OS(=O)=O),$([CX4]([CX3]=[CX3])OS(=O)=O)]",
                          "benzylic, allylic or 3° C–X, or a 2°/3°/benzylic/allylic sulfonate (solvolysis, "
                          "hydrogenolysis)"),
    # live run 7 (2026-11-25): TsCl/pyridine turns a benzylic or allylic OH largely into the chloride
    "activated_oh":      ("[CX4;$([CX4]c),$([CX4][CX3]=[CX3])][OX2H1]", "benzylic or allylic OH"),
    # SN2′ gives a DIFFERENT product (allyl chloride itself gives the same one either way and stays allowed)
    "lone_activated_cx": ("[$([CX4]([Cl,Br,I])c),$([CX4]([Cl,Br,I])[CX3]=[CX3]),$([CX4]([#6])([#6])([#6])[Cl,Br,I]);"
                          "!$([CX4]([Cl,Br,I])[CX4][Cl,Br,I])]",
                          "benzylic, allylic or 3° C–X outside a vicinal dihalide"),
    "allylic_halide":    ("[$([CX4;!H2]([Cl,Br,I])[CX3]=[CX3]),$([CH2]([Cl,Br,I])[CX3]=[CX3;!H2])]",
                          "substituted allylic C–X (SN2′ gives another product)"),
    "neopentyl_halide":  ("[CH2]([Cl,Br,I])[CX4H0]", "neopentyl-type CH2–X (no SN2)"),
    "beta_hydroxy_carbonyl": ("[OX2H1][CX4][CX4;!H0][$([CX3]=O),$(C#N)]", "β-hydroxy C=O / C≡N (dehydrates on heating)"),
}


@lru_cache(maxsize=None)
def _pat(name: str):
    if name not in GROUPS:
        raise KeyError(f"unknown scope group {name!r} (core/engine/organic/scope.py GROUPS)")
    p = Chem.MolFromSmarts(GROUPS[name][0])
    if p is None:
        raise ValueError(f"bad SMARTS for scope group {name}")
    return p


def count(smiles: str, name: str) -> int:
    return len(mol(smiles).GetSubstructMatches(_pat(name), uniquify=True))


def has(smiles: str, name: str) -> bool:
    return mol(smiles).HasSubstructMatch(_pat(name))


def _all_equivalent(smiles: str, name: str) -> bool:
    """Every match of the group sits on symmetry-equivalent atoms (one match counts as equivalent)."""
    from rdkit import Chem
    m = mol(smiles)
    matches = m.GetSubstructMatches(_pat(name))
    if len(matches) <= 1:
        return True
    ranks = list(Chem.CanonicalRankAtoms(m, breakTies=False))
    return len({tuple(sorted(ranks[i] for i in mt)) for mt in matches}) == 1


def trusted(edge: dict) -> bool:
    """The edge has an approved substrate scope (requires_absent or firing_condition, written from
    tools/apply_rule_scope.py). An edge without one fires on any molecule that has its group: live run 7
    (2026-11-24) took conc. H2SO4, 383 K on a 2° benzylic alcohol with a C=C to the hydrogen sulfate."""
    fc = edge.get("firing_condition") or {}
    if fc.get("left_out"):                         # reviewed and dropped from draws (the reason is in the graph)
        return False
    return bool((edge.get("chemoselectivity") or {}).get("requires_absent")) or bool(fc)


def check(edge: dict, smiles: str) -> None:
    """EngineError if the molecule is outside the edge's approved scope."""
    eid = edge.get("id", "?")
    fc = edge.get("firing_condition") or {}
    only = fc.get("only_smiles")
    if only and canon(smiles) not in {canon(x) for x in only}:
        raise EngineError(f"{eid}: modelled only for {', '.join(only)} (scope)")
    for g in fc.get("requires", []):
        if not has(smiles, g):
            raise EngineError(f"{eid}: needs {GROUPS[g][1]} (scope)")
    for g in fc.get("at_most_one", []):
        if count(smiles, g) > 1:
            raise EngineError(f"{eid}: more than one {GROUPS[g][1]} (scope)")
    for g in fc.get("equivalent_only", []):           # several are fine only if symmetry-equivalent (live run 12)
        if not _all_equivalent(smiles, g):
            raise EngineError(f"{eid}: two different {GROUPS[g][1]} sites: which reacts is not settled (scope)")
    for g in (edge.get("chemoselectivity") or {}).get("requires_absent", []):
        if has(smiles, g):
            raise EngineError(f"{eid}: {GROUPS[g][1]} present: outside the approved scope")
