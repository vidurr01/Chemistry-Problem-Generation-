"""
One rule per reaction edge of knowledge/reaction_graph.json: rule(smiles) -> Result (product as canonical SMILES,
co-products, traps = the products a wrong selectivity gives). A rule raises EngineError when the edge does not
apply to that molecule (no such group, or no single major product), so a walk only keeps molecules the rule
decides.

Generic reagents ("RCOCl", "ROH", "RNH2", "RX") are fixed to the simplest member (acetyl chloride, methanol,
methylamine, methyl iodide) and named in REAGENT_USED, so the question can state them.

Edges that are not a reaction step (concepts, intermediates, polymers) are in edges.CONCEPT; edges whose graph
entry looks wrong are in edges.SUSPECT with the proposed fix, waiting for the user's approval: they have no rule.
"""

from __future__ import annotations

from rdkit import Chem

from core.engine.base import EngineError
from core.engine.organic.mol import canon, mol
from core.engine.organic.react import (Result, anti_markovnikov, atom_by_map, carbon_degree, eas, exhaust, hofmann,
                                       markovnikov, one, pick, run, smi, zaitsev)

RULES: dict = {}
REAGENT_USED: dict = {}


def rule(edge_id: str, reagent: str | None = None):
    def deco(fn):
        RULES[edge_id] = fn
        if reagent:
            REAGENT_USED[edge_id] = reagent
        return fn
    return deco


def _has(smiles: str, smarts: str) -> bool:
    return mol(smiles).HasSubstructMatch(Chem.MolFromSmarts(smarts))


def _need(smiles: str, smarts: str, what: str):
    if not _has(smiles, smarts):
        raise EngineError(f"{smiles} has no {what}")


def _no(smiles: str, smarts: str, what: str):
    if _has(smiles, smarts):
        raise EngineError(f"{smiles}: {what}")


ALKENE = "[CX3;!a]=[CX3;!a]"


# ── Hydrocarbons ─────────────────────────────────────────────────────────────

@rule("alkane_to_alkyl_halide_x", "Br2, hν")
def _alkane_bromination(s):
    _no(s, "[!#6;!#1]", "not an alkane")
    prods = run("[CX4;!H0:1]>>[C:1]Br", s)

    def key(p):   # Br2 is highly selective: 3° > 2° > 1° H
        return carbon_degree(atom_by_map(p, 1))
    return pick(prods, key, "radical bromination: the most substituted C–H (most stable radical)", "less_selective_product")


@rule("alkane_to_benzene_al2o3cr2o3")
def _aromatise(s):
    _no(s, "[!#6]", "not an alkane")
    m = mol(s)
    if m.GetRingInfo().NumRings() or not 6 <= m.GetNumAtoms() <= 8 or _has(s, "[CX4]([#6])([#6])[#6]"):
        raise EngineError(f"{s}: aromatisation is modelled for straight-chain C6–C8 alkanes")
    n = m.GetNumAtoms()
    side = {6: "", 7: "C", 8: "CC"}[n]
    return Result(canon(f"{side}c1ccccc1" if side else "c1ccccc1"), coproducts=["[H][H]"],
                  why="aromatisation (cyclisation + dehydrogenation) of the C6 chain end")


@rule("alkene_to_alcohol_ho")
def _hydration(s):
    _need(s, ALKENE, "C=C")
    return pick(run("[C:1]=[C:2]>>[C:1](O)[C:2]", s), markovnikov,
                "acid-catalysed hydration: OH on the more substituted carbon (Markovnikov)", "anti_markovnikov_product")


@rule("alkene_to_aldehyde_o")
def _ozonolysis_alkene(s):
    _need(s, ALKENE, "C=C")
    if len(mol(s).GetSubstructMatches(Chem.MolFromSmarts(ALKENE))) != 1:
        raise EngineError(f"{s}: ozonolysis modelled for one C=C")
    m = mol(s)
    rxn = Chem.AllChem.ReactionFromSmarts("[C:1]=[C:2]>>([C:1]=O.[C:2]=O)")
    prods = rxn.RunReactants((m,))
    out = Chem.Mol(prods[0][0])
    Chem.SanitizeMol(out)
    p = canon(Chem.MolToSmiles(out))
    return Result(p, why="reductive ozonolysis cleaves C=C into two C=O")


_ozonolysis = _ozonolysis_alkene
RULES["cycloalkene_to_alkane_o3"] = _ozonolysis_alkene


@rule("alkene_to_alkane_h")
def _hydrogenate(s):
    _need(s, ALKENE, "C=C")
    return Result(exhaust("[C:1]=[C:2]>>[C:1][C:2]", s), why="catalytic hydrogenation of C=C")


@rule("alkene_to_alkyl_halide_hx", "HBr (no peroxide)")
def _hx_add(s):
    _need(s, ALKENE, "C=C")
    return pick(run("[C:1]=[C:2]>>[C:1](Br)[C:2]", s), markovnikov,
                "HBr addition via the more stable carbocation (Markovnikov)", "anti_markovnikov_product")


def _oxidative_cleavage(s, bond: str):
    m = mol(s)
    rxn = Chem.AllChem.ReactionFromSmarts(bond)
    prods = rxn.RunReactants((m,))
    if not prods:
        raise EngineError(f"{s}: nothing to cleave")
    out = Chem.Mol(prods[0][0])
    Chem.SanitizeMol(out)
    parts = []
    for part in canon(Chem.MolToSmiles(out)).split("."):
        # =CH2 ends become CO2; aldehydes are oxidised to acids by hot KMnO4
        if part in ("C=O",):
            parts.append("O=C=O")
            continue
        parts.append(exhaust("[CX3H1:1]=[O:2]>>[C:1](=[O:2])O", part) if _has(part, "[CX3H1]=O") else part)
    return canon(".".join(parts))


@rule("alkene_to_carboxylic_acid_hotkmno4acid")
def _hot_kmno4(s):
    _need(s, ALKENE, "C=C")
    p = _oxidative_cleavage(s, "[C:1]=[C:2]>>([C:1]=O.[C:2]=O)")
    return Result(p, why="hot acidic KMnO4 cleaves C=C: =CHR → RCOOH, =CR2 → ketone, =CH2 → CO2")


@rule("alkene_to_diol_oso")
def _dihydroxylate(s):
    _need(s, ALKENE, "C=C")
    return one("[C:1]=[C:2]>>[C:1](O)[C:2]O", s, why="OsO4: syn dihydroxylation")


@rule("alkene_to_epoxide_mcpba")
def _epoxidise(s):
    _need(s, ALKENE, "C=C")
    return one("[C:1]=[C:2]>>[C:1]1O[C:2]1", s, why="peracid epoxidation")


@rule("alkene_to_ether_hgoacrohorhg", "CH3OH")
def _alkoxymercuration(s):
    _need(s, ALKENE, "C=C")
    return pick(run("[C:1]=[C:2]>>[C:1](OC)[C:2]", s), markovnikov,
                "alkoxymercuration–demercuration: OR on the more substituted carbon, no rearrangement",
                "anti_markovnikov_product")


@rule("alkene_to_halohydrin_br")
def _halohydrin(s):
    _need(s, ALKENE, "C=C")
    return pick(run("[C:1]=[C:2]>>[C:1](O)[C:2]Br", s), markovnikov,
                "bromonium ion opened by water at the more substituted carbon", "regio_reversed_product")


@rule("alkene_to_vicinal_dihalide_x", "Br2")
def _dibromide(s):
    _need(s, ALKENE, "C=C")
    return one("[C:1]=[C:2]>>[C:1](Br)[C:2]Br", s, why="Br2 adds across C=C (anti)")


@rule("diene_conjugated_to_alkyl_halide_hbr1eq")
def _diene_hbr(s):
    _need(s, "C=CC=C", "conjugated diene")
    one2 = run("[CH2:1]=[C:2][C:3]=[C:4]>>[CH3:1][C:2](Br)[C:3]=[C:4]", s)
    one4 = run("[CH2:1]=[C:2][C:3]=[C:4]>>[CH3:1][C:2]=[C:3][C:4]Br", s)
    if not one2:
        raise EngineError(f"{s}: needs a terminal =CH2")
    p12 = pick(one2, markovnikov, "1,2-adduct", "other_1_2")
    traps = {"1,4_adduct (thermodynamic)": smi(one4[0])} if one4 else {}
    return Result(p12.product, traps=traps, why="HBr at low temperature: kinetic 1,2-addition")


@rule("alkyne_to_alkane_o3")
def _ozonolysis_alkyne(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    _no(s, "[CX2H1]#C", "a terminal alkyne gives an aldehyde-ketone and CO2 mixture here")
    return one("[C:1]#[C:2]>>[C:1](=O)[C:2]=O", s, why="ozonolysis of an internal alkyne → 1,2-dicarbonyl")


@rule("alkyne_to_alkene_h")
def _lindlar(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    return one("[C:1]#[C:2]>>[C:1]=[C:2]", s, why="Lindlar: partial hydrogenation, cis alkene")


@rule("alkyne_to_carboxylic_acid_hotkmno4acid")
def _alkyne_cleave(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    p = _oxidative_cleavage(s, "[C:1]#[C:2]>>([C:1](=O)O.[C:2](=O)O)")
    p = canon(".".join("O=C=O" if x == "O=CO" else x for x in p.split(".")))
    return Result(p, why="hot KMnO4 cleaves C≡C to two acids (≡CH → CO2)")


@rule("alkyne_to_geminal_dihalide_hxexcess2equ", "HBr (2 equiv)")
def _alkyne_2hx(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    return pick(run("[C:1]#[C:2]>>[C:1](Br)(Br)[C:2]", s), markovnikov,
                "two HBr add Markovnikov: both Br on the same (more substituted) carbon", "anti_markovnikov_product")


@rule("alkyne_to_ketone_ho")
def _alkyne_hydration(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    return pick(run("[C:1]#[C:2]>>[C:1](=O)[C:2]", s), markovnikov,
                "HgSO4/H2SO4 hydration: Markovnikov enol tautomerises to the ketone (ethyne gives ethanal)",
                "anti_markovnikov_product")


@rule("alkyne_to_vinyl_halide_hx1equiv", "HBr (1 equiv)")
def _alkyne_hx(s):
    _need(s, "[CX2]#[CX2]", "C≡C")
    return pick(run("[C:1]#[C:2]>>[C:1](Br)=[C:2]", s), markovnikov, "Markovnikov addition of one HBr",
                "anti_markovnikov_product")


# ── Alkyl halides ────────────────────────────────────────────────────────────

HAL = "[CX4][Cl,Br,I]"


@rule("alkyl_halide_to_alcohol_naoh")
def _hydrolyse(s):
    _need(s, HAL, "C–X")
    return Result(exhaust("[CX4:1][Cl,Br,I]>>[C:1]O", s), why="substitution of X by OH")


@rule("alkyl_halide_to_alkane_zn")
def _reduce_halide(s):
    _need(s, HAL, "C–X")
    return Result(exhaust("[CX4:1][Cl,Br,I]>>[C:1]", s), why="Zn/H+ reduces C–X to C–H")


@rule("alkyl_halide_to_alkene_alckoh")
def _e2(s):
    _need(s, HAL, "C–X")
    if len(mol(s).GetSubstructMatches(Chem.MolFromSmarts(HAL))) != 1:
        raise EngineError(f"{s}: elimination modelled for one C–X")
    return pick(run("[CX4:1]([Cl,Br,I])[CX4;!H0:2]>>[C:1]=[C:2]", s), zaitsev,
                "E2 with alcoholic KOH: the more substituted alkene (Saytzeff)", "hofmann_product")


@rule("alkyl_halide_to_alkyl_halide_nai")
def _finkelstein(s):
    _need(s, "[CX4][Cl,Br]", "C–Cl or C–Br")
    return Result(exhaust("[CX4:1][Cl,Br]>>[C:1]I", s), why="Finkelstein: NaI in acetone (NaCl/NaBr precipitate)")


@rule("alkyl_halide_to_amine_excessnh")
def _ammonolysis(s):
    _need(s, HAL, "C–X")
    _no(s, "[CX4]([#6])([#6])([#6])[Cl,Br,I]", "a tertiary halide eliminates with NH3")
    return Result(exhaust("[CX4:1][Cl,Br,I]>>[C:1]N", s), why="excess NH3 gives the primary amine")


@rule("alkyl_halide_to_cycloalkane_mgmagnesiumm")
def _intramolecular_wurtz(s):
    m = run("[Br,Cl,I][CH2:1][C:3][CH2:2][Br,Cl,I]>>[C:1]1[C:3][C:2]1", s) or \
        run("[Br,Cl,I][CH2:1][C:3][C:4][CH2:2][Br,Cl,I]>>[C:1]1[C:3][C:4][C:2]1", s)
    if not m:
        raise EngineError(f"{s}: ring closure needs a 1,3- or 1,4-dihalide")
    return Result(smi(m[0]), why="intramolecular coupling of a 1,3/1,4-dihalide")


@rule("alkyl_halide_to_ether_rona", "CH3ONa")
def _williamson(s):
    _need(s, HAL, "C–X")
    _no(s, "[CX4]([#6])([#6])([#6])[Cl,Br,I]", "a tertiary halide gives the alkene with an alkoxide (E2)")
    return one("[CX4:1][Cl,Br,I]>>[C:1]OC", s, why="Williamson synthesis (SN2)")


@rule("alkyl_halide_to_grignard_mg")
def _grignard(s):
    _need(s, "[CX4][Cl,Br,I]", "C–X")
    if len(mol(s).GetSubstructMatches(Chem.MolFromSmarts(HAL))) != 1:
        raise EngineError(f"{s}: one C–X expected")
    return one("[CX4:1][Br,Cl,I:2]>>[C:1][Mg][*:2]", s, why="Mg in dry ether inserts into C–X")


@rule("alkyl_halide_to_ketone_dmsodimethyl")
def _kornblum(s):
    _need(s, "[CX4;H1]([#6])([#6])[Cl,Br,I]", "secondary C–X")
    return one("[CX4;H1:1][Cl,Br,I]>>[C:1]=O", s, why="Kornblum oxidation (DMSO): sec-halide → ketone")


@rule("alkyl_halide_to_nitrile_nacn")
def _cyanide(s):
    _need(s, HAL, "C–X")
    _no(s, "[CX4]([#6])([#6])([#6])[Cl,Br,I]", "a tertiary halide eliminates with CN-")
    r = one("[CX4:1][Cl,Br,I]>>[C:1]C#N", s, why="NaCN: SN2, C-attack gives the nitrile")
    r.traps = {"isocyanide (AgCN)": smi(run("[CX4:1][Cl,Br,I]>>[C:1][N+]#[C-]", s)[0])}
    return r


@rule("alkyl_halide_to_nitro_compound_agno2silvern")
def _agno2(s):
    _need(s, HAL, "C–X")
    _no(s, "[CX4]([#6])([#6])([#6])[Cl,Br,I]", "a tertiary halide reacts by SN1/E1 with AgNO2 (nitrite, alkene)")
    r = one("[CX4:1][Cl,Br,I]>>[C:1][N+](=O)[O-]", s, why="AgNO2: N-attack gives the nitroalkane")
    r.traps = {"alkyl nitrite (NaNO2/KNO2)": smi(run("[CX4:1][Cl,Br,I]>>[C:1]ON=O", s)[0])}
    return r


@rule("alkyl_halide_to_acid_chloride_o2")
def _phosgene(s):
    if canon(s) != canon("ClC(Cl)Cl"):
        raise EngineError("air oxidation to an acid chloride is the chloroform → phosgene reaction only")
    return Result(canon("O=C(Cl)Cl"), coproducts=["Cl"], why="CHCl3 + O2 (light) → COCl2 + HCl")


# ── Alcohols, phenols, ethers ────────────────────────────────────────────────

P_OH = "[CX4;H2]([#6])[OX2H1]"
S_OH = "[CX4;H1]([#6])([#6])[OX2H1]"


@rule("alcohol_to_aldehyde_pcc")
def _pcc_1(s):
    _need(s, P_OH, "primary OH")
    return one("[CX4;H2:1]([#6:2])[OX2H1]>>[C:1](=O)[#6:2]", s, why="PCC stops at the aldehyde")


@rule("alcohol_to_ketone_pcc")
def _pcc_2(s):
    _need(s, S_OH, "secondary OH")
    return one("[CX4;H1:1]([#6:2])([#6:3])[OX2H1]>>[C:1](=O)([#6:2])[#6:3]", s, why="PCC oxidises a sec-alcohol to the ketone")


@rule("alcohol_to_carboxylic_acid_kmno")
def _kmno4_1(s):
    _need(s, P_OH, "primary OH")
    r = one("[CX4;H2:1]([#6:2])[OX2H1]>>[C:1](=O)(O)[#6:2]", s, why="KMnO4/H+ oxidises a 1° alcohol to the acid")
    r.traps = {"aldehyde (PCC)": _pcc_1(s).product}
    return r


@rule("alcohol_to_alkene_conchso")
def _dehydrate(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    if len(mol(s).GetSubstructMatches(Chem.MolFromSmarts("[CX4][OX2H1]"))) != 1:
        raise EngineError(f"{s}: one OH expected")
    if _has(s, "[CX4;H2]([CX4]([#6])([#6])[#6])[OX2H1]"):
        raise EngineError(f"{s}: neopentyl-type alcohol rearranges (methyl shift)")
    return pick(run("[CX4:1]([OX2H1])[CX4;!H0:2]>>[C:1]=[C:2]", s), zaitsev,
                "acid dehydration (E1): the more substituted alkene", "less_substituted_alkene")


@rule("alcohol_to_alkyl_halide_socl")
def _socl2(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return Result(exhaust("[CX4:1][OX2H1]>>[C:1]Cl", s), coproducts=["O=S=O", "Cl"], why="SOCl2/pyridine: OH → Cl")


@rule("alcohol_to_carbene_chndiazometh")
def _ch2n2_alcohol(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return one("[CX4:1][OX2H1]>>[C:1]OC", s, why="CH2N2 (with HBF4) methylates the OH: methyl ether")


@rule("alcohol_to_ester_rcocl", "CH3COCl")
def _acylate_alcohol(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return one("[CX4:1][OX2H1:2]>>[C:1][O:2]C(C)=O", s, why="acylation of the OH (ester)")


@rule("alcohol_to_ether_na", "Na, then CH3I")
def _alkoxide_ether(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return one("[CX4:1][OX2H1:2]>>[C:1][O:2]C", s, why="alkoxide + CH3I (Williamson)")


@rule("alcohol_to_substituted_benzene_4methylbenze")
def _tosylate(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return one("[CX4:1][OX2H1:2]>>[C:1][O:2]S(=O)(=O)c1ccc(C)cc1", s, why="TsCl/pyridine: tosylate, configuration kept")


@rule("alcohol_to_sulfonate_conchso")
def _alkyl_hso4(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return one("[CX4:1][OX2H1:2]>>[C:1][O:2]S(=O)(=O)O", s, why="conc. H2SO4 below 110 °C: alkyl hydrogen sulphate")


@rule("diol_to_aldehyde_hio4periodic")
def _periodate(s):
    _need(s, "[CX4]([OX2H1])[CX4][OX2H1]", "vicinal diol")
    m = run("[CX4:1]([OX2H1])[CX4:2][OX2H1]>>[C:1]=O.[C:2]=O", s)
    rxn = Chem.AllChem.ReactionFromSmarts("[CX4:1]([OX2H1])[CX4:2][OX2H1]>>([C:1]=O.[C:2]=O)")
    prods = rxn.RunReactants((mol(s),))
    if not prods or not m:
        raise EngineError(f"{s}: no vicinal diol")
    out = Chem.Mol(prods[0][0])
    Chem.SanitizeMol(out)
    return Result(canon(Chem.MolToSmiles(out)), why="HIO4 cleaves the C–C between vicinal OH groups")


@rule("diol_to_alkane_redp")
def _hi_reduce(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return Result(exhaust("[CX4:1][OX2H1]>>[C:1]", s), why="red P/HI reduces every C–OH to C–H")


@rule("diol_to_alkyl_halide_pi")
def _pi3(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return Result(exhaust("[CX4:1][OX2H1]>>[C:1]I", s), why="PI3 (excess) replaces every OH by I")


@rule("diol_to_carboxylic_acid_kmno")
def _diol_cleave(s):
    _need(s, "[CX4]([OX2H1])[CX4][OX2H1]", "vicinal diol")
    p = _periodate(s).product
    parts = [exhaust("[CX3H1:1]=[O:2]>>[C:1](=[O:2])O", x) if _has(x, "[CX3H1]=O") else
             ("O=C=O" if x == "C=O" else x) for x in p.split(".")]
    return Result(canon(".".join(parts)), why="hot KMnO4 cleaves the diol; aldehydes go on to acids")


@rule("diol_to_ester_conchno")
def _nitrate_ester(s):
    _need(s, "[CX4][OX2H1]", "C–OH")
    return Result(exhaust("[CX4:1][OX2H1:2]>>[C:1][O:2][N+](=O)[O-]", s),
                  why="conc. HNO3/H2SO4 esterifies every OH (glycerol → nitroglycerin)")


@rule("epoxide_to_alcohol_rnh", "CH3NH2")
def _epoxide_amine(s):
    _need(s, "C1OC1", "epoxide")
    return pick(run("[C:1]1O[C:2]1>>[C:1](NC)[C:2]O", s), anti_markovnikov,
                "amine (basic) opens the epoxide at the less hindered carbon (SN2)", "more_hindered_attack")


def _epoxide_acid(s, nu: str, what: str):
    _need(s, "C1OC1", "epoxide")
    prods = run(f"[C:1]1O[C:2]1>>[C:1]({nu})[C:2]O", s)
    tertiary = any(carbon_degree(atom_by_map(p, 1)) >= 3 for p in prods)
    key = markovnikov if tertiary else anti_markovnikov
    return pick(prods, key, f"{what}: X⁻ attacks the {'tertiary' if tertiary else 'less hindered'} carbon",
                "other_regioisomer")


@rule("epoxide_to_diol_ho")
def _epoxide_water(s):
    _need(s, "C1OC1", "epoxide")
    return one("[C:1]1O[C:2]1>>[C:1](O)[C:2]O", s, why="ring opening by water: 1,2-diol (anti)")


RULES["epoxide_to_epoxide_h3odiluteaci"] = _epoxide_water


@rule("epoxide_to_halohydrin_hx", "HBr (1 equiv)")
def _epoxide_hx(s):
    return _epoxide_acid(s, "Br", "HBr opens the protonated epoxide")


@rule("epoxide_to_vicinal_dihalide_hx", "HBr (excess)")
def _epoxide_2hx(s):
    _need(s, "C1OC1", "epoxide")
    return one("[C:1]1O[C:2]1>>[C:1](Br)[C:2]Br", s, why="excess HBr: both C–O become C–Br")


@rule("ether_to_alkyl_halide_conchxhihbra", "HI (1 equiv)")
def _ether_hi(s):
    _need(s, "[#6;!$(C=O)][OX2][#6;!$(C=O)]", "ether")
    if _has(s, "c[OX2][CX4]"):
        return Result(smi(run("[c:3][OX2:1][CX4:2]>>[C:2]I", s)[0]),
                      coproducts=[smi(run("[c:3][OX2:1][CX4:2]>>[c:3][O:1]", s)[0])],
                      why="aryl alkyl ether: I attacks the alkyl carbon; the phenol stays")
    prods = run("[CX4:1][OX2][CX4:2]>>[C:1]I.[C:2]O", s)
    tert = [p for p in prods if carbon_degree(atom_by_map(p, 1)) >= 3]
    key = (lambda p: carbon_degree(atom_by_map(p, 1))) if tert else (lambda p: -carbon_degree(atom_by_map(p, 1)))
    return pick(prods, key, "HI cleaves the ether: SN1 at a tertiary carbon, else SN2 at the less hindered one",
                "other_cleavage")


@rule("ether_to_ester_co")
def _ether_co(s):
    _need(s, "[CX4][OX2][CX4]", "dialkyl ether")
    return pick(run("[CX4:1][OX2:2][CX4:3]>>[C:1]C(=O)[O:2][C:3]", s), lambda p: 0,
                "CO inserts into a C–O bond (BF3)", "other_insertion")


@rule("ether_to_phenol_thermalnocat")
def _claisen(s):
    _need(s, "C=CC[OX2]c", "allyl aryl ether")
    return pick(run("[CH2:1]=[CH:2][CH2:3][OX2:4][c:5][cH:6]>>[C:3]=[C:2][C:1][c:6]:[c:5][O:4]", s), lambda p: 0,
                "Claisen rearrangement: allyl group to the ortho carbon", "other")


@rule("phenol_to_aldehyde_naoh")
def _reimer(s):
    _need(s, "c[OX2H1]", "phenol")
    prods = run("[OX2H1:9][c:1][cH:2]>>[O:9][c:1][c:2]C=O", s)
    if not prods:
        raise EngineError(f"{s}: no free ortho position")
    r = pick(prods, lambda p: 0, "Reimer–Tiemann: CHO ortho to OH (dichlorocarbene)", "other_ortho")
    para = run("[OX2H1:9][c:1]1[cH:2][cH:3][cH:4][c:5][c:6]1>>[O:9][c:1]1[c:2][c:3][c:4](C=O)[c:5][c:6]1", s)
    if para:
        r.traps["para_product"] = smi(para[0])
    return r


RULES["substituted_benzene_to_aldehyde_naoh"] = _reimer


@rule("phenol_to_aryl_halide_pclslowreact")
def _phenol_pcl5(s):
    _need(s, "c[OX2H1]", "phenol")
    return one("[c:1][OX2H1]>>[c:1]Cl", s, why="PCl5 replaces the phenolic OH (poor yield)")


@rule("phenol_to_benzene_znreductionl")
def _zn_dust(s):
    _need(s, "c[OX2H1]", "phenol")
    return Result(exhaust("[c:1][OX2H1]>>[c:1]", s), why="zinc dust removes the OH")


@rule("phenol_to_ester_rcoclacylchl", "CH3COCl")
def _phenyl_ester(s):
    _need(s, "c[OX2H1]", "phenol")
    return one("[c:1][OX2H1:2]>>[c:1][O:2]C(C)=O", s, why="O-acylation of the phenol")


@rule("phenol_to_geminal_dihalide_kso")
def _elbs(s):
    _need(s, "c[OX2H1]", "phenol")
    p = run("[OX2H1:9][c:1]1[c:2][c:3][cH:4][c:5][c:6]1>>[O:9][c:1]1[c:2][c:3][c:4](O)[c:5][c:6]1", s)
    if not p:
        raise EngineError(f"{s}: the para position is taken")
    return Result(smi(p[0]), why="Elbs persulphate oxidation: OH introduced para")


@rule("phenol_to_ketone_kmnoornacroh")
def _quinone(s):
    if canon(s) != canon("Oc1ccccc1"):
        raise EngineError("oxidation to the quinone is modelled for phenol itself")
    return Result(canon("O=C1C=CC(=O)C=C1"), why="phenol is oxidised to p-benzoquinone")


@rule("phenol_to_substituted_benzene_chndiazometh")
def _anisole(s):
    _need(s, "c[OX2H1]", "phenol")
    return one("[c:1][OX2H1:2]>>[c:1][O:2]C", s, why="O-methylation (CH2N2 or Me2SO4)")


# ── Aldehydes and ketones ────────────────────────────────────────────────────

ALD = "[CX3H1](=O)"
KET = "[#6][CX3](=O)[#6]"


@rule("aldehyde_to_acetal_roh2", "CH3OH (2 equiv)")
def _acetal(s):
    _need(s, "[CX3H1,CX3H2]=O", "CHO")
    return one("[CX3;H1,H2:1]=[O]>>[C:1](OC)OC", s, why="two ROH add to C=O (dry HCl): acetal")


@rule("aldehyde_to_alcohol_nabh")
def _nabh4_ald(s):
    _need(s, "[CX3H1,CX3H2]=O", "CHO")
    return Result(exhaust("[CX3;H1,H2:1]=[O:2]>>[C:1][O:2]", s), why="NaBH4 reduces CHO to CH2OH (C=C untouched)")


@rule("aldehyde_to_aldehyde_naohdilute51")
def _aldol(s):
    _need(s, "[CX4;!H0][CX3H1]=O", "α-H aldehyde")
    a = canon(s)
    prods = run("[C;!H0:1][CH2:2][CX3H1:3]=[O:4].[CX3H1:5](=[O:6])[CH2:7][C:8]>>[C:1][CH2:2][CH1:3]=[C:7]([C:8])[CH1:5]=[O:6]",
                a, a)
    if not prods:
        prods = run("[CH3:2][CX3H1:3]=[O:4].[CX3H1:5](=[O:6])[CH3:7]>>[CH3:2][CH1:3]=[CH1:7][CH1:5]=[O:6]", a, a)
    if not prods:
        raise EngineError(f"{s}: aldol condensation needs an α-CH2 or α-CH3")
    return Result(smi(prods[0]), coproducts=["O"], why="aldol condensation: β-hydroxy aldehyde dehydrates to the enal")


@rule("aldehyde_to_alkane_znhg")
def _clemmensen_ald(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=O>>[C:1]", s, why="Clemmensen reduction: C=O → CH2")


@rule("aldehyde_to_amine_h2ptornabh3c", "NH3")
def _reductive_amination(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=O>>[C:1]N", s, why="reductive amination with NH3: primary amine")


@rule("aldehyde_to_carboxylic_acid_kmnoortollen")
def _tollens(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=[O:2]>>[C:1](=[O:2])O", s, why="Tollens'/KMnO4 oxidise CHO to COOH")


@rule("aldehyde_to_cyanohydrin_hcn")
def _cyanohydrin_ald(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=[O:2]>>[C:1]([O:2])C#N", s, why="HCN adds to C=O")


@rule("aldehyde_to_diol_lahallylalco")
def _acrolein_glycerol(s):
    _need(s, "C=C[CX3H1]=O", "α,β-unsaturated aldehyde")
    t = one("[CX3H1:1]=[O:2]>>[C:1][O:2]", s).product
    return one("[C:1]=[C:2]>>[C:1](O)[C:2]O", t, why="LAH reduces C=O; cold KMnO4 then hydroxylates C=C")


@rule("aldehyde_to_geminal_dihalide_pcl5")
def _pcl5_ald(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=O>>[C:1](Cl)Cl", s, why="PCl5 replaces C=O by CCl2")


@rule("aldehyde_to_imine_rnh", "CH3NH2")
def _imine(s):
    _need(s, "[CX3H1]=O", "CHO")
    return one("[CX3H1:1]=O>>[C:1]=NC", s, why="condensation with the amine (Schiff base)")


@rule("ketone_to_alcohol_nabh")
def _nabh4_ket(s):
    _need(s, KET, "ketone")
    return Result(exhaust("[#6][CX3:1](=[O:2])[#6]>>[#6][C:1]([O:2])[#6]", s), why="NaBH4: ketone → sec-alcohol")


@rule("ketone_to_aldehyde_seo2selenium")
def _seo2(s):
    _need(s, "[CH3][CX3](=O)[#6]", "methyl ketone")
    return pick(run("[CH3:1][CX3:2](=[O:3])[#6:4]>>[CH1:1](=O)[C:2](=[O:3])[#6:4]", s), lambda p: 0,
                "SeO2 oxidises the α-CH3 to CHO", "other")


@rule("ketone_to_alkane_nhnh")
def _wolff(s):
    _need(s, KET, "ketone")
    return Result(exhaust("[#6][CX3:1](=O)[#6]>>[#6][C:1][#6]", s), why="Wolff–Kishner: C=O → CH2")


@rule("ketone_to_alkyl_halide_i2")
def _iodoform(s):
    _need(s, "[CH3][CX3](=O)[#6]", "methyl ketone")
    acid = one("[CH3][CX3:1](=[O:2])[#6:3]>>[O:2]=[C:1](O)[#6:3]", s).product
    return Result(canon("IC(I)I"), coproducts=[acid], why="iodoform test: CH3CO– gives CHI3 (yellow)")


@rule("ketone_to_carboxylic_acid_x2cl2br2ori2")
def _haloform_acid(s):
    _need(s, "[CH3][CX3](=O)[#6]", "methyl ketone")
    return one("[CH3][CX3:1](=[O:2])[#6:3]>>[O:2]=[C:1](O)[#6:3]", s,
               why="haloform reaction: the acid with one carbon fewer (plus CHX3)")


@rule("ketone_to_carbene_methylenepho")
def _wittig(s):
    _need(s, KET, "ketone")
    return one("[#6:3][CX3:1](=O)[#6:4]>>[#6:3][C:1](=C)[#6:4]", s, why="Wittig: C=O → C=CH2")


@rule("ketone_to_cyanohydrin_hcn")
def _cyanohydrin_ket(s):
    _need(s, KET, "ketone")
    return one("[#6:3][CX3:1](=[O:2])[#6:4]>>[#6:3][C:1]([O:2])(C#N)[#6:4]", s, why="HCN adds to C=O")


_MIGRATE = {3: 4, 2: 3, 1: 1, 0: 0}   # carbons on the migrating C (after it moved to O): 3° > 2° (≈ aryl, 3) > 1° > CH3


@rule("ketone_to_ester_mcpbametachl")
def _baeyer_villiger(s):
    _need(s, KET, "ketone")
    prods = run("[#6:3][CX3:1](=[O:2])[#6:4]>>[#6:3][C:1](=[O:2])O[#6:4]", s)

    def key(p):   # the group now on O is the one that migrated
        a = atom_by_map(p, 4)
        return 3 if a.GetIsAromatic() else _MIGRATE[min(3, carbon_degree(a))]
    return pick(prods, key, "Baeyer–Villiger: the better migrating group (3° > 2° ≈ aryl > 1° > CH3) moves to O",
                "wrong_migration")


@rule("ketone_to_ketone_x2", "Br2, CH3COONa")
def _alpha_halo(s):
    _need(s, "[CX4;!H0][CX3](=O)", "α-H")
    return pick(run("[CX4;!H0:1][CX3:2](=O)>>[C:1](Br)[C:2]=O", s), markovnikov,
                "acid-catalysed α-halogenation through the more substituted enol", "less_substituted_alpha")


@rule("ketone_to_oxime_nhohhcl")
def _oxime(s):
    _need(s, KET, "ketone")
    return one("[#6:3][CX3:1](=O)[#6:4]>>[#6:3][C:1](=NO)[#6:4]", s, why="NH2OH condenses with C=O: oxime")


@rule("nitrile_to_ketone_12ch3mgbr")
def _nitrile_grignard(s):
    _need(s, "[#6]C#N", "nitrile")
    return one("[#6:2][C:1]#N>>[#6:2][C:1](C)=O", s, why="CH3MgBr adds once to C≡N; hydrolysis of the imine gives the ketone")


# ── Acids and derivatives ────────────────────────────────────────────────────

COOH = "[CX3](=O)[OX2H1]"


def _one_cooh(s):
    if len(mol(s).GetSubstructMatches(Chem.MolFromSmarts(COOH))) != 1:
        raise EngineError(f"{s}: modelled for one COOH")


@rule("acid_chloride_to_alcohol_1lialh4lithi")
def _lah_cocl(s):
    _need(s, "C(=O)Cl", "COCl")
    return one("[C:1](=O)Cl>>[C:1]O", s, why="LiAlH4 reduces COCl to CH2OH")


@rule("acid_chloride_to_amine_nan3h3o")
def _curtius(s):
    _need(s, "[#6]C(=O)Cl", "COCl")
    return one("[#6:2]C(=O)Cl>>[#6:2]N", s, why="Curtius: acyl azide → isocyanate → amine (one carbon fewer)")


@rule("acid_chloride_to_ketone_dimethylcupr")
def _gilman(s):
    _need(s, "C(=O)Cl", "COCl")
    return one("[C:1](=[O:2])Cl>>[C:1](=[O:2])C", s, why="Gilman reagent stops at the ketone")


@rule("carboxylic_acid_to_acid_chloride_socl")
def _acid_socl2(s):
    _need(s, COOH, "COOH")
    return Result(exhaust("[CX3:1](=[O:2])[OX2H1]>>[C:1](=[O:2])Cl", s), why="SOCl2: COOH → COCl")


@rule("carboxylic_acid_to_alcohol_lialh")
def _lah_acid(s):
    _need(s, COOH, "COOH")
    return Result(exhaust("[CX3:1](=O)[OX2H1:2]>>[C:1][O:2]", s), why="LiAlH4: COOH → CH2OH")


@rule("carboxylic_acid_to_alkane_naoh")
def _decarboxylate(s):
    _one_cooh(s)
    _need(s, "[CX4]C(=O)[OX2H1]", "aliphatic COOH")
    return one("[CX4:1]C(=O)[OX2H1]>>[C:1]", s, why="soda lime: decarboxylation, one carbon fewer")


@rule("carboxylic_acid_to_benzene_naoh")
def _decarboxylate_ar(s):
    _one_cooh(s)
    _need(s, "cC(=O)[OX2H1]", "aromatic COOH")
    return one("[c:1]C(=O)[OX2H1]>>[c:1]", s, why="soda lime: Ar–COOH → Ar–H")


@rule("carboxylic_acid_to_alkyl_halide_agohtomakeag")
def _hunsdiecker(s):
    _one_cooh(s)
    _need(s, "[CX4]C(=O)[OX2H1]", "aliphatic COOH")
    return one("[CX4:1]C(=O)[OX2H1]>>[C:1]Br", s, why="Hunsdiecker: RCOOAg + Br2 → RBr (one carbon fewer)")


@rule("carboxylic_acid_to_amide_nh")
def _amide(s):
    _need(s, COOH, "COOH")
    return one("[CX3:1](=[O:2])[OX2H1]>>[C:1](=[O:2])N", s, why="ammonium salt dehydrates on heating: amide")


@rule("carboxylic_acid_to_amine_hn3h2so4")
def _schmidt(s):
    _one_cooh(s)
    _need(s, "[#6]C(=O)[OX2H1]", "COOH")
    return one("[#6:1]C(=O)[OX2H1]>>[#6:1]N", s, why="Schmidt: RCOOH + HN3 → RNH2 (one carbon fewer)")


@rule("carboxylic_acid_to_anhydride_hso")
def _cyclic_anhydride(s):
    p = run("[OX2H1]-[C:1](=[O:2])[#6:3]~[#6:4][C:5](=[O:6])-[OX2H1]>>[C:1]1(=[O:2])[#6:3]~[#6:4][C:5](=[O:6])O1", s) or \
        run("[OX2H1]-[C:1](=[O:2])[#6:3][#6:7][#6:4][C:5](=[O:6])-[OX2H1]>>[C:1]1(=[O:2])[#6:3][#6:7][#6:4][C:5](=[O:6])O1", s)
    if not p:
        raise EngineError(f"{s}: a cyclic anhydride needs a 1,4- or 1,5-dicarboxylic acid")
    return Result(smi(p[0]), coproducts=["O"], why="heating a 1,4/1,5-diacid closes the 5/6-membered anhydride")


@rule("carboxylic_acid_to_carboxylic_acid_x", "Br2, red P")
def _hvz(s):
    _need(s, "[CX4;!H0]C(=O)[OX2H1]", "α-H")
    return one("[CX4;!H0:1][C:2](=[O:3])[OX2H1:4]>>[C:1](Br)[C:2](=[O:3])[O:4]", s, why="HVZ: α-bromination")


@rule("carboxylic_acid_to_ester_roh", "CH3OH")
def _fischer(s):
    _need(s, COOH, "COOH")
    return one("[CX3:1](=[O:2])[OX2H1]>>[C:1](=[O:2])OC", s, why="Fischer esterification")


@rule("anhydride_to_alkane_1lialh4exces")
def _lah_anhydride(s):
    _need(s, "C(=O)OC(=O)", "anhydride")
    rxn = Chem.AllChem.ReactionFromSmarts("[C:1](=O)[O:3][C:2](=O)>>([C:1]O.[C:2][O:3])")
    prods = rxn.RunReactants((mol(s),))
    out = Chem.Mol(prods[0][0])
    Chem.SanitizeMol(out)
    return Result(canon(Chem.MolToSmiles(out)), why="excess LiAlH4 reduces both acyl groups to CH2OH")


@rule("amide_to_amine_lah")
def _lah_amide(s):
    _need(s, "C(=O)N", "amide")
    return Result(exhaust("[C:1](=O)[NX3:2]>>[C:1][N:2]", s), why="LiAlH4: C=O of the amide → CH2 (amine, same carbons)")


RULES["lactam_to_amine_lah"] = _lah_amide


@rule("ester_to_acid_chloride_pcl5")
def _ester_pcl5(s):
    _need(s, "[#6]C(=O)O[CX4]", "alkyl ester")
    rxn = Chem.AllChem.ReactionFromSmarts("[C:1](=[O:2])[O][CX4:3]>>([C:1](=[O:2])Cl.[C:3]Cl)")
    out = Chem.Mol(rxn.RunReactants((mol(s),))[0][0])
    Chem.SanitizeMol(out)
    parts = canon(Chem.MolToSmiles(out)).split(".")
    acyl = [x for x in parts if _has(x, "C(=O)Cl")]
    return Result(acyl[0], coproducts=[x for x in parts if x not in acyl], why="PCl5 splits the ester: RCOCl + R'Cl")


@rule("ester_to_aldehyde_dibalhdiisob")
def _dibal_ester(s):
    _need(s, "[#6]C(=O)O[#6]", "ester")
    return pick(run("[#6:4][C:1](=[O:2])[O][#6:3]>>[#6:4][C:1]=[O:2]", s), lambda p: 0,
                "DIBAL-H at -78 °C stops at the aldehyde", "other")


def _hydrolyse_ester(s):
    _need(s, "[#6]C(=O)O[#6]", "ester")
    rxn = Chem.AllChem.ReactionFromSmarts("[#6:4][C:1](=[O:2])[O:5][#6:3]>>([#6:4][C:1](=[O:2])O.[#6:3][O:5])")
    out = Chem.Mol(rxn.RunReactants((mol(s),))[0][0])
    Chem.SanitizeMol(out)
    parts = canon(Chem.MolToSmiles(out)).split(".")
    acid = [x for x in parts if _has(x, COOH)][0]
    return Result(acid, coproducts=[x for x in parts if x != acid], why="hydrolysis: acid + alcohol (phenol)")


RULES["ester_to_carboxylic_acid_h3odiluteaci"] = _hydrolyse_ester
RULES["ester_to_ester_aqnaoh"] = _hydrolyse_ester


@rule("ester_to_ether_conchso", "CH3OH, conc. H2SO4")
def _tbu_ester(s):
    _need(s, "C(=O)O[CX4]([CH3])([CH3])[CH3]", "tert-butyl ester")
    return one("C(=O)O[CX4:1]([CH3:2])([CH3:3])[CH3:4]>>[C:1]([C:2])([C:3])([C:4])OC", s,
               why="AAL1: the tert-butyl cation leaves and is trapped by CH3OH")


@rule("ester_to_ketone_alcl")
def _fries(s):
    _need(s, "[#6]C(=O)Oc", "aryl ester")
    p = run("[#6:7][C:8](=[O:9])[O:1][c:2]1[cH:3][cH:4][cH:5][cH:6][cH:10]1>>"
            "[O:1][c:2]1[c:3][c:4][c:5]([C:8](=[O:9])[#6:7])[c:6][c:10]1", s)
    o = run("[#6:7][C:8](=[O:9])[O:1][c:2][cH:3]>>[O:1][c:2][c:3][C:8](=[O:9])[#6:7]", s)
    if not p:
        raise EngineError(f"{s}: the para position is taken")
    return Result(smi(p[0]), traps={"ortho_product (high temperature)": smi(o[0])} if o else {},
                  why="Fries rearrangement: acyl to the para position at low temperature")


@rule("carbohydrate_to_carbohydrate_ch3co2o")
def _peracetylate(s):
    _need(s, "[CX4][OX2H1]", "OH")
    return Result(exhaust("[CX4:1][OX2H1:2]>>[C:1][O:2]C(C)=O", s), why="every OH is acetylated")


# ── Aromatics ────────────────────────────────────────────────────────────────

@rule("benzene_to_alcohol_oxirane")
def _bz_oxirane(s):
    if canon(s) != "c1ccccc1":
        raise EngineError("modelled for benzene")
    return Result(canon("OCCc1ccccc1"), why="oxirane/AlCl3: 2-phenylethanol")


@rule("benzene_to_aldehyde_co")
def _gattermann_koch(s):
    return eas(s, "C=O", "Gattermann–Koch formylation")


@rule("benzene_to_alkyl_halide_3cl2")
def _bhc(s):
    if canon(s) != "c1ccccc1":
        raise EngineError("modelled for benzene")
    return Result(canon("ClC1C(Cl)C(Cl)C(Cl)C(Cl)C1Cl"), why="radical addition of 3 Cl2: BHC")


@rule("benzene_to_aryl_halide_x", "Br2, FeBr3")
def _brominate(s):
    return eas(s, "Br", "bromination")


@rule("benzene_to_carboxylic_acid_fuminghsoole")
def _sulfonate(s):
    return eas(s, "S(=O)(=O)O", "sulphonation")


@rule("benzene_to_ketone_rcocl", "CH3COCl, AlCl3")
def _fc_acyl(s):
    _no(s, "[$([N+](=O)[O-]),$(c[NX3])]", "Friedel–Crafts fails on deactivated rings and anilines")
    return eas(s, "C(C)=O", "Friedel–Crafts acylation")


@rule("benzene_to_phenol_feso")
def _fenton(s):
    if canon(s) != "c1ccccc1":
        raise EngineError("modelled for benzene")
    return Result(canon("Oc1ccccc1"), why="Fenton's reagent hydroxylates benzene")


@rule("benzene_to_substituted_benzene_conchno")
def _nitrate(s):
    return eas(s, "[N+](=O)[O-]", "nitration")


RULES["substituted_benzene_to_substituted_benzene_conchno3"] = _nitrate


@rule("substituted_benzene_to_ketone_oradicalinit")
def _cumene(s):
    if canon(s) != canon("CC(C)c1ccccc1"):
        raise EngineError("the cumene process starts from cumene")
    return Result(canon("CC(C)=O"), coproducts=[canon("Oc1ccccc1")], why="cumene hydroperoxide → phenol + acetone")


@rule("aryl_halide_to_grignard_mgmagnesiumm")
def _ar_grignard(s):
    _need(s, "c[Br,I]", "Ar–Br or Ar–I")
    _no(s, "[N+](=O)[O-]", "a nitro group destroys the Grignard reagent")
    return one("[c:1][Br,I:2]>>[c:1][Mg][*:2]", s, why="Mg in dry ether: aryl Grignard")


@rule("aryl_halide_to_phenol_naoh")
def _dow(s):
    _need(s, "c[Cl,Br]", "Ar–X")
    return one("[c:1][Cl,Br]>>[c:1]O", s, why="Dow process: NaOH, 623 K, 300 atm, then H+")


@rule("aryl_halide_to_substituted_benzene_naome", "NaOCH3")
def _snar(s):
    _need(s, "c[Cl,Br,F]", "Ar–X")
    act = "[$(c1([Cl,Br,F])ccc([N+](=O)[O-])cc1),$(c1([Cl,Br,F])c([N+](=O)[O-])cccc1)]"
    _need(s, act, "nitro group ortho/para to X (SNAr needs it)")
    return one("[c:1][Cl,Br,F]>>[c:1]OC", s, why="SNAr: addition–elimination, activated by o/p NO2")


@rule("aniline_to_diazonium_salt_nano2hclat05")
def _diazotise(s):
    _need(s, "c[NX3H2]", "ArNH2")
    return one("[c:1][NX3H2]>>[c:1][N+]#N", s, why="NaNO2/HCl at 0–5 °C: diazonium salt")


@rule("aniline_to_ketone_kmno4heatorh")
def _aniline_quinone(s):
    if canon(s) != canon("Nc1ccccc1"):
        raise EngineError("modelled for aniline itself")
    return Result(canon("O=C1C=CC(=O)C=C1"), why="aniline is oxidised to p-benzoquinone")


@rule("aniline_to_substituted_benzene_carosacidh2s")
def _caro(s):
    _need(s, "c[NX3H2]", "ArNH2")
    return one("[c:1][NX3H2]>>[c:1]N=O", s, why="Caro's acid oxidises ArNH2 to ArN=O")


DIAZO = "c[N+]#N"


def _diazo(s, group: str, why: str) -> Result:
    _need(s, DIAZO, "ArN2+")
    main = [x for x in canon(s).split(".") if _has(x, DIAZO)][0]
    return one(f"[c:1][N+]#N>>[c:1]{group}", main, why=why)


@rule("diazonium_salt_to_aryl_halide_cuxsandmeyer", "CuCl/HCl")
def _sandmeyer(s):
    return _diazo(s, "Cl", "Sandmeyer: CuCl gives ArCl")


@rule("diazonium_salt_to_azo_compound_arohorarnhco", "phenol (alkaline)")
def _couple(s):
    _need(s, DIAZO, "ArN2+")
    main = [x for x in canon(s).split(".") if _has(x, DIAZO)][0]
    p = run("[c:1][N+]#N.[OH:2][c:3]1[cH:4][cH:5][cH:6][cH:7][cH:8]1>>[c:1]/N=N/[c:6]1[c:5][c:4][c:3]([O:2])[c:8][c:7]1",
            main, "Oc1ccccc1")
    return Result(smi(p[0]), why="azo coupling para to the phenolic OH")


@rule("diazonium_salt_to_nitrile_nacn")
def _sandmeyer_cn(s):
    return _diazo(s, "C#N", "CuCN: ArCN")


@rule("diazonium_salt_to_phenol_ho")
def _diazo_phenol(s):
    return _diazo(s, "O", "warming with water: phenol + N2")


@rule("diazonium_salt_to_substituted_benzene_hpo")
def _deaminate(s):
    return _diazo(s, "", "H3PO2 replaces N2+ by H")


@rule("naphthalene_to_anhydride_o2")
def _phthalic(s):
    if canon(s) != canon("c1ccc2ccccc2c1"):
        raise EngineError("modelled for naphthalene")
    return Result(canon("O=C1OC(=O)c2ccccc21"), why="V2O5 air oxidation: phthalic anhydride")


@rule("naphthalene_to_naphthalene_conch2so4")
def _naph_sulfonate(s):
    if canon(s) != canon("c1ccc2ccccc2c1"):
        raise EngineError("modelled for naphthalene")
    return Result(canon("O=S(=O)(O)c1cccc2ccccc12"),
                  traps={"2-sulphonic acid (160 °C, thermodynamic)": canon("O=S(=O)(O)c1ccc2ccccc2c1")},
                  why="sulphonation at ≤ 80–110 °C: kinetic 1-substitution")


@rule("nitro_compound_to_azo_compound_znnaoh1mol")
def _azobenzene(s):
    _need(s, "c[N+](=O)[O-]", "ArNO2")
    a = canon(s)
    p = run("[c:1][N+](=O)[O-].[c:2][N+](=O)[O-]>>[c:1]/N=N/[c:2]", a, a)
    return Result(smi(p[0]), why="Zn/NaOH: bimolecular reduction to the azo compound")


@rule("nitro_compound_to_aniline_znnaoh2molor")
def _sn_hcl(s):
    _need(s, "c[N+](=O)[O-]", "ArNO2")
    return Result(exhaust("[c:1][N+](=O)[O-]>>[c:1]N", s), why="Sn/HCl reduces ArNO2 to ArNH2")


# ── Amines ───────────────────────────────────────────────────────────────────

PRIM = "[CX4][NX3H2]"


@rule("amine_to_alcohol_nano")
def _hono(s):
    _need(s, PRIM, "primary aliphatic NH2")
    return one("[CX4:1][NX3H2]>>[C:1]O", s, why="HNO2: RNH2 → ROH + N2 (no rearrangement assumed)")


@rule("amine_to_amide_rcocl", "CH3COCl")
def _acetylate_amine(s):
    _need(s, "[CX4][NX3;H2,H1]", "N–H")
    return one("[CX4:1][NX3;H2,H1:2]>>[C:1][N:2]C(C)=O", s, why="acylation of the amine N–H")


@rule("amine_to_imine_rcho", "benzaldehyde")
def _amine_imine(s):
    _need(s, PRIM, "primary NH2")
    p = run("[CX4:1][NX3H2:2].[CX3H1:3](=O)[c:4]>>[C:1][N:2]=[C:3][c:4]", s, "O=Cc1ccccc1")
    return Result(smi(p[0]), why="condensation with benzaldehyde (Schiff base)")


@rule("amine_to_nitro_compound_kmno4")
def _tert_amine_oxidation(s):
    _need(s, "[CX4]([#6])([#6])([#6])[NX3H2]", "NH2 on a tertiary carbon")
    return one("[CX4:1][NX3H2]>>[C:1][N+](=O)[O-]", s, why="KMnO4 oxidises a tert-alkyl NH2 to NO2")


@rule("amine_to_isocyanide_carbylaminetest")
def _carbylamine(s):
    _need(s, "[#6][NX3H2]", "primary NH2")
    return one("[#6:1][NX3H2]>>[#6:1][N+]#[C-]", s, why="carbylamine reaction: 1° amines only")


@rule("isocyanide_to_amine_hydrolysis")
def _isocyanide_hydrolysis(s):
    _need(s, "[N+]#[C-]", "isocyanide")
    return one("[#6:1][N+]#[C-]>>[#6:1]NC", s, why="acid hydrolysis: secondary N-methyl amine + HCOOH")


@rule("nitrile_to_aldehyde_dibalhdiisob")
def _dibal_nitrile(s):
    _need(s, "[#6]C#N", "nitrile")
    return one("[#6:2][C:1]#N>>[#6:2][C:1]=O", s, why="DIBAL-H then hydrolysis: aldehyde")


@rule("nitrile_to_amine_h")
def _nitrile_reduce(s):
    _need(s, "[#6]C#N", "nitrile")
    return one("[#6:2][C:1]#N>>[#6:2][C:1]N", s, why="H2/Ni: RCH2NH2")


@rule("nitrile_to_carboxylic_acid_ho")
def _nitrile_hydrolysis(s):
    _need(s, "[#6]C#N", "nitrile")
    return one("[#6:2][C:1]#N>>[#6:2][C:1](=O)O", s, why="complete hydrolysis to the acid")


@rule("grignard_to_alcohol_hcho")
def _grignard_hcho(s):
    _need(s, "[#6][Mg]", "C–Mg")
    return one("[#6:1][Mg][Br,Cl,I]>>[#6:1]CO", s, why="RMgX + HCHO: primary alcohol, one carbon more")


@rule("grignard_to_carboxylic_acid_co")
def _grignard_co2(s):
    _need(s, "[#6][Mg]", "C–Mg")
    return one("[#6:1][Mg][Br,Cl,I]>>[#6:1]C(=O)O", s, why="RMgX + CO2 then H3O+: RCOOH")


@rule("substituted_benzene_to_carboxylic_acid_1naoh")
def _kolbe(s):
    _need(s, "c[OX2H1]", "phenol")
    p = run("[OX2H1:9][c:1][cH:2]>>[O:9][c:1][c:2]C(=O)O", s)
    if not p:
        raise EngineError(f"{s}: no free ortho position")
    return pick(p, lambda q: 0, "Kolbe: CO2 enters ortho to O⁻ (salicylic acid)", "other_ortho")


def apply(edge: dict, smiles: str) -> Result:
    """Run the edge's rule on the molecule and check the product is in the edge's end node; EngineError if the
    edge has no rule (concept or suspect), does not apply, or leads outside its end node (Clemmensen on
    benzaldehyde gives toluene, not an alkane: that molecule is not used for that edge)."""
    from core.engine.organic.mol import classes
    fn = RULES.get(edge["id"])
    if fn is None:
        raise EngineError(f"{edge['id']} has no rule (concept or suspect edge)")
    r = fn(smiles)
    if edge["to"] not in classes(r.product):
        raise EngineError(f"{edge['id']}: {smiles} gives {r.product}, which is not a {edge['to']}")
    return r



# ── edges fixed on 2026-11-20 (user-approved, docs/organic_suspect_edges.md) ──

@rule("aldehyde_to_substituted_benzene_naohaqueouss")
def _cannizzaro(s):
    _need(s, "[CX3H1,CX3H2]=O", "CHO")
    if not (_has(s, "[CX3H2]=O") or _has(s, "c[CX3H1]=O") or _has(s, "[CX4;H0]([#6])([#6])([#6])[CX3H1]=O")):
        raise EngineError(f"{s}: Cannizzaro is modelled for HCHO, aromatic aldehydes and R3C–CHO (no α-H)")
    alcohol = one("[CX3;H1,H2:1]=[O:2]>>[C:1][O:2]", s).product
    acid = one("[CX3;H1,H2:1]=[O:2]>>[C:1](=[O:2])O", s).product
    r = Result(alcohol, coproducts=[acid], why="Cannizzaro: no α-H, so the aldehyde disproportionates")
    r.traps = {"carboxylic acid (the other half)": acid}
    return r


@rule("vicinal_dihalide_to_alkyne_zndeltaexces")
def _zn_dehalogenate(s):
    _need(s, "[Cl,Br,I][CX4][CX4][Cl,Br,I]", "vicinal dihalide")
    return one("[Cl,Br,I][CX4:1][CX4:2][Cl,Br,I]>>[C:1]=[C:2]", s, why="Zn removes both halogens: the alkene")


@rule("diazonium_salt_to_naphthalene_alkalinecoup")
def _naphthol_couple(s):
    _need(s, DIAZO, "ArN2+")
    main = [x for x in canon(s).split(".") if _has(x, DIAZO)][0]
    p = run("[c:1][N+]#N.[OH:2][c:3]1[cH:4][cH:10][c:11]2[cH:5][cH:6][cH:7][cH:8][c:9]2[cH:12]1>>"
            "[c:1]/N=N/[c:12]1[c:3]([O:2])[c:4][c:10][c:11]2[c:5][c:6][c:7][c:8][c:9]21", main, "Oc1ccc2ccccc2c1")
    if not p:
        raise EngineError("coupling with 2-naphthol failed")
    return Result(smi(p[0]), why="coupling at C-1 of 2-naphthol (alkaline): an orange-red azo dye")


@rule("diol_to_diol_2eqchcooh")
def _diacetate(s):
    _need(s, "[CX4][OX2H1]", "OH")
    return Result(exhaust("[CX4:1][OX2H1:2]>>[C:1][O:2]C(C)=O", s), why="every OH is acetylated (diester)")


@rule("ketone_to_ether_roh", "CH3OH (excess), dry HCl")
def _ketal(s):
    _need(s, KET, "ketone")
    return one("[#6:3][CX3:1](=O)[#6:4]>>[#6:3][C:1](OC)(OC)[#6:4]", s, why="two CH3OH add to C=O: the ketal")


@rule("ketone_to_lactone_diazomethane")
def _ring_expand(s):
    _need(s, "[#6;R][CX3;R](=O)[CH2;R]", "cyclic ketone with an α-CH2")
    prods = run("[#6;R:3][CX3;R:1](=[O:2])[CH2;R:4]>>[#6:3][C:1](=[O:2])C[C:4]", s)
    return pick(prods, lambda p: 0, "CH2N2 inserts CH2 next to C=O: the ring grows by one", "other_insertion")


@rule("diol_to_aldehyde_cu")
def _cu_dehydrogenate(s):
    _need(s, P_OH, "primary OH")
    return one("[CX4;H2:1]([#6:2])[OX2H1]>>[C:1](=O)[#6:2]", s, why="Cu/573 K dehydrogenates a 1° alcohol to the aldehyde")


@rule("substituted_benzene_to_phenol_1conch2so4de")
def _picric(s):
    if canon(s) != canon("Oc1ccccc1"):
        raise EngineError("picric acid is made from phenol itself")
    return Result(canon("O=[N+]([O-])c1cc([N+](=O)[O-])c(O)c([N+](=O)[O-])c1"),
                  traps={"mononitration only": canon("O=[N+]([O-])c1ccc(O)cc1")},
                  why="sulphonation then nitration: 2,4,6-trinitrophenol (picric acid)")


@rule("alcohol_to_amine_al2o3450c")
def _ammonolysis_alcohol(s):
    _need(s, P_OH, "primary OH")
    return one("[CX4;H2:1][OX2H1]>>[C:1]N", s, why="NH3 over Al2O3: the primary amine")


@rule("amine_to_amine_heatsn2", "CH3I (excess)")
def _quaternise(s):
    _need(s, "[NX3;!$(NC=O)]([CX4])", "aliphatic amine")
    cur = canon(s)
    while True:
        p = run("[NX3;!$(NC=O);!H0:1]>>[N:1]C", cur)
        if not p:
            break
        cur = smi(p[0])
    p = run("[NX3;H0;!$(NC=O):1]>>[N+:1]C", cur)
    if not p:
        raise EngineError(f"{s}: nothing to quaternise")
    return Result(smi(p[0]), coproducts=["[I-]"], why="exhaustive methylation: quaternary ammonium iodide")


@rule("substituted_benzene_to_anhydride_seecondition")
def _oxylene(s):
    if canon(s) != canon("Cc1ccccc1C"):
        raise EngineError("modelled for o-xylene")
    return Result(canon("O=C1OC(=O)c2ccccc21"), why="V2O5/air oxidises o-xylene to phthalic anhydride")
