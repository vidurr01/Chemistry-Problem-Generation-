"""
Reaction machinery for the organic rules (RDKit reaction SMARTS) and the selectivity rankings JEE asks about.

    run("[C:1]=[O:2]>>[C:1][O:2]", "CC(C)=O")      -> [ProductMol] every distinct product (one per site)
    pick(prods, key)                               -> (major, rejected): the major product by a ranking key;
                                                      a tie between different products raises EngineError
    exhaust(smarts, smiles)                        -> apply a one-site rule until no site is left

Mapped atoms keep their map number in a product as the atom property "old_mapno", so a ranking can look at the
atom that changed (markovnikov, zaitsev, ring_position).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import AllChem

from core.engine.base import EngineError
from core.engine.organic.mol import canon, mol


@dataclass
class Result:
    """What a rule returns: the product (canonical SMILES), co-products, the products the rule rejected (each a
    trap: what a student who applied the wrong selectivity would write) and a short reason."""
    product: str
    coproducts: list = field(default_factory=list)
    traps: dict = field(default_factory=dict)
    why: str = ""


@lru_cache(maxsize=None)
def _rxn(smarts: str):
    r = AllChem.ReactionFromSmarts(smarts)
    if r is None:
        raise EngineError(f"bad reaction SMARTS {smarts}")
    return r


def _clean(m):
    m = Chem.Mol(m)
    for a in m.GetAtoms():            # template atoms come out with fixed H counts ("[C]", "[Mg][Br]"): let RDKit
        if a.GetNoImplicit() and not a.GetIsAromatic() and a.GetFormalCharge() == 0                 and a.GetNumRadicalElectrons() == 0:      # recompute them, as for any parsed molecule
            a.SetNoImplicit(False)
            a.SetNumExplicitHs(0)
    try:
        Chem.SanitizeMol(m)
    except Exception:  # noqa: BLE001  (RDKit raises several types for impossible valences)
        return None
    return m


def run(smarts: str, *reactants: str) -> list:
    """Every distinct first product of the reaction (sanitised), as RDKit molecules carrying old_mapno."""
    r = _rxn(smarts)
    mols = tuple(mol(s) for s in reactants)
    seen, out = set(), []
    for prods in r.RunReactants(mols):
        p = _clean(prods[0])
        if p is None:
            continue
        s = Chem.MolToSmiles(p)
        if Chem.MolFromSmiles(s) is None or s in seen:
            continue
        seen.add(s)
        out.append(p)
    return out


def smi(m) -> str:
    return canon(Chem.MolToSmiles(m))


def one(smarts: str, *reactants: str, why: str = "") -> Result:
    """The rule has one product whatever site it acts on (symmetric or single site)."""
    prods = {smi(p) for p in run(smarts, *reactants)}
    if not prods:
        raise EngineError(f"the reaction does not apply to {reactants[0]}")
    if len(prods) > 1:
        raise EngineError(f"{reactants[0]} has several reacting sites giving different products: no single product")
    return Result(prods.pop(), why=why)


def exhaust(smarts: str, smiles: str, limit: int = 12) -> str:
    """Apply a one-site rule at every site (all OH reduced, all OH acetylated); EngineError if it never applies."""
    cur, n = canon(smiles), 0
    while n < limit:
        prods = run(smarts, cur)
        if not prods:
            break
        cur, n = smi(prods[0]), n + 1
    if n == 0:
        raise EngineError(f"the reaction does not apply to {smiles}")
    return cur


def atom_by_map(m, n: int):
    for a in m.GetAtoms():
        if a.HasProp("old_mapno") and a.GetIntProp("old_mapno") == n:
            return a
    return None


def carbon_degree(a) -> int:
    return sum(1 for nb in a.GetNeighbors() if nb.GetSymbol() == "C")


def pick(prods: list, key, what: str, trap_name: str) -> Result:
    """The product with the highest key is the major one; the others are traps named trap_name. Different
    products sharing the top key: no single major product (EngineError: the question would be ambiguous)."""
    scored = {}
    for p in prods:
        s = smi(p)
        k = key(p)
        if s not in scored or k > scored[s]:
            scored[s] = k
    if not scored:
        raise EngineError(f"{what}: the reaction does not apply")
    best = max(scored.values())
    top = [s for s, k in scored.items() if k == best]
    if len(top) > 1:
        raise EngineError(f"{what}: two products are equally favoured ({', '.join(top)}): no single major product")
    rest = sorted((s for s in scored if s != top[0]), key=lambda s: -scored[s])
    traps = {trap_name if i == 0 else f"{trap_name}_{i + 1}": s for i, s in enumerate(rest)}
    return Result(top[0], traps=traps, why=what)


# ── rankings ─────────────────────────────────────────────────────────────────

def markovnikov(p) -> int:
    """The atom mapped 1 received the nucleophile / X: the more substituted (benzylic counts) the better."""
    a = atom_by_map(p, 1)
    bonus = 1 if a is not None and any(nb.GetIsAromatic() for nb in a.GetNeighbors()) else 0
    return (carbon_degree(a) + bonus) if a is not None else -1


def anti_markovnikov(p) -> int:
    return -markovnikov(p)


def zaitsev(p) -> int:
    """The new C=C between atoms mapped 1 and 2: more carbon substituents, and conjugation, is more stable."""
    a, b = atom_by_map(p, 1), atom_by_map(p, 2)
    if a is None or b is None:
        return -1
    subs = carbon_degree(a) + carbon_degree(b) - 2
    conj = sum(1 for x in (a, b) for nb in x.GetNeighbors() if nb.GetIsAromatic())
    return subs + 2 * conj


def hofmann(p) -> int:
    return -zaitsev(p)


# ── electrophilic aromatic substitution on a monosubstituted benzene ─────────

_META = Chem.MolFromSmarts("[$([N+](=O)[O-]),$(C=O),$(C#N),$(S(=O)=O),$([N+]([#6])([#6])[#6])]")


def _director(ring_atom, ring) -> str:
    """'op' or 'm' for the substituent on ring_atom."""
    subs = [nb for nb in ring_atom.GetNeighbors() if nb.GetIdx() not in ring]
    if not subs:
        return ""
    s = subs[0]
    m = ring_atom.GetOwningMol()
    if any(s.GetIdx() == match[0] for match in m.GetSubstructMatches(_META)):
        return "m"
    return "op"


def eas(smiles: str, group: str, name: str) -> Result:
    """Introduce `group` (SMILES fragment bonded through its first atom, e.g. '[N+](=O)[O-]') on benzene or a
    monosubstituted benzene: para for an o/p director (ortho is the trap), meta for a meta director."""
    m0 = mol(smiles)
    if m0.HasSubstructMatch(Chem.MolFromSmarts("c[OX2H1,NX3;H2,H1;!$(NC=O)]")):
        # Br2 gives the 2,4,6-tribromo product, conc. HNO3 oxidises phenol and protonates aniline (much meta):
        # no single monosubstitution product, so these rings are not used here
        raise EngineError(f"{smiles}: phenols and anilines over-react under these conditions")
    prods = run(f"[cH:1]>>[c:1]{group}", smiles)
    rings = [r for r in m0.GetRingInfo().AtomRings() if len(r) == 6 and all(m0.GetAtomWithIdx(i).GetIsAromatic() for i in r)]
    if len(rings) != 1:
        raise EngineError(f"{smiles}: EAS is modelled for one benzene ring")
    ring = set(rings[0])
    subst = [i for i in ring if any(nb.GetIdx() not in ring and nb.GetAtomicNum() > 1
                                    for nb in m0.GetAtomWithIdx(i).GetNeighbors())]
    if not subst:
        return one(f"[cH:1]>>[c:1]{group}", smiles, why=f"{name} of benzene")
    if len(subst) > 1:
        raise EngineError(f"{smiles}: EAS directing is modelled for one substituent only")
    kind = _director(m0.GetAtomWithIdx(subst[0]), ring)
    dist_of = {}
    for p in prods:
        a = atom_by_map(p, 1)
        # products are renumbered: find the substituted ring atom by its reactant index (react_atom_idx)
        here = [x.GetIdx() for x in p.GetAtoms()
                if x.HasProp("react_atom_idx") and x.GetIntProp("react_atom_idx") == subst[0]]
        if not here:
            raise EngineError(f"{smiles}: lost the substituent while placing the new group")
        d = Chem.GetDistanceMatrix(p)[a.GetIdx()][here[0]]
        dist_of[smi(p)] = int(d)
    pos = {1: "ortho", 2: "meta", 3: "para"}
    by_pos = {pos[d]: s for s, d in dist_of.items() if d in pos}
    major = "para" if kind == "op" else "meta"
    if major not in by_pos:
        raise EngineError(f"{smiles}: the {major} position is blocked")
    traps = {f"{k}_product": v for k, v in by_pos.items() if k != major}
    return Result(by_pos[major], traps=traps,
                  why=f"{name}: the substituent is an {'ortho/para' if kind == 'op' else 'meta'} director; {major} major")
