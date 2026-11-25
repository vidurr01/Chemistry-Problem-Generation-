"""
inorg_system.py: the JEE Advanced "one reaction system, products as letters" question for INORGANIC chemistry.

What real Advanced papers do (2019-2025, 75 inorganic questions read on 2026-11-25): one connected system whose
products are letters, then several properties of those hidden species in one question:

    2019  Zn + hot conc. H2SO4 -> G + R + X;  Zn + conc. NaOH -> T + Q;  G + H2S + NH4OH -> Z ...
          Choose the correct option(s)
    2019  Fusion of MnO2 with KOH in presence of O2 produces a salt W. Alkaline solution of W upon electrolytic
          oxidation yields another salt X ... Correct statement(s) is(are)
    2022  The reaction of HClO3 with HCl gives a paramagnetic gas, which upon reaction with O3 produces ...

Code builds it from the inorganic graph: a chain (A -> P -> Q -> R) or a fork (one start, two reagents), every
product a letter. Two forms:
    msq        four statements about the lettered species, mixing properties (magnetism, geometry,
               hybridisation, oxidation state, d electrons, spin-only moment ...); each true or false by code,
               a false one carries the classic wrong value (high spin for low spin, sp3 for dsp2, +4 for +6)
    numerical  a number over the letters: total unpaired electrons, or the spin-only moment of one
Every value is computed by core/engine/inorganic/species.py. An LLM may reword the reaction text into JEE prose
(polish_stem); code then checks that no product is named, and GPT-6 Luna names every letter blind from the final
reaction text, without the options (check_letters), before anything else is paid for.
"""

from __future__ import annotations

import datetime
import json
import os
import re

from core import models
from core.engine.base import ChainResult, EngineError
from core.engine.chem import Z_OF, parse_formula
from core.engine.inorganic import properties as P
from core.engine.inorganic import species as S
from core.pipeline import inorg_list as IL
from core.pipeline import inorg_products as IP

LETTER_SETS = ("PQRS", "WXYZ", "GRTZ", "XYZQ", "LMNO")        # never A-D: those are the options
OPTION = "ABCD"
CHAIN_MIN, CHAIN_MAX = 2, 3
MIN_FACTS = 4                 # statement-able (letter, property) pairs, over at least two letters

# property key -> family (one statement per family per question, so properties are mixed)
FAMILY = {
    "metal_ion_magnetism": "magnetism", "complex_magnetism": "magnetism", "mo_magnetism": "magnetism",
    "metal_ion_unpaired": "unpaired", "complex_unpaired": "unpaired", "mo_unpaired": "unpaired",
    "metal_ion_spin_only_moment": "moment", "complex_spin_only_moment": "moment",
    "shape": "geometry", "central_shape": "geometry", "complex_geometry": "geometry", "anion_shape": "geometry",
    "hybridisation": "hybrid", "central_hybridisation": "hybrid", "complex_hybridisation": "hybrid",
    "anion_hybridisation": "hybrid",
    "complex_oxidation_state": "oxidation", "complex_d_electrons": "d", "metal_ion_d_electrons": "d",
    "basicity": "basicity", "bond_order": "bond_order", "polarity": "polarity",
}
# magnetism, unpaired electrons, spin-only moment and d count are one fact seen four ways: one per letter
CATEGORY = {"magnetism": "electrons", "unpaired": "electrons", "moment": "electrons", "d": "electrons",
            "geometry": "geometry", "hybrid": "hybrid", "oxidation": "oxidation",
            "basicity": "other", "bond_order": "other", "polarity": "other"}
MIN_CATEGORIES = 3
# chance a draw sharing one asked species with an accepted question is passed over (batch 2026-11-25: three
# nitrogen chains in a row, NO in two); not 1, or the nitrogen and sulphur families would run out
REPEAT_SKIP = 0.7
# the shape a hybridisation gives when the central atom has no lone pair
PARENT_SHAPE = {"sp": "linear", "sp2": "trigonal planar", "sp3": "tetrahedral", "sp3d": "trigonal bipyramidal",
                "sp3d2": "octahedral", "d2sp3": "octahedral", "dsp2": "square planar"}


def categories(fs) -> dict:
    """One letter's facts -> {family: category}. Shape and hybridisation are ONE fact when the shape is the
    hybridisation's own (no lone pair: CO₂ sp and linear; batch 2026-11-25 asked both, so one gave the other away);
    with lone pairs (XeF₄ sp³d², square planar) they are two judgements."""
    vals = {fam: v for fam, _k, v, _e in fs}
    same = PARENT_SHAPE.get(str(vals.get("hybrid", "")).replace("³", "3").replace("²", "2")) == vals.get("geometry")
    return {fam: ("structure" if same and fam in ("geometry", "hybrid") else CATEGORY[fam]) for fam in vals}

SHAPES = ["linear", "bent", "trigonal planar", "trigonal pyramidal", "T-shaped", "tetrahedral", "square planar",
          "see-saw", "trigonal bipyramidal", "square pyramidal", "octahedral"]
# the classic confusions a false statement uses (value -> wrong values), first is preferred
SHAPE_TRAP = {"tetrahedral": ["square planar", "trigonal pyramidal"], "square planar": ["tetrahedral", "see-saw"],
              "trigonal pyramidal": ["trigonal planar", "tetrahedral"], "trigonal planar": ["trigonal pyramidal", "T-shaped"],
              "bent": ["linear"], "linear": ["bent"], "see-saw": ["tetrahedral", "square planar"],
              "T-shaped": ["trigonal planar"], "octahedral": ["trigonal prismatic", "hexagonal planar"],
              "trigonal bipyramidal": ["square pyramidal"], "square pyramidal": ["trigonal bipyramidal"]}
HYB_TRAP = {"sp3": ["dsp2", "sp2"], "dsp2": ["sp3"], "d2sp3": ["sp3d2"], "sp3d2": ["d2sp3"], "sp2": ["sp3", "sp"],
            "sp": ["sp2"], "sp3d": ["sp3d2", "dsp3"]}
_SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_ROMAN = ("i", "ii", "iii", "iv")


# ── facts about a species ────────────────────────────────────────────────────

def _metal(sid):
    try:
        counts = S.parse_formula(S.to_formula_charge(sid)[0].split("·")[0])[0]
    except (EngineError, ValueError, AttributeError):
        return None
    ms = [e for e in counts if P.is_transition(e)]
    return ms[0] if len(ms) == 1 else None


def facts(sid) -> list:
    """[(family, key, value, element)] a statement may be about; the audit's exclusions applied."""
    props = S.askable(sid)
    base = sid.split("·")[0]
    out = []
    for key, value in props.items():
        fam = FAMILY.get(key)
        if fam is None:
            continue
        el = IP.focus(sid, key) if fam in ("geometry", "hybrid", "magnetism") else _metal(sid)
        if fam in ("geometry", "hybrid") and (el in IP.METAL_CENTRES or base in IP.NO_SHAPE):
            continue
        if fam == "hybrid" and base in IL.NO_HYBRID:
            continue
        if fam == "basicity" and not value:          # CO2 "basicity 0": not an acid, nothing to ask
            continue
        if fam in ("geometry", "hybrid") and not el:
            continue
        out.append((fam, key, value, el))
    metal = _metal(sid)                            # oxidation state of the transition metal (not K, O, Cl ...)
    if metal and f"oxidation_state:{metal}" in props and not any(f[0] == "oxidation" for f in out):
        out.append(("oxidation", f"oxidation_state:{metal}", props[f"oxidation_state:{metal}"], metal))
    return out


def _wrong(fam, key, value, rng, el_is_metal=False, el=None):
    """A plausible wrong value, or None. dsp2 / d2sp3 are offered as traps only for a transition metal.
    Never an impossible one (review #10, 2026-11-25): d¹², 7 unpaired electrons or Mn +9 is ruled out without any
    chemistry, so the statement would be a free point. d count 0-10, unpaired 0-5 on a metal and 0-2 in a diatomic
    (MO), oxidation state 0 to the group's highest."""
    if fam == "magnetism":
        return "diamagnetic" if value == "paramagnetic" else "paramagnetic"
    if fam == "polarity":
        return "non-polar" if value == "polar" else "polar"
    if fam == "geometry":
        return (SHAPE_TRAP.get(value) or [None])[0]
    if fam == "hybrid":
        traps = [t for t in HYB_TRAP.get(value) or [] if el_is_metal or "d" not in t or "sp3d" in t]
        return traps[0] if traps else None
    if fam == "moment":
        n = round((value ** 2 + 1) ** 0.5 - 1)     # unpaired electrons behind the moment
        m = n + 2 if n <= 2 else n - 2              # the high-spin / low-spin partner value
        return round((m * (m + 2)) ** 0.5, 2)
    if fam == "basicity":                           # mono-, di- or tribasic only
        return rng.choice([b for b in (1, 2, 3) if b != value])
    if fam in ("unpaired", "d"):
        hi = 10 if fam == "d" else (2 if key.startswith("mo_") else 5)
        alt = [v for v in (value + 2, value - 2, value + 1, value - 1) if 0 <= v <= hi]
        return rng.choice(alt[:2]) if alt else None
    if fam == "oxidation":
        hi = S._max_ox(el) if el else None
        alt = [value + d for d in (-1, 1, 2, -2) if value + d >= 0 and (hi is None or value + d <= hi)]
        return rng.choice(alt) if alt else None
    if fam == "bond_order":
        return value + 0.5 if value < 3 else value - 0.5
    return None


def tag(letter: str) -> str:
    """A product letter as printed: <N>, so it can never be read as an element (N is nitrogen; <N> is a species
    to work out). The author, 2026-11-25. Option letters (A)-(D) are not tagged."""
    return f"<{letter}>"


def _untag(text) -> str:
    return str(text or "").strip().strip("<>").strip()


def _text(letter, fam, key, value, el) -> str:
    """The statement as JEE prints it."""
    v = value
    if fam == "hybrid":
        v = str(value).translate(_SUP)
    if fam == "magnetism":
        return f"{letter} is {v}"
    if fam == "polarity":
        return f"{letter} is a {v} molecule"
    if fam == "geometry":
        if key == "anion_shape":
            return f"The anion present in {letter} is {v}"
        if key == "shape":                          # "is T-shaped", "has an octahedral shape" (not "a octahedral")
            return (f"{letter} is {v}" if str(v).endswith("shaped")
                    else f"{letter} has {'an' if str(v)[0] in 'aeiou' else 'a'} {v} shape")
        if key == "central_shape":                  # SHAPE, not "geometry": the A/B of 2026-11-25 found "the
            # geometry around S in H2SO3 is tetrahedral" read as the electron-pair arrangement, which IS
            # tetrahedral, so a "false" statement was arguably true
            return (f"{letter} is {v} around {el}" if str(v).endswith("shaped")
                    else f"{letter} has {'an' if str(v)[0] in 'aeiou' else 'a'} {v} shape around {el}")
        return f"The geometry around {el} in {letter} is {v}"   # complexes: the metal has no lone pair
    if fam == "hybrid":
        if key == "anion_hybridisation":
            return f"The central atom of the anion in {letter} is {v} hybridised"
        return f"{el} in {letter} is {v} hybridised"
    if fam == "moment":
        return (f"The spin-only magnetic moment of {letter} is zero" if not v
                else f"The spin-only magnetic moment of {letter} is {float(v):.2f} BM")
    if fam == "unpaired":
        return f"{letter} has {v} unpaired electron{'s' if v != 1 else ''}"
    if fam == "d":
        return f"The metal in {letter} has a d{str(v).translate(_SUP)} configuration"
    if fam == "oxidation":
        return f"The oxidation state of {el} in {letter} is {'+' if v > 0 else ''}{v}"
    if fam == "basicity":
        return f"{letter} is a {('mono', 'di', 'tri', 'tetra')[int(v) - 1]}basic acid"
    if fam == "bond_order":
        return f"The bond order of {letter} is {v:g}"
    raise ValueError(fam)


# ── the system ───────────────────────────────────────────────────────────────

def _condition_text(e) -> str:
    """Reagents and conditions as printed (the start and any product never shown)."""
    reagents = [IP.pretty(r) if re.fullmatch(r"[A-Za-z0-9()\[\]+\-^]+", IP._plain(r)) else r for r in _reagents(e)]
    cond = IP.printed_condition(e)
    return ", ".join(IP.drop_repeated(reagents, cond) + ([cond] if cond else []))


_THERMAL = re.compile(r"heat|fus|roast|ignit|calcin|burn|electroly|°C|\d\s*K\b|warm|boil|spark|discharge|sunlight", re.I)


def _reagents(e) -> list:
    src = IP._plain(e["from"])
    return [r for r in (e.get("reagents") or [])
            if IP._plain(r) != src and "dissolution" not in r and r.strip().lower() not in IP.START_NAMES]


def _usable(e) -> bool:
    """A reaction a student can read: a reagent, or a heating / electrolysis step (live preview 2026-11-25 printed
    "Na2CrO4 + room temperature")."""
    if e.get("synthetic") or e.get("conditions_variants") or IP._reaction(e) is None:
        return False
    return bool(_reagents(e)) or bool(_THERMAL.search(str(e.get("conditions") or "")))


def _elements(start, steps) -> set:
    """Element symbols written anywhere in the system: start, products, reagents."""
    text = " ".join([start] + [e["to"] for e in steps]
                    + [IP._plain(r) for e in steps for r in (e.get("reagents") or [])])
    return set(re.findall(r"[A-Z][a-z]?", text)) & set(Z_OF)


def letter_sets(start, steps, n) -> list:
    """The letter sets (first n letters) with no letter that is an element of this system. Review #11, 2026-11-25:
    6% of systems read like "M + H₂O → N" in nitrogen chemistry, or "PCl₅ + H₂O → P". GRT and XYZ almost never
    clash, so the list is never empty in practice; if it were, every set is offered as before."""
    els = _elements(start, steps)
    ok = [s[:n] for s in LETTER_SETS if not set(s[:n]) & els]
    return ok or [s[:n] for s in LETTER_SETS]


# Share of draws built around a reaction whose product is a d-block species (the author, 2026-11-25). The plain walk
# picks a start uniformly and walks on; sulphur and nitrogen compounds form long chains while a third of the metal
# products are dead ends, so only 18 of 167 drawable systems had a transition metal (11%), and hard JEE Advanced
# inorganic is largely d-block and coordination chemistry.
# CHECKED against data/jee_advanced the same day: about half of real Advanced inorganic involves a d-block metal or a
# complex (86/167), and the hard ones are no more d-block than the easier ones (5/8 hard, 6/14 medium, 12/20 easier,
# by real student results). So d-block is a coverage gap, not a difficulty lever. At 0.5 the draw gave only 14
# metal systems, mostly ZnCl2 -> zincate (metal salts have one kind of fact, so most fail MIN_CATEGORIES): OFF until
# that is fixed.
D_BLOCK_SHARE = 0.0


def _walk(out, starts, rng):
    """(start, shape, steps) by the plain walk: a fork (one start, two reagents, maybe one step more) or a chain."""
    start = rng.choice(starts)
    if rng.random() < 0.35 and len(out[start]) >= 2:
        a, b = rng.sample(out[start], 2)
        if a["to"] == b["to"]:
            return None
        steps = [a, b]
        more = [e for e in out.get(a["to"], []) if e["to"] not in (start, a["to"], b["to"])]
        if more and rng.random() < 0.5:
            steps.append(rng.choice(more))
        return start, "fork", steps
    steps, node = [], start
    for _k in range(rng.randint(CHAIN_MIN, CHAIN_MAX)):
        nxt = [e for e in out.get(node, []) if e["to"] not in {start} | {s["to"] for s in steps}]
        if not nxt:
            break
        e = rng.choice(nxt)
        steps.append(e)
        node = e["to"]
    return (start, "chain", steps) if len(steps) >= CHAIN_MIN else None


def _around_dblock(out, inc, dblock, rng):
    """(start, shape, steps) built around one reaction t that makes a d-block product: a step leading into t's
    start (then maybe one step on from t's product), a step on from t's product, or a fork with another reaction
    of t's start. None if t allows none of these."""
    t = rng.choice(dblock)
    ways = []
    before = [p for p in inc.get(t["from"], []) if p["from"] not in (t["to"],) and p["to"] != t["to"]]
    after = [n for n in out.get(t["to"], []) if n["to"] not in (t["from"], t["to"])]
    beside = [o for o in out.get(t["from"], []) if o["to"] != t["to"]]
    if before:
        ways.append("in")
    if after:
        ways.append("out")
    if beside:
        ways.append("fork")
    if not ways:
        return None
    way = rng.choice(ways)
    if way == "in":
        p = rng.choice(before)
        steps = [p, t]
        more = [n for n in after if n["to"] not in (p["from"], p["to"])]
        if more and rng.random() < 0.5:
            steps.append(rng.choice(more))
        return p["from"], "chain", steps
    if way == "out":
        return t["from"], "chain", [t, rng.choice(after)]
    return t["from"], "fork", [t, rng.choice(beside)]


def draw(graph, rng, tried=(), bad=(), asked=()):
    """A one-system candidate, or None. graph: inorg_qfirst._graph(adapter); bad: edge ids the blind check did
    not confirm in this run; asked: species sets accepted questions already ask about (two shared = a repeat)."""
    tried = IL.tried_keys(tried)
    out = {s: [e for e in es if e["id"] not in bad and _usable(e)] for s, es in graph["out"].items()}
    starts = [s for s, es in out.items() if es]
    inc = {}
    for es in out.values():
        for e in es:
            inc.setdefault(e["to"], []).append(e)
    dblock = [e for es in out.values() for e in es if _metal(e["to"]) and facts(e["to"])]
    for _ in range(600):
        made = (_around_dblock(out, inc, dblock, rng) if dblock and rng.random() < D_BLOCK_SHARE
                else _walk(out, starts, rng))
        if made is None:
            continue
        start, shape, steps = made
        products = list(dict.fromkeys(e["to"] for e in steps))
        if len(products) != len(steps):
            continue
        key = "system:" + ",".join(sorted(e["id"] for e in steps))   # the set of reactions is the system: a fork
        # drawn b-then-a is the same question as a-then-b (run 11 drew the Ag fork both ways)
        if key in tried:
            continue
        letters = rng.choice(letter_sets(start, steps, len(products)))
        lab = dict(zip(products, letters))
        fs = {lab[p]: facts(p) for p in products}
        n_facts = sum(len(v) for v in fs.values())
        if n_facts < MIN_FACTS or sum(1 for v in fs.values() if v) < 2:
            continue
        if any(not fs[lab[p]] for p in _leaves(steps)):
            continue                                # a last product nothing is asked about (run 13's <T> = NH4OH)
        shared = max((len({p for p in products if fs[lab[p]]} & set(s)) for s in asked), default=0)
        if shared >= 2:
            continue                                # the same species asked again, only the lead-in differs
        if shared == 1 and rng.random() < REPEAT_SKIP:
            continue                                # one species asked before: drawn less often (spread topics)
        if len({c for v in fs.values() for c in categories(v).values()}) < MIN_CATEGORIES:
            continue                                # a question needs several kinds of fact, not one
        if not msq_fits(fs):
            continue                                # _msq could not make four statements: not a draw
        cand = {"_system": {"labels": lab, "steps": steps}}
        if leaks(cand, scheme(cand)):
            continue                                # a product written as another step's reagent
        rivals = rival_values(steps, lab, fs, out)
        return {"edges": [key], "nodes": [start] + products,
                "chapters": list(dict.fromkeys(e.get("chapter", "") for e in steps)),
                "txs": [t for e in steps for t in (e.get("tx_ids") or [])], "trap_ids": [],
                "description": f"one system ({shape}, {len(steps)} reactions): {start} → " + ", ".join(products),
                "_system": {"shape": shape, "start": start, "steps": steps, "labels": lab, "facts": fs,
                            "rivals": rivals},
                "_hint": "Work out every lettered species from its reaction first (oxidation state of the metal, "
                         "what the reagent does); then count its electrons before judging spin, shape or "
                         "hybridisation."}
    return None


def rival_values(steps, lab, fs, out) -> dict:
    """{"<letter>|<family>": (value, rival species)}: a fact on which a letter's product differs from a RIVAL
    product, i.e. what the same start gives with another reagent or condition in our graph (same kind of fact, same
    element). A false statement carrying the rival's value tests the student's real mistake: working out the wrong
    product (the author, 2026-11-25: kept for students; on the models it made no difference once the wording was
    equal, tools/ab_inorganic_statements.py)."""
    out_r = {}
    for e in steps:
        L = lab[e["to"]]
        mine = {f: (k, v, el) for f, k, v, el in fs[L]}
        for o in out.get(e["from"], []):
            if o["to"] == e["to"]:
                continue
            for f, k, v, el in facts(o["to"]):
                if f in mine and mine[f][0] == k and mine[f][2] == el and mine[f][1] != v:
                    out_r.setdefault(f"{L}|{f}", (v, o["to"]))
    return out_r


def scheme(cand) -> str:
    """The reactions as a JEE scheme: 'MnO₂ + KOH, O₂, fusion → W' ... (unbalanced)."""
    D = cand["_system"]
    lab = D["labels"]
    lines = []
    for e in D["steps"]:
        left = tag(lab[e["from"]]) if e["from"] in lab else IP.pretty(e["from"])
        el = carrier(e)
        note = f" (the {el}-containing product)" if el else ""
        lines.append(f"{left} + {_condition_text(e)} → {tag(lab[e['to']])}{note}")
    return "\n".join(lines)


def carrier(e) -> str | None:
    """The element a lettered product carries over from its starting species, so the reaction names WHICH product
    the letter is: CO + H₂O gives CO₂ and H₂, NH₃ + O₂ gives N₂ and H₂O (batch 2026-11-25: the blind letter check
    read <X> as H₂ and <M> as H₂O). A metal first, then any element but H and O, then O, then H."""
    try:
        prod = parse_formula(S.to_formula_charge(e["to"])[0].replace("[", "(").replace("]", ")"))[0]
        src = parse_formula(S.to_formula_charge(e["from"])[0].replace("[", "(").replace("]", ")"))[0]
    except EngineError:
        return None
    # a transition metal the product gains from a reagent ([Ag(CN)₂]⁻ + Zn → [Zn(CN)₄]²⁻) names it best
    common = [x for x in prod if x in src or P.is_transition(x)] or list(prod)
    return min(common, key=_carrier_rank) if common else None


_MAIN_METALS = {"Li", "Na", "K", "Rb", "Cs", "Be", "Mg", "Ca", "Sr", "Ba", "Al", "Ga", "In", "Tl", "Sn", "Pb", "Bi"}


def _carrier_rank(x: str) -> int:
    """Transition metal 0, other metal 1, non-metal 2, O 3, H 4 (Mn in KMnO₄ before K; N in NH₃ before H)."""
    if P.is_transition(x):
        return 0
    if x in _MAIN_METALS:
        return 1
    return {"O": 3, "H": 4}.get(x, 2)


def build(cand, rng, form=None):
    """(stem_body, ChainResult, form). stem_body is the question without the reaction text (scheme or prose
    goes in front). form: "msq" or "numerical" (chosen by rng if None)."""
    D = cand["_system"]
    letters = list(D["labels"].values())
    form = form or ("numerical" if rng.random() < 0.3 else "msq")
    if form == "numerical":
        q = _numerical(D, rng)
        if q is not None:
            return q
        form = "msq"
    return _msq(D, rng)


def _numerical(D, rng):
    unp = {L: next((v for f, k, v, _e in fs if f == "unpaired"), None) for L, fs in D["facts"].items()}
    unp = {L: v for L, v in unp.items() if v is not None}
    if len(unp) >= 2 and sum(unp.values()) > 0:
        names = [tag(L) for L in sorted(unp)]
        ask = (f"The total number of unpaired electrons present in {', '.join(names[:-1])} and {names[-1]} is")
        answer = sum(unp.values())
        trace = [{"tx": [], "src": L, "dst": "unpaired electrons", "formula": "computed by code",
                  "inputs": {"species": _sid(D, L)}, "outputs": {"unpaired": v}} for L, v in unp.items()]
        res = ChainResult(answer=answer, unit="", kind="count", asks=ask, trace=trace,
                          traps=[{"id": f"wrong_{L}", "desc": f"misjudges {L}", "wrong_answer": answer + 2}
                                 for L in unp], constants=[])
        res.tolerance = 0.001
        res.options = []
        res.form = "inorganic_system:numerical_unpaired"
        return ask + "\nGive the answer as an integer.", res, "numerical"
    mom = [(L, v) for L, fs in D["facts"].items() for f, k, v, _e in fs if f == "moment" and v > 0]
    if mom:
        L, v = rng.choice(mom)
        ask = f"The spin-only magnetic moment of {tag(L)} (in BM) is"
        res = ChainResult(answer=round(float(v), 2), unit="BM", kind="number", asks=ask,
                          trace=[{"tx": [], "src": L, "dst": "spin-only moment", "formula": "√(n(n+2)) by code",
                                  "inputs": {"species": _sid(D, L)}, "outputs": {"moment": v}}],
                          traps=[], constants=[])
        res.tolerance = 0.01
        res.options = []
        res.form = "inorganic_system:numerical_moment"
        return ask + "\nGive the answer correct to two decimal places.", res, "numerical"
    return None


def msq_fits(facts_by_letter) -> bool:
    """_msq can make its four statements: at most two per letter, one per (letter, kind of fact). Its limits are
    per letter, so it reaches the sum over letters of min(2, kinds of fact) whatever the order. Checked in draw():
    live run 11 lost 3 of its 10 draws to "no four mixed statements" (review of 2026-11-25)."""
    return sum(min(2, len(set(categories(fs).values()))) for fs in facts_by_letter.values()) >= 4


def _leaves(steps) -> list:
    """Products no other step starts from: each must be asked about, or its reaction is decoration."""
    starts = {e["from"] for e in steps}
    return list(dict.fromkeys(e["to"] for e in steps if e["to"] not in starts))


def _sid(D, letter):
    return next(s for s, L in D["labels"].items() if L == letter)


def _msq(D, rng):
    rivals = D.get("rivals") or {}
    pool = [(L, f, k, v, e) for L, fs in D["facts"].items() for f, k, v, e in fs]
    rng.shuffle(pool)
    sid = {L: s for s, L in D["labels"].items()}
    before = set(D.get("asked_facts") or ())        # (species, fact) accepted questions already state
    # facts with a rival-product value first; a fact an accepted question already asked last (batch 2026-11-25:
    # "the bond order of NO is 2.5" in two questions in a row)
    pool.sort(key=lambda it: (f"{it[0]}|{it[1]}" not in rivals, (sid.get(it[0]), it[2]) in before))
    chosen, used_cat, seen = [], set(), set()
    catmap = {L: categories(fs) for L, fs in D["facts"].items()}
    for L in [D["labels"][p] for p in _leaves(D.get("steps") or [])][:4]:   # every last product gets a statement
        item = next((it for it in pool if it[0] == L), None)
        if item:
            chosen.append(item)
            used_cat.add(catmap[L][item[1]])
            seen.add((L, catmap[L][item[1]]))
    for strict in (True, False):                    # first pass: four different kinds of fact
        for item in pool:
            L, f = item[0], item[1]
            cat = catmap[L][f]
            if item in chosen or (L, cat) in seen or (strict and cat in used_cat):
                continue
            if sum(1 for c in chosen if c[0] == L) >= 2:
                continue
            chosen.append(item)
            used_cat.add(cat)
            seen.add((L, cat))
            if len(chosen) == 4:
                break
        if len(chosen) == 4:
            break
    if len(chosen) < 4:
        return None
    n_true = rng.choice((1, 2, 2, 3))
    rng.shuffle(chosen)                              # option order
    # false slots go to facts with a rival-product value first: that false value is the student's real mistake
    order = sorted(range(4), key=lambda i: (f"{chosen[i][0]}|{chosen[i][1]}" not in rivals, rng.random()))
    false_slots = set(order[:4 - n_true])
    truth = [i not in false_slots for i in range(4)]
    stmts, trace = [], []
    for (L, f, k, v, e), t in zip(chosen, truth):
        rival = rivals.get(f"{L}|{f}")
        if t:
            shown = v
        elif rival:
            shown = rival[0]
        else:
            shown = _wrong(f, k, v, rng, el_is_metal=bool(e and P.is_transition(e)), el=e)
        if shown is None or shown == v:
            shown, t = v, True
        stmts.append(_text(tag(L), f, k, shown, e))
        trace.append({"tx": [], "src": L, "dst": k, "formula": f"{k} computed by code (species {_sid(D, L)})",
                      "inputs": {"statement": stmts[-1]},
                      "outputs": {"computed value": v, "statement true": t,
                                  **({"trap": f"true for the rival product {rival[1]}"} if rival and not t else {})}})
    truth = [tr["outputs"]["statement true"] for tr in trace]
    if not any(truth):
        return None
    answer = "".join(OPTION[i] for i, t in enumerate(truth) if t)
    traps = [{"id": f"option{OPTION[i]}", "desc": f"chooses option {OPTION[i]}", "wrong_answer": OPTION[i]}
             for i, t in enumerate(truth) if not t]
    res = ChainResult(answer=answer, unit="", kind="letters", asks="Choose the correct option(s)", trace=trace,
                      traps=traps, constants=[])
    res.options = stmts
    res.form = "inorganic_system:msq"
    body = "Choose the correct option(s).\n" + "\n".join(f"({OPTION[i]}) {s}" for i, s in enumerate(stmts))
    return body, res, "msq"


# ── wording ──────────────────────────────────────────────────────────────────

def leaks(cand, text) -> list:
    """Product formulas the text gives away."""
    found = []
    plain = IP._flat(text)
    for sid in cand["_system"]["labels"]:
        body = S.to_formula_charge(sid)[0].split("·")[0]
        if re.search(r"(?<![A-Za-z0-9(\[])" + re.escape(body) + r"(?![A-Za-z0-9([])", plain):
            found.append(sid)
    return found


def polish_stem(cand) -> str | None:
    """The reactions reworded as a JEE Advanced stem (prose or scheme), or None if the rewrite names a product,
    drops a letter, or writes a letter without its angle brackets (<W>, never a bare W)."""
    D = cand["_system"]
    tags = [tag(L) for L in D["labels"].values()]
    prompt = f"""Rewrite these inorganic reactions as the opening of a JEE Advanced question, in the style of real
papers, e.g. "Fusion of MnO₂ with KOH in the presence of O₂ produces a salt <W>. Alkaline solution of <W> upon
electrolytic oxidation yields another salt <X>." or "Consider the following reactions (unbalanced): ...".
{scheme(cand)}
Rules: keep every lettered species exactly as written, WITH its angle brackets ({', '.join(tags)}), every time it
appears: the brackets show it is an unknown species, not an element; keep every reagent and condition; keep each
"(the X-containing product)" note with the element SYMBOL, e.g. "gives the N-containing product <M>": it says which
product the letter is when a reaction gives two; write every
substance as its formula, never its name (KOH, not potassium hydroxide); never name, give the formula of, or
describe the colour/state of any lettered species beyond "a salt", "a gas", "a compound";
add no facts; plain text with Unicode subscripts, no LaTeX; one to three sentences or a short scheme; do not ask the
question (it follows).
Return JSON: {{"stem": "..."}}"""
    try:
        out = models.ask_json("generator", models.GENERATOR, "You write chemistry exam questions. Output JSON only.",
                              prompt, temperature=0.4, max_tokens=1500)
    except Exception:                               # noqa: BLE001  the scheme is used instead
        return None
    text = str(out.get("stem") or "").strip()
    if not text or leaks(cand, text) or any(t not in text for t in tags) or bare_letters(cand, text):
        return None
    if _EXPLAINS.search(text):
        return None                                 # it added a mechanism or a reason: the scheme is used
    if named_or_coloured(cand, text):
        return None                                 # a name or colour could give a product away: the scheme is used
    return text


# The graph has no names for inorganic species, so a name cannot be matched to a product. The rewrite is told to
# write every substance as a formula; a chemical name or a colour in it that the scheme itself does not contain is
# refused (it could be a product's: "a salt <W> (potassium manganate)", "a green salt <W>"). Review, 2026-11-25.
_NAME_WORDS = re.compile(
    r"\b(?:(?:chlor|brom|iod|fluor|ox|sulph|sulf|thiosulph|thiosulf|nitr|carbon|bicarbon|phosph|hydr|cyan|perox|"
    r"chrom|dichrom|mangan|permangan|alumin|silic|bor|plumb|stann|ferr|cupr|argent|aur|zinc|amm)\w*(?:ide|ate|ite)|"
    r"sodium|potassium|calcium|magnesium|aluminium|aluminum|zinc|copper|silver|gold|iron|tin|mercury|"
    r"chromium|manganese|cobalt|nickel|barium|strontium|lithium|beryllium|titanium|vanadium|platinum|palladium|"
    r"oxygen|hydrogen|nitrogen|chlorine|bromine|iodine|fluorine|sulphur|sulfur|phosphorus|carbon|silicon|boron|"
    r"arsenic|xenon|ozone|ammonia|cuprous|cupric|ferrous|ferric|stannous|stannic|mercurous|mercuric|plumbous|"
    r"green|purple|violet|blue|yellow|orange|red|brown|black|white|colourless|colorless|pink|scarlet)\b", re.I)


def named_or_coloured(cand, text) -> list:
    """Chemical names and colour words in the rewrite that the scheme does not already contain."""
    allowed = {w.lower() for w in _NAME_WORDS.findall(scheme(cand))}
    return sorted({w.lower() for w in _NAME_WORDS.findall(text)} - allowed)


# words a rewrite uses when it explains instead of stating conditions (run 11: "via an addition-elimination pathway")
_EXPLAINS = re.compile(r"\bvia\b|pathway|mechanism|\bbecause\b|\bdue to\b|\bcalled\b|\bknown as\b|\bso that\b"
                       r"|nucleophil|electrophil|\bintermediate\b", re.I)


def bare_letters(cand, text) -> list:
    """Product letters written WITHOUT angle brackets: "a salt W" instead of "a salt <W>". A letter inside a
    formula (the N of NO₂) is not one: it touches another letter, digit or subscript."""
    return [L for L in cand["_system"]["labels"].values()
            if re.search(r"(?<![<A-Za-z0-9])" + L + r"(?![>A-Za-z0-9₀-₉⁰-⁹⁺⁻])", text)]


def check_letters(cand, stem, model=IP.CHECKER) -> list:
    """Every letter GPT-6 Luna, reading only the reaction text, does not identify as the graph's species:
    [{"letter", "graph", "checker"}]. [] = all agree. A failed call holds every letter.
    stem: the opening only (question()'s res.opening), never the options: a true option such as "the oxidation
    state of Cr in Q is +3" tells the checker the answer, so the check would not be blind (review #9, 2026-11-25)."""
    D = cand["_system"]
    prompt = f"""Read this JEE Advanced inorganic question opening and identify each lettered species, written in
angle brackets such as <P> (standard textbook chemistry). Write the species actually formed (a salt as the
neutral salt, an ion with its charge).
{stem}
Return JSON: {{"species": [{{"letter": "P", "formula": "...", "charge": 0}}]}}"""
    try:
        out = models.ask_json("step_checker", model, "You are an expert inorganic chemist. Output JSON only.",
                              prompt, temperature=0.0, max_tokens=6000)
        got = {_untag(x.get("letter")): x for x in out.get("species") or [] if isinstance(x, dict)}
    except Exception as e:                          # noqa: BLE001
        return [{"letter": L, "graph": s, "checker": f"error: {str(e)[:80]}"} for s, L in D["labels"].items()]
    bad = []
    for sid, L in D["labels"].items():
        x = got.get(L) or {}
        f, q = x.get("formula"), x.get("charge")
        ok = IP.same_species(sid, f, q) or same_entity(sid, f, q)
        if not ok:                                  # another form is fine only for metal-centred facts
            fams = {fam for fam, *_ in D["facts"][L]}
            if fams <= {"magnetism", "unpaired", "moment", "d", "oxidation"}:
                ok = IP.same_answer({"edge": {"to": sid}, "element": _metal(sid) or "", "family": "magnetism"}, f, q)
        if not ok:
            bad.append({"letter": L, "graph": sid, "checker": json.dumps({"formula": f, "charge": q},
                                                                         ensure_ascii=False)})
    return bad


def same_entity(sid, formula, charge) -> bool:
    """The same coordination entity written as a salt or as the ion: Na[Ag(CN)₂] and [Ag(CN)₂]⁻, K₄[Fe(CN)₆] and
    [Fe(CN)₆]⁴⁻. Every fact a statement asks of it (metal, d electrons, spin, geometry, hybridisation) belongs to
    the entity, so both are the same answer. Live run 12 counted Na[Ag(CN)₂] as a disagreement."""
    try:
        theirs = S._complex_text(IP._graph_id(formula, charge))
        ours = S._complex_text(sid)
    except (EngineError, ValueError, TypeError, IndexError, AttributeError):
        return False
    norm = [re.sub(r"\]1([+-])$", r"]\1", x or "") for x in (ours, theirs)]
    return bool(norm[0]) and norm[0] == norm[1]


def blamed_steps(cand, bad) -> list:
    """The steps a disagreement says something about: the step that makes a misread letter, but only when the
    step's own input was read right (the start, or a letter not in bad). A failed call blames nothing. Live run 12:
    the checker misread the first step of C + Al₂O₃ + N₂ (CO and AlN both form), and the two correct steps after it
    (CO + Cl₂ → COCl₂, COCl₂ + NH₃ → urea) were blamed for its mistake."""
    D = cand["_system"]
    real = {b["letter"]: b for b in bad if not str(b.get("checker", "")).startswith("error:")}
    misread = {sid for sid, L in D["labels"].items() if L in real}
    return [(e, real[D["labels"][e["to"]]]) for e in D["steps"]
            if D["labels"].get(e["to"]) in real and e["from"] not in misread]


# ── memory across runs ───────────────────────────────────────────────────────
# Before 2026-11-25 every run forgot what earlier runs had paid to learn. Two things are kept (review item #6, the
# author's choice): reactions the blind letter check named differently (never a failed call: that says nothing
# about the reaction), and systems the BOTTOM ladder step solved (easy whatever four statements are drawn; a system
# only GLM solved may come back with new statements). Not knowledge/inorg_blocked_edges.json: that list is
# checked by hand; this one is a checker's opinion, kept with its answer for the author to review.

MEMORY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "outputs", "inorg_system_memory.json")


def load_memory(path=None) -> dict:
    """{"unconfirmed_edges": {edge id: why}, "bottom_solved": {system key: why}}; empty if no file yet."""
    try:
        with open(path or MEMORY_PATH, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        m = {}
    return {"unconfirmed_edges": dict(m.get("unconfirmed_edges") or {}),
            "bottom_solved": dict(m.get("bottom_solved") or {})}


def _remember(section, key, info, path=None):
    from core.llm import write_json_atomic
    m = load_memory(path)
    m[section][key] = {**info, "date": datetime.date.today().isoformat()}
    write_json_atomic(path or MEMORY_PATH, m, ensure_ascii=False)


def remember_unconfirmed(cand, bad, path=None) -> list:
    """Keep every step the checker named differently, from a correctly read input (blamed_steps); a failed call
    ("error: ...") is not kept. Returns the edge ids kept."""
    kept = []
    for e, b in blamed_steps(cand, bad):
        _remember("unconfirmed_edges", e["id"], {"graph": b["graph"], "checker": b["checker"]}, path)
        kept.append(e["id"])
    return kept


def remember_bottom_solved(cand, solver, stem, path=None) -> None:
    _remember("bottom_solved", cand["edges"][0], {"solver": solver, "stem": stem[:300]}, path)


# ── rewording some statements (the author, 2026-11-25) ──────────────────────
# Code's own wording is terse and samey, and once ambiguous ("geometry around S"). A model rewrites one or two of
# the four statements, chosen at random (never by which version a solver misses: the target is students, not the
# ladder), and code keeps a rewrite only if faithful() finds nothing lost or changed. Tested on 120 statements
# (tools/ab_inorganic_statements.py, reword_only): 119 kept, all checked by hand, none changed in meaning.

REWORD_MAX = 2
_VOCAB = sorted(set(SHAPES) | {"trigonal prismatic", "hexagonal planar", "pentagonal bipyramidal",
                               "distorted octahedral", "paramagnetic", "diamagnetic", "polar", "non-polar",
                               "monobasic", "dibasic", "tribasic", "same", "different", "higher", "unpaired",
                               "bond order", "oxidation state", "spin-only", "zero", "shape", "geometry", "sp", "sp2",
                               "sp3", "sp3d", "sp3d2", "sp3d3", "dsp2", "d2sp3"}, key=len, reverse=True)
_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉", "01234567890123456789")
_NEG = ("not", "never", "neither", "nor", "cannot", "isn't", "aren't", "doesn't")


def _norm(t):
    return str(t).translate(_DIGITS).lower().replace("nonpolar", "non-polar").replace("non polar", "non-polar")


def _tokens(code_text):
    """What a rewording must keep: letter tags, numbers standing alone, elements and the key chemistry words."""
    from core.engine.chem import Z_OF
    t = _norm(code_text)
    toks = set(re.findall(r"<[a-z]>", t)) | set(re.findall(r"(?<![a-z0-9.])[+-]?\d+(?:\.\d+)?(?![a-z0-9])",
                                                          re.sub(r"<[a-z]>", "", t)))
    toks |= {w for w in _VOCAB if re.search(r"(?<![a-z0-9-])" + re.escape(w) + r"(?![a-z0-9])", t)}
    toks |= {"el:" + e for e in re.findall(r"(?<![<A-Za-z])([A-Z][a-z]?)(?![a-z>])", str(code_text)) if e in Z_OF}
    return toks


def faithful(code_text, wording) -> list:
    """What a rewording lost or changed ([] = faithful): a missing tag, number, element or key word, a new
    negation, or the letters of a "higher ... than" comparison in another order."""
    w = _norm(wording)
    problems = []
    for tok in _tokens(code_text):
        if tok.startswith("el:"):
            if not re.search(r"(?<![A-Za-z<])" + tok[3:] + r"(?![a-z>])", str(wording)):
                problems.append(f"element {tok[3:]}")
        elif tok.startswith("<"):
            if tok not in w:
                problems.append(f"letter {tok}")
        elif not re.search(r"(?<![a-z0-9.-])" + re.escape(tok) + r"(?![a-z0-9]|\.\d)", w):
            problems.append(f"'{tok}'")
    for n in _NEG:
        if re.search(rf"\b{re.escape(n)}\b", w) and not re.search(rf"\b{re.escape(n)}\b", _norm(code_text)):
            problems.append(f"adds '{n}'")
    if "higher" in _norm(code_text):
        order = lambda t: re.findall(r"<[a-z]>", t)
        if order(_norm(code_text)) != order(w):
            problems.append("comparison order")
    return problems


def reword_some(cand, res, rng) -> int:
    """Rewrite one or two of the msq options in place (res.options); returns how many were kept."""
    opts = list(res.options or [])
    if len(opts) != 4:
        return 0
    pick = sorted(rng.sample(range(4), rng.randint(1, REWORD_MAX)))
    listing = "\n".join(f"{j + 1}. {opts[i]}" for j, i in enumerate(pick))
    prompt = f"""Rewrite each option below so it reads like a well-written JEE Advanced paper; do NOT copy the given
sentence. Examples of the kind of change wanted (not of content):
  "<X> has a trigonal pyramidal shape"  ->  "The shape of <X> is trigonal pyramidal"
  "S in <G> is sp² hybridised"          ->  "The S atom in <G> uses sp² hybrid orbitals"
Rules: the meaning must stay exactly the same; keep every <letter> tag, every number as digits, every element
symbol and every chemical term as written; add no negation, no facts, no hints; plain text, no LaTeX.
Reactions:
{scheme(cand)}
Options:
{listing}
Return JSON: {{"options": [{', '.join(['"..."'] * len(pick))}]}}"""
    try:
        out = models.ask_json("generator", models.GENERATOR, "You edit chemistry exam papers. Output JSON only.",
                              prompt, temperature=0.7, max_tokens=1500)
        new = [str(x).strip() for x in out.get("options") or []]
    except Exception:                               # noqa: BLE001  code's wording stays
        return 0
    kept = 0
    for j, i in enumerate(pick):
        w = new[j] if j < len(new) else ""
        if w and not faithful(opts[i], w) and _norm(w).strip(" .") != _norm(opts[i]).strip(" .") \
                and not bare_letters(cand, w):
            for tr in res.trace:
                if tr["inputs"].get("statement") == opts[i]:
                    tr["inputs"]["code wording"] = opts[i]
                    tr["inputs"]["statement"] = w
            opts[i] = w
            kept += 1
    res.options = opts
    return kept


def question(cand, rng, polish=True):
    """(stem, ChainResult, form, prose_used). The full stem: reactions (prose or scheme) + the question."""
    made = build(cand, rng)
    if made is None:
        return None
    body, res, form = made
    if polish and form == "msq" and reword_some(cand, res, rng):
        body = "Choose the correct option(s).\n" + "\n".join(f"({OPTION[i]}) {s}" for i, s in enumerate(res.options))
    opening = polish_stem(cand) if polish else None
    prose = opening is not None
    if opening is None:
        opening = "Consider the following reactions (unbalanced):\n" + scheme(cand)
    stem = f"{opening}\n{body}"
    res.asks = stem
    res.opening = opening      # the reaction text alone: what check_letters reads (the options would hint)
    return stem, res, form, prose
