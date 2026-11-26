"""
org_qfirst.py — the question-first flow for ORGANIC chemistry (same pattern as inorg_qfirst.py and physical's qfirst.py).

    draw       a real starting molecule (core/engine/organic/pool.py) and a reaction SCHEME of 4-6 steps: a main chain
               with one or two branch points (R → S with one reagent and R → T with another, each branch going on);
               every step computed by its RDKit rule (core/engine/organic/rules.py); compounds labelled P, Q, R, ...
    design     the designer (models.DESIGNER) plans the question: which compounds it asks about, which property
               (structure, formula, stereocentres, tests ...), the format and the trap; Jev's design check
    write      the writer (models.GENERATOR) writes the lead, the question line and every option as a CLAIM
               (compound label, property, value); the scheme itself is printed by code (exact reagents and labels)
    evaluate   code decides every claim (core/engine/organic/props.py), so the key is code's ("the coder")
    judge      flow.judge: the same ladder, grading by code, hold rule; accepted -> saved

Formats: msq (4 claims, 1-3 true), mcq_correct (exactly one true), count (4-8 claims, how many are true), integer
(a numeric property of one compound, e.g. the number of stereoisomers of U).
"""

from __future__ import annotations

import json
import os
import re
import random

from core import dedup, models
from core.engine.base import ChainResult, EngineError
from core.engine.organic import pool as P
from core.engine.organic import props as OP
from core.engine.organic import rules as R
from core.engine.organic.labels import REAGENT_LABEL
from core.engine.organic.mol import canon
from core.pipeline import queues
from core.llm import CutOffError

MAX_DRAWS = 6
# Schemes tried per picked starting molecule (the author, 2026-11-24): the picker is ~60 % of a run's cost, a
# further scheme from the same molecule is free code plus ~Rs 0.2 of step check (runs 12-13 held every scheme).
SCHEMES_PER_START = 3
STEPS_MIN, STEPS_MAX = 4, 6       # the author, 2026-11-23 (was 5-8)
MAX_BRANCHES = 2
LETTERS = "ABCD"
LABELS = "PQRSTUVWXYZ"
FORMATS = ("msq", "mcq_correct", "count", "integer")
CLAIM_RETRIES = 1
# Hardness by code (the author, 2026-11-24): live run 6's options were one-step checks that no selectivity step
# decided. A "hinge" statement is true for the right structure and false for a tempting wrong one (or the reverse):
# a scheme needs at least MIN_HINGE such facts to be drawn, and a question at least MIN_HINGE such statements.
MIN_HINGE = 2
# O2 (live review 2026-11-26): statements no wrong turn flips are rote fillers ("NaCN gives a nitrile"); both accepted
# questions of the review had two of four. At most this many per 4 statements now.
MAX_ROTE_PER_4 = 1
# Reagent reuse: a reaction already in this many accepted questions is not drawn (AgNO2 -> nitro was in 6 of 10
# accepted, Br2/H2O, CH3COCl and HBr in 4 each; the same trap again is rote for a student who has seen it).
MAX_EDGE_USES = 2
# Blind per-step check (core/pipeline/org_step_check.py, the author 2026-11-24): measured on known-good and
# known-bad steps before use; a step GPT-6 Luna does not confirm holds the scheme (queue step_disagreement).
STEP_CHECK = True
_NOT_HINGE = {"structure", "molar_mass"}          # a SMILES or a mass is not how a JEE statement is decided
_NUMERIC = {k for k, v in OP.PROPERTIES.items() if v == "number"}


# ── draw ─────────────────────────────────────────────────────────────────────

# Only edges with an approved scope are drawn (the author, 2026-11-24): the 62 without one fire on any molecule
# that has their group. They come back one by one as their scopes are approved (tools/apply_rule_scope.py).
TRUSTED_ONLY = True


def _graph(adapter):
    """Ruled edges by start node. Used by the draw and by the start picker's check and reaction menu."""
    from core.engine.organic.scope import trusted
    if not hasattr(adapter, "_g"):
        with open(adapter.config["graph_path"], encoding="utf-8") as f:
            g = json.load(f)
        out = {}
        for e in g["edges"]:
            if e["id"] in R.RULES and (trusted(e) or not TRUSTED_ONLY):
                out.setdefault(e["from"], []).append(e)
        adapter._g = {"out": out, "edges": {e["id"]: e for e in g["edges"]}}
    return adapter._g


def _single(smiles: str) -> bool:
    return "." not in smiles


def _heavy(smiles: str) -> int:
    """Heavy atoms of an organic molecule (0 if it has no carbon)."""
    from rdkit import Chem
    m = Chem.MolFromSmiles(smiles)
    if m is None or not any(a.GetAtomicNum() == 6 for a in m.GetAtoms()):
        return 0
    return m.GetNumHeavyAtoms()


def _main_piece(r) -> bool:
    """When a step splits the molecule, the lettered compound must be strictly the largest organic piece (live run 9,
    2026-11-24: an aryl acetate's hydrolysis called acetic acid "S", so a student taking the phenol got the key
    wrong; HI on anisole likewise gave CH3I as the product). Equal pieces (Cannizzaro) are ambiguous too."""
    from core.pipeline.org_step_check import SMALL
    own = _heavy(r.product)
    for co in r.coproducts or ():
        if canon(co) not in SMALL and _heavy(co) and _heavy(co) >= own:
            return False
    return True


def _step(g, node, smiles, seen, rng, avoid=()):
    """One applicable edge from this compound to a new single compound: (edge, result) or None. The edges of
    EVERY node the compound belongs to are tried (a keto-ester can take ketone and ester steps), not only the
    node it was reached as."""
    from core.engine.organic.mol import classes
    nodes = [node] + sorted(classes(smiles) - {node})
    nxt, ids = [], set()
    for n in nodes:
        for e in g["out"].get(n, []):
            if e["id"] not in avoid and e["id"] not in ids:
                ids.add(e["id"])
                nxt.append(e)
    rng.shuffle(nxt)
    for e in nxt:
        try:
            r = R.apply(e, smiles)
        except EngineError:
            continue
        c = canon(r.product)
        if not _single(r.product) or c in seen:
            continue
        if not _main_piece(r):                    # the molecule splits and the letter is not clearly the main piece
            continue
        if _heavy(r.product) * 2 < _heavy(smiles):   # most of the skeleton is gone (live run 10: HI on a methyl
            continue                              # ether, "T = CH3I"; a rule may not list the other piece)
        try:
            OP.askable(r.product)
        except EngineError:
            continue
        return e, r
    return None


def decorative_steps(comps, order) -> list:
    """O1 (live review 2026-11-26): labels X whose step changes nothing: every child of X comes out the same when its
    reagent acts on X's parent directly (round 1: Q --NaI--> R --NaCN--> S, and NaCN on Q gives the same S). A last
    compound (no child) is never decorative: it is what the question can ask about."""
    out = []
    for x in order[1:]:
        kids = [k for k in order if comps[k]["parent"] == x]
        par = comps[x]["parent"]
        if not kids or par is None:
            continue
        same = True
        for k in kids:
            try:
                r = R.apply(comps[k]["edge"], comps[par]["smiles"])
                same = same and _single(r.product) and canon(r.product) == comps[k]["smiles"]
            except EngineError:
                same = False
            if not same:
                break
        if same:
            out.append(x)
    return out


def overused_edges(adapter) -> set:
    """Edge ids already in MAX_EDGE_USES accepted organic questions (engine graph_edges of the output file)."""
    import collections
    p = adapter.config.get("output_file", "")
    try:
        with open(p, encoding="utf-8") as f:
            recs = json.load(f)
    except (OSError, ValueError, TypeError):
        return set()
    c = collections.Counter(e for r in recs if isinstance(r, dict) and not r.get("rejected")
                            for e in ((r.get("engine") or {}).get("graph_edges") or []))
    return {e for e, n in c.items() if n >= MAX_EDGE_USES}


MAX_SHARED_COMPOUNDS = 2   # compounds a new scheme may share with any accepted one (batch 2026-11-26: a nitrile start
                           # became the accepted 4-(2-bromoethyl)benzaldehyde question after one DIBAL-H step: 4 shared)
_SCHEME_LINE = re.compile(r"^([A-Z]) --\[(.+)\]--> ([A-Z])$")


def scheme_compounds(rec: dict, g: dict) -> set:
    """Canonical SMILES of every compound of an accepted question's scheme, replayed from its printed scheme lines
    (in order, one per graph edge) and its start; empty if the record cannot be replayed."""
    eng = rec.get("engine") or {}
    start = (eng.get("givens") or {}).get("start")
    ids = eng.get("graph_edges") or []
    lines = [m for ln in str(rec.get("question") or "").splitlines() if (m := _SCHEME_LINE.match(ln.strip()))]
    seen_lines, steps = set(), []
    for m in lines:                                  # a scheme printed twice (fixed 2026-11-26) counts once
        if m.group(0) not in seen_lines:
            seen_lines.add(m.group(0))
            steps.append(m)
    if not start or not ids or len(steps) != len(ids):
        return set()
    smi = {"P": canon(start)}
    try:
        for m, eid in zip(steps, ids):
            parent, child = m.group(1), m.group(3)
            smi[child] = canon(R.apply(g["edges"][eid], smi[parent]).product)
    except (EngineError, KeyError):
        return set()
    return set(smi.values())


def accepted_compound_sets(adapter) -> list:
    """scheme_compounds of every accepted (not rejected) organic question, read once per run."""
    if not hasattr(adapter, "_accepted_sets"):
        try:
            with open(adapter.config.get("output_file", ""), encoding="utf-8") as f:
                recs = json.load(f)
        except (OSError, ValueError, TypeError):
            recs = []
        g = _graph(adapter)
        sets = [scheme_compounds(r, g) for r in recs if isinstance(r, dict) and not r.get("rejected")]
        adapter._accepted_sets = [x for x in sets if x]
    return adapter._accepted_sets


def draw(adapter, rng, tried=(), start=None, attempts=800, avoid=(), accepted=()):
    """A scheme of STEPS_MIN..STEPS_MAX steps with 1..MAX_BRANCHES branch points. A candidate dict, or None.
    start=(name, smiles): build from that molecule (the start picker's); otherwise a random pool molecule.
    avoid: edge ids never used (overused_edges). accepted: compound sets of accepted questions
    (accepted_compound_sets); a scheme sharing more than MAX_SHARED_COMPOUNDS with one is a near-copy."""
    from core.engine.organic.mol import classes
    avoid = set(avoid)
    g = _graph(adapter)
    starts = [n for n in P.POOL if g["out"].get(n)]
    if start is not None:
        nodes0 = sorted(n for n in classes(start[1]) if g["out"].get(n))
        if not nodes0:
            return None
    for _ in range(attempts):
        if start is None:
            node0 = rng.choice(starts)
            name, start_smi = rng.choice(P.POOL[node0])
        else:
            node0 = rng.choice(nodes0)
            name, start_smi = start
        target = rng.randint(STEPS_MIN, STEPS_MAX)
        # compounds: label -> {"smiles", "node", "parent", "edge", "result"}
        comps = {"P": {"smiles": canon(start_smi), "node": node0, "parent": None, "edge": None, "result": None}}
        seen = {canon(start_smi)}
        order = ["P"]
        main = ["P"]
        main_len = rng.randint(3, target - 1)
        while len(main) - 1 < main_len:
            cur = comps[main[-1]]
            got = _step(g, cur["node"], cur["smiles"], seen, rng, avoid=avoid)
            if got is None:
                break
            e, r = got
            lab = LABELS[len(order)]
            comps[lab] = {"smiles": canon(r.product), "node": e["to"], "parent": main[-1], "edge": e, "result": r}
            seen.add(canon(r.product))
            order.append(lab)
            main.append(lab)
        if len(main) - 1 < 3:
            continue
        branches = 0
        for _try in range(10):
            if len(order) - 1 >= target or branches >= MAX_BRANCHES:
                break
            at = rng.choice(main[1:-1])               # branch from an intermediate (P → Q → R, then R → S and R → T)
            used = {comps[k]["edge"]["id"] for k in order if comps[k]["parent"] == at}
            got = _step(g, comps[at]["node"], comps[at]["smiles"], seen, rng, avoid=used | avoid)
            if got is None:
                continue
            branches += 1
            tip = at
            e, r = got
            while got is not None and len(order) - 1 < target and len(order) < len(LABELS):
                e, r = got
                lab = LABELS[len(order)]
                comps[lab] = {"smiles": canon(r.product), "node": e["to"], "parent": tip, "edge": e, "result": r}
                seen.add(canon(r.product))
                order.append(lab)
                tip = lab
                if rng.random() < 0.5:
                    break
                got = _step(g, comps[tip]["node"], comps[tip]["smiles"], seen, rng, avoid=avoid)
        n_steps = len(order) - 1
        if branches == 0 or not STEPS_MIN <= n_steps <= STEPS_MAX:
            continue
        key = tuple(comps[k]["edge"]["id"] for k in order[1:])
        if key in tried:
            continue
        if decorative_steps(comps, order):
            continue                                  # a step that changes nothing (O1)
        mine = {comps[k]["smiles"] for k in order}
        if any(len(mine & a) > MAX_SHARED_COMPOUNDS for a in accepted):
            continue                                  # a near-copy of an accepted question
        cand = _candidate(comps, order, name, start_smi, branches)
        if len({(h[0], h[1]) for h in cand["_hinge"]}) < MIN_HINGE or len(hinge_sources(cand)) < MIN_HINGE:
            continue                                  # fewer than two steps where a wrong turn changes a fact: not hard
        return cand
    return None


def _candidate(comps, order, name, start_smi, branches) -> dict:
    """The candidate dict for a built scheme (draw, and rebuild() for a resumed run)."""
    path = [comps[k]["edge"] for k in order[1:]]
    chapters = list(dict.fromkeys(e.get("chapter", "") for e in path))
    txs = [t for e in path for t in (e.get("tx_ids") or [])]
    cand = {"edges": [e["id"] for e in path], "nodes": [comps[k]["node"] for k in order], "chapters": chapters,
            "txs": txs, "trap_ids": [], "_comps": comps, "_order": order, "_start": (name, canon(start_smi)),
            "description": f"{name}: {len(order) - 1} steps, {branches} branch point(s)",
            "_hint": "Work out every lettered compound in order, deciding at each step which product is major; "
                     "only then judge each statement about it."}
    cand["_props"] = {k: OP.askable(comps[k]["smiles"]) for k in order}
    cand["_wrong"] = wrong_structures(cand)
    cand["_hinge"] = hinge_facts(cand)
    return cand


# ── checkpoint: resume a run at the stage where it stopped (the author, 2026-11-25) ──
# After every paid stage the run writes what it has (the scheme as start + edges, the design, the question) to
# CHECKPOINT. `run_groundup_final.py --subject organic --resume` rebuilds the scheme with the engine (free: the
# rules are deterministic) and goes on from the next stage, so a fix is checked on the very case that failed.

CHECKPOINT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "outputs", "org_checkpoint.json")


def scheme_spec(cand) -> dict:
    return {"start": list(cand["_start"]),
            "steps": [[k, cand["_comps"][k]["parent"], cand["_comps"][k]["edge"]["id"]] for k in cand["_order"][1:]]}


def save_checkpoint(stage: str, cand, **data) -> None:
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump({"stage": stage, "scheme": scheme_spec(cand), **data}, f, ensure_ascii=False, indent=1)


def clear_checkpoint() -> None:
    if os.path.exists(CHECKPOINT):
        os.remove(CHECKPOINT)


def rebuild(adapter, spec: dict) -> dict:
    """The candidate of a saved scheme, every step recomputed by today's rules and scopes. EngineError if a step
    no longer applies (the fix changed the scheme)."""
    from core.engine.organic.mol import classes
    g = _graph(adapter)
    name, start_smi = spec["start"]
    comps = {"P": {"smiles": canon(start_smi), "node": None, "parent": None, "edge": None, "result": None}}
    order = ["P"]
    for lab, parent, eid in spec["steps"]:
        e = g["edges"][eid]
        r = R.apply(e, comps[parent]["smiles"])
        comps[lab] = {"smiles": canon(r.product), "node": e["to"], "parent": parent, "edge": e, "result": r}
        order.append(lab)
    first = comps[order[1]]["edge"]["from"]
    comps["P"]["node"] = first if first in classes(start_smi) else sorted(classes(start_smi))[0]
    parents = [comps[k]["parent"] for k in order[1:]]
    branches = sum(1 for p in set(parents) if parents.count(p) > 1)
    return _candidate(comps, order, name, start_smi, branches)


def load_checkpoint(adapter):
    """(cand, saved checkpoint) from CHECKPOINT, or None when there is nothing to resume."""
    if not os.path.exists(CHECKPOINT):
        print("  [resume] no checkpoint: a normal run")
        return None
    with open(CHECKPOINT, encoding="utf-8") as f:
        cp = json.load(f)
    try:
        cand = rebuild(adapter, cp["scheme"])
    except EngineError as e:
        print(f"  [resume] the saved scheme no longer builds ({e}): a normal run")
        return None
    print(f"  [resume] from after stage '{cp['stage']}' of {cand['description']}")
    return cand, cp


def _wrong_props(cand) -> dict:
    """label -> [(wrong SMILES, why, its properties)] (cached on the candidate)."""
    if "_wrong_props" not in cand:
        out = {}
        for lab, ws in cand["_wrong"].items():
            for w, how in ws.items():
                try:
                    out.setdefault(lab, []).append((w, how, OP.askable(w)))
                except EngineError:
                    continue
        cand["_wrong_props"] = out
    return cand["_wrong_props"]


def hinge_facts(cand) -> list:
    """(label, property, right value, wrong value, why) for every property a tempting wrong structure changes."""
    out = []
    for lab, rows in _wrong_props(cand).items():
        right = cand["_props"][lab]
        for w, how, wp in rows:
            for prop, v in right.items():
                if prop in _NOT_HINGE or prop not in wp or wp[prop] == v:
                    continue
                out.append((lab, prop, v, wp[prop], how))
    return out


def _source(how: str) -> str:
    """The step a wrong turn is taken at ("wrong turn at R (...)" -> "R")."""
    m = re.match(r"wrong turn at (\S+)", how)
    return m.group(1) if m else how


def hinge_sources(cand) -> set:
    """The steps whose wrong turn changes at least one checkable fact."""
    return {_source(h[4]) for h in cand.get("_hinge") or []}


def claim_sources(cand, lab: str, prop: str, value) -> set:
    """The steps at which a wrong turn flips this statement's truth (empty: no wrong turn changes it)."""
    if prop in _NOT_HINGE:
        return set()
    right = OP.compare(prop, cand["_props"][lab][prop], value)
    return {_source(how) for _w, how, wp in _wrong_props(cand).get(lab, [])
            if prop in wp and OP.compare(prop, wp[prop], value) != right}


def claim_hinges(cand, lab: str, prop: str, value) -> bool:
    """The statement's truth differs between the right structure and some tempting wrong one."""
    return bool(claim_sources(cand, lab, prop, value))


def wrong_structures(cand) -> dict:
    """label -> {wrong SMILES: why}: what a student assigns to that compound after one wrong turn (a step's
    selectivity trap, carried through the later steps to that compound)."""
    comps, out = cand["_comps"], {}

    def descendants_path(src, dst):
        path, k = [], dst
        while k != src and k is not None:
            path.append(k)
            k = comps[k]["parent"]
        return list(reversed(path)) if k == src else None
    for lab in cand["_order"][1:]:
        r = comps[lab]["result"]
        for tname, t in r.traps.items():
            if not _single(t):
                continue
            for dst in cand["_order"]:
                p = descendants_path(lab, dst) if dst != lab else []
                if p is None:
                    continue
                cur = t
                for k in p:
                    try:
                        cur = R.apply(comps[k]["edge"], cur).product
                    except EngineError:
                        cur = None
                        break
                if cur and _single(cur) and canon(cur) != comps[dst]["smiles"]:
                    out.setdefault(dst, {})[canon(cur)] = f"wrong turn at {lab} ({tname})"
    return out


def scheme_text(cand) -> str:
    """The scheme as printed in the question (code writes it: exact reagents and labels)."""
    comps = cand["_comps"]
    lines = [f"P = {cand['_start'][0]}"]
    for lab in cand["_order"][1:]:
        c = comps[lab]
        e = c["edge"]
        reag = REAGENT_LABEL[e["id"]]
        lines.append(f"{c['parent']} --[{reag}]--> {lab}")
    return "\n".join(lines)


def _props_line(p: dict) -> str:
    keep = []
    for k, v in p.items():
        if k == "functional_group":
            v = ", ".join(v)
        keep.append(f"{k}={v}")
    return "; ".join(keep)


def facts_text(cand) -> str:
    """Every compound with its structure and the properties code computes (for the designer and writer only)."""
    lines = []
    for lab in cand["_order"]:
        c = cand["_comps"][lab]
        why = f"   ({c['result'].why})" if c["result"] else ""
        lines.append(f"{lab}: {c['smiles']}{why}\n   {_props_line(cand['_props'][lab])}")
        for w, how in cand["_wrong"].get(lab, {}).items():
            lines.append(f"   tempting wrong structure for {lab}: {w} ({how})")
    hinge = cand.get("_hinge") or []
    if hinge:
        lines.append(f"\nDECISIVE FACTS (a student who took the wrong turn gets these wrong; at least {MIN_HINGE} "
                     f"statements must test them, from at least {MIN_HINGE} DIFFERENT steps; the code checks this):")
        seen = set()
        for lab, prop, right, wrong, how in sorted(hinge, key=lambda h: (_source(h[4]), h[0], h[1])):
            if (lab, prop, _source(how)) in seen:
                continue
            seen.add((lab, prop, _source(how)))
            lines.append(f"   [step {_source(how)}] {lab}: {prop} is {right} (wrong turn gives {wrong}; {how})")
    return "\n".join(lines)


# ── design ───────────────────────────────────────────────────────────────────

def design_question(subject_name: str, cand) -> dict:
    from core.pipeline.qf_design import finish_design
    prompt = f"""You are a senior JEE Advanced {subject_name} paper setter. DESIGN (do not write) ONE question that would
sit among the hardest of a real paper, on this reaction scheme (computed by code, true chemistry):
{scheme_text(cand)}

What each compound is, with the properties code can check (the answer key comes ONLY from these):
{facts_text(cand)}

The student sees only the scheme: P is named, every other compound is a letter. The question asks about properties
of compounds anywhere in the scheme (start, middle, branches, ends): structure, molecular formula, number of
stereocentres or stereoisomers, π bonds, tests (iodoform, Tollens', Fehling's, NaHCO₃, FeCl₃, Lucas, carbylamine,
2,4-DNP, bromine water), class of amine, functional group. WHAT MAKES IT HARD: a statement that is decided only if
the student got a branch or a selectivity step right (the tempting wrong structures above show where students slip).
At least {MIN_HINGE} statements must be DECISIVE FACTS that depend on at least {MIN_HINGE} DIFFERENT steps (each fact in
the list names its step), so the student must get two separate decisions right; two statements on the same step
test one decision twice. An integer must change under wrong turns at {MIN_HINGE} different steps. Code rejects the
question otherwise. A statement any student gets right without that step (e.g. a C=C every route keeps) does not
count, and at most ONE statement in four may be such a filler.

Choose the format: "msq" (4 statements, 1-3 true), "mcq_correct" (4 statements, exactly one true), "count" (4-8
statements, "how many are correct"), "integer" (one numeric property of one compound).

If no hard question can be built on this scheme, return only {{"impossible": "why"}}.

LENGTH: your thinking and the design TOGETHER must not exceed 2000 words.

Return JSON:
{{"system": "the scheme as the student meets it", "hidden": {{"Q": "what Q is", "...": "..."}},
  "hidden_link": "what the student must work out", "route": "how a solver reaches the answer",
  "student_must_notice": "the step that decides it", "trap": "the tempting wrong answer and why",
  "given": "the scheme", "asked": "which compounds and properties", "format": "msq|mcq_correct|count|integer",
  "why_hard": "one sentence"}}"""
    think = {"max_tokens": models.GEMINI3_DESIGN_CAP,
             **({"reasoning_effort": models.GEMINI3_DESIGN_LEVEL} if models.GEMINI3_DESIGN_LEVEL else {})} \
        if models.DESIGNER.startswith("google/gemini-3") else {"max_tokens": 8000}
    try:
        d = models.ask_json("designer", models.DESIGNER, "You design hard chemistry exam questions. Output JSON only.",
                            prompt, temperature=0.8, retry_cut_off=False, **think)
    except CutOffError as e:
        d = finish_design(prompt, e)
    if d.get("impossible") and not d.get("system"):
        return {"impossible": str(d["impossible"])}
    if not d.get("system"):
        raise ValueError("the designer returned no usable design")
    d["format"] = d.get("format") if d.get("format") in FORMATS else "msq"
    d["hidden"] = {str(k): str(v) for k, v in (d.get("hidden") or {}).items()}
    d.setdefault("situation", d["system"])
    d.setdefault("insight", d.get("student_must_notice", ""))
    d.setdefault("links", d.get("route", ""))
    return d


# ── write ────────────────────────────────────────────────────────────────────

def write_question(subject_name: str, cand, design, feedback: str | None = None) -> dict:
    fmt = design["format"]
    shape = {"msq": 'exactly 4 "claims", 1 to 3 true', "mcq_correct": 'exactly 4 "claims", exactly one true',
             "count": '4 to 8 "claims", not all true and not all false',
             "integer": 'one "claim" with compound and property only (a numeric property); no value',
             "amount": 'no claims ("claims": []); write only "lead" (one plain sentence before the scheme) and '
                       '"ask": "-" (code writes the question line: the mass of a compound from a mass of P)'}[fmt]
    redo = f"\nYour previous draft was rejected: {feedback}\nFix exactly that.\n" if feedback else ""
    # real JEE Advanced stems of this format, for wording only (reviewer, 2026-11-26; style_examples.copied rejects
    # a draft that copies one)
    import random as _random
    from core.pipeline import style_examples
    examples = style_examples.stems("organic", fmt, _random.Random())
    prompt = f"""Write ONE JEE Advanced {subject_name} question from this design, worded exactly as a real JEE Advanced paper
words its questions. Plain text, Unicode subscripts, no LaTeX.

DESIGN:
{json.dumps({k: design.get(k) for k in ("system", "hidden", "hidden_link", "student_must_notice", "trap", "asked", "format")}, ensure_ascii=False, indent=1)}

The scheme (code prints it in the question exactly like this):
{scheme_text(cand)}

What each compound is and the properties code checks (NEVER reveal these in the question):
{facts_text(cand)}
{redo}
Rules:
- "lead": one or two sentences before the scheme (no structures, no names of lettered compounds except P).
- "ask": the question line after the scheme (e.g. "Which of the following statements is/are correct?").
- Format "{fmt}": {shape}. Each claim: "compound" (a letter of the scheme), "property" (a key from the list exactly:
  {", ".join(OP.PROPERTIES)}), "value" (what the statement asserts: a number, true/false, a formula, a SMILES for
  "structure", a group name for "functional_group"), and "text" (the statement as printed). A false claim states a
  WRONG value on purpose (a tempting wrong structure or property where possible).
- Do not write option letters or the answer; code adds them.
{style_examples.block(examples)}
Return JSON: {{"lead": "...", "ask": "...", "format": "{fmt}",
  "claims": [{{"text": "...", "compound": "S", "property": "...", "value": "..."}}]}}"""
    out = models.ask_json("generator", models.GENERATOR, "You write chemistry exam questions. Output JSON only.",
                          prompt, temperature=0.4, max_tokens=4000)
    if not out.get("ask") or not isinstance(out.get("claims"), list):
        raise ValueError("the writer returned no question or claims")
    out["format"] = fmt
    out["_style_examples"] = examples
    return out


# ── evaluate (the answer key, by code) ───────────────────────────────────────

def evaluate(cand, q) -> tuple:
    """(result, problems). Every claim decided by code; problems the writer can fix are listed."""
    fmt = q["format"]
    if fmt == "amount":                            # keyed by code from the target the run chose (no claims)
        lab = q.get("_amount_target")
        if not lab or lab not in cand["_comps"]:
            return None, ["amount: no target compound"]
        seed = sum(ord(c) for c in "".join(cand["edges"]) + lab)
        nums, res = amount_result(cand, lab, random.Random(seed))
        q["_amount"] = nums
        return res, []
    rows = [r for r in q.get("claims") or [] if isinstance(r, dict)]
    problems = []
    need = {"msq": (4, 4), "mcq_correct": (4, 4), "count": (4, 8), "integer": (1, 1)}[fmt]
    if not need[0] <= len(rows) <= need[1]:
        problems.append(f"format {fmt} needs {need[0]}" + (f" to {need[1]}" if need[1] != need[0] else "")
                        + f" claims, the draft has {len(rows)}")
    text = f"{q.get('lead', '')} {q.get('ask', '')}"
    from core.pipeline import style_examples
    every = text + " " + " ".join(str(r.get("text", "")) for r in rows)
    hit = style_examples.copied(every, q.get("_style_examples"))
    if hit:
        problems.append(f"the draft copies the wording of a real JEE question (\"{hit}\"): use the real questions "
                        f"for style only and write your own sentences")
    for lab in cand["_order"][1:]:
        if cand["_comps"][lab]["smiles"] in text:
            problems.append(f"the lead or question shows the structure of {lab}")
    truth, trace = [], []
    for i, r in enumerate(rows):
        lab, prop = str(r.get("compound") or "").strip(), str(r.get("property") or "").strip()
        if lab not in cand["_props"]:
            problems.append(f"claim {i + 1}: compound {lab!r} is not a letter of the scheme")
            truth.append(None)
            continue
        props = cand["_props"][lab]
        if prop not in props:
            problems.append(f"claim {i + 1}: property {prop!r} is not computed for {lab} "
                            f"(computed: {', '.join(props)})")
            truth.append(None)
            continue
        if fmt == "integer":
            if prop not in _NUMERIC:
                problems.append(f"integer: {prop!r} is not a numeric property")
            truth.append(props[prop])
            continue
        ok = OP.compare(prop, props[prop], r.get("value"))
        if ok is None:
            problems.append(f"claim {i + 1}: value {r.get('value')!r} cannot be read for {prop}")
        truth.append(ok)
        trace.append({"tx": [], "src": lab, "dst": prop, "formula": f"{OP.DESCRIPTIONS.get(prop, prop)} computed by code",
                      "inputs": {"claim": i + 1, "compound": lab, "structure": cand["_comps"][lab]["smiles"],
                                 "claimed value": r.get("value")},
                      "outputs": {"computed value": props[prop], "claim true": ok}})
    if not problems and fmt != "integer":
        n_true = sum(bool(t) for t in truth)
        if fmt == "msq" and not 1 <= n_true <= 3:
            problems.append(f"msq needs 1 to 3 true claims, the draft has {n_true}")
        if fmt == "mcq_correct" and n_true != 1:
            problems.append(f"mcq_correct needs exactly one true claim, the draft has {n_true}")
        if fmt == "count" and n_true in (0, len(rows)):
            problems.append("count: not every claim may be true or false")
    if not problems:                                  # hardness by code: statements a wrong turn would flip
        if fmt == "integer":
            lab, prop = rows[0]["compound"].strip(), rows[0]["property"].strip()
            right = cand["_props"][lab][prop]
            steps = {_source(h) for _w, h, wp in _wrong_props(cand).get(lab, []) if prop in wp and wp[prop] != right}
            if len(steps) < MIN_HINGE:
                problems.append(f"integer: {lab}'s {prop} changes under a wrong turn at {len(steps)} step(s); it must "
                                f"depend on at least {MIN_HINGE} different steps (see DECISIVE FACTS)")
        else:
            srcs = [claim_sources(cand, str(r["compound"]).strip(), str(r["property"]).strip(), r.get("value"))
                    for r in rows]
            n_hinge = sum(bool(s) for s in srcs)
            steps = set().union(*srcs) if srcs else set()
            # two hinges on the same step test one decision twice (live run 10: "S has NO2" and "T has NO2")
            if n_hinge < MIN_HINGE or len(steps) < MIN_HINGE:
                problems.append(f"{n_hinge} statement(s) depend on a wrong turn, at {len(steps)} different step(s) "
                                f"({', '.join(sorted(steps)) or 'none'}); at least {MIN_HINGE} statements must test "
                                f"DECISIVE FACTS from at least {MIN_HINGE} DIFFERENT steps")
            rote = [i + 1 for i, s in enumerate(srcs) if not s]
            allowed = max(1, MAX_ROTE_PER_4 * len(rows) // 4)
            if len(rote) > allowed:
                problems.append(f"statement(s) {', '.join(map(str, rote))} are decided by no step (rote facts any "
                                f"student gets right); at most {allowed} such statement is allowed: replace the others "
                                f"with DECISIVE FACTS")
    if problems:
        return None, problems
    texts = [str(r.get("text") or "").strip() for r in rows]
    if fmt in ("count", "integer"):
        if fmt == "count":
            answer = sum(bool(t) for t in truth)
            traps = [{"id": f"item{i + 1}", "desc": f"misjudges statement {i + 1}",
                      "wrong_answer": answer + (-1 if truth[i] else 1)} for i in range(len(rows))]
        else:
            r = rows[0]
            lab, prop = r["compound"], r["property"]
            answer = cand["_props"][lab][prop]
            traps = []
            for w, how in cand["_wrong"].get(lab, {}).items():
                try:
                    wv = OP.askable(w).get(prop)
                except EngineError:
                    continue
                if wv is not None and wv != answer:
                    traps.append({"id": f"wrong_{lab}", "desc": how, "wrong_answer": wv})
            trace = [{"tx": [], "src": lab, "dst": prop, "formula": f"{OP.DESCRIPTIONS.get(prop, prop)} computed by code",
                      "inputs": {"compound": lab, "structure": cand["_comps"][lab]["smiles"]},
                      "outputs": {"value": answer}}]
        res = ChainResult(answer=answer, unit="", kind="count", asks=q.get("ask"), trace=trace, traps=traps,
                          constants=[])
        res.tolerance = 0.001
    else:
        answer = "".join(LETTERS[i] for i, t in enumerate(truth) if t)
        traps = [{"id": f"option{LETTERS[i]}", "desc": f"chooses option {LETTERS[i]}", "wrong_answer": LETTERS[i]}
                 for i, t in enumerate(truth) if not t]
        res = ChainResult(answer=answer, unit="", kind="letters", asks=q.get("ask"), trace=trace, traps=traps,
                          constants=[])
    res.options = texts if fmt != "integer" else []
    res.form = f"organic_question_first:{fmt}"
    return res, []


# ── amounts through the scheme (live review 2026-11-26, item 3: hidden intermediates) ───────────────────────────
# "m g of P, every step y % yield: the mass of U formed". The student must work out every hidden intermediate,
# because U's formula decides the answer; each wrong turn gives another mass (a saved trap). Real Advanced:
# organic amounts through a scheme, ~7 % full marks. Code picks U, m and y and computes the key; the writer
# writes only the lead.
AMOUNT_SHARE = 1.0            # asked as an amount whenever a compound qualifies (only ~1 scheme in 30 does)
ATOMIC = {"H": 1, "C": 12, "N": 14, "O": 16, "F": 19, "Na": 23, "Mg": 24, "P": 31, "S": 32, "Cl": 35.5, "K": 39,
          "Br": 80, "I": 127}  # the values printed in the question, so the key uses exactly these
YIELDS = (50, 60, 70, 75, 80, 90)
AMOUNT_GAP = 0.02             # a wrong turn counts only if it moves the mass by more than 2 %


def _mass(smiles):
    from core.engine.chem import parse_formula
    f = OP.askable(smiles).get("molecular_formula")
    counts = parse_formula(f)[0]
    if any(el not in ATOMIC for el in counts):
        return None, {}
    return sum(ATOMIC[el] * n for el, n in counts.items()), counts


def _depth(cand, lab):
    n, k = 0, lab
    while cand["_comps"][k]["parent"] is not None:
        k, n = cand["_comps"][k]["parent"], n + 1
    return n


def amount_target(cand):
    """(label, its wrong masses by step) of the compound whose mass changes under wrong turns at the most different
    steps (at least MIN_HINGE), or None."""
    best = None
    for lab in cand["_order"][1:]:
        try:
            right, _ = _mass(cand["_comps"][lab]["smiles"])
        except EngineError:
            continue
        if right is None:
            continue
        by_step = {}
        for w, how in cand["_wrong"].get(lab, {}).items():
            try:
                wm, _ = _mass(w)
            except EngineError:
                continue
            if wm is not None and abs(wm - right) > AMOUNT_GAP * right:
                by_step.setdefault(_source(how), wm)
        if len(by_step) >= MIN_HINGE and (best is None or len(by_step) > len(best[1])):
            best = (lab, by_step)
    return best


def amount_result(cand, lab, rng):
    """(numbers dict, ChainResult) for "mass of lab from m g of P at y % per step"."""
    mp, cp = _mass(cand["_comps"]["P"]["smiles"])
    ml, cl = _mass(cand["_comps"][lab]["smiles"])
    k = _depth(cand, lab)
    mol = rng.choice((0.02, 0.025, 0.04, 0.05, 0.08, 0.1, 0.2))
    m_p = round(mol * mp, 2)
    y = rng.choice(YIELDS)
    answer = round(m_p / mp * (y / 100) ** k * ml, 2)
    traps = []
    for w, how in cand["_wrong"].get(lab, {}).items():
        try:
            wm, _ = _mass(w)
        except EngineError:
            continue
        if wm is not None and abs(wm - ml) > AMOUNT_GAP * ml:
            traps.append({"id": f"wrong_{lab}", "desc": how, "wrong_answer": round(m_p / mp * (y / 100) ** k * wm, 2)})
    traps.append({"id": "yield_once", "desc": "applies the yield once, not at every step",
                  "wrong_answer": round(m_p / mp * (y / 100) * ml, 2)})
    els = sorted(set(cp) | set(cl), key=lambda e: ATOMIC[e])
    nums = {"m_P": m_p, "yield": y, "steps": k, "label": lab,
            "given": ", ".join(f"{e} = {ATOMIC[e]:g}" for e in els)}
    trace = [{"tx": [], "src": "P", "dst": lab, "formula": "m(L) = m(P)/M(P) × (y/100)^k × M(L), computed by code",
              "inputs": {"m(P)": m_p, "M(P)": mp, "yield %": y, "steps": k, "M(L)": ml,
                         "structure": cand["_comps"][lab]["smiles"]}, "outputs": {"mass": answer}}]
    res = ChainResult(answer=answer, unit="g", kind="real", asks=f"mass of {lab}", trace=trace, traps=traps,
                      constants=[])
    res.tolerance = 0.01
    res.options = []
    res.form = "organic_question_first:amount"
    return nums, res


def amount_ask(nums) -> str:
    return (f"If {nums['m_P']:g} g of P is used and every step of the sequence proceeds with {nums['yield']}% yield, "
            f"the mass (in g) of {nums['label']} obtained is ____.\n(Given: atomic masses {nums['given']})\n"
            f"Give the answer correct to two decimal places.")


def _no_scheme(text) -> str:
    """The model's lead/ask without scheme lines: code prints the scheme once (the model sometimes copies it)."""
    keep = [ln for ln in str(text or "").splitlines() if "--[" not in ln and not ln.strip().startswith("P = ")]
    return " ".join(ln.strip() for ln in keep if ln.strip())


def full_stem(cand, q, result) -> str:
    if q["format"] == "amount":
        return f"{_no_scheme(q.get('lead'))}\n{scheme_text(cand)}\n{amount_ask(q['_amount'])}"
    head = f"{_no_scheme(q.get('lead'))}\n{scheme_text(cand)}\n{_no_scheme(q['ask'])}"
    if q["format"] == "integer":
        return f"{head}\nGive the answer as an integer."
    if q["format"] == "count":
        lines = "\n".join(f"({i + 1}) {t}" for i, t in enumerate(result.options))
        return f"{head}\n{lines}\nGive the answer as an integer."
    lines = "\n".join(f"({LETTERS[i]}) {t}" for i, t in enumerate(result.options))
    tail = "Choose all the correct options." if q["format"] == "msq" else "Choose the one correct option."
    return f"{head}\n{lines}\n{tail}"


# ── run ──────────────────────────────────────────────────────────────────────

def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Like inorg_qfirst.run, for organic. {"status": "accepted", "payload"} or {"status": "none"}; raises Parked."""
    from core.pipeline import flow
    from core.pipeline.qf_design import design_problems
    from core.pipeline.qfirst import over_budget
    rng = rng or random.Random()
    cap = adapter.config.get("max_run_spend")
    name = adapter.config["display_name"]
    used_starts = []
    start, uses = None, 0
    resumed = load_checkpoint(adapter) if adapter.config.get("resume") else None
    for n_draw in range(1, MAX_DRAWS + 1):
        if over_budget(cap):
            break
        saved = {}
        if resumed is not None:                       # the checkpointed scheme first, from its next stage
            cand, saved = resumed
            resumed = None
            start, uses = cand["_start"], 1
            used_starts.append(start[0])
        elif adapter.config.get("start_picker"):          # a model invents the start, the engine checks it
            if start is None or uses >= SCHEMES_PER_START:
                from core.pipeline import org_start
                pick = org_start.pick_start(adapter, rng, avoid=used_starts, log=log)
                if pick is None:
                    if bb.current is not None:        # the first draw has no chain open yet (batch crash 2026-11-26)
                        bb.note("start_refused", tries=org_start.PICK_TRIES)
                    print("  start picker: no acceptable starting molecule this draw")
                    start = None
                    continue
                used_starts.append(pick["name"])
                start, uses = (pick["name"], pick["smiles"]), 0
            else:
                print(f"  [start] same molecule, scheme {uses + 1} of {SCHEMES_PER_START}: {start[0]}")
        if not saved:
            clear_checkpoint()                        # the previous scheme ended (held, rejected): nothing to resume
            cand = draw(adapter, rng, tried=bb.tried_edges(), start=start, avoid=overused_edges(adapter),
                        accepted=accepted_compound_sets(adapter))
            uses += 1
        if cand is None:
            if start is not None:
                print("  no new scheme from this start")
                start = None                            # a new molecule next time
                continue
            print("  no reaction schemes left")
            break
        print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
        print("  " + scheme_text(cand).replace("\n", "\n  "))
        print("  " + "\n  ".join(f"{k} = {cand['_comps'][k]['smiles']}" for k in cand["_order"]))
        bb.start_chain(cand)
        if STEP_CHECK and saved:
            print("  [step check] passed before the resume")
        elif STEP_CHECK:                              # every step checked blind before anything is paid for
            from core.pipeline import org_step_check
            bad = org_step_check.check_scheme(cand)
            if bad:
                qid = queues.add("step_disagreement", adapter.subject, {
                    "chain": cand["edges"], "start": cand["_start"],
                    "structures": {k: cand["_comps"][k]["smiles"] for k in cand["_order"]}, "steps": bad})
                bb.note("step_check", held=qid, steps=bad)
                log({"event": "step_disagreement", "chain": cand["edges"], "queue_id": qid,
                     "steps": [(b["label"], b["edge"], b["verdict"]) for b in bad]})
                for b in bad:
                    print(f"    [step check] {b['label']} ({b['reagent']}): engine {b['engine']}, checker "
                          f"{b['checker_product'] or 'no single product'} ({str(b['reason'])[:110]})")
                print(f"  ✗ {len(bad)} step(s) not confirmed: scheme held for review ({qid}); next draw")
                continue
            bb.note("step_check", held=None, steps=[])
            print(f"  [step check] all {len(cand['_order']) - 1} steps confirmed (GPT-6 Luna, blind)")
            save_checkpoint("step_check", cand)
        try:
            design = saved.get("design") or design_question(name, cand)
        except ValueError as e:
            bb.note("design_unusable", error=str(e)[:300])
            print(f"    design unusable: {str(e)[:160]}")
            continue
        if "impossible" in design:
            bb.note("impossible", reason=design["impossible"], at="design")
            print(f"    designer: no hard question on this scheme: {design['impossible'][:160]}")
            log({"event": "formulas_impossible", "chain": cand["edges"]})
            continue
        bb.note("design", **{k: v for k, v in design.items() if not k.startswith("_")})
        print(f"  [design] format {design['format']}; asks {str(design.get('asked'))[:100]}; "
              f"trap: {str(design.get('trap'))[:100]}")
        problem = design_problems(design, adapter.subject)
        if problem:
            bb.note("design_rejected", problem=problem)
            print(f"    design rejected: {problem[:160]}")
            continue
        # amounts through the scheme (item 3): asked when a compound's mass hinges on wrong turns at 2+ steps
        target = amount_target(cand)
        if target and design.get("format") != "amount" and rng.random() < AMOUNT_SHARE:
            design = dict(design, format="amount")
            print(f"  [amount] asking the mass of {target[0]} (wrong turns at {', '.join(sorted(target[1]))} "
                  f"change it)")
        if not saved.get("design"):
            save_checkpoint("design", cand, design=design)
        feedback, made = None, None
        for attempt in range(1 + CLAIM_RETRIES):
            if over_budget(cap):
                return {"status": "none"}
            try:
                q = saved.pop("question", None) or write_question(name, cand, design, feedback=feedback)
            except ValueError as e:
                bb.note("question", attempt=attempt + 1, error=str(e)[:300])
                print(f"    question reply unusable: {str(e)[:120]}")
                continue
            if q.get("format") == "amount" or design.get("format") == "amount":
                if not target:
                    target = amount_target(cand)
                q["format"], q["_amount_target"] = "amount", target[0] if target else None
            result, probs = evaluate(cand, q)
            bb.note("question", attempt=attempt + 1, **{k: q.get(k) for k in ("lead", "ask", "format", "claims")})
            if probs:
                bb.note("question_rejected", attempt=attempt + 1, problems=probs)
                print(f"    claims rejected: {'; '.join(probs)[:220]}")
                feedback = "; ".join(probs)
                continue
            made = (q, result)
            save_checkpoint("question", cand, design=design, question=q)
            break
        if made is None:
            log({"event": "question_failed", "chain": cand["edges"]})
            continue
        q, result = made
        stem = full_stem(cand, q, result)
        values = {"start": cand["_start"][1], "options": result.options, "mode": q["format"]}
        bb.note("qfirst", stem=stem, answer=result.answer, trace=result.trace, traps=result.traps)
        print(f"  [key] {result.answer} (computed by code)")
        from core.pipeline import qf_checks       # Jev's level check, calibrated on real organic papers
        floor = qf_checks._level_floor(adapter.subject)
        if floor is not None:
            lvl = qf_checks.jev_level(stem)
            if lvl is not None:
                print(f"    [level] Jev: {lvl:.2f}; floor {floor:.2f}")
                bb.note("level", score=lvl, floor=floor)
                if lvl < floor:
                    log({"event": "too_easy", "chain": cand["edges"], "reason": f"level {lvl:.2f} < {floor:.2f}"})
                    print("  ✗ below JEE Advanced level (before the ladder is paid for); next draw")
                    continue
        sig = dedup.signature(adapter.subject, cand["edges"], {"start": values["start"], "options": result.options})
        if dedup.duplicate_of(sig):
            print("  [dedup] same as an accepted question; next draw")
            continue
        decision = flow.judge(adapter, cand, None, values, result, stem, bb, log)
        if decision["decision"] == "accept" and decision.get("first_solver") is None:
            # no ladder model reached the key (2026-11-24): with code-made keys a wrong engine step looks exactly
            # like a very hard question, so organic holds it for review instead of accepting it
            qid = queues.add("unconfirmed_key", adapter.subject, {
                "chain": cand["edges"], "start": cand["_start"], "stem": stem, "engine_answer": result.answer,
                "structures": {k: cand["_comps"][k]["smiles"] for k in cand["_order"]},
                "members": [{"name": g["name"], "answer": g["final_answer"]} for g in decision.get("graded", [])]})
            log({"event": "unconfirmed_key", "chain": cand["edges"], "queue_id": qid, "stem": stem,
                 "answer": result.answer})
            print(f"  ✗ no solver reached the key {result.answer}: held for review ({qid}), not accepted; next draw")
            continue
        log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
             "answer": result.answer, "reason": decision.get("reason")})
        if decision["decision"] == "accept":
            clear_checkpoint()
            return {"status": "accepted", "payload": {
                "cand": cand, "plan": None, "values": values, "scenario": f"organic question-first ({q['format']})",
                "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
        print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
              + "; next draw")
    return {"status": "none"}
