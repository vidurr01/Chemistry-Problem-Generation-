"""
org_start.py — choosing the STARTING MOLECULE of an organic scheme (the author, 2026-11-23).

    pick_start   one call to models.START_PICKER: invent a rich starting molecule (name + SMILES)
    check_start  the engine checks it: real and single, properties computable, at least two functional groups the
                 rules can act on, and a branched 4-6 step scheme can be built from it
    name check   a different model (models.NAME_CHECKER) turns the NAME back into a structure without seeing the
                 SMILES; the two must agree (the student only ever reads the name)
On a failed check the picker is told why and asked again (PICK_TRIES in all). No real exam question is shown to
the picker: novelty is the point, JEE is only the yardstick (tools/start_batch.py compares features).
"""

from __future__ import annotations

import random

from rdkit import Chem

from core import models
from core.engine.base import EngineError
from core.engine.organic import props as OP
from core.engine.organic import rules as R
from core.engine.organic import scope
from core.engine.organic.labels import REAGENT_LABEL
from core.engine.organic.mol import canon, classes

PICK_TRIES = 3
HEAVY_MIN, HEAVY_MAX = 5, 22
DRAW_ATTEMPTS = 300
FEATURE_GROUPS = ["aldehyde", "ketone", "carboxylic_acid", "ester", "acid_chloride", "anhydride", "amide", "nitrile",
                  "epoxide", "nitro", "alkene", "alkyne", "alcohol", "phenol", "amine_any", "alkyl_halide",
                  "alkoxy_aryl"]


def features(smiles: str) -> dict:
    """Size and richness of a molecule (the same measure for picks and for the JEE yardstick)."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        raise EngineError(f"not a molecule: {smiles}")
    s = Chem.MolToSmiles(m)
    return {"heavy": m.GetNumHeavyAtoms(), "rings": m.GetRingInfo().NumRings(),
            "aromatic": any(a.GetIsAromatic() for a in m.GetAtoms()),
            "groups": [g for g in FEATURE_GROUPS if scope.has(s, g)],
            "stereocentres": len(Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False))}


def _reaction_menu(graph, avoid=()) -> str:
    """What the engine can do, per functional group (node): the reagents as a question prints them. avoid: edge ids
    used up (overused_edges), left out so the picker does not build on reagents no scheme may use."""
    lines = []
    for node in sorted(graph["out"]):
        labs = sorted({REAGENT_LABEL[e["id"]] for e in graph["out"][node]
                       if e["id"] in REAGENT_LABEL and e["id"] not in avoid})
        if labs:
            lines.append(f"- {node}: " + "; ".join(labs))
    return "\n".join(lines)


def check_start(adapter, smiles: str, rng=None) -> tuple:
    """(ok, reason, stats). ok means the molecule can start a branched 4-6 step scheme with two or more groups the
    rules act on; stats always carries what was found (for the log and the batch report)."""
    from core.pipeline import org_qfirst as O
    rng = rng or random.Random(0)
    if not smiles:
        return False, "no SMILES given", {}
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return False, "the SMILES does not parse", {}
    if "." in smiles:
        return False, "one molecule only (no salts or mixtures)", {}
    nitro = {i for match in m.GetSubstructMatches(Chem.MolFromSmarts("[N+](=O)[O-]")) for i in match}
    if any(a.GetFormalCharge() and a.GetIdx() not in nitro for a in m.GetAtoms()):
        return False, "a neutral molecule only", {}
    smi = canon(smiles)
    st = features(smi)
    if not HEAVY_MIN <= st["heavy"] <= HEAVY_MAX:
        return False, f"{st['heavy']} heavy atoms: use {HEAVY_MIN}-{HEAVY_MAX}", st
    close = close_groups(smi)
    if close:
        return False, ("groups that can react with each other: " + "; ".join(close) + f". Keep every OH, NH2 or "
                       f"COOH at least {CLOSE_BONDS + 1} bonds from any C=O, ester, C–X, epoxide, C=C or C≡N "
                       f"(meta / para across a benzene ring is fine; an o-hydroxy aryl carbonyl and a 1,4-diacid "
                       f"are fine)"), st
    try:
        OP.askable(smi)
    except EngineError as e:
        return False, f"its properties cannot be computed ({e})", st
    g = O._graph(adapter)
    used_up = O.overused_edges(adapter)   # batch 2026-11-26: starts whose only reactions were used up built no scheme
    first, nodes_used = [], set()
    for n in sorted(classes(smi)):
        for e in g["out"].get(n, []):
            if e["id"] in used_up:
                continue
            try:
                r = R.apply(e, smi)
            except EngineError:
                continue
            if "." not in r.product:
                first.append(e["id"])
                nodes_used.add(n)
    st.update(classes=sorted(classes(smi)), first_steps=len(set(first)), groups_reacting=sorted(nodes_used))
    if len(nodes_used) < 2:
        return False, (f"the engine's reagents act on only {len(nodes_used)} of its groups "
                       f"({', '.join(nodes_used) or 'none'}): give two or more groups that the listed reagents attack"), st
    cand = O.draw(adapter, rng, start=("start", smi), attempts=DRAW_ATTEMPTS)
    if cand is None:
        return False, "no branched 4-6 step scheme can be built from it with the listed reagents", st
    st["scheme_steps"] = len(cand["_order"]) - 1
    st["selectivity_steps"] = sum(1 for k in cand["_order"][1:] if cand["_comps"][k]["result"].traps)
    return True, "", st


def _same(a: str, b: str) -> bool:
    try:
        stereo = "@" in a or "/" in a or "\\" in a
        return canon(a, stereo=stereo) == canon(b, stereo=stereo)
    except EngineError:
        return False


def name_matches(name: str, smiles: str) -> tuple:
    """(ok, the checker's SMILES): a different model turns the name into a structure without seeing ours."""
    try:
        d = models.ask_json("name_checker", models.NAME_CHECKER,
                            "You convert IUPAC names to SMILES. Output JSON only.",
                            f'Give the SMILES of this compound, with stereochemistry if the name states it.\nName: {name}\n'
                            'Return JSON: {"smiles": "..."}', temperature=0.0, max_tokens=3000)
    except Exception as e:  # noqa: BLE001  (a failed check is a failed pick, never a crash)
        return False, f"(name check failed: {str(e)[:80]})"
    theirs = str(d.get("smiles") or "")
    return _same(smiles, theirs), theirs


# Groups that react WITH EACH OTHER (the author, 2026-11-24, after runs 12-14: almost every held scheme came from
# two groups of the start interacting: an o-allyl phenol cyclising under Hg2+, a cyanohydrin reverting, a
# β-bromoamine closing an aziridine). A nucleophile within CLOSE_BONDS bonds of an electrophile can react with it
# or close a 3- to 6-membered ring, which the one-group rules cannot model. Allowed: pairs across a benzene ring
# (meta / para cannot close a ring) and the motifs the engine handles on purpose.
CLOSE_BONDS = 5
_NUC = {"OH": "[CX4][OX2H1:1]", "phenol OH": "c[OX2H1:1]", "NH": "[NX3;H2,H1;!$(NC=O);!$(N-[N,O]):1]",
        "COOH": "[CX3](=O)[OX2H1:1]"}
_ELEC = {"C=O": "[CX3;$([CX3H1](=O)[#6]),$([CX3]([#6])(=O)[#6]):1]=O", "ester": "[CX3:1](=O)[OX2][#6]",
         "COCl": "[CX3:1](=O)Cl", "C≡N": "[CX2:1]#N", "C–X": "[CX4:1][Cl,Br,I]", "epoxide": "[C:1]1OC1",
         "C=C": "[CX3;!a:1]=[CX3;!a]"}           # (C≡C only reacts with an OH under Hg2+: run 10's good start had one)
_ALLOWED = ["OC(=O)[#6]~[#6]C(=O)O",                     # 1,4-diacid / phthalic acid: the cyclic anhydride edge
            "[OX2H1]c:c[CX3]=O", "[NX3H2]c:c[CX3]=O",    # o-hydroxy / o-amino aryl carbonyl (salicyl type)
            "[OX2H1]C(=O)C=C"]                            # α,β-unsaturated acid: its own conjugated system (cinnamic)


def _mapped(m, smarts: str) -> set:
    patt = Chem.MolFromSmarts(smarts)
    idx = next(a.GetIdx() for a in patt.GetAtoms() if a.GetAtomMapNum() == 1)
    return {match[idx] for match in m.GetSubstructMatches(patt)}


def close_groups(smiles: str) -> list:
    """['OH and C=C are 4 bonds apart', ...] for every nucleophile-electrophile pair that may react together."""
    m = Chem.MolFromSmiles(smiles)
    if m is None:
        return []
    allowed = [set(mt) for s in _ALLOWED for mt in m.GetSubstructMatches(Chem.MolFromSmarts(s))]
    dist = Chem.GetDistanceMatrix(m)
    out = []
    for nname, ns in _NUC.items():
        for ename, es in _ELEC.items():
            for a in _mapped(m, ns):
                for b in _mapped(m, es):
                    d = int(dist[a][b])
                    if d <= 1 or d > CLOSE_BONDS:  # 1: the same group (a COOH's own C=O)
                        continue
                    path = Chem.GetShortestPath(m, a, b)
                    if sum(m.GetAtomWithIdx(i).GetIsAromatic() for i in path) >= 3:   # meta / para on a ring
                        continue
                    if any(a in s and b in s for s in allowed):
                        continue
                    out.append(f"{nname} and {ename} are {d} bonds apart")
    return sorted(set(out))


def _canon_or_none(smi: str):
    from core.engine.organic.mol import canon
    try:
        return canon(smi)
    except Exception:  # noqa: BLE001
        return None


def _accepted_starts(adapter) -> set:
    """Canonical start SMILES of every accepted organic question (outputs file), so runs do not repeat a start."""
    import json
    import os
    p = adapter.config.get("output_file", "")
    if not p or not os.path.exists(p):
        return set()
    with open(p, encoding="utf-8") as f:
        items = json.load(f)
    out = set()
    for q in items if isinstance(items, list) else []:
        s = ((q.get("engine") or {}).get("givens") or {}).get("start")
        c = _canon_or_none(s) if s else None
        if c:
            out.add(c)
    return out


def pick_start(adapter, rng=None, avoid=(), log=None) -> dict | None:
    """{"name", "smiles", "why", "stats", "tries"} for a start the engine accepts, or None after PICK_TRIES."""
    from core.pipeline import org_qfirst as O
    rng = rng or random.Random()
    menu = _reaction_menu(O._graph(adapter), O.overused_edges(adapter))
    avoid_txt = ("\nDo not reuse any of these (already used): " + "; ".join(avoid)) if avoid else ""
    feedback = ""
    for t in range(1, PICK_TRIES + 1):
        prompt = f"""Invent ONE starting molecule for a hard multi-step organic reaction scheme (4-6 steps, with a branch:
one intermediate is treated with two different reagents). The scheme will be built ONLY from these reagents, listed
by the functional group they act on:
{menu}

What makes a starting molecule good:
- two or three DIFFERENT functional groups that the reagents above act on, so that a reagent must choose between
  them (chemoselectivity) and later steps depend on which group reacted;
- at least one of: a ring, a stereocentre, an unsymmetrical C=C or ketone (regioselectivity), two similar groups
  in different environments (1° vs 2° OH, aryl vs alkyl);
- the groups must NOT react with EACH OTHER: keep every OH, NH2 or COOH at least {CLOSE_BONDS + 1} bonds from any
  C=O, ester, C–X, epoxide, C=C or C≡N (e.g. on different arms of a ring, or meta / para on a benzene ring).
  Closer pairs cyclise or decompose in ways the scheme cannot follow. Fine on purpose: an o-hydroxy aryl
  aldehyde / ketone (salicylaldehyde type), a 1,4-diacid, an α,β-unsaturated acid, a conjugated diene, an allyl
  aryl ether;
- {HEAVY_MIN}-{HEAVY_MAX} heavy atoms; a real, stable, neutral compound with a correct IUPAC name;
- not a textbook one-group molecule (no propane, ethanol, benzene, acetone) and not copied from any exam question.{avoid_txt}
{feedback}
Return JSON: {{"name": "IUPAC name", "smiles": "SMILES", "why": "one line: which groups compete for which reagent"}}"""
        try:
            d = models.ask_json("start_picker", models.START_PICKER, "You are an organic chemist. Output JSON only.",
                                prompt, temperature=1.0, max_tokens=1500)
        except Exception as e:  # noqa: BLE001
            feedback = ""
            if log:
                log({"event": "start_pick_error", "try": t, "error": str(e)[:200]})
            continue
        name, smi = str(d.get("name") or "").strip(), str(d.get("smiles") or "").strip()
        ok, reason, st = check_start(adapter, smi, rng)
        if ok and _canon_or_none(smi) in _accepted_starts(adapter):
            # live runs 8-9 (2026-11-25): the picker reused starts of accepted questions across runs
            ok, reason = False, "an accepted question already starts from this molecule: invent a different one"
        if ok:
            same, theirs = name_matches(name, smi)
            if not same:
                ok, reason = False, f"the name '{name}' is the structure {theirs}, not {smi}: name and SMILES must agree"
        if log:
            log({"event": "start_pick", "try": t, "name": name, "smiles": smi, "ok": ok, "reason": reason,
                 "stats": st, "why": d.get("why")})
        print(f"  [start] try {t}: {name} ({smi}) → {'accepted' if ok else 'refused: ' + reason[:140]}")
        if ok:
            return {"name": name, "smiles": canon(smi), "why": d.get("why"), "stats": st, "tries": t}
        feedback = f"\nYour previous molecule {name} ({smi}) was refused: {reason}. Invent a different one."
    return None
