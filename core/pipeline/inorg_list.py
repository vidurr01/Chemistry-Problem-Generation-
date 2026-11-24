"""
inorg_list.py: the JEE Advanced "how many species in this list" question for INORGANIC chemistry, built by code.

    "Among [Co(CO)₃(NO)], XeF₄, [PCl₄]⁺, [PdCl₄]²⁻, [Cu(CN)₄]³⁻ …, the total number of species with tetrahedral
     geometry is"

About nine in ten real Advanced inorganic questions make the student judge every item of a list of mixed species
(complexes, molecules, ions, diatomics), and the lists are chosen so that the usual rule fails on some of them
(d⁸ Pd is square planar while d¹⁰ Cu(I) is tetrahedral; XeF₄ has four F but is square planar). Main asks one fact.

Code builds the whole question: it picks a property and a value, then a list in which
    - several classes of species are mixed,
    - some species have the value and some do not (the answer is never 0, 1 or the whole list), and
    - at least two species that do NOT have the value look like those that do: the same number of attached
      ligands or atoms (four-coordinate but square planar), or, for magnetism, the same kind of species.
Every value is computed by core/engine/inorganic/properties.py; no model writes or judges any part of the key.
"""

from __future__ import annotations

import re

from core.engine.base import ChainResult, EngineError
from core.engine.inorganic import properties as P
from core.engine.inorganic import tables as T

N_MIN, N_MAX = 7, 10           # species in the list (real papers: 6 to 11)
MIN_LOOKALIKES = 2             # species without the value that look like those with it

# Species added to the fact tables' lists for these questions (each value checked by hand on 2026-11-24).
# Left out on purpose: [Co(NH3)6]2+ (books differ on its hybridisation), P4 and metal nitrosyls (outside the
# property functions), [Cu(NH3)4]2+ (see tables.py).
EXTRA_COMPLEXES = ("[PdCl4]2-", "[Cu(CN)4]3-", "[Ni(H2O)6]2+", "[Cr(CN)6]3-", "[Zn(CN)4]2-", "[Co(CN)6]3-")
EXTRA_MOLECULES = ("SiO4^4-", "PO4^3-", "XeO2F2", "I3+", "BrF3", "SCl2", "SiCl4", "ClO2-", "BrO3-", "IO4-",
                   "NCl3", "CCl4", "ICl2-", "IF4+", "BrF4-", "ClF2+", "PH3", "H2S")
CENTRAL = {"SO2Cl2": "S", "SOCl2": "S", "XeOF2": "Xe"}            # species whose central atom must be named
EXTRA_MOLECULES += tuple(CENTRAL)
# JEE treats PH3 and H2S as unhybridised (bond angles near 90°, Drago's rule): no hybridisation claim on them
NO_HYBRID = {"PH3", "H2S", "AsH3", "SbH3", "H2Se", "H2Te"}   # the heavier hydrides too (audit, 2026-11-24)
# XeF6 is a distorted octahedron with a small dipole that books report both ways: no polarity claim on it
NO_POLARITY = {"XeF6"}

# property -> (classes it applies to, stem phrase for a value)
PROPS = {
    "shape": (("complex", "molecule"), "species with {value} geometry"),
    "hybridisation": (("complex", "molecule"), "species having {value} hybridised central atom"),
    "magnetism": (("complex", "diatomic"), "{value} species"),
    "polarity": (("molecule",), "{value} molecules"),
}
CHAPTER = {"complex": "coordination_compounds", "molecule": "chemical_bonding", "diatomic": "chemical_bonding"}


def _rows():
    """species -> {"class", "attached", "shape", "hybridisation", "magnetism", "polarity"} (only what code decides)."""
    rows = {}
    for e in dict.fromkeys(T.COMPLEXES + EXTRA_COMPLEXES):
        try:
            d = P.complex_info(e)
        except EngineError:
            continue
        rows[e] = {"class": "complex", "attached": d["coordination_number"], "shape": d["geometry"],
                   "hybridisation": d["hybridisation"], "magnetism": d["magnetism"]}
    for s in dict.fromkeys(T.MOLECULES + EXTRA_MOLECULES):
        try:
            d = P.vsepr(s, CENTRAL.get(s))
        except EngineError:
            continue
        r = {"class": "molecule", "attached": sum(d["ligands"].values()), "shape": d["shape"],
             "hybridisation": None if s in NO_HYBRID else d["hybridisation"]}
        if d["polar"] is not None and not re.search(r"[+-]$", s) and s not in NO_POLARITY:  # molecules only
            r["polarity"] = "polar" if d["polar"] else "non-polar"
        rows[s] = r
    for s in T.DIATOMICS:
        try:
            d = P.mo_diatomic(s)
        except EngineError:
            continue
        if d.get("bond_order", 0) > 0:             # He2, Be2, Ne2 do not exist
            rows[s] = {"class": "diatomic", "attached": 1, "magnetism": d["magnetism"]}
    return rows


ROWS = _rows()

_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_SUP_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")          # sp3d2 -> sp³d²


def pretty(sid: str) -> str:
    """'SO4^2-' -> 'SO₄²⁻', '[Fe(CN)6]4-' -> '[Fe(CN)₆]⁴⁻', 'I3-' -> 'I₃⁻', 'NO2+' -> 'NO₂⁺'."""
    m = re.fullmatch(r"(.*?)(?:\^(\d*[+-])|(?<=\])(\d*[+-])|([+-]))?", sid)
    body, charge = m.group(1), m.group(2) or m.group(3) or m.group(4) or ""
    body = re.sub(r"(?<=[A-Za-z\)\]])(\d+)", lambda x: x.group(1).translate(_SUB), body)
    return body + charge.translate(_SUP)


def draw(rng, tried=()):
    """A candidate for one list question, or None. tried: keys already used in this run."""
    for _ in range(300):
        prop = rng.choice(sorted(PROPS))
        classes, _phrase = PROPS[prop]
        pool = {s: r for s, r in ROWS.items() if r["class"] in classes and r.get(prop)}
        values = sorted({r[prop] for r in pool.values()})
        value = rng.choice(values)
        have = [s for s, r in pool.items() if r[prop] == value]
        lack = [s for s, r in pool.items() if r[prop] != value]
        if prop == "magnetism":                     # look alike: same kind of species (complex, diatomic)
            kinds = {pool[s]["class"] for s in have}
            look = [s for s in lack if pool[s]["class"] in kinds]
        else:                                       # look alike: as many attached atoms or ligands as a true one
            counts = {pool[s]["attached"] for s in have}
            look = [s for s in lack if pool[s]["attached"] in counts]
        n = rng.randint(N_MIN, N_MAX)
        k = rng.randint(2, n - 2)
        if len(have) < k or len(look) < MIN_LOOKALIKES:
            continue
        pick_have = rng.sample(have, k)
        n_look = min(len(look), rng.randint(MIN_LOOKALIKES, n - k))
        pick_look = rng.sample(look, n_look)
        rest = [s for s in lack if s not in pick_look]
        if len(rest) < n - k - n_look:
            continue
        chosen = pick_have + pick_look + rng.sample(rest, n - k - n_look)
        if len({pool[s]["class"] for s in chosen}) < min(2, len(classes)):
            continue                                # mix the classes where the property allows it
        rng.shuffle(chosen)
        key = (f"list:{prop}:{value}:" + ",".join(sorted(chosen)),)
        if key[0] in tried:
            continue
        truth = [pool[s][prop] == value for s in chosen]
        chapters = list(dict.fromkeys(CHAPTER[pool[s]["class"]] for s in chosen))
        return {"edges": list(key), "nodes": chosen, "chapters": chapters, "txs": [], "trap_ids": [],
                "description": f"how many species: {prop} = {value} ({n} species, {sum(truth)} true)",
                "_list": {"property": prop, "value": value, "species": chosen, "truth": truth,
                          "computed": [pool[s][prop] for s in chosen], "lookalikes": pick_look},
                "_hint": "Judge every species on its own: count its electrons (metal d electrons and the ligand's "
                         "field strength, or the central atom's lone pairs) before naming its geometry or spin; "
                         "species with the same formula type need not share it."}
    return None


def question(cand):
    """(stem, ChainResult) for a candidate from draw()."""
    L = cand["_list"]
    value = L["value"].translate(_SUP_DIGITS) if L["property"] == "hybridisation" else L["value"]
    phrase = PROPS[L["property"]][1].format(value=value)
    names = ", ".join(pretty(s) for s in L["species"][:-1]) + " and " + pretty(L["species"][-1])
    stem = f"Among {names}, the total number of {phrase} is\nGive the answer as an integer."
    answer = sum(L["truth"])
    trace = [{"tx": [], "src": s, "dst": L["property"],
              "formula": f"{L['property']} computed by code (core/engine/inorganic/properties.py)",
              "inputs": {"species": s, "counted when": L["value"]},
              "outputs": {"computed value": v, "counted": t}}
             for s, v, t in zip(L["species"], L["computed"], L["truth"])]
    traps = [{"id": f"item{i + 1}", "desc": f"misjudges {pretty(s)}", "wrong_answer": answer + (-1 if t else 1)}
             for i, (s, t) in enumerate(zip(L["species"], L["truth"]))]
    res = ChainResult(answer=answer, unit="", kind="count", asks=stem, trace=trace, traps=traps, constants=[])
    res.tolerance = 0.001
    res.options = [pretty(s) for s in L["species"]]
    res.form = f"inorganic_species_list:{L['property']}"
    return stem, res
