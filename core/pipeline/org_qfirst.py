"""
org_qfirst.py — the question-first flow for ORGANIC chemistry (same pattern as inorg_qfirst.py and physical's qfirst.py).

    draw       a real starting molecule (core/engine/organic/pool.py) and a walk of 2-3 reaction edges of
               knowledge/reaction_graph.json, every step computed by its RDKit rule (core/engine/organic/rules.py)
    options    built by CODE: the final product, and the products of the wrong turns a student takes (the rules'
               selectivity traps carried through the later steps, the product of a missed step); so the key is
               code's ("the coder"), never a model's
    design     the designer (models.DESIGNER) plans which intermediates are hidden and what the trap is; Jev's
               design check, as for the other subjects (off while organic has no design calibration)
    write      the writer (models.GENERATOR) writes the stem only: start molecule, reagents in order, hidden
               intermediates as X, Y; it may not show any product
    judge      flow.judge: the same ladder, grading by code (option letters), hold rule; accepted -> saved

Options are printed as SMILES, which every solver model reads; a name could be wrong, a SMILES is the structure.
"""

from __future__ import annotations

import json
import random

from core import dedup, models
from core.engine.base import ChainResult, EngineError
from core.engine.organic import pool as P
from core.engine.organic import rules as R
from core.engine.organic.mol import canon, classes
from core.llm import CutOffError

MAX_DRAWS = 6
CHAIN_MIN, CHAIN_MAX = 2, 3
LETTERS = "ABCD"
WRITE_RETRIES = 1


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


def _follow(path, start_index: int, smiles: str):
    """Run the steps path[start_index:] on smiles; None if a step does not apply."""
    cur = smiles
    for e in path[start_index:]:
        if not _single(cur):
            return None
        try:
            cur = R.apply(e, cur).product
        except EngineError:
            return None
    return cur


def options_for(path, start: str, steps: list) -> tuple:
    """(final product, distractors with why) — distractors are what a student gets by one wrong turn."""
    final = steps[-1].product
    out = {}

    def add(smi, why):
        try:
            c = canon(smi)
        except EngineError:
            return
        if c != canon(final) and c not in out:
            out[c] = why
    for i, r in enumerate(steps):
        for name, t in r.traps.items():
            later = _follow(path, i + 1, t) if i + 1 < len(path) else t
            if later:
                add(later, f"step {i + 1} with the wrong selectivity ({name}), then the later steps")
    for i in range(len(path)):                       # a step skipped (the student misses one reagent's effect)
        before = start if i == 0 else steps[i - 1].product
        skipped = _follow(path, i + 1, before) if i + 1 < len(path) else None
        if skipped:
            add(skipped, f"step {i + 1} ignored")
    if len(steps) >= 2:
        add(steps[-2].product, "stops one step early")
    return final, out


def draw(adapter, rng, tried=()):
    """A starting molecule and a walk of CHAIN_MIN..CHAIN_MAX ruled edges with at least 3 code-made distractors,
    one of them from a selectivity trap. A candidate dict, or None after many tries."""
    g = _graph(adapter)
    starts = [n for n in P.POOL if g["out"].get(n)]
    for _ in range(600):
        node = rng.choice(starts)
        name, start = rng.choice(P.POOL[node])
        path, steps, nodes, cur = [], [], [node], start
        k = rng.randint(CHAIN_MIN, CHAIN_MAX)
        while len(path) < k and _single(cur):
            nxt = [e for e in g["out"].get(nodes[-1], []) if e["id"] not in {p["id"] for p in path}]
            rng.shuffle(nxt)
            for e in nxt:
                try:
                    r = R.apply(e, cur)
                except EngineError:
                    continue
                path.append(e)
                steps.append(r)
                nodes.append(e["to"])
                cur = r.product
                break
            else:
                break
        if len(path) < CHAIN_MIN or not _single(steps[-1].product):
            continue
        key = tuple(e["id"] for e in path)
        if key in tried:
            continue
        final, wrong = options_for(path, start, steps)
        if len(wrong) < 3 or not any("selectivity" in w for w in wrong.values()):
            continue
        chapters = list(dict.fromkeys(e.get("chapter", "") for e in path))
        txs = [t for e in path for t in (e.get("tx_ids") or [])]
        return {"edges": list(key), "nodes": nodes, "chapters": chapters, "txs": txs, "trap_ids": [],
                "_path": path, "_steps": steps, "_start": (name, canon(start)), "_final": final, "_wrong": wrong,
                "description": f"{name} → " + " → ".join(nodes[1:]),
                "_hint": "Work out each intermediate in order; at each step decide the selectivity (which carbon, "
                         "which product is major) before going on."}
    return None


def _reagents(e) -> str:
    return R.REAGENT_USED.get(e["id"]) or "; ".join(e.get("reagents") or [])


def chain_text(cand) -> str:
    name, start = cand["_start"]
    lines = [f"Start: {name} ({start})"]
    for i, (e, r) in enumerate(zip(cand["_path"], cand["_steps"]), 1):
        traps = "; ".join(f"{k}: {v}" for k, v in r.traps.items())
        lines.append(f"Step {i}: [{_reagents(e)}] → {r.product}   ({r.why})" + (f"   wrong turns: {traps}" if traps else ""))
    return "\n".join(lines)


# ── design ───────────────────────────────────────────────────────────────────

def design_question(subject_name: str, cand) -> dict:
    from core.pipeline.qf_design import finish_design
    wrong = "\n".join(f"- {s}: {w}" for s, w in cand["_wrong"].items())
    prompt = f"""You are a senior JEE Advanced {subject_name} paper setter. DESIGN (do not write) ONE question that would
sit among the hardest of a real paper, on this reaction sequence (computed by code, true chemistry):
{chain_text(cand)}

The question asks for the FINAL product, as a single-correct MCQ. Code builds the options: the final product and
these wrong products (what a student gets by one wrong turn):
{wrong}

WHAT MAKES IT HARD: hidden intermediates. The student is told the starting compound and the reagents in order, but
not what forms in between (call the intermediates X, Y); the decisive step is the one whose selectivity (which
carbon, which product is major) a good student can get wrong.

Rules: the sequence is fixed (do not change reagents or products); do not reveal any product.

If no hard question can be built on this sequence, return only {{"impossible": "why"}}.

LENGTH: your thinking and the design TOGETHER must not exceed 1500 words.

Return JSON:
{{"system": "the sequence as the student meets it", "hidden": {{"X": "step 1 product", "Y": "..."}},
  "hidden_link": "what the student must work out", "route": "how a solver reaches the final product",
  "student_must_notice": "the selectivity point that decides the answer", "trap": "the tempting wrong product and why",
  "given": "what the question states", "asked": "the final product", "why_hard": "one sentence"}}"""
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
    d["format"] = "mcq_correct"
    d["hidden"] = {str(k): str(v) for k, v in (d.get("hidden") or {}).items()}
    d.setdefault("situation", d["system"])
    d.setdefault("insight", d.get("student_must_notice", ""))
    d.setdefault("links", d.get("route", ""))
    return d


# ── write ────────────────────────────────────────────────────────────────────

def write_question(subject_name: str, cand, design, feedback: str | None = None) -> dict:
    name, start = cand["_start"]
    steps = "\n".join(f"Step {i}: {_reagents(e)}" for i, e in enumerate(cand["_path"], 1))
    redo = f"\nYour previous draft was rejected: {feedback}\nFix exactly that.\n" if feedback else ""
    prompt = f"""Write the STEM of ONE JEE Advanced {subject_name} question from this design. Plain text, no LaTeX.

DESIGN:
{json.dumps({k: design.get(k) for k in ("system", "hidden", "hidden_link", "student_must_notice", "trap", "given", "asked")}, ensure_ascii=False, indent=1)}

Starting compound: {name}
Reagents, in order:
{steps}
{redo}
Rules:
- Name the starting compound exactly as "{name}" and give every step's reagents in order.
- Call the intermediates X, Y as in the design and the final product Z; ask which option is Z.
- Do NOT name, draw or describe any product or intermediate, and do not write options: code adds them.

Return JSON: {{"stem": "the question without its options"}}"""
    out = models.ask_json("generator", models.GENERATOR, "You write chemistry exam questions. Output JSON only.",
                          prompt, temperature=0.4, max_tokens=2000)
    if not out.get("stem"):
        raise ValueError("the writer returned no stem")
    return out


# ── evaluate (the answer key, by code) ───────────────────────────────────────

def evaluate(cand, q, rng) -> tuple:
    """(result, problems): the stem is checked by code; options and key are code's."""
    stem = str(q["stem"])
    name, _ = cand["_start"]
    problems = []
    if name.lower() not in stem.lower():
        problems.append(f'the stem must name the starting compound as "{name}"')
    shown = [cand["_final"]] + [r.product for r in cand["_steps"]]
    if any(s in stem for s in shown):
        problems.append("the stem shows a product or intermediate; refer to them only as X, Y, Z")
    if problems:
        return None, problems
    wrong = list(cand["_wrong"].items())
    sel = [w for w in wrong if "selectivity" in w[1]]
    rest = [w for w in wrong if "selectivity" not in w[1]]
    rng.shuffle(sel)
    rng.shuffle(rest)
    picked = (sel[:2] + rest + sel[2:])[:3]
    opts = [(cand["_final"], None)] + picked
    rng.shuffle(opts)
    letter = LETTERS[[o[0] for o in opts].index(cand["_final"])]
    trace = [{"tx": e.get("tx_ids") or [], "src": e["from"], "dst": e["to"], "formula": r.why,
              "inputs": {"reagents": _reagents(e)}, "outputs": {"product": r.product, "traps": r.traps}}
             for e, r in zip(cand["_path"], cand["_steps"])]
    traps = [{"id": f"option{LETTERS[i]}", "desc": why, "wrong_answer": LETTERS[i]}
             for i, (s, why) in enumerate(opts) if why]
    res = ChainResult(answer=letter, unit="", kind="letters", asks=stem, trace=trace, traps=traps, constants=[])
    res.options = [s for s, _ in opts]
    res.form = "organic_question_first:mcq_correct"
    return res, []


def full_stem(q, result) -> str:
    lines = "\n".join(f"({LETTERS[i]}) {s}" for i, s in enumerate(result.options))
    return (f"{str(q['stem']).strip()}\nOptions (structures as SMILES):\n{lines}\n"
            f"Choose the one correct option.")


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
            print("  no reaction chains left")
            break
        print(f"\n╔═══ DRAW {n_draw}: {cand['description']} ({', '.join(cand['chapters'])}) ═══╗")
        print("  " + chain_text(cand).replace("\n", "\n  "))
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
        print(f"  [design] hides {design['hidden']}; trap: {str(design.get('trap'))[:110]}")
        problem = design_problems(design, adapter.subject)
        if problem:
            bb.note("design_rejected", problem=problem)
            print(f"    design rejected: {problem[:160]}")
            continue
        feedback, made = None, None
        for attempt in range(1 + WRITE_RETRIES):
            if over_budget(cap):
                return {"status": "none"}
            try:
                q = write_question(name, cand, design, feedback=feedback)
            except ValueError as e:
                bb.note("question", attempt=attempt + 1, error=str(e)[:300])
                print(f"    question reply unusable: {str(e)[:120]}")
                continue
            result, probs = evaluate(cand, q, rng)
            bb.note("question", attempt=attempt + 1, stem=q.get("stem"))
            if probs:
                bb.note("question_rejected", attempt=attempt + 1, problems=probs)
                print(f"    stem rejected: {'; '.join(probs)[:220]}")
                feedback = "; ".join(probs)
                continue
            made = (q, result)
            break
        if made is None:
            log({"event": "question_failed", "chain": cand["edges"]})
            continue
        q, result = made
        stem = full_stem(q, result)
        values = {"start": cand["_start"][1], "options": result.options, "mode": "mcq_correct"}
        bb.note("qfirst", stem=stem, answer=result.answer, trace=result.trace, traps=result.traps)
        print(f"  [key] {result.answer} = {cand['_final']} (computed by code)")
        sig = dedup.signature(adapter.subject, cand["txs"] or cand["edges"], {"start": values["start"]})
        if dedup.duplicate_of(sig):
            print("  [dedup] same as an accepted question; next draw")
            continue
        decision = flow.judge(adapter, cand, None, values, result, stem, bb, log)
        log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"], "stem": stem,
             "answer": result.answer, "reason": decision.get("reason")})
        if decision["decision"] == "accept":
            return {"status": "accepted", "payload": {
                "cand": cand, "plan": None, "values": values, "scenario": "organic question-first (mcq_correct)",
                "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": None}}
        print(f"  ✗ {decision['decision']}" + (f" ({decision.get('reason')})" if decision.get("reason") else "")
              + "; next draw")
    return {"status": "none"}
