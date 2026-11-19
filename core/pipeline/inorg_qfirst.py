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
import random
import re

from core import dedup, models
from core.engine.base import ChainResult, EngineError
from core.engine.inorganic import species as S
from core.llm import CutOffError

MAX_DRAWS = 6
CHAIN_MIN, CHAIN_MAX = 2, 4
LETTERS = "ABCD"
FORMATS = ("msq", "mcq_correct", "mcq_incorrect", "count", "identify")
CLAIM_RETRIES = 1        # a draft whose claims code cannot read is sent back once with the exact problems


# ── draw ─────────────────────────────────────────────────────────────────────

def _graph(adapter):
    if not hasattr(adapter, "_g"):
        with open(adapter.config["graph_path"], encoding="utf-8") as f:
            g = json.load(f)
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
    for n_draw in range(1, MAX_DRAWS + 1):
        if over_budget(cap):
            break
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
