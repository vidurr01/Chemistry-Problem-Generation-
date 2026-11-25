"""
inorg_qfirst.py — the question-first flow for INORGANIC chemistry (same pattern as physical's qfirst.py).

    draw       a random walk of 2-4 reactions in the inorganic graph (knowledge/reaction_graph_inorg.json), kept
               only if a species after the start has a property code can compute (core/engine/inorganic/species)
    design     the designer (models.DESIGNER) plans ONE question on that chain: which species are hidden (X, Y),
               what the student is told, what is asked, the format (msq, mcq_correct, mcq_incorrect, count,
               identify) and the trap; Jev's design check, as for physical
    write      the writer (models.GENERATOR) writes the stem and every option as a CHECKABLE CLAIM
               (species, property, value); no option is judged by a model
    evaluate   code decides every claim with the property functions, so the key is code's ("the coder")
    judge      flow.judge: the same ladder, grading by code, hold rule; accepted -> saved like physical

What differs from physical is only the draw (a reaction chain, not formulas) and the answer key (properties of
graph species, not a program over engine steps).
"""

from __future__ import annotations

import json
import os
import random
import re

from core import dedup, models
from core.engine.base import ChainResult, EngineError
from core.engine.inorganic import species as S
from core.llm import CutOffError

MAX_DRAWS = 10           # inorganic only; medium-hard rejects more draws (spend cap still applies)
CHAIN_MIN, CHAIN_MAX = 2, 4
LETTERS = "ABCD"
FORMATS = ("msq", "mcq_correct", "mcq_incorrect", "count", "identify")
CLAIM_RETRIES = 1        # a draft whose claims code cannot read is sent back once with the exact problems
SYSTEM_SHARE = 0.7       # "one reaction system, products as letters" (inorg_system.py): the commonest real
                         # Advanced inorganic shape (2019-2025 papers read on 2026-11-25)
PRODUCTS_SHARE = 0.0     # "hidden products" counts (inorg_products.py): retired 2026-11-25, not a real JEE format
LIST_SHARE = 0.3         # "how many species in this list" (inorg_list.py): a real Advanced format (2023, 2024)
# Inorganic only. A model listed here solving a question makes it "too easy". GLM was listed on 2026-11-25 and
# removed the same day: on 17 real Advanced inorganic questions with student results, altered so nothing could be
# recalled (calibration/ladder_vs_students_inorganic.py), GLM solved 4 of 6 hard and 4 of 6 medium ones, while
# Granite solved 1 of 6 hard, 2 of 6 medium, 4 of 5 easier. "Granite fails" is the medium-hard bar; GLM only labels.
TOO_EASY_SOLVERS = ()
# Granite answers up to BOTTOM_TRIES times and FAILS only if right at most BOTTOM_MAX_RIGHT times; asking stops once
# decided (a 2nd right answer: solved; BOTTOM_TRIES - BOTTOM_MAX_RIGHT wrong: failed). Measured 2026-11-25
# (calibration/granite_tries_stability.py, Granite 7-10 tries on 44 real question versions): real questions are
# nearly all-or-nothing for Granite, so "3 tries, >= 2" flipped only 6%; the flips came from our borderline drafts
# (Granite right ~half the time), which "3, >= 2" accepted 50% of the time, this rule 19%. Real accepted: hard 83 ->
# 81%, medium 80 -> 69%, easier 23 -> 20%, Mains 30 -> 25%.
BOTTOM_TRIES, BOTTOM_MAX_RIGHT = 5, 1
REASKS = 2                             # an unreadable answer is asked again up to twice; never a failure


# ── draw ─────────────────────────────────────────────────────────────────────

BLOCKED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "knowledge", "inorg_blocked_edges.json")


def blocked_edges() -> set:
    """Edge ids never used for a question (wrong or condition-dependent; graph audit of 2026-11-24)."""
    try:
        with open(BLOCKED_PATH, encoding="utf-8") as f:
            b = json.load(f)
    except OSError:
        return set()
    return set(b.get("wrong", {})) | set(b.get("depends_on_conditions", {}))


def _graph(adapter):
    if not hasattr(adapter, "_g"):
        with open(adapter.config["graph_path"], encoding="utf-8") as f:
            g = json.load(f)
        blocked = blocked_edges()
        g["edges"] = [e for e in g["edges"] if e["id"] not in blocked]
        out = {}
        for e in g["edges"]:
            out.setdefault(e["from"], []).append(e)
        adapter._g = {"nodes": {n["id"]: n for n in g["nodes"]}, "out": out, "edges": {e["id"]: e for e in g["edges"]}}
        adapter._ask = {}
    return adapter._g


def _ask(adapter, sid):
    if sid not in adapter._ask:
        adapter._ask[sid] = S.askable(sid)
    return adapter._ask[sid]


def draw(adapter, rng, tried=()):
    """A connected walk of CHAIN_MIN..CHAIN_MAX reactions whose products include a species with a computable
    property. A candidate dict, or None after many tries."""
    g = _graph(adapter)
    starts = [s for s in g["out"] if g["out"][s]]
    for _ in range(400):
        node = rng.choice(starts)
        path, nodes = [], [node]
        k = rng.randint(CHAIN_MIN, CHAIN_MAX)
        while len(path) < k:
            nxt = [e for e in g["out"].get(nodes[-1], []) if e["to"] not in nodes]
            if not nxt:
                break
            e = rng.choice(nxt)
            path.append(e)
            nodes.append(e["to"])
        if len(path) < CHAIN_MIN:
            continue
        key = tuple(e["id"] for e in path)
        if key in tried:
            continue
        props = {sid: _ask(adapter, sid) for sid in nodes[1:]}
        props = {sid: p for sid, p in props.items() if p}
        if not props:
            continue
        chapters = list(dict.fromkeys(e.get("chapter", "") for e in path))
        txs = [t for e in path for t in (e.get("tx_ids") or [])]
        return {"edges": list(key), "nodes": nodes, "chapters": chapters, "txs": txs, "trap_ids": [],
                "_path": path, "_props": props, "description": " → ".join(nodes),
                "_hint": "Identify each species formed in the sequence first; then judge every option about it on "
                         "its own (oxidation state, electrons, geometry), not by its general idea."}
    return None


def chain_text(cand) -> str:
    lines = []
    for i, e in enumerate(cand["_path"], 1):
        cond = f"; {e['conditions']}" if e.get("conditions") else ""
        lines.append(f"Step {i}: {e['from']} --[{', '.join(e.get('reagents') or [])}{cond}]--> {e['to']}")
    return "\n".join(lines)


def props_text(cand) -> str:
    lines = []
    for sid, props in cand["_props"].items():
        items = []
        for k, v in props.items():
            name = (f"oxidation state of {k.split(':', 1)[1]}" if k.startswith("oxidation_state:")
                    else S.DESCRIPTIONS.get(k, k))
            items.append(f"{k} ({name}) = {v}")
        lines.append(f"- {sid}: " + "; ".join(items))
    return "\n".join(lines)


# ── design ───────────────────────────────────────────────────────────────────

def design_question(subject_name: str, cand) -> dict:
    from core.pipeline.qf_design import finish_design
    prompt = f"""You are a senior JEE Advanced {subject_name} paper setter. DESIGN (do not write) ONE question that would
sit among the hardest of a real paper, built on this reaction sequence (true chemistry, from our reaction graph):
{chain_text(cand)}

Properties code can compute for the species formed (the answer key comes ONLY from these):
{props_text(cand)}

WHAT MAKES IT HARD: a HIDDEN species. Hide one or more species of the sequence (call them X, Y, Z): the student
is told what is done (reagents, conditions, observations a chemist would see) but not what forms, so they must
work out the species first and then reason about its properties. The trap: a tempting wrong species (another
product of a similar reaction, a common confusion of oxidation state or spin) that a good student might choose.

Choose the format:
- "msq": four statements, one or more correct; "mcq_correct": exactly one correct; "mcq_incorrect": exactly one
  NOT correct; "count": "how many of the following ..." over 4-8 items (integer answer);
  "identify": which species is X (four candidate species, one correct).
Every statement or item must be about a species above and one of its listed properties, so code can decide it.

Rules: one real sequence as given (do not change reagents or products); never invent a property or value;
nothing the student must work out is given away in the question.

If no hard question can be built on this sequence, return only {{"impossible": "why"}}.

LENGTH: your thinking and the design TOGETHER must not exceed 2000 words.

Return JSON:
{{"system": "the sequence as the student meets it (what is done, what is observed)",
  "hidden": {{"X": "<species id from the sequence>", "...": "..."}},
  "hidden_link": "what the student must work out and from what",
  "route": "how a solver goes from the given facts to the answer",
  "student_must_notice": "the non-obvious point that decides the answer",
  "trap": "the tempting wrong species or property, and why",
  "given": "what the question states", "asked": "what is asked",
  "format": "one of msq, mcq_correct, mcq_incorrect, count, identify",
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
    if not d.get("system") or not isinstance(d.get("hidden"), dict):
        raise ValueError("the designer returned no usable design")
    d["format"] = d.get("format") if d.get("format") in FORMATS else "msq"
    d["hidden"] = {str(k): str(v) for k, v in d["hidden"].items() if str(v) in cand["nodes"]}
    d.setdefault("situation", d["system"])
    d.setdefault("insight", d.get("student_must_notice", ""))
    d.setdefault("links", d.get("route", ""))
    return d


# ── write ────────────────────────────────────────────────────────────────────

def write_question(subject_name: str, cand, design, feedback: str | None = None) -> dict:
    fmt = design["format"]
    shape = {
        "msq": 'exactly 4 "options"', "mcq_correct": 'exactly 4 "options", exactly one true',
        "mcq_incorrect": 'exactly 4 "options", exactly one false', "identify": 'exactly 4 "options", each a species',
        "count": '4 to 8 "items"',
    }[fmt]
    redo = f"\nYour previous draft was rejected: {feedback}\nFix exactly that.\n" if feedback else ""
    prompt = f"""Write ONE JEE Advanced {subject_name} question from this design. Plain text, Unicode subscripts, no LaTeX.

DESIGN:
{json.dumps({k: design.get(k) for k in ("system", "hidden", "hidden_link", "route", "student_must_notice", "trap", "given", "asked", "format")}, ensure_ascii=False, indent=1)}

The reaction sequence (true chemistry):
{chain_text(cand)}

What code can check (species id: property key = value):
{props_text(cand)}
{redo}
Rules:
- The stem must NOT name or give the formula of a hidden species; call it X, Y, Z as in the design.
- Format "{fmt}": {shape}. Every option or item is a CLAIM code checks: "species" (a species id from the list, or a
  hidden label X/Y/Z), "property" (a property key from the list, exactly), "value" (the value the statement asserts).
  A false claim states a WRONG value on purpose (the trap's value where possible). "text" is the option as printed.
- For "identify", each option has "text" and "species" (a species id: the right one and three plausible wrong ones;
  property and value are omitted) and "asked_label" names the hidden label asked about.
- Do not write the option letters or the answer; code adds them.

Return JSON: {{"stem": "the question without its options", "format": "{fmt}", "labels": {{"X": "<species id>"}},
  "asked_label": "X (identify only)", "options": [{{"text": "...", "species": "...", "property": "...", "value": "..."}}],
  "items": [{{"text": "...", "species": "...", "property": "...", "value": "..."}}]}}"""
    out = models.ask_json("generator", models.GENERATOR, "You write chemistry exam questions. Output JSON only.",
                          prompt, temperature=0.4, max_tokens=4000)
    if not out.get("stem"):
        raise ValueError("the writer returned no stem")
    out["format"] = fmt
    return out


# ── evaluate (the answer key, by code) ───────────────────────────────────────

def _resolve(sid, labels):
    s = str(sid or "").strip()
    return labels.get(s, s)


def evaluate(cand, q) -> tuple:
    """(result, problems). Every claim decided by code; problems the writer can fix are listed."""
    fmt = q["format"]
    labels = {str(k): str(v) for k, v in (q.get("labels") or {}).items()}
    problems = [f"label {k} is {v!r}, which is not a species of the sequence" for k, v in labels.items()
                if v not in cand["nodes"]]
    stem = str(q["stem"])
    for lab, sid in labels.items():
        for name in {sid, _display(cand, sid)}:
            if name and len(name) > 2 and re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![a-z0-9])", stem):
                problems.append(f"the stem names the hidden species {lab} ({name}); call it {lab} only")
    rows = q.get("items") if fmt == "count" else q.get("options")
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    need = (4, 8) if fmt == "count" else (4, 4)
    if not need[0] <= len(rows) <= need[1]:
        problems.append(f"format {fmt} needs {need[0]}" + (f" to {need[1]}" if need[1] != need[0] else "")
                        + f" claims, the draft has {len(rows)}")
    truth, trace = [], []
    if fmt == "identify":
        asked = labels.get(str(q.get("asked_label") or "").strip())
        if asked is None:
            problems.append("identify: asked_label must be a hidden label with its species in labels")
        for i, r in enumerate(rows):
            sid = _resolve(r.get("species"), labels)
            truth.append(asked is not None and sid == asked)
            trace.append({"tx": [], "src": sid, "dst": "identity", "formula": "the species formed in the sequence",
                          "inputs": {"option": LETTERS[i] if i < 4 else i + 1, "species": sid, "asked": q.get("asked_label")},
                          "outputs": {"is the hidden species": truth[-1], "hidden species": asked}})
    else:
        for i, r in enumerate(rows):
            sid = _resolve(r.get("species"), labels)
            prop = str(r.get("property") or "").strip()
            props = S.askable(sid) if sid in cand["nodes"] else {}
            if sid not in cand["nodes"]:
                problems.append(f"claim {i + 1}: species {r.get('species')!r} is not in the sequence")
                truth.append(None)
                continue
            if prop not in props:
                problems.append(f"claim {i + 1}: property {prop!r} cannot be computed for {sid} "
                                f"(computable: {', '.join(props) or 'none'})")
                truth.append(None)
                continue
            ok = S.compare(prop, props[prop], r.get("value"))
            if ok is None:
                problems.append(f"claim {i + 1}: value {r.get('value')!r} cannot be read for {prop}")
            truth.append(ok)
            trace.append({"tx": [], "src": sid, "dst": prop,
                          "formula": f"{S.DESCRIPTIONS.get(prop, prop)} computed by code (core/engine/inorganic)",
                          "inputs": {"claim": i + 1, "species": sid, "claimed value": r.get("value")},
                          "outputs": {"computed value": props[prop], "claim true": ok}})
    if not problems:
        n_true = sum(bool(t) for t in truth)
        if fmt == "msq" and not 1 <= n_true <= 3:
            problems.append(f"msq needs 1 to 3 true options, the draft has {n_true}")
        if fmt in ("mcq_correct", "identify") and n_true != 1:
            problems.append(f"{fmt} needs exactly one true option, the draft has {n_true}")
        if fmt == "mcq_incorrect" and n_true != 3:
            problems.append(f"mcq_incorrect needs exactly one false option, the draft has {4 - n_true} false")
        if fmt == "count" and n_true in (0, len(rows)):
            problems.append("count: not every item may be true or false (the trap must change the count)")
    if problems:
        return None, problems
    texts = [str(r.get("text") or "").strip() for r in rows]
    if fmt == "count":
        answer = sum(bool(t) for t in truth)
        traps = [{"id": f"item{i + 1}", "desc": f"misjudges item {i + 1}",
                  "wrong_answer": answer + (-1 if truth[i] else 1)} for i in range(len(rows))]
        res = ChainResult(answer=answer, unit="", kind="count", asks=q.get("stem"), trace=trace, traps=traps,
                          constants=[])
        res.tolerance = 0.001
    else:
        if fmt == "mcq_incorrect":
            answer = "".join(LETTERS[i] for i, t in enumerate(truth) if not t)
        else:
            answer = "".join(LETTERS[i] for i, t in enumerate(truth) if t)
        traps = [{"id": f"option{LETTERS[i]}", "desc": f"chooses option {LETTERS[i]}", "wrong_answer": LETTERS[i]}
                 for i, t in enumerate(truth) if (t if fmt == "mcq_incorrect" else not t)]
        res = ChainResult(answer=answer, unit="", kind="letters", asks=q.get("stem"), trace=trace, traps=traps,
                          constants=[])
    res.options = texts
    res.form = f"inorganic_question_first:{fmt}"
    return res, []


def _display(cand, sid):
    return sid


def full_stem(q, result) -> str:
    stem = str(q["stem"]).strip()
    if q["format"] == "count":
        lines = "\n".join(f"({i + 1}) {t}" for i, t in enumerate(result.options))
        return f"{stem}\n{lines}\nGive the answer as an integer."
    lines = "\n".join(f"({LETTERS[i]}) {t}" for i, t in enumerate(result.options))
    tail = ("Choose all the correct options." if q["format"] == "msq" else "Choose the one correct option.")
    return f"{stem}\n{lines}\n{tail}"


# ── run ──────────────────────────────────────────────────────────────────────

def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Like qfirst.run, for inorganic. {"status": "accepted", "payload"} or {"status": "none"}; raises Parked."""
    from core.pipeline import flow
    from core.pipeline.qf_design import design_problems
    from core.pipeline.qfirst import over_budget
    rng = rng or random.Random()
    cap = adapter.config.get("max_run_spend")
    name = adapter.config["display_name"]
    only = os.environ.get("INORG_ONLY")            # "products" / "list" / "system": one kind only (pilots)
    for n_draw in range(1, MAX_DRAWS + 1):
        if over_budget(cap):
            break
        if only in ("products", "list"):
            made = _list_question(adapter, rng, bb, log, n_draw, kind=only)
            if made is not None:
                return made
            continue
        r = 0.0 if only == "system" else rng.random()
        if r < SYSTEM_SHARE:
            made = _system_question(adapter, rng, bb, log, n_draw)
            if made is not None:
                return made
            continue
        r -= SYSTEM_SHARE
        if r < PRODUCTS_SHARE + LIST_SHARE:
            made = _list_question(adapter, rng, bb, log, n_draw,
                                  kind="products" if r < PRODUCTS_SHARE else "list")
            if made is not None:
                return made
            continue
        cand = draw(adapter, rng, tried=bb.tried_edges())
        if cand is None:
            print("  no reaction chains left")
            break
        print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
        bb.start_chain(cand)
        try:
            design = design_question(name, cand)
        except ValueError as e:
            bb.note("design_unusable", error=str(e)[:300])
            print(f"    design unusable: {str(e)[:160]}")
            continue
        if "impossible" in design:
            bb.note("impossible", reason=design["impossible"], at="design")
            print(f"    designer: no hard question on this sequence: {design['impossible'][:160]}")
            log({"event": "formulas_impossible", "chain": cand["edges"]})
            continue
        bb.note("design", **{k: v for k, v in design.items() if not k.startswith("_")})
        print(f"  [design] hides {design['hidden']}; format {design['format']}; trap: {str(design.get('trap'))[:110]}")
        problem = design_problems(design, adapter.subject)
        if problem:
            bb.note("design_rejected", problem=problem)
            print(f"    design rejected: {problem[:160]}")
            continue
        feedback, made = None, None
        for attempt in range(1 + CLAIM_RETRIES):
            if over_budget(cap):
                return {"status": "none"}
            try:
                q = write_question(name, cand, design, feedback=feedback)
            except ValueError as e:
                bb.note("question", attempt=attempt + 1, error=str(e)[:300])
                print(f"    question reply unusable: {str(e)[:120]}")
                continue
            result, probs = evaluate(cand, q)
            bb.note("question", attempt=attempt + 1, **{k: q.get(k) for k in ("stem", "format", "labels", "options",
                                                                               "items", "asked_label")})
            if probs:
                bb.note("question_rejected", attempt=attempt + 1, problems=probs)
                print(f"    claims rejected: {'; '.join(probs)[:220]}")
                feedback = "; ".join(probs)
                continue
            made = (q, result)
            break
        if made is None:
            log({"event": "question_failed", "chain": cand["edges"]})
            continue
        q, result = made
        stem = full_stem(q, result)
        values = {"options": result.options, "mode": q["format"], "labels": q.get("labels") or {}}
        bb.note("qfirst", stem=stem, answer=result.answer, trace=result.trace, traps=result.traps)
        n_true = sum(1 for t in result.trace if t["outputs"].get("claim true") or t["outputs"].get("is the hidden species"))
        print(f"  [key] {result.answer} (computed by code: {n_true} true claim(s))")
        sig = dedup.signature(adapter.subject, cand["txs"] or cand["edges"], values)
        if dedup.duplicate_of(sig):
            print("  [dedup] same as an accepted question; next draw")
            continue
        decision = flow.judge(adapter, cand, None, values, result, stem, bb, log)
        log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
             "answer": result.answer, "reason": decision.get("reason")})
        if decision["decision"] == "accept":
            return {"status": "accepted", "payload": {
                "cand": cand, "plan": None, "values": values, "scenario": f"inorganic question-first ({q['format']})",
                "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
        print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
              + "; next draw")
    return {"status": "none"}


def _list_question(adapter, rng, bb, log, n_draw, kind="list"):
    """One count question built and keyed by code, then judged like any other: kind "list" (how many species
    in this list, inorg_list.py) or "products" (hidden products of listed reactions, inorg_products.py).
    The accepted result, or None (a product not confirmed, too easy, a duplicate, nothing left to draw)."""
    from core.pipeline import flow, inorg_list, inorg_products
    if kind == "products":
        if not hasattr(adapter, "_bad_products"):
            adapter._bad_products = set()          # reactions the blind check did not confirm in this run
        edges = inorg_products.with_naive(list(_graph(adapter)["edges"].values())) + inorg_products.variant_edges()
        cand = inorg_products.draw(edges, rng, tried=bb.tried_edges(), bad=adapter._bad_products)
    else:
        cand = inorg_list.draw(rng, tried=bb.tried_edges(), used=used_list_conditions(adapter))
    if cand is None:
        print(f"  no {'reaction list' if kind == 'products' else 'species list'} left")
        return None
    print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
    bb.start_chain(cand)
    if kind == "products":                         # every product named blind before anything else is paid for
        bad = inorg_products.check(cand)
        bb.note("product_check", disagree=bad)
        if bad:
            adapter._bad_products.update(b["edge"] for b in bad)
            log({"event": "product_disagreement", "chain": cand["edges"], "reactions": bad})
            print(f"  ✗ product check (GPT-6 Luna, blind) differs on {len(bad)} reaction(s): "
                  + "; ".join(f"{b['graph']} vs {b['checker']}" for b in bad)[:240] + "; next draw")
            return None
        print(f"  [product check] all {len(cand['_products']['rows'])} products confirmed (GPT-6 Luna, blind)")
        stem, result = inorg_products.question(cand)
    else:
        stem, result = inorg_list.question(cand)
    values = {"options": result.options, "mode": "hidden_products" if kind == "products" else "species_list",
              "labels": {}}
    bb.note("qfirst", stem=stem, answer=result.answer, trace=result.trace, traps=result.traps)
    print(f"  [question] {stem.splitlines()[0]}")
    print(f"  [key] {result.answer} (computed by code)")
    # hidden products (retired) keep their old signature so earlier accepted ones still match
    sig = (_signature(adapter, cand, "species_list") if kind == "list"
           else dedup.signature(adapter.subject, cand["edges"], values))
    if dedup.duplicate_of(sig):                    # before the level check is paid for
        print("  [dedup] same as an accepted question; next draw")
        return None
    from core.pipeline import qf_checks            # Jev's level check, calibrated on real inorganic papers
    floor = qf_checks._level_floor(adapter.subject)
    if floor is not None:                          # live run of 2026-11-24: a Main-level list (1.33) was accepted
        lvl = qf_checks.jev_level(stem)
        if lvl is not None:
            print(f"    [level] Jev: {lvl:.2f}; floor {floor:.2f}")
            bb.note("level", score=lvl, floor=floor)
            if lvl < floor:
                log({"event": "too_easy", "chain": cand["edges"], "reason": f"level {lvl:.2f} < {floor:.2f}"})
                print("  ✗ below JEE Advanced level (before the ladder is paid for); next draw")
                return None
    decision = _judge_medium_hard(adapter, cand, values, result, stem, bb, log)
    log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
         "answer": result.answer, "reason": decision.get("reason")})
    if decision["decision"] == "accept":
        return {"status": "accepted", "payload": {
            "cand": cand, "plan": None, "values": values, "scenario": ("inorganic hidden products (count)" if kind == "products"
                                                     else "inorganic species list (count)"),
            "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
    print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
          + "; next draw")
    return None


def _accepted_engines(adapter) -> list:
    """The engine records of accepted inorganic questions (rejected-on-review ones left out), [] if none."""
    path = adapter.config.get("output_file")
    try:
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    return [r.get("engine") or {} for r in recs if isinstance(r, dict) and not r.get("rejected")]


def asked_species_sets(adapter) -> list:
    """For each accepted reaction-system question, the set of lettered species it asks about. A new system that
    asks about two of the same species is the same question to a student whatever reaction leads in (batch
    2026-11-25: NaNO₂ + NH₄Cl → N₂ → NH₃ accepted after NH₄NO₂ → N₂ → NH₃ and NaNO₃ → ... → N₂ → NH₃)."""
    out = []
    for e in _accepted_engines(adapter):
        labels = (e.get("givens") or {}).get("labels") or {}
        if str(e.get("form", "")).startswith("inorganic_system") and labels:
            out.append(frozenset(labels))
    return out


def asked_fact_pairs(adapter) -> set:
    """(species, fact key) pairs accepted reaction-system questions already state, e.g. ("NO", "bond_order")."""
    out = set()
    for e in _accepted_engines(adapter):
        if not str(e.get("form", "")).startswith("inorganic_system"):
            continue
        for t in e.get("trace") or []:
            m = re.search(r"\(species (.+)\)\s*$", str(t.get("formula", "")))
            if m:
                out.add((m.group(1), t.get("dst")))
    return out


def used_list_conditions(adapter) -> dict:
    """How many accepted species-list questions use each condition pair, e.g. {"magnetism=paramagnetic&
    hybridisation=d2sp3": 3}; the list draw favours the less used (batch 2026-11-25: 3 of the first 4 were that one)."""
    out = {}
    for e in _accepted_engines(adapter):
        for key in e.get("graph_edges") or []:
            if str(key).startswith("list:"):
                cond = str(key).split(":")[1]
                out[cond] = out.get(cond, 0) + 1
    return out


def _signature(adapter, cand, mode) -> str:
    """The duplicate-store signature of a code-built question: what the student works on, never its random
    dressing. cand["edges"] is already order-free (a system's sorted reaction ids; a list's conditions and sorted
    species). Before 2026-11-25 the signature also held the random letters and the shuffled options, so the same
    system or list could be accepted again with other letters or in another order (review item #13). For a system
    this means one accepted question per reaction system, whatever its form or statements."""
    return dedup.signature(adapter.subject, cand["edges"], {"mode": mode})


class _SolvedTooLow(Exception):
    """Raised inside flow.judge once the ladder's result is noted and a TOO_EASY_SOLVERS model solved first."""

    def __init__(self, council: dict):
        super().__init__(council.get("first_solver"))
        self.council = council


class _StopAtLadder:
    """The blackboard as flow.judge sees it, for inorganic only: every call goes to the real one, but the moment
    the ladder's result is noted with GLM first, the judgement stops. Without it flow.judge went on to a second
    Jev level call and an insight-hint re-solve for every failed model, then _medium_hard threw the result away
    (review item #7, 2026-11-25; run 11 draw 3 paid for both). flow.judge itself is unchanged."""

    def __init__(self, bb):
        self._bb = bb

    def __getattr__(self, name):
        return getattr(self._bb, name)

    def note(self, stage, **data):
        out = self._bb.note(stage, **data)
        if stage == "council" and data.get("first_solver") in TOO_EASY_SOLVERS:
            raise _SolvedTooLow(data)
        return out


def _readable(result, m) -> bool:
    """The member gave an answer code can read: a parsed answer line, or an option-letter / number answer.
    A garbled line ("[TYPE: chemistry] [CALC_VALUE:] ...", live run 12) is NOT a wrong answer: it says nothing
    about the question, only about the model's formatting."""
    from core.pipeline import flow
    if m.get("final_value") is not None:
        return True
    v = m.get("final_answer")
    if v is None:
        return False
    if result.kind == "letters":
        return bool(re.fullmatch(r"\s*\(?[A-D]\)?(?:\s*(?:,|and|&)?\s*\(?[A-D]\)?)*\s*\.?\s*", str(v)))
    return flow._code_match(result, m) is not None


def _measured_solver(result, solve):
    """stages.council_solve as the inorganic ladder uses it (the author, 2026-11-25, after the real-question
    measurement in calibration/ladder_vs_students_inorganic.py):
      - an unreadable answer is asked again, up to REASKS times; it never counts as a failure. Still unreadable:
        CouncilMemberFailed, so flow.judge parks the question (held, judged again next run), never a verdict;
      - the bottom step (Granite) answers up to BOTTOM_TRIES times and counts as solved once it is right more
        than BOTTOM_MAX_RIGHT times; it fails after BOTTOM_TRIES - BOTTOM_MAX_RIGHT wrong answers. A question
        Granite gets right about half the time is borderline, not medium-hard: it is not accepted."""
    from core.pipeline import flow
    from core.pipeline.stages import CouncilMemberFailed
    bottom = models.LADDER[0][0]

    def one(stem, name, spec):
        for k in range(1 + REASKS):
            m = solve(stem, [name], spec)[0]
            if _readable(result, m):
                return m
            print(f"    [{name}] unreadable answer ({str(m.get('final_answer'))[:50]!r}); asking again")
        raise CouncilMemberFailed(f"{name}: no readable answer in {1 + REASKS} tries")

    def measured(stem, names=None, spec=None):
        out = []
        for name in names or [n for n, _ in models.COUNCIL]:
            if name != bottom:
                out.append(one(stem, name, spec))
                continue
            tries, ok = [], []
            while (sum(ok) <= BOTTOM_MAX_RIGHT and len(ok) - sum(ok) < BOTTOM_TRIES - BOTTOM_MAX_RIGHT):
                tries.append(one(stem, name, spec))
                ok.append(flow._grade(result, tries[-1])["counts_as_solved"])
            n = sum(ok)
            solved = n > BOTTOM_MAX_RIGHT
            print(f"    [{name}] {n}/{len(tries)} tries right → {'solved' if solved else 'failed'} "
                  f"({', '.join(str(m.get('final_answer'))[:12] for m in tries)})")
            pick = next(m for m, s in zip(tries, ok) if s == solved)
            out.append({**pick, "bottom_tries": f"{n}/{len(tries)}",
                        "bottom_answers": [m.get("final_answer") for m in tries]})
        return out
    return measured


def _judge_medium_hard(adapter, cand, values, result, stem, bb, log) -> dict:
    """flow.judge for inorganic, with the measured solver (_measured_solver) in place of stages.council_solve
    for this judgement only; flow.judge's own code is unchanged, and so are organic and physical."""
    from unittest import mock
    from core.pipeline import flow, stages
    try:
        with mock.patch.object(stages, "council_solve", _measured_solver(result, stages.council_solve)):
            return _medium_hard(flow.judge(adapter, cand, None, values, result, stem, _StopAtLadder(bb), log))
    except _SolvedTooLow as e:
        for g in e.council.get("members") or []:
            print(f"    [{g['name']}] {g.get('final_answer')} → {'solved' if g.get('counts_as_solved') else 'failed'}")
        solver = e.council["first_solver"]
        print(f"    inorganic: {solver} solved it → below medium Advanced (no level check or hints paid)")
        return {"decision": "too_easy", "reason": f"{solver} solved it (inorganic: medium-hard only)",
                "first_solver": solver, "graded": e.council.get("members") or []}


def _medium_hard(decision: dict) -> dict:
    """Inorganic only: an accepted question that GLM solves is lower-tier Advanced; the author wants medium to
    hard (2026-11-25), so it counts as too easy here. flow.judge itself is unchanged for every subject."""
    if decision.get("decision") == "accept" and decision.get("first_solver") in TOO_EASY_SOLVERS:
        print(f"    inorganic: {decision['first_solver']} solved it → below medium Advanced")
        return {**decision, "decision": "too_easy", "reason": f"{decision['first_solver']} solved it (inorganic: "
                                                                "medium-hard only)"}
    return decision


def _system_question(adapter, rng, bb, log, n_draw):
    """One "reaction system, products as letters" question (inorg_system.py): built and keyed by code, worded
    like a real paper, every letter confirmed blind, then the level gate and the ladder (medium-hard only).
    The accepted result, or None."""
    from core.pipeline import flow, inorg_system as SY, qf_checks
    if not hasattr(adapter, "_bad_system"):
        adapter._bad_system = set()                # edges whose product the blind check did not confirm
    memory = SY.load_memory()                      # what earlier runs learned (review item #6, 2026-11-25)
    cand = SY.draw(_graph(adapter), rng, tried=bb.tried_edges() | {(k,) for k in memory["bottom_solved"]},
                   bad=adapter._bad_system | set(memory["unconfirmed_edges"]), asked=asked_species_sets(adapter))
    if cand is None:
        print("  no reaction system left")
        return None
    cand["_system"]["asked_facts"] = asked_fact_pairs(adapter)   # the statements avoid what was asked before
    print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
    bb.start_chain(cand)
    sig = _signature(adapter, cand, "inorganic_system")
    if dedup.duplicate_of(sig):                    # checked before anything is paid for
        print("  [dedup] a question on this reaction system was already accepted; next draw")
        return None
    made = SY.question(cand, rng)
    if made is None:
        print("  ✗ no four mixed statements on this system; next draw")
        return None
    stem, result, form, prose = made
    print(f"  [question] {form}, {'prose' if prose else 'scheme'} opening; key {result.answer} (code)")
    bad = SY.check_letters(cand, result.opening)   # identity of every letter, blind (reactions only, no options)
    bb.note("letter_check", disagree=bad)
    if bad:
        for e, _b in SY.blamed_steps(cand, bad):  # not the correct steps after a misread one
            adapter._bad_system.add(e["id"])
        SY.remember_unconfirmed(cand, bad)         # later runs skip it too (a failed call is not kept)
        log({"event": "letter_disagreement", "chain": cand["edges"], "letters": bad})
        print(f"  ✗ letter check (GPT-6 Luna, blind) differs on {len(bad)}: "
              + "; ".join(f"{b['letter']} {b['graph']} vs {b['checker']}" for b in bad)[:240] + "; next draw")
        return None
    print(f"  [letter check] all {len(cand['_system']['labels'])} letters confirmed (GPT-6 Luna, blind)")
    values = {"options": result.options, "mode": f"system_{form}", "labels": dict(cand["_system"]["labels"])}
    bb.note("qfirst", stem=stem, answer=result.answer, trace=result.trace, traps=result.traps)
    floor = qf_checks._level_floor(adapter.subject)
    if floor is not None:
        lvl = qf_checks.jev_level(stem)
        if lvl is not None:
            print(f"    [level] Jev: {lvl:.2f}; floor {floor:.2f}")
            bb.note("level", score=lvl, floor=floor)
            if lvl < floor:
                log({"event": "too_easy", "chain": cand["edges"], "reason": f"level {lvl:.2f} < {floor:.2f}"})
                print("  ✗ below JEE Advanced level (before the ladder is paid for); next draw")
                return None
    decision = _judge_medium_hard(adapter, cand, values, result, stem, bb, log)
    log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
         "answer": result.answer, "reason": decision.get("reason")})
    if decision["decision"] == "too_easy" and decision.get("first_solver") == models.LADDER[0][0]:
        SY.remember_bottom_solved(cand, decision["first_solver"], stem)    # easy whatever the statements
    if decision["decision"] == "accept":
        return {"status": "accepted", "payload": {
            "cand": cand, "plan": None, "values": values, "scenario": f"inorganic reaction system ({form})",
            "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
    print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
          + "; next draw")
    return None
