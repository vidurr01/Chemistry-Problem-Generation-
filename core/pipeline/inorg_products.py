"""
inorg_products.py: the JEE Advanced "hidden products" count for INORGANIC chemistry, built by code.

    Consider the following reactions (the product asked about is the one containing the named element):
    (i)   Cu(OH)₂, heating  →  [Cu]
    (ii)  KClO₃, MnO₂, heating  →  [O]
    ...
    The number of reactions in which that product is paramagnetic is

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

N_MIN, N_MAX = 5, 8            # reactions in the list (real papers: 4 to 8)
MIN_LOOKALIKES = 2             # reactions without the value whose product is of the same kind as a true one
CHECKER = "openai/gpt-6-luna"  # names each product blind; not used elsewhere in the inorganic pipeline

# family -> (property keys of species.py it reads, stem phrase for a value)
FAMILIES = {
    "magnetism": (("metal_ion_magnetism", "complex_magnetism", "mo_magnetism"), "that product is {value}"),
    "geometry": (("shape", "central_shape", "complex_geometry"),
                 "the geometry around the named element in that product is {value}"),
    "hybridisation": (("hybridisation", "central_hybridisation", "complex_hybridisation"),
                      "the named element in that product is {value} hybridised"),
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


def _plain(text: str) -> str:
    """Plain digits and signs, no spaces: the checker writes '2−' with U+2212 and Unicode sub/superscripts."""
    return str(text or "").translate(_PLAIN).replace("−", "-").replace("–", "-").replace(" ", "")


# reagents that only repeat the start's common name (graph: "Na2B4O7", "Borax", ...)
START_NAMES = {"borax", "borazine", "dolomite"}


# parts of a graph "conditions" text that are notes, not conditions (live run 7 printed "werner's study")
_NOTE_PART = re.compile(r"mechanism|\bstud(y|ies)\b|commercial|industrial|\bvia\b|\bused (in|for)\b", re.I)


def _conditions(text) -> str:
    """The printable conditions: 'Trace alkali, push-pull mechanism.' -> 'Trace alkali';
    '50-100°C (used in baking powder).' -> '50-100°C'; "Werner's study." -> ''."""
    s = re.sub(r"\s*\([^()]*\)", lambda m: "" if _NOTE_PART.search(m.group(0)) else m.group(0),
               str(text or "").strip().rstrip("."))
    parts = [p.strip() for p in re.split(r"[;,]", s)]
    return ", ".join(p for p in parts if p and not _NOTE_PART.search(p))


def _reaction(e):
    """'Cu(OH)₂, heating' as printed (the product never shown), or None when the edge's text gives it away."""
    src = _plain(e["from"])
    reagents = [r for r in (e.get("reagents") or []) if _plain(r) != src and "dissolution" not in r
                and r.strip().lower() not in START_NAMES]
    if any(r.strip() == "M" for r in reagents):        # a placeholder metal, not a reagent a student can read
        return None
    cond = _conditions(e.get("conditions"))
    prod = S.to_formula_charge(e["to"])[0]
    if prod == S.to_formula_charge(e["from"])[0]:      # FeSO4·7H2O -> FeSO4: the start names the product
        return None
    leak = re.compile(r"(?<![A-Za-z0-9(\[])" + re.escape(prod) + r"(?![A-Za-z0-9([])")
    if any(leak.search(_plain(r)) for r in reagents):
        return None
    if cond and (leak.search(_plain(cond)) or len(cond) > 60 or re.search(r"\bvia\b|gives|forms|provides", cond)):
        cond = ""                                  # a mechanism note or the product: not printed
    return ", ".join([pretty(e["from"])] + reagents + ([cond[0].lower() + cond[1:]] if cond else []))


def _pool(graph_edges):
    """family -> [{"edge", "key", "value", "element", "text"}], one row per usable reaction."""
    out = {f: [] for f in FAMILIES}
    for e in graph_edges:
        if e.get("synthetic") or e.get("conditions_variants"):
            continue
        props = S.askable(e["to"])
        for fam, (keys, _phrase) in FAMILIES.items():
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


def draw(graph_edges, rng, tried=(), bad=()):
    """A candidate for one hidden-products question, or None. tried: keys already used; bad: edge ids the blind
    check did not confirm in this run."""
    pool = _pool([e for e in graph_edges if e["id"] not in bad])
    for _ in range(300):
        fam = rng.choice(sorted(FAMILIES))
        rows = pool[fam]
        value = rng.choice(sorted({r["value"] for r in rows}))
        have = [r for r in rows if r["value"] == value]
        lack = [r for r in rows if r["value"] != value]
        kinds = {r["key"] for r in have}
        look = [r for r in lack if r["key"] in kinds]     # same kind of product (metal salt, complex, molecule)
        n = rng.randint(N_MIN, N_MAX)
        k = rng.randint(2, n - 2)
        if len(have) < k or len(look) < MIN_LOOKALIKES:
            continue
        chosen = rng.sample(have, k) + rng.sample(look, min(len(look), rng.randint(MIN_LOOKALIKES, n - k)))
        rest = [r for r in lack if r not in chosen]
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
        truth = [r["value"] == value for r in chosen]
        return {"edges": [key], "nodes": products, "chapters": list(dict.fromkeys(r["edge"].get("chapter", "")
                                                                                     for r in chosen)),
                "txs": [t for r in chosen for t in (r["edge"].get("tx_ids") or [])], "trap_ids": [],
                "description": f"hidden products: {fam} = {value} ({n} reactions, {sum(truth)} true)",
                "_products": {"family": fam, "value": value, "rows": chosen, "truth": truth},
                "_hint": "Write the product of every reaction first; then count the electrons of the named "
                         "element in it (d electrons, lone pairs) before judging its spin or geometry."}
    return None


def question(cand):
    """(stem, ChainResult) for a candidate from draw()."""
    D = cand["_products"]
    value = D["value"].translate(_SUP_DIGITS) if D["family"] == "hybridisation" else D["value"]
    lines = [f"({ROMAN[i]}) {r['text']}  →  product containing {r['element']}" for i, r in enumerate(D["rows"])]
    stem = ("Consider the following reactions. In each, look at the product that contains the named element "
            "(balanced equations are not needed).\n" + "\n".join(lines)
            + f"\nThe number of reactions in which {FAMILIES[D['family']][1].format(value=value)} is"
              "\nGive the answer as an integer.")
    answer = sum(D["truth"])
    trace = [{"tx": r["edge"].get("tx_ids") or [], "src": r["edge"]["from"], "dst": r["edge"]["to"],
              "formula": f"product from the reaction graph ({r['edge']['id']}); {r['key']} computed by code",
              "inputs": {"reaction": r["text"], "named element": r["element"], "counted when": D["value"]},
              "outputs": {"product": r["edge"]["to"], "computed value": r["value"], "counted": t}}
             for r, t in zip(D["rows"], D["truth"])]
    traps = [{"id": f"reaction{ROMAN[i]}", "desc": f"wrong product or misjudges it in reaction ({ROMAN[i]})",
              "wrong_answer": answer + (-1 if t else 1)} for i, t in enumerate(D["truth"])]
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
        if not same_species(r["edge"]["to"], p.get("formula"), p.get("charge")) and                 not same_answer(dict(r, family=cand["_products"]["family"]), p.get("formula"), p.get("charge")):
            bad.append({"edge": r["edge"]["id"], "graph": r["edge"]["to"],
                        "checker": json.dumps({k: p.get(k) for k in ("formula", "charge")}), "reason": "differs"})
    return bad
