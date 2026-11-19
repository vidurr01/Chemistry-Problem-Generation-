"""
org_qfirst.py — the question-first flow for ORGANIC chemistry (same pattern as inorg_qfirst.py and physical's qfirst.py).

    draw       a real starting molecule (core/engine/organic/pool.py) and a reaction SCHEME of 5-8 steps: a main chain
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
import random

from core import dedup, models
from core.engine.base import ChainResult, EngineError
from core.engine.organic import pool as P
from core.engine.organic import props as OP
from core.engine.organic import rules as R
from core.engine.organic.labels import REAGENT_LABEL
from core.engine.organic.mol import canon
from core.llm import CutOffError

MAX_DRAWS = 6
STEPS_MIN, STEPS_MAX = 5, 8
MAX_BRANCHES = 2
LETTERS = "ABCD"
LABELS = "PQRSTUVWXYZ"
FORMATS = ("msq", "mcq_correct", "count", "integer")
CLAIM_RETRIES = 1
_NUMERIC = {k for k, v in OP.PROPERTIES.items() if v == "number"}


# ── draw ─────────────────────────────────────────────────────────────────────

def _graph(adapter):
    if not hasattr(adapter, "_g"):
        with open(adapter.config["graph_path"], encoding="utf-8") as f:
            g = json.load(f)
        out = {}
        for e in g["edges"]:
            if e["id"] in R.RULES:
                out.setdefault(e["from"], []).append(e)
        adapter._g = {"out": out, "edges": {e["id"]: e for e in g["edges"]}}
    return adapter._g


def _single(smiles: str) -> bool:
    return "." not in smiles


def _step(g, node, smiles, seen, rng, avoid=()):
    """One applicable edge from this compound to a new single compound: (edge, result) or None."""
    nxt = [e for e in g["out"].get(node, []) if e["id"] not in avoid]
    rng.shuffle(nxt)
    for e in nxt:
        try:
            r = R.apply(e, smiles)
        except EngineError:
            continue
        c = canon(r.product)
        if not _single(r.product) or c in seen:
            continue
        try:
            OP.askable(r.product)
        except EngineError:
            continue
        return e, r
    return None


def draw(adapter, rng, tried=()):
    """A scheme of STEPS_MIN..STEPS_MAX steps with 1..MAX_BRANCHES branch points. A candidate dict, or None."""
    g = _graph(adapter)
    starts = [n for n in P.POOL if g["out"].get(n)]
    for _ in range(800):
        node0 = rng.choice(starts)
        name, start = rng.choice(P.POOL[node0])
        target = rng.randint(STEPS_MIN, STEPS_MAX)
        # compounds: label -> {"smiles", "node", "parent", "edge", "result"}
        comps = {"P": {"smiles": canon(start), "node": node0, "parent": None, "edge": None, "result": None}}
        seen = {canon(start)}
        order = ["P"]
        main = ["P"]
        main_len = rng.randint(3, target - 1)
        while len(main) - 1 < main_len:
            cur = comps[main[-1]]
            got = _step(g, cur["node"], cur["smiles"], seen, rng)
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
            got = _step(g, comps[at]["node"], comps[at]["smiles"], seen, rng, avoid=used)
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
                got = _step(g, comps[tip]["node"], comps[tip]["smiles"], seen, rng)
        n_steps = len(order) - 1
        if branches == 0 or not STEPS_MIN <= n_steps <= STEPS_MAX:
            continue
        key = tuple(comps[k]["edge"]["id"] for k in order[1:])
        if key in tried:
            continue
        path = [comps[k]["edge"] for k in order[1:]]
        chapters = list(dict.fromkeys(e.get("chapter", "") for e in path))
        txs = [t for e in path for t in (e.get("tx_ids") or [])]
        cand = {"edges": list(key), "nodes": [comps[k]["node"] for k in order], "chapters": chapters, "txs": txs,
                "trap_ids": [], "_comps": comps, "_order": order, "_start": (name, canon(start)),
                "description": f"{name}: {n_steps} steps, {branches} branch point(s)",
                "_hint": "Work out every lettered compound in order, deciding at each step which product is major; "
                         "only then judge each statement about it."}
        cand["_props"] = {k: OP.askable(comps[k]["smiles"]) for k in order}
        cand["_wrong"] = wrong_structures(cand)
        return cand
    return None


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
             "integer": 'one "claim" with compound and property only (a numeric property); no value'}[fmt]
    redo = f"\nYour previous draft was rejected: {feedback}\nFix exactly that.\n" if feedback else ""
    prompt = f"""Write ONE JEE Advanced {subject_name} question from this design. Plain text, Unicode subscripts, no LaTeX.

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

Return JSON: {{"lead": "...", "ask": "...", "format": "{fmt}",
  "claims": [{{"text": "...", "compound": "S", "property": "...", "value": "..."}}]}}"""
    out = models.ask_json("generator", models.GENERATOR, "You write chemistry exam questions. Output JSON only.",
                          prompt, temperature=0.4, max_tokens=4000)
    if not out.get("ask") or not isinstance(out.get("claims"), list):
        raise ValueError("the writer returned no question or claims")
    out["format"] = fmt
    return out


# ── evaluate (the answer key, by code) ───────────────────────────────────────

def evaluate(cand, q) -> tuple:
    """(result, problems). Every claim decided by code; problems the writer can fix are listed."""
    fmt = q["format"]
    rows = [r for r in q.get("claims") or [] if isinstance(r, dict)]
    problems = []
    need = {"msq": (4, 4), "mcq_correct": (4, 4), "count": (4, 8), "integer": (1, 1)}[fmt]
    if not need[0] <= len(rows) <= need[1]:
        problems.append(f"format {fmt} needs {need[0]}" + (f" to {need[1]}" if need[1] != need[0] else "")
                        + f" claims, the draft has {len(rows)}")
    text = f"{q.get('lead', '')} {q.get('ask', '')}"
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


def full_stem(cand, q, result) -> str:
    head = f"{str(q.get('lead') or '').strip()}\n{scheme_text(cand)}\n{str(q['ask']).strip()}"
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
    for n_draw in range(1, MAX_DRAWS + 1):
        if over_budget(cap):
            break
        cand = draw(adapter, rng, tried=bb.tried_edges())
        if cand is None:
            print("  no reaction schemes left")
            break
        print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
        print("  " + scheme_text(cand).replace("\n", "\n  "))
        print("  " + "\n  ".join(f"{k} = {cand['_comps'][k]['smiles']}" for k in cand["_order"]))
        bb.start_chain(cand)
        try:
            design = design_question(name, cand)
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
            bb.note("question", attempt=attempt + 1, **{k: q.get(k) for k in ("lead", "ask", "format", "claims")})
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
        log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
             "answer": result.answer, "reason": decision.get("reason")})
        if decision["decision"] == "accept":
            return {"status": "accepted", "payload": {
                "cand": cand, "plan": None, "values": values, "scenario": f"organic question-first ({q['format']})",
                "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
        print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
              + "; next draw")
    return {"status": "none"}
