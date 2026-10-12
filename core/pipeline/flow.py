"""
flow.py — one question through the pipeline. Every decision here is code.

    for up to MAX_CHAINS chains (best coverage first):
        pick inputs (generator; may veto an incoherent chain) → engine
        loop over rounds (at most MAX_ROUNDS refinements):
            write stem → gate (original + GATE_RETRIES) → duplicate check
            council → verifier on every member → grade in code
            reference wrong / unresolved objection → queue, drop chain
            2+ solved → too easy → refine (new inputs or reword), next round
            ≤1 solved → hint tests on the failed members
                clarification solves → reword, next round
                otherwise → ACCEPT (tagged recall if a knowledge hint was needed)

judge() (council onward) is separate so a question parked by an API failure can be
judged again on the next run without regenerating it.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import random

from core import answers, dedup
from core.engine.base import EngineError, round_sig
from core.pipeline import gate, queues, stages
from core.pipeline.stages import CouncilMemberFailed

MAX_CHAINS = 3          # chains (question ideas) per run
MAX_ROUNDS = 3          # refinements per chain (too easy, or reworded for clarity)
GATE_RETRIES = 2        # stem rewrites after a gate mismatch (original + 2)
INPUT_TRIES = 3         # input proposals per round before the chain is dropped
TOO_EASY_IF_SOLVED_GE = 2


class Parked(Exception):
    """The council could not be measured (an API failure); the question is saved for
    a recheck on the next run."""

    def __init__(self, item):
        super().__init__(item.get("error", "parked"))
        self.item = item


# ── text helpers ─────────────────────────────────────────────────────────────

def answer_text(result) -> str:
    return f"{result.answer}{(' ' + result.unit) if result.unit else ''}"


def trace_text(result) -> str:
    lines = []
    for i, t in enumerate(result.trace):
        ins = ", ".join(f"{k} = {json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}"
                        for k, v in t["inputs"].items())
        outs = ", ".join(f"{k} = {v}" for k, v in t["outputs"].items())
        lines.append(f"Step {i + 1}: {t['formula']}\n   with {ins}\n   gives {outs}")
    if result.constants:
        lines.append("Constants used: " + "; ".join(result.constants))
    lines.append(f"Final answer: {answer_text(result)}")
    return "\n".join(lines)


def knowledge_hint(plan) -> str:
    rels = [st.formula for st in plan.steps if st.formula]
    return "Relations that may help: " + "; ".join(rels) + "."


def insight_hint(plan, failed_step) -> str:
    """Names the kind of step, never the result: written by code from the step and one
    of its listed mistakes."""
    steps = plan.steps
    idx = (failed_step - 1) if isinstance(failed_step, int) and 1 <= failed_step <= len(steps) else None
    if idx is None:
        idx = max((i for i, s in enumerate(steps) if s.traps), default=len(steps) - 1)
    st = steps[idx]
    text = f"Look again at the step where you work out the {st.asks}."
    if st.traps:
        text += f" A common mistake there: {st.traps[0].desc}."
    return text


# ── stages wired together ────────────────────────────────────────────────────

def _propose(adapter, cand, spec, bb, log, refine=None):
    """Up to INPUT_TRIES proposals; returns (values, scenario, result) or None to drop."""
    errors = []
    for attempt in range(INPUT_TRIES):
        out = stages.propose_inputs(adapter.config["display_name"], adapter.chain_text(cand["_plan"]),
                                    spec, refine=refine, errors=errors or None)
        if not out["coherent"]:
            bb.note("inputs_veto", reason=out.get("reason", ""))
            log({"event": "inputs_veto", "chain": cand["edges"], "reason": out.get("reason", "")})
            print(f"    generator vetoed the chain: {str(out.get('reason', ''))[:140]}")
            return None
        values, errs = stages.coerce_values(spec, out.get("values"))
        if not errs:
            try:
                result = adapter.compute(cand["_plan"], values)
                bb.note("inputs", values=values, scenario=out.get("scenario", ""), answer=result.answer)
                return values, out.get("scenario", ""), result
            except EngineError as e:
                errs = [str(e)]
            except Exception as e:                               # an engine bug, not bad inputs
                queues.add("engine_unknown", adapter.subject, {
                    "chain": cand["edges"], "txs": cand["txs"], "values": values,
                    "error": f"{type(e).__name__}: {e}"})
                print(f"    engine failed unexpectedly ({type(e).__name__}); queued engine_unknown")
                return None
        errors = errs
        bb.note("inputs_rejected", attempt=attempt + 1, errors=errs)
        print(f"    inputs rejected ({attempt + 1}/{INPUT_TRIES}): {'; '.join(errs)[:160]}")
    log({"event": "inputs_failed", "chain": cand["edges"], "errors": errors})
    return None


def _ask_options(plan, rng):
    final = plan.steps[-1]
    final_asks = (final.final[3] if final.final else final.asks)
    others = [s.asks for s in plan.steps[:-1] if s.asks and s.asks != final_asks]
    opts = list(dict.fromkeys([final_asks] + others + ["something else"]))
    shuffled = opts[:-1]
    rng.shuffle(shuffled)
    shuffled.append(opts[-1])
    return shuffled, shuffled.index(final_asks) + 1


def _stem_and_gate(adapter, cand, spec, values, scenario, result, bb, rng, previous=None, feedback=None):
    """Write the stem and pass the gate. Returns (stem, None) or (None, reason)."""
    plan = cand["_plan"]
    traps = [t["desc"] for t in result.traps]
    options, correct = _ask_options(plan, rng)
    for attempt in range(GATE_RETRIES + 1):
        stem = stages.write_stem(adapter.config["display_name"], scenario, adapter.chain_text(plan), spec,
                                 values, result.constants, result.asks, result.unit, traps,
                                 previous=previous, feedback=feedback)
        ext = stages.gate_extract(stem, spec, options, result.constants)
        g = gate.compare(spec, values, ext, correct, result.constants)
        bb.note("gate", attempt=attempt + 1, stem=stem, ok=g["ok"], mismatches=g["mismatches"],
                unreadable=g["unreadable"])
        if g["ok"]:
            print(f"    gate passed (attempt {attempt + 1})")
            return stem, None
        if g["unreadable"]:
            queues.add("gate_unreadable", adapter.subject, {"chain": cand["edges"], "stem": stem,
                                                            "extraction": ext})
            print("    gate could not read the stem; queued gate_unreadable")
            return None, "gate_unreadable"
        print(f"    gate mismatch ({attempt + 1}/{GATE_RETRIES + 1}): {'; '.join(g['mismatches'])[:200]}")
        previous, feedback = stem, "Fix these problems: " + "; ".join(g["mismatches"])
    return None, "gate_failed"


def _grade(result, member, diag) -> dict:
    """Facts and judgement for one member, both kept (answer_matches is never overwritten)."""
    match = answers.matches(result.answer, member.get("final_answer"), result.kind)
    solved, slip_confirmed = False, None
    if match and diag["verdict"] == "correct":
        solved = True
    elif not match and diag.get("failure_type") == "slip" or (not match and diag["verdict"] == "correct"):
        expr = diag.get("member_expression")
        try:
            slip_confirmed = expr is not None and isinstance(result.answer, (int, float)) and \
                answers.matches(result.answer, answers.safe_eval(expr))
        except (ValueError, ZeroDivisionError, OverflowError, SyntaxError, TypeError):
            slip_confirmed = False
        solved = bool(slip_confirmed)
    return {"answer_matches": match, "verdict": diag["verdict"], "failure_type": diag.get("failure_type"),
            "slip_confirmed": slip_confirmed, "counts_as_solved": solved}


def judge(adapter, cand, plan, values, result, stem, bb, log) -> dict:
    """Council → verifier → grading → hint tests. Returns one of:
       {"decision": "accept", ...} | {"decision": "too_easy", ...} | {"decision": "reword", "feedback"}
       | {"decision": "drop", "reason"}.  Raises Parked if a council call fails."""
    try:
        members = stages.council_solve(stem)
    except CouncilMemberFailed as e:
        raise Parked({"error": str(e)})
    rtext, atext = trace_text(result), answer_text(result)
    with cf.ThreadPoolExecutor(max_workers=len(members)) as ex:
        diags = list(ex.map(lambda m: stages.verify_member(stem, rtext, atext, m), members))
    graded = [{**m, "diagnosis": d, **_grade(result, m, d)} for m, d in zip(members, diags)]
    bb.note("council", members=graded)
    for g in graded:
        tag = "solved" if g["counts_as_solved"] else ("correct-but-not-counted" if g["answer_matches"] else "failed")
        print(f"    [{g['name']}] {g['final_answer']} {g['unit']} → {tag}"
              f" ({g['verdict']}{', ' + g['failure_type'] if g['failure_type'] else ''})")

    # engine or question judged wrong, or an objection nobody can settle
    for g in graded:
        d = g["diagnosis"]
        if d["verdict"] == "reference_wrong" or d.get("objection_assessment") == "valid":
            qid = queues.add("engine_wrong", adapter.subject, {
                "chain": cand["edges"], "txs": cand["txs"], "values": values, "stem": stem,
                "engine_answer": atext, "member": g["name"], "member_answer": g["final_answer"],
                "diagnosis": d})
            log({"event": "engine_wrong", "chain": cand["edges"], "queue_id": qid, "member": g["name"]})
            return {"decision": "drop", "reason": "engine_wrong", "graded": graded}
        if g.get("objection") and d.get("objection_assessment") == "unsure":
            qid = queues.add("objection_unresolved", adapter.subject, {
                "chain": cand["edges"], "txs": cand["txs"], "values": values, "stem": stem,
                "engine_answer": atext, "member": g["name"], "objection": g["objection"], "diagnosis": d})
            log({"event": "objection_unresolved", "chain": cand["edges"], "queue_id": qid})
            return {"decision": "drop", "reason": "objection_unresolved", "graded": graded}

    n_correct = sum(g["answer_matches"] for g in graded)
    n_solved = sum(g["counts_as_solved"] for g in graded)
    print(f"    council: {n_correct}/3 answers match, {n_solved}/3 count as solved")
    if n_solved >= TOO_EASY_IF_SOLVED_GE:
        return {"decision": "too_easy", "graded": graded, "n_correct": n_correct, "n_solved": n_solved}

    # hint tests on every member that did not solve
    recall, hint_log = False, []
    for g in graded:
        if g["counts_as_solved"]:
            continue
        d = g["diagnosis"]
        kind = d.get("failure_type") or "genuine_difficulty"
        if d["verdict"] == "right_answer_wrong_reasoning" or kind == "slip":
            kind = "genuine_difficulty"            # an unconfirmed slip or a lucky answer is tested like any failure

        if kind == "unclear_wording":
            hint = stages.clarification_hint(stem, d.get("ambiguous_text") or "", d.get("clarification") or "")
            re_ = stages.solve_with_hint(g, stem, hint)
            ok = answers.matches(result.answer, re_["final_answer"], result.kind)
            hint_log.append({"member": g["name"], "hint": "clarification", "text": hint, "solved": ok,
                             "answer": re_["final_answer"]})
            print(f"    [hint] {g['name']}: clarification → {'solved (wording was the obstacle)' if ok else 'still wrong'}")
            if ok:
                bb.note("hints", tests=hint_log)
                return {"decision": "reword", "graded": graded,
                        "feedback": f"Solvers misread: {d.get('ambiguous_text')}. State it plainly: {d.get('clarification')}"}
            kind = "genuine_difficulty"

        if kind == "missing_knowledge":
            hint = knowledge_hint(plan)
            re_ = stages.solve_with_hint(g, stem, hint)
            ok = answers.matches(result.answer, re_["final_answer"], result.kind)
            hint_log.append({"member": g["name"], "hint": "knowledge", "text": hint, "solved": ok,
                             "answer": re_["final_answer"]})
            print(f"    [hint] {g['name']}: knowledge → {'solved (recall)' if ok else 'still wrong'}")
            if ok:
                recall = True
                continue
            kind = "genuine_difficulty"

        # genuine difficulty: always confirmed with the code-written insight hint
        hint = insight_hint(plan, d.get("failed_step"))
        re_ = stages.solve_with_hint(g, stem, hint)
        ok = answers.matches(result.answer, re_["final_answer"], result.kind)
        entry = {"member": g["name"], "hint": "insight", "text": hint, "solved": ok, "answer": re_["final_answer"]}
        print(f"    [hint] {g['name']}: insight → {'solved (difficulty confirmed)' if ok else 'still wrong; verifier re-checks'}")
        if not ok:
            d2 = stages.verify_member(stem, rtext, atext, re_, after_hint=hint)
            entry["recheck"] = d2
            if d2["verdict"] == "reference_wrong":
                qid = queues.add("engine_wrong", adapter.subject, {
                    "chain": cand["edges"], "txs": cand["txs"], "values": values, "stem": stem,
                    "engine_answer": atext, "member": g["name"], "member_answer": re_["final_answer"],
                    "diagnosis": d2, "after_hint": hint})
                hint_log.append(entry)
                bb.note("hints", tests=hint_log)
                log({"event": "engine_wrong", "chain": cand["edges"], "queue_id": qid, "after_hint": True})
                return {"decision": "drop", "reason": "engine_wrong", "graded": graded}
            if d2.get("failure_type") == "unclear_wording":
                hint_log.append(entry)
                bb.note("hints", tests=hint_log)
                return {"decision": "reword", "graded": graded,
                        "feedback": f"After a hint a solver still misread: {d2.get('ambiguous_text')}. "
                                    f"State it plainly: {d2.get('clarification')}"}
        hint_log.append(entry)

    bb.note("hints", tests=hint_log)
    return {"decision": "accept", "graded": graded, "n_correct": n_correct, "n_solved": n_solved,
            "recall": recall, "hints": hint_log}


def _solved_summary(graded) -> str:
    out = []
    for g in graded:
        if g["counts_as_solved"]:
            out.append(f"- {g['name']}: {str(g.get('working', ''))[:1200]}")
    return "\n".join(out) or "(none)"


def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Try up to MAX_CHAINS chains. Returns {"status": "accepted", "payload"} or
    {"status": "none"}. Raises Parked."""
    rng = rng or random.Random()
    cands = adapter.candidates(coverage, chapter, n=MAX_CHAINS * 4, exclude=bb.tried_edges())
    if not cands:
        print("  no computable chains available")
        return {"status": "none"}
    for chain_no, cand in enumerate(cands[:MAX_CHAINS], 1):
        print(f"\n╔═══ CHAIN {chain_no}: {' → '.join(cand['nodes'])}  (txs {cand['txs']}) ═══╗")
        bb.start_chain(cand)
        plan = cand["_plan"]
        spec = adapter.input_spec(plan)
        print("  [inputs] generator proposes values...")
        picked = _propose(adapter, cand, spec, bb, log)
        if picked is None:
            continue
        values, scenario, result = picked
        print(f"  [engine] answer {answer_text(result)}; traps: {[t['id'] for t in result.traps]}")
        previous = feedback = None
        while True:
            print(f"  [stem] round {bb.current['rounds']}: writing the question...")
            stem, why = _stem_and_gate(adapter, cand, spec, values, scenario, result, bb, rng,
                                       previous=previous, feedback=feedback)
            if stem is None:
                log({"event": why, "chain": cand["edges"]})
                break
            sig = dedup.signature(adapter.subject, cand["txs"], values)
            dup = dedup.duplicate_of(sig)
            if dup:
                print(f"  [dedup] same inputs as accepted question {dup}; choosing new inputs")
                bb.note("duplicate", of=dup)
                decision = {"decision": "too_easy", "graded": []}
            else:
                print("  [council] three closed-book solves...")
                decision = judge(adapter, cand, plan, values, result, stem, bb, log)
            log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"],
                 "stem": stem, "answer": round_sig(result.answer), "reason": decision.get("reason"),
                 "council": [{k: g.get(k) for k in ("name", "final_answer", "answer_matches", "counts_as_solved",
                                                    "verdict", "failure_type")} for g in decision.get("graded", [])]})
            if decision["decision"] == "accept":
                return {"status": "accepted", "payload": {
                    "cand": cand, "plan": plan, "values": values, "scenario": scenario, "result": result,
                    "stem": stem, "decision": decision, "sig": sig}}
            if decision["decision"] == "drop":
                break
            if bb.current["rounds"] >= MAX_ROUNDS:
                print(f"  ✗ {MAX_ROUNDS} refinements used; dropping this chain")
                log({"event": "rounds_exhausted", "chain": cand["edges"]})
                break
            bb.current["rounds"] += 1
            if decision["decision"] == "reword":
                print("  [refine] rewording for clarity")
                previous, feedback = stem, decision["feedback"]
                continue
            choice = stages.choose_refinement(stem, _solved_summary(decision["graded"]), adapter.refine_modes)
            bb.note("refine", **choice)
            print(f"  [refine] too easy → {choice['mode']}: {choice['feedback'][:140]}")
            if choice["mode"] == "reword":
                previous, feedback = stem, "Too easy: " + choice["feedback"]
                continue
            picked = _propose(adapter, cand, spec, bb, log,
                              refine={"values": values, "summary": choice["feedback"]})
            if picked is None:
                break
            values, scenario, result = picked
            print(f"  [engine] new answer {answer_text(result)}")
            previous = feedback = None
    return {"status": "none"}
