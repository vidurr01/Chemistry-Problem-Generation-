"""
inorg_products.py: the JEE Advanced "hidden products" count for INORGANIC chemistry, built by code.

    Consider the following reactions (the product asked about is the one containing the named element):
    (i)   Cu(OH)₂, heating  →  [Cu]
    (ii)  KClO₃, MnO₂, heating  →  [O]
    ...
    The total number of reactions in which the indicated product is paramagnetic is ____.

Three things make real Advanced inorganic questions hard (2026-11-24 analysis of the papers), and this question
has all three: the products are never named, so the student must first work out each one (hidden identity);
every product is then judged on its own (enumeration); and the property is chosen where the usual rule
misleads on some items (d⁰ Cr(VI) and d¹⁰ Zn(II) diamagnetic, O₂ paramagnetic, oxoanions tetrahedral).

Code builds everything: the reactions come from the inorganic graph (knowledge/reaction_graph_inorg.json), the
property of each product from core/engine/inorganic/species.py. Before anything is paid for, GPT-6 Luna names
each product blind (check()); a reaction it names differently is left out, so the graph's product and the one a
student would write must agree.
"""

from __future__ import annotations

import json
import os
import re

from core import models
from core.engine.base import ChainResult, EngineError
from core.engine.chem import parse_formula
from core.engine.inorganic import properties as P
from core.engine.inorganic import species as S
from core.pipeline import inorg_list as IL

# central atoms whose halides and oxides are ionic or polymeric solids (SnCl2 chains, PbCl2, AlCl3 dimer, BeCl2
# chains): VSEPR of the lone molecule is not what a book asks of the solid product, so no geometry or
# hybridisation claim on them (live run 4, 2026-11-24: PbCl2 "sp2" vs "sp3" split the solvers)
METAL_CENTRES = {"Be", "Mg", "Al", "Ga", "In", "Tl", "Sn", "Pb", "Bi"}
# products whose geometry / hybridisation code gets wrong or JEE would not ask (blind audit of 2026-11-24,
# tools/audit_inorg_props.py, ruled by the author): [Cu(NH3)4]2+ is square planar in JEE but d9 gives
# tetrahedral; PH4Br is read as one molecule, not PH4+ Br-; N2O's central atom is taken as O (and N is named
# twice); SbOCl is a layered solid
NO_SHAPE = {"[Cu(NH3)4]SO4", "[Cu(NH3)4]2+", "PH4Br", "N2O", "SbOCl"}

# reactions in the list: 4 to 5 since 2026-11-26 (was 6 to 8; real papers 4 to 8). Live review round 3: seven
# reactions made part of the difficulty the length (one slip changes the count), which the reviewer does not want
# rewarded; the hard part must be the designed traps (MIN_TRAP_ROWS of them). hp_2 with 5 had ONE trap.
N_MIN, N_MAX = 4, 5
MIN_LOOKALIKES = 2             # reactions without the value whose product is of the same kind as a true one
CHECKER = "openai/gpt-6-luna"  # names each product blind; not used elsewhere in the inorganic pipeline

# family -> (property keys of species.py it reads, stem phrase for a value)
FAMILIES = {
    "magnetism": (("metal_ion_magnetism", "complex_magnetism", "mo_magnetism"), "the indicated product is {value}"),
    "geometry": (("shape", "central_shape", "complex_geometry"),
                 "the geometry around the indicated element in its product is {value}"),
    "hybridisation": (("hybridisation", "central_hybridisation", "complex_hybridisation"),
                      "the indicated element in its product is {value} hybridised"),
}

_SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
_SUP = str.maketrans("0123456789+-", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻")
_SUP_DIGITS = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")
_PLAIN = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789" "0123456789" "+-")
ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii")


def pretty(sid: str) -> str:
    """A graph species id as printed: 'Cr2O72-' -> 'Cr₂O₇²⁻', 'Cu(OH)2' -> 'Cu(OH)₂'."""
    body, q = S.to_formula_charge(sid)
    body = re.sub(r"(?<=[A-Za-z\)\]])(\d+)", lambda m: m.group(1).translate(_SUB), body)
    if q == 0:
        return body
    return body + (str(abs(q)) if abs(q) > 1 else "").translate(_SUP) + ("+" if q > 0 else "-").translate(_SUP)


def focus(sid: str, key: str):
    """The element the question names for this product: the metal (complex, metal ion), the central atom
    (molecule, oxoanion) or the non-O atom of a diatomic. None when it cannot be told."""
    body, q = S.to_formula_charge(sid)
    try:
        counts = parse_formula(body)[0]
    except EngineError:
        return None
    if key.startswith("complex") or key.startswith("metal_ion"):
        metals = [e for e in counts if P.is_transition(e)]
        return metals[0] if len(metals) == 1 else None
    if key == "mo_magnetism":
        els = [e for e in counts if e != "O"] or list(counts)
        return els[0] if len(set(els)) == 1 and els[0] != "H" else None   # "the product containing H": any
    if key.startswith("central"):
        others = [e for e in counts if e not in ("H", "O")]
        return others[0] if len(others) == 1 else None
    try:
        return P.vsepr(body + ("" if q == 0 else f"^{abs(q)}{'+' if q > 0 else '-'}"))["central"]
    except EngineError:
        return None


def _flat(text: str) -> str:
    """Plain digits and signs, spaces KEPT: for finding a formula as a word ('gives CO2', not 'givesCO2')."""
    return str(text or "").translate(_PLAIN).replace("−", "-").replace("–", "-")


def _plain(text: str) -> str:
    """Plain digits and signs, no spaces: the checker writes '2−' with U+2212 and Unicode sub/superscripts."""
    return str(text or "").translate(_PLAIN).replace("−", "-").replace("–", "-").replace(" ", "")


# reagents that only repeat the start's common name (graph: "Na2B4O7", "Borax", ...)
START_NAMES = {"borax", "borazine", "dolomite"}


# parts of a graph "conditions" text that are notes, not conditions (live run 7 printed "werner's study"; the review
# of 2026-11-25 found "Addition-elimination" reworded into "via an addition-elimination pathway", and notes that
# name the product: "ZnO called philosopher's wool", "SiO₂ also dissolves as Na₂SiO₃")
_NOTE_PART = re.compile(
    r"mechanism|\bstud(y|ies)\b|commercial|industrial|\bvia\b|\bused (in|for)\b|pathway"
    r"|\baddition|elimination|\bnot\b|\bbut\b|\balso\b|\bcalled\b|amphoteric|dissolves|exothermic|equilibrium"
    r"|reversible|\breaction\b|double decomposition|\bproduct\b|protective|explosive|readily|\bslow in\b"
    r"|stomach|water treatment|concentration of|included|percolating|b\.p\."
    # what the product is or looks like (review 2026-11-25: "Pt(II), square planar", "purple to colourless"),
    # alternatives ("(or with KClO3/KNO3)") and explanations ("(low OH- concentration)", "(violent)")
    r"|square planar|tetrahedral|octahedral|paramagnetic|diamagnetic|colourless|\bor with\b|violent"
    r"|\b(low|high) \S+ concentration", re.I)
_NAMED = re.compile(r"\s*\(\s*[A-Z][a-z]+[A-Z]?[a-z]+-[A-Z][a-z]{2,}\s*\)")   # "(McArthur-Forrest)": a named process
_COLOUR = r"\((?:white|black|yellow|red|green|blue|brown|violet)\)"
# what drives a reaction that has no reagent (else it is a salt dissolving: 'NaBr' alone)
_DRIVER = re.compile(r"heat|therm|decompos|fus|roast|ignit|calcin|burn|electr|°C|\d\s*K\b|warm|boil|spark|"
                     r"discharge|sunlight|UV|arc|cool|unstable|high temperature", re.I)
_COLOUR_PAIR = re.compile(_COLOUR + r".*" + _COLOUR, re.I)    # "room temperature (white), boiling (black)"
_PURPOSE = re.compile(r"\s+to (lower|avoid|keep|prevent|remove|increase|reduce)\b[^,;()]*", re.I)   # "... to lower m.p."


def _conditions(text) -> str:
    """The printable conditions: 'Trace alkali, push-pull mechanism.' -> 'Trace alkali';
    '50-100°C (used in baking powder).' -> '50-100°C'; "Werner's study." -> '';
    'Electrolysis of molten NaCl with CaCl₂ to lower melting point' -> 'Electrolysis of molten NaCl with CaCl₂'."""
    s = re.sub(r"\s*\([^()]*\)", lambda m: "" if _NOTE_PART.search(m.group(0)) else m.group(0),
               str(text or "").strip().rstrip("."))
    s = _PURPOSE.sub("", _NAMED.sub("", s))
    parts = [p.strip() for p in re.split(r"[;,]", s)]
    return ", ".join(p for p in parts if p and not _NOTE_PART.search(p))


def lead_lower(cond: str) -> str:
    """'Room temperature' -> 'room temperature'; a leading formula keeps its case ('I₂ vapour', 'Pt(II)':
    the review of 2026-11-25 found 'i₂ vapour' and 'pt(II)' printed)."""
    w = re.match(r"[A-Za-z]+", cond or "")
    if w and len(w.group(0)) > 2 and w.group(0)[1:].islower() and not re.match(r"[A-Za-z]+[₀-₉0-9(\[⁺⁻]", cond):
        return cond[0].lower() + cond[1:]
    return cond


def printed_condition(e) -> str:
    """An edge's conditions as printed; '' when they name the product or are a note (mechanism, 'gives ...')."""
    cond = _conditions(e.get("conditions"))
    prod = S.to_formula_charge(e["to"])[0]
    leak = re.compile(r"(?<![A-Za-z0-9(\[])" + re.escape(prod) + r"(?![A-Za-z0-9([])")
    if cond and (leak.search(_flat(cond)) or len(cond) > 60 or re.search(r"\bvia\b|gives|forms|provides", cond)):
        return ""
    return lead_lower(cond)


def drop_repeated(reagents, cond: str) -> list:
    """Reagents the condition already names: 'CuSO₄, KI, excess KI' -> 'CuSO₄, excess KI'."""
    flat = _flat(cond)
    return [r for r in reagents
            if not re.search(r"(?<![A-Za-z0-9(\[])" + re.escape(_plain(r)) + r"(?![A-Za-z0-9(\[])", flat)]


def _reaction(e):
    """'Cu(OH)₂, heating' as printed (the product never shown), or None when the edge's text gives it away."""
    src = _plain(e["from"])
    reagents = [r for r in (e.get("reagents") or []) if _plain(r) != src and "dissolution" not in r
                and r.strip().lower() not in START_NAMES]
    if any(r.strip() == "M" for r in reagents):        # a placeholder metal, not a reagent a student can read
        return None
    if _COLOUR_PAIR.search(str(e.get("conditions") or "")):
        return None                                # two conditions, two products: no single answer
    prod = S.to_formula_charge(e["to"])[0]
    if prod == S.to_formula_charge(e["from"])[0]:      # FeSO4·7H2O -> FeSO4: the start names the product
        return None
    leak = re.compile(r"(?<![A-Za-z0-9(\[])" + re.escape(prod) + r"(?![A-Za-z0-9([])")
    if any(leak.search(_flat(r)) for r in reagents):
        return None
    cond = printed_condition(e)                    # a mechanism note or the product: not printed
    if not reagents and not _DRIVER.search(cond):
        return None                                # "NaBr", "K[PtCl₃(C₂H₄)], Pt(II)": no reaction to read
    return ", ".join([pretty(e["from"])] + drop_repeated(reagents, cond) + ([cond] if cond else []))


def _pool(graph_edges):
    """family -> [{"edge", "key", "value", "element", "text"}], one row per usable reaction."""
    out = {f: [] for f in FAMILIES}
    for e in graph_edges:
        if e.get("synthetic") or e.get("conditions_variants"):
            continue
        props = S.askable(e["to"])
        for fam, (keys, _phrase) in FAMILIES.items():
            if e.get("ask") and fam not in e["ask"]:
                continue                           # a variant whose product books write in several forms
            key = next((k for k in keys if k in props), None)
            if key is None:
                continue
            el, text = focus(e["to"], key), _reaction(e)
            if fam in ("geometry", "hybridisation") and (el in METAL_CENTRES or e["to"].split("·")[0] in NO_SHAPE):
                continue                           # Al(OH)3 came in as an oxoacid (central_shape): same rule
            if fam == "hybridisation" and e["to"] in IL.NO_HYBRID:
                continue
            if el and text:
                out[fam].append({"edge": e, "key": key, "value": props[key], "element": el, "text": text})
    return out


# Designed trap (redesign plan 2026-11-25, inorganic kind 1): at least MIN_TRAP_ROWS reactions whose start gives a
# RIVAL product in the graph (same start, another reagent or condition) that would flip the count. A student who
# works out the rival (ignores the printed condition, takes the usual reagent's product) gets the trap answer.
MIN_TRAP_ROWS = 2             # live run hp_2: one trap among 5 obvious reactions was Advanced-easy at most
VARIANTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                             "knowledge", "inorg_condition_variants.json")


def _load_variants(path=None) -> dict:
    try:
        with open(path or VARIANTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def variant_edges(path=None) -> list:
    """The condition variants of knowledge/inorg_condition_variants.json as graph-style edges (ids 'cv_...')."""
    out = []
    for v in _load_variants(path).get("variants", []):
        for i, o in enumerate(v["options"]):
            out.append({"id": f"{v['id']}_{i + 1}", "from": v["from"], "to": o["to"], "reagents": o["reagents"],
                        "conditions": o["conditions"], "chapter": v.get("chapter", ""), "tx_ids": [],
                        **({"ask": o["ask"]} if o.get("ask") else {}),
                        **({"naive": o["naive"], "naive_why": o.get("why", "")} if o.get("naive") else {})})
    return out


def with_naive(graph_edges, path=None) -> list:
    """Graph edges with the tempting wrong products of 'naive_for_graph_edges' attached (copies; graph unchanged)."""
    data = _load_variants(path)
    naive = data.get("naive_for_graph_edges", {})
    printed = data.get("print_reagents_for_graph_edges", {})   # alternatives listed as one set (live run hp_4)
    two = data.get("two_products_contain_the_element", {})     # no single "product containing X" (hp_5)
    kept_out = data.get("not_for_hidden_products", {})         # disputed by the blind check (graph audit 2026-11-26)
    out = []
    for e in graph_edges:
        if e["id"] in two or e["id"] in kept_out:
            continue
        if e["id"] in printed:
            e = {**e, "reagents": printed[e["id"]]}
        if e["id"] in naive:
            e = {**e, "naive": naive[e["id"]]["naive"], "naive_why": naive[e["id"]].get("why", "")}
        out.append(e)
    return out


def _reagent_set(e) -> set:
    src = _plain(e["from"])
    return {_plain(r).lower() for r in (e.get("reagents") or []) if _plain(r) != src}


def rivals(graph_edges) -> dict:
    """{edge id: [(rival species, how it is reached)]}: TEMPTING other products for the same start: the product of
    the same reagents under another condition (or of another heating), and the edge's own 'naive' wrong product.
    A product of different reagents (CO + Cl₂ against CO + H₂O) is not a trap: no student confuses them."""
    out = {}
    for e in graph_edges:
        if not e.get("synthetic"):
            out.setdefault(e["from"], []).append(e)
    res = {}
    for e in graph_edges:
        mine, lst = _reagent_set(e), []
        for o in out.get(e["from"], []):
            theirs = _reagent_set(o)
            if o["to"] != e["to"] and ((mine & theirs) or (not mine and not theirs)):
                cond = _conditions(o.get("conditions"))
                lst.append((o["to"], ", ".join(o.get("reagents") or []) + (f"; {cond}" if cond else "")))
        if e.get("naive"):
            lst.append((e["naive"], f"the usual product, missing that {e.get('naive_why') or 'the conditions change it'}"))
        res[e["id"]] = lst
    return res


def trap_of(row, fam, value, riv) -> dict | None:
    """The rival that flips this row's count for the asked value: {"rival", "rival_value", "via"}, or None.
    The rival's property must be of the same kind and about the same named element."""
    keys = FAMILIES[fam][0]
    for sid, via in riv.get(row["edge"]["id"], []):
        try:
            props = S.askable(sid)
        except EngineError:
            continue
        k = next((k for k in keys if k in props), None)
        if k is None or focus(sid, k) != row["element"]:
            continue
        if (props[k] == value) != (row["value"] == value):
            return {"rival": sid, "rival_value": props[k], "via": via}
    return None


MAX_SHARED = 2                 # reactions a new question may share with any accepted one (hp_10 shared 4 of 8)
# a reaction may appear in at most this many accepted questions (live review 2026-11-26: CuCl2 -> [CuCl4]2- was in
# 6 of 18 accepted, Ag + CN- in 5; MAX_SHARED only stops two questions sharing many rows)
MAX_ROW_USES = 2


def draw(graph_edges, rng, tried=(), bad=(), prefer=None, asked=(), used=None):
    """A candidate for one hidden-products question, or None. tried: keys already used; bad: edge ids the blind
    check did not confirm (this run and earlier ones); used: {edge id: accepted questions using it}. At least
    MIN_TRAP_ROWS reactions carry a designed trap (trap_of)."""
    tried = IL.tried_keys(tried)
    used = used or {}
    usable = [e for e in graph_edges if e["id"] not in bad and used.get(e["id"], 0) < MAX_ROW_USES]
    pool = _pool(usable)
    riv = rivals(usable)
    for attempt in range(300):
        # the less-used family first (live runs hp_1-6: 5 of 6 were magnetism), any family after 200 tries
        fam = prefer if (prefer in FAMILIES and attempt < 200) else rng.choice(sorted(FAMILIES))
        rows = pool[fam]
        value = rng.choice(sorted({r["value"] for r in rows}))
        trap_rows = [r for r in rows if trap_of(r, fam, value, riv)]
        if len(trap_rows) < MIN_TRAP_ROWS:
            continue
        seed = rng.sample(trap_rows, min(len(trap_rows), rng.randint(MIN_TRAP_ROWS, MIN_TRAP_ROWS + 1)))
        have = [r for r in rows if r["value"] == value and r not in seed]
        lack = [r for r in rows if r["value"] != value and r not in seed]
        kinds = {r["key"] for r in have} | {r["key"] for r in seed if r["value"] == value}
        look = [r for r in lack if r["key"] in kinds]     # same kind of product (metal salt, complex, molecule)
        n = rng.randint(N_MIN, N_MAX)
        n_true = rng.randint(2, n - 2)                 # reactions counted
        need_true = n_true - sum(r["value"] == value for r in seed)
        need_false = n - len(seed) - need_true
        if need_true < 0 or need_false < 0 or len(have) < need_true:
            continue
        n_look = min(len(look), need_false, rng.randint(MIN_LOOKALIKES, max(MIN_LOOKALIKES, need_false)))
        if n_look < min(MIN_LOOKALIKES, need_false):
            continue
        chosen = seed + rng.sample(have, need_true) + rng.sample(look, n_look)
        # no free eliminations (live run hp_1: C, S, Zn and Ag products in a d²sp³ count): every reaction gives the
        # same kind of product as the counted ones, so the student must judge each one
        rest = [r for r in lack if r not in chosen and r["key"] in kinds]
        if len(rest) < n - len(chosen):
            continue
        chosen += rng.sample(rest, n - len(chosen))
        products = [r["edge"]["to"] for r in chosen]
        starts = [r["edge"]["from"] for r in chosen]
        if len(set(products)) < n or len(set(starts)) < n:
            continue                                  # one reaction per product and per start
        if len({r["edge"].get("chapter") for r in chosen}) < 2:
            continue                                  # mix the chapters
        rng.shuffle(chosen)
        key = f"products:{fam}:{value}:" + ",".join(sorted(r["edge"]["id"] for r in chosen))
        if key in tried:
            continue
        ids = {r["edge"]["id"] for r in chosen}
        if any(len(ids & set(a)) > MAX_SHARED for a in asked):
            continue                                  # a repeat for the student (hp_10)
        truth = [r["value"] == value for r in chosen]
        traps = {i: t for i, r in enumerate(chosen) if (t := trap_of(r, fam, value, riv))}
        if len(traps) < MIN_TRAP_ROWS:
            continue
        if len({truth[i] for i in traps}) > 1:
            continue                                  # traps pushing opposite ways cancel: both mistakes, right count
        return {"edges": [key], "nodes": products, "chapters": list(dict.fromkeys(r["edge"].get("chapter", "")
                                                                                     for r in chosen)),
                "txs": [t for r in chosen for t in (r["edge"].get("tx_ids") or [])], "trap_ids": [],
                "description": f"hidden products: {fam} = {value} ({n} reactions, {sum(truth)} true)",
                "_products": {"family": fam, "value": value, "rows": chosen, "truth": truth, "traps": traps},
                "_hint": "Write the product of every reaction first; then count the electrons of the named "
                         "element in it (d electrons, lone pairs) before judging its spin or geometry."}
    return None


def question(cand):
    """(stem, ChainResult) for a candidate from draw()."""
    D = cand["_products"]
    value = D["value"].translate(_SUP_DIGITS) if D["family"] == "hybridisation" else D["value"]
    # JEE Advanced wording (reviewer, 2026-11-26): "Consider the following reactions:" and "The total number of ...
    # is" as real papers write them; was "In each, look at the product that contains the named element (balanced
    # equations are not needed)" and "The number of reactions in which that product is ..."
    lines = [f"({ROMAN[i]}) {r['text']}  →  (product containing {r['element']})" for i, r in enumerate(D["rows"])]
    stem = ("Consider the following reactions:\n" + "\n".join(lines)
            + f"\nThe total number of reactions in which {FAMILIES[D['family']][1].format(value=value)} is ____."
              "\nGive the answer as an integer.")
    answer = sum(D["truth"])
    trace = [{"tx": r["edge"].get("tx_ids") or [], "src": r["edge"]["from"], "dst": r["edge"]["to"],
              "formula": f"product from the reaction graph ({r['edge']['id']}); {r['key']} computed by code",
              "inputs": {"reaction": r["text"], "named element": r["element"], "counted when": D["value"]},
              "outputs": {"product": r["edge"]["to"], "computed value": r["value"], "counted": t}}
             for r, t in zip(D["rows"], D["truth"])]
    designed = D.get("traps") or {}
    traps = [{"id": f"rival{ROMAN[i]}", "designed": True,
              "desc": f"writes {designed[i]['rival']} for reaction ({ROMAN[i]}) ({designed[i]['via']})",
              "wrong_answer": answer + (-1 if t else 1)} for i, t in enumerate(D["truth"]) if i in designed]
    if len(designed) >= 2:                             # every designed trap taken together
        traps.append({"id": "all_rivals", "designed": True, "desc": "writes the rival product in every trap reaction",
                      "wrong_answer": answer + sum(-1 if D["truth"][i] else 1 for i in designed)})
    traps += [{"id": f"reaction{ROMAN[i]}", "desc": f"wrong product or misjudges it in reaction ({ROMAN[i]})",
               "wrong_answer": answer + (-1 if t else 1)} for i, t in enumerate(D["truth"]) if i not in designed]
    res = ChainResult(answer=answer, unit="", kind="count", asks=stem, trace=trace, traps=traps, constants=[])
    res.tolerance = 0.001
    res.options = [r["text"] for r in D["rows"]]
    res.form = f"inorganic_hidden_products:{D['family']}"
    return stem, res


# ── the blind product check ──────────────────────────────────────────────────

def same_species(sid: str, formula, charge) -> bool:
    """The graph's species and the checker's (formula, charge) are the same: same atoms and charge."""
    try:
        body, q = S.to_formula_charge(sid)
        want = parse_formula(body)[0]
        f = _plain(formula).split("·")[0].replace("^", "")
        got_body, got_q = S.to_formula_charge(f)       # 'MnO4-' written with its charge
        got_q = int(charge) if charge not in (None, "", 0, "0") else got_q
        return want == parse_formula(got_body)[0] and got_q == q
    except (EngineError, ValueError, TypeError, IndexError):
        return False


def _graph_id(formula, charge) -> str:
    """The checker's (formula, charge) as a graph-style id: ('Fe(CN)6' in brackets, -4) -> '[Fe(CN)6]4-'."""
    f = _plain(formula).split("·")[0].replace("^", "")
    body, q = S.to_formula_charge(f)
    q = int(charge) if charge not in (None, "", 0, "0") else q
    return body if q == 0 else body + (str(abs(q)) if abs(q) > 1 else "") + ("+" if q > 0 else "-")


def same_answer(row, formula, charge) -> bool:
    """The checker named another form of the same thing, which leaves the count and the working unchanged: the
    same coordination entity (K4[Fe(CN)6] and [Fe(CN)6]4-), or, with no complex on either side, the same named
    element in the same oxidation state with the same property value (CuSO4 and Cu2+, SrCrO4 and CrO4 2-).
    A salt against a complex (Cu(OH)2 against [Cu(NH3)4]SO4) is a different product, even if the count agrees."""
    try:
        sid = _graph_id(formula, charge)
        ent = [re.sub(r"\]1([+-])$", r"]\1", S._complex_text(x) or "") for x in (row["edge"]["to"], sid)]
        if ent[0] or ent[1]:
            return bool(ent[0]) and ent[0] == ent[1]
        ours, theirs = S.askable(row["edge"]["to"]), S.askable(sid)
        el = row["element"]

        def ox(x, props):                          # a 3d metal: its d electrons fix its oxidation state
            if "metal_ion_d_electrons" in props:
                return ("d", props["metal_ion_d_electrons"])
            body, q = S.to_formula_charge(x)
            return ("ox", q if body == el else props.get(f"oxidation_state:{el}"))
        keys = FAMILIES[row["family"]][0]
        vals = [next((p[k] for k in keys if k in p), None) for p in (ours, theirs)]
        oxs = [ox(row["edge"]["to"], ours), ox(sid, theirs)]
    except (EngineError, ValueError, TypeError, IndexError):
        return False
    return vals[0] is not None and vals[0] == vals[1] and oxs[0][1] is not None and oxs[0] == oxs[1]


_SPECTATORS = {"Li", "Na", "K", "Rb", "Cs"}
_EXTRA_KEYS = {"geometry": ("anion_shape",), "hybridisation": ("anion_hybridisation",),
               "magnetism": ()}                    # a salt's anion property (NaBO2's BO2-) answers the same question


def _core(sid):
    """(element counts without alkali-metal spectators, charge with them taken off) of a species id."""
    body, q = S.to_formula_charge(sid)
    counts = dict(parse_formula(body)[0])
    for el in _SPECTATORS & set(counts):
        q -= counts.pop(el)
    return counts, q


def _ox_of(props, el):
    for k in (f"oxidation_state:{el}", "complex_oxidation_state"):
        if props.get(k) is not None:
            return props[k]
    return None


_LEAD_SPECTATORS = re.compile(r"^((?:Li|Na|K|Rb|Cs)\d*)+")


def _bracketed(formula, charge) -> list:
    """The checker's species id and, if it wrote a complex without brackets ("Zn(OH)4" 2-, "K3Co(NO2)6"), the bracketed
    form the engine knows ("[Zn(OH)4]2-", "K3[Co(NO2)6]") (graph audit 2026-11-26)."""
    out = [_graph_id(formula, charge)]
    f = _plain(formula).split("·")[0].replace("^", "")
    if "[" in f or "(" not in f:
        return out
    body = re.sub(r"\d*[+-]$", "", f)
    lead = _LEAD_SPECTATORS.match(body)
    pre = lead.group(0) if lead else ""
    try:
        out.append(_graph_id(f"{pre}[{body[len(pre):]}]", charge))
    except (EngineError, ValueError, TypeError, IndexError):
        pass
    return out


def other_form(row, formula, charge) -> bool:
    """The checker wrote the same product in another form that cannot change the count (live review 2026-11-26,
    round 2: 2 of 5 refusals were Na2ZnO2 vs [Zn(OH)4]2- and BO2- vs NaBO2): the formulas differ only by alkali-metal
    spectator ions and whole H2O, the named element keeps its oxidation state, and the asked property computed by
    the engine is the same for both. SO2 vs H2SO3 with geometry asked (bent vs pyramidal) stays refused."""
    try:
        ours, theirs = row["edge"]["to"], _graph_id(formula, charge)
        (a, qa), (b, qb) = _core(ours), _core(theirs)
        if qa != qb:
            return False
        diff = {el: b.get(el, 0) - a.get(el, 0) for el in set(a) | set(b)}
        n = diff.get("O", 0)
        if any(v for el, v in diff.items() if el not in ("H", "O")) or diff.get("H", 0) != 2 * n:
            return False
        pa = S.askable(ours)
        el = row["element"]
        keys = FAMILIES[row["family"]][0] + _EXTRA_KEYS.get(row["family"], ())
        va = next((pa[k] for k in keys if k in pa), None)
        if _ox_of(pa, el) is None or va is None:
            return False
        for alt in _bracketed(formula, charge):
            try:
                pb = S.askable(alt)
            except (EngineError, ValueError, TypeError, IndexError, KeyError):
                continue
            vb = next((pb[k] for k in keys if k in pb), None)
            if _ox_of(pb, el) == _ox_of(pa, el) and vb == va:
                return True
        return False
    except (EngineError, ValueError, TypeError, IndexError, KeyError):
        return False


def check(cand, model: str = CHECKER) -> list:
    """Every reaction GPT-6 Luna does not name the graph's product for: [{"edge", "graph", "checker", "reason"}].
    [] means all agree. A failed call holds every reaction (never a pass)."""
    rows = cand["_products"]["rows"]
    listing = "\n".join(f"{i + 1}. {r['text']}  ->  the product containing {r['element']}" for i, r in enumerate(rows))
    prompt = f"""Inorganic reactions (JEE Advanced / NCERT, standard textbook outcome). For each, name the product that
contains the named element (the main one if the reaction gives several containing it). Write its formula as the
species actually formed (a salt as the neutral salt, an ion in solution as the ion with its charge).
{listing}
Return JSON: {{"products": [{{"n": 1, "formula": "e.g. K2MnO4 or MnO4", "charge": 0, "sure": true}}, ...]}}"""
    try:
        out = models.ask_json("step_checker", model, "You are an expert inorganic chemist. Output JSON only.",
                              prompt, temperature=0.0, max_tokens=6000)
        got = {int(p.get("n")): p for p in out.get("products") or [] if isinstance(p, dict)}
    except Exception as e:                        # noqa: BLE001  a failed call is a result, never a pass
        return [{"edge": r["edge"]["id"], "graph": r["edge"]["to"], "checker": f"error: {str(e)[:100]}",
                 "reason": "call failed"} for r in rows]
    bad = []
    for i, r in enumerate(rows, 1):
        p = got.get(i) or {}
        row = dict(r, family=cand["_products"]["family"])
        if not same_species(r["edge"]["to"], p.get("formula"), p.get("charge")) and \
                not same_answer(row, p.get("formula"), p.get("charge")) and \
                not other_form(row, p.get("formula"), p.get("charge")):
            bad.append({"edge": r["edge"]["id"], "graph": r["edge"]["to"],
                        "checker": json.dumps({k: p.get(k) for k in ("formula", "charge")}), "reason": "differs"})
    return bad
