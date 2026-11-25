"""
inorg_list.py: the JEE Advanced "how many species in this list" question for INORGANIC chemistry, built by code.

    "Among [Co(CO)₃(NO)], XeF₄, [PCl₄]⁺, [PdCl₄]²⁻, [Cu(CN)₄]³⁻ …, the total number of species with tetrahedral
     geometry is"

About nine in ten real Advanced inorganic questions make the student judge every item of a list of mixed species
(complexes, molecules, ions, diatomics), and the lists are chosen so that the usual rule fails on some of them
(d⁸ Pd is square planar while d¹⁰ Cu(I) is tetrahedral; XeF₄ has four F but is square planar). Main asks one fact.

Code builds the whole question: since 2026-11-25 it picks TWO conditions ("paramagnetic and tetrahedral",
"polar and sp³d") and a list in which
    - some species meet both (the answer is never 0, 1 or all but one),
    - at least one meets only the first and one only the second (half right: the trap), and
    - the rest meet neither.
One condition was too easy at medium-hard (Granite solved 6 of 8 judged lists).
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


def tried_keys(tried) -> set:
    """The draw keys already used, as strings. The pipeline passes Blackboard.tried_edges(), a set of TUPLES of
    edge keys (("list:...",)); tests pass a plain list. Comparing a string against the tuples never matched, so a
    question could be drawn twice in one run (review of 2026-11-25)."""
    return {k for t in tried or () for k in (t if isinstance(t, (tuple, list)) else (t,))}


# Two conditions per list (the author, 2026-11-25): one condition was solved by Granite in 6 of 8 judged lists, so
# every item now needs two judgements. Pairs where one value does not fix the other: shape x hybridisation left
# out (a molecule's shape fixes its hybridisation), polarity x shape too (in our table every shape is all polar or
# all non-polar, so no draw passed the "half right both ways" rule).
PAIRS = (("magnetism", "shape"), ("magnetism", "hybridisation"),       # complexes
         ("polarity", "hybridisation"))                                 # molecules
# "the total number of species that ... and ..."
THAT = {"magnetism": "are {value}", "polarity": "are {value}", "shape": "have {value} geometry",
        "hybridisation": "have {value} hybridisation of the central atom"}


def _shown(prop, value):
    return value.translate(_SUP_DIGITS) if prop == "hybridisation" else value


def _cond(props, values) -> str:
    return "&".join(f"{p}={v}" for p, v in zip(props, values))


def draw(rng, tried=(), used=None):
    """A candidate for one two-condition list question, or None. tried: keys already used in this run.
    used: {condition: accepted questions using it}; a condition is drawn with weight 1/(1 + uses), so accepted
    lists spread over the conditions (batch 2026-11-25: 3 of the first 4 asked paramagnetic and d2sp3).
    Items: some meet both conditions (counted), at least one meets only the first and one only the second
    (the traps: half right), the rest neither."""
    tried = tried_keys(tried)
    used = used or {}
    options = []                                    # every (pair, values) a list can ask, with its weight
    for props in PAIRS:
        pool = {s: r for s, r in ROWS.items() if all(r.get(p) for p in props)}
        for values in sorted({tuple(r[p] for p in props) for r in pool.values()}):
            options.append((props, values, 1.0 / (1 + used.get(_cond(props, values), 0))))
    for _ in range(300):
        props, values, _w = rng.choices(options, weights=[w for *_, w in options])[0]
        pool = {s: r for s, r in ROWS.items() if all(r.get(p) for p in props)}
        meets = {s: tuple(r[p] == v for p, v in zip(props, values)) for s, r in pool.items()}
        both = [s for s, m in meets.items() if all(m)]
        first = [s for s, m in meets.items() if m == (True, False)]
        second = [s for s, m in meets.items() if m == (False, True)]
        neither = [s for s, m in meets.items() if not any(m)]
        if not first or not second:
            continue                                # one condition would imply the other: not two judgements
        n = rng.randint(N_MIN, N_MAX)
        k = rng.randint(2, n - 2)
        n1 = rng.randint(1, max(1, min(len(first), (n - k) // 2)))
        n2 = rng.randint(1, max(1, min(len(second), n - k - n1 - 1)))
        n0 = n - k - n1 - n2
        if len(both) < k or n0 < 0 or len(neither) < n0 or n1 > len(first) or n2 > len(second):
            continue
        half = rng.sample(first, n1) + rng.sample(second, n2)
        chosen = rng.sample(both, k) + half + rng.sample(neither, n0)
        rng.shuffle(chosen)
        cond = _cond(props, values)
        key = f"list:{cond}:" + ",".join(sorted(chosen))
        if key in tried:
            continue
        truth = [all(meets[s]) for s in chosen]
        chapters = list(dict.fromkeys(CHAPTER[pool[s]["class"]] for s in chosen))
        return {"edges": [key], "nodes": chosen, "chapters": chapters, "txs": [], "trap_ids": [],
                "description": f"how many species: {' and '.join(f'{p} = {v}' for p, v in zip(props, values))} "
                               f"({n} species, {sum(truth)} true)",
                "_list": {"properties": list(props), "values": list(values), "species": chosen, "truth": truth,
                          "computed": [[pool[s][p] for p in props] for s in chosen], "lookalikes": half},
                "_hint": "Judge every species on both conditions: count its electrons (metal d electrons and the "
                         "ligand's field strength, or the central atom's lone pairs) first; a species that meets "
                         "only one condition is not counted."}
    return None


def question(cand):
    """(stem, ChainResult) for a candidate from draw()."""
    L = cand["_list"]
    props, values = L["properties"], L["values"]
    phrase = " and ".join(THAT[p].format(value=_shown(p, v)) for p, v in zip(props, values))
    names = ", ".join(pretty(s) for s in L["species"][:-1]) + " and " + pretty(L["species"][-1])
    stem = f"Among {names}, the total number of species that {phrase} is\nGive the answer as an integer."
    answer = sum(L["truth"])
    trace = [{"tx": [], "src": s, "dst": " and ".join(props),
              "formula": f"{' and '.join(props)} computed by code (core/engine/inorganic/properties.py)",
              "inputs": {"species": s, "counted when": dict(zip(props, values))},
              "outputs": {"computed value": dict(zip(props, v)), "counted": t}}
             for s, v, t in zip(L["species"], L["computed"], L["truth"])]
    traps = [{"id": f"item{i + 1}", "desc": f"misjudges {pretty(s)}", "wrong_answer": answer + (-1 if t else 1)}
             for i, (s, t) in enumerate(zip(L["species"], L["truth"]))]
    res = ChainResult(answer=answer, unit="", kind="count", asks=stem, trace=trace, traps=traps, constants=[])
    res.tolerance = 0.001
    res.options = [pretty(s) for s in L["species"]]
    res.form = f"inorganic_species_list:{'+'.join(props)}"
    return stem, res
