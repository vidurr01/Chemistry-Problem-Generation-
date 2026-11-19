"""
Molecules for the organic engine (RDKit): canonical SMILES, formulas, and which graph node a molecule belongs to.

    canon("OCC")                 'CCO'
    same("C(C)O", "CCO")         True     (answers are compared as canonical SMILES)
    formula("CCO")               'C2H6O'
    classes("CC(C)=O")           {'ketone'}   graph nodes (knowledge/reaction_graph.json) the molecule is in
"""

from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem.rdMolDescriptors import CalcMolFormula

from core.engine.base import EngineError

RDLogger.DisableLog("rdApp.*")


def mol(smiles: str):
    m = Chem.MolFromSmiles(smiles) if isinstance(smiles, str) else None
    if m is None:
        raise EngineError(f"not a valid SMILES: {smiles!r}")
    return m


def canon(smiles: str, stereo: bool = True) -> str:
    """Canonical SMILES; '.'-separated parts are sorted, so a mixture compares as a set."""
    m = mol(smiles)
    s = Chem.MolToSmiles(m, isomericSmiles=stereo)
    return ".".join(sorted(s.split(".")))


def same(a: str, b: str, stereo: bool = True) -> bool:
    try:
        return canon(a, stereo) == canon(b, stereo)
    except EngineError:
        return False


def formula(smiles: str) -> str:
    return CalcMolFormula(mol(smiles))


# one SMARTS (or several, any of which may match) per graph node; a molecule may be in several nodes
_NODE_SMARTS = {
    "alkene": ["[CX3;!a]=[CX3;!a]"],
    "alkyne": ["[CX2]#[CX2]"],
    "diene_conjugated": ["[CX3;!a]=[CX3;!a]-[CX3;!a]=[CX3;!a]"],
    "diene_isolated": ["[CX3;!a]=[CX3;!a]-[CX4]-[CX3;!a]=[CX3;!a]", "[CX3;!a]=[CX3;!a]-[CX4]-[CX4]-[CX3;!a]=[CX3;!a]"],
    "cycloalkene": ["[CX3;R;!a]=[CX3;R;!a]"],
    "substituted_benzene": ["c1ccccc1-[!#1]", "c1ccccc1[!#1]"],
    "naphthalene": ["c1ccc2ccccc2c1"],
    "aryl_halide": ["c[F,Cl,Br,I]"],
    "alkyl_halide": ["[CX4][F,Cl,Br,I]"],
    "vinyl_halide": ["[CX3;!a]=[CX3;!a][F,Cl,Br,I]"],
    "vicinal_dihalide": ["[F,Cl,Br,I][CX4][CX4][F,Cl,Br,I]"],
    "geminal_dihalide": ["[F,Cl,Br,I][CX4][F,Cl,Br,I]"],
    "alcohol": ["[CX4][OX2H1]"],
    "phenol": ["c[OX2H1]"],
    "ether": ["[#6;!$(C=O)][OX2;!R3][#6;!$(C=O)]"],
    "epoxide": ["C1OC1"],
    "diol": ["[OX2H1][#6]~[#6][OX2H1]", "[OX2H1]c1ccc([OX2H1])cc1"],
    "halohydrin": ["[F,Cl,Br,I][CX4][CX4][OX2H1]"],
    "aldehyde": ["[CX3H1](=O)[#6]", "[CX3H2]=O"],
    "ketone": ["[#6][CX3](=O)[#6]"],
    "acetal": ["[CX4]([OX2][#6])[OX2][#6]"],
    "cyanohydrin": ["[CX4]([OX2H1])C#N"],
    "carboxylic_acid": ["[CX3](=O)[OX2H1]"],
    "ester": ["[#6][CX3](=O)[OX2][#6]", "[#6][CX3](=O)[OX2]c", "[CX4][OX2][N+](=O)[O-]", "[#6][OX2]S(=O)(=O)[OH]"],
    "amide": ["[CX3](=O)[NX3]"],
    "acid_chloride": ["[CX3](=O)Cl"],
    "anhydride": ["[CX3](=O)[OX2][CX3](=O)"],
    "lactone": ["[#6;R][CX3;R](=O)[OX2;R][#6;R]"],
    "lactam": ["[#6;R][CX3;R](=O)[NX3;R][#6;R]"],
    "amine": ["[NX3;H2,H1,H0;!$(N-C=O);!$(N=*);!$(N-N);!$(N-O);!$(N-S)]([CX4])"],
    "aniline": ["c[NX3H2]"],
    "diazonium_salt": ["c[N+]#N"],
    "nitrile": ["[CX2]#[NX1]"],
    "nitro_compound": ["[#6][N+](=O)[O-]"],
    "imine": ["[CX3]=[NX2][#6,#1]", "[CX3]=[NX2H1]"],
    "oxime": ["[CX3]=[NX2][OX2H1]"],
    "hydrazone": ["[CX3]=[NX2][NX3]"],
    "isocyanate": ["N=C=O"],
    "azo_compound": ["c/N=N/c", "cN=Nc"],
    "sulfonate": ["[CX4][OX2]S(=O)(=O)[#6]", "[CX4][OX2]S(=O)(=O)[OX2H1]"],
    "grignard": ["[#6][Mg]"],
    "amino_acid": ["[NX3][CX4][CX3](=O)[OX2H1]"],
    "isocyanide": ["[#6][N+]#[C-]"],
    "polymer": ["[*:1]"],          # never matched: polymers are not molecules here (see classes)
}
_PATTERNS = {k: [Chem.MolFromSmarts(s) for s in v] for k, v in _NODE_SMARTS.items() if k != "polymer"}


def classes(smiles: str) -> set:
    """Every graph node the molecule (each part of a mixture) belongs to."""
    out = set()
    for part in canon(smiles).split("."):
        m = mol(part)
        heavy = {a.GetSymbol() for a in m.GetAtoms()}
        for node, pats in _PATTERNS.items():
            if any(m.HasSubstructMatch(p) for p in pats):
                out.add(node)
        if heavy <= {"C"}:
            ring_info = m.GetRingInfo()
            arom = any(a.GetIsAromatic() for a in m.GetAtoms())
            if part == "c1ccccc1":
                out.add("benzene")
            elif not arom and not any(b.GetBondType() != Chem.BondType.SINGLE for b in m.GetBonds()):
                out.add("cycloalkane" if ring_info.NumRings() else "alkane")
        oh = len(m.GetSubstructMatches(Chem.MolFromSmarts("[CX4][OX2H1]")))
        o_sub = len(m.GetSubstructMatches(Chem.MolFromSmarts("[CX4;!$(C(O)O)][OX2;H1,$(OC(=O)C)]")))
        if o_sub >= 3 and m.HasSubstructMatch(Chem.MolFromSmarts("[CX3H1]=O")):
            out.add("carbohydrate")      # polyhydroxy aldehyde (also its acetates)
        if oh >= 2:
            out.add("diol")
    return out
