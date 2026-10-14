"""
flow.py — one question through the pipeline. Every decision here is code.

    for up to MAX_CHAINS chains (best coverage first):
        pick inputs (generator; may veto an incoherent chain) → engine
        loop over rounds (at most MAX_ROUNDS refinements):
            write stem → gate (original + GATE_RETRIES) → duplicate check
            ladder (weakest first; next step only if all below failed) → verifier → grade in code
            reference wrong / unresolved objection → queue, drop chain
            first step solves → too easy → refine (new inputs or reword), next round
            first step fails → hint tests on the failed steps
                clarification solves → reword, next round
                otherwise → ACCEPT, labelled by the first step that solved it
                (tagged recall if a knowledge hint was needed)

judge() (ladder onward) is separate so a question parked by an API failure can be
judged again on the next run without regenerating it.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import random
import re

from core import answers, dedup, models
from core.engine.base import EngineError, round_sig
from core.pipeline import gate, queues, stages
from core.pipeline.stages import CouncilMemberFailed

MAX_CHAINS = 3          # chains (question ideas) per run
MAX_ROUNDS = 3          # refinements per chain (too easy, or reworded for clarity)
GATE_RETRIES = 2        # stem rewrites after a gate mismatch (original + 2)
INPUT_TRIES = 3         # input proposals per round before the chain is dropped


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


def _fact_source(cand):
    from core.engine.physical.facts_data import BY_ID
    return BY_ID[cand["nodes"][0]]


def knowledge_hint(cand) -> str:
    """The knowledge a question rests on, written by code: the chain's relations, or for a
    fact question, true facts from the same table (solving after this tags it 'recall')."""
    if "_fact" in cand:
        true, _ = _fact_source(cand).statements()
        return "Facts that may help: " + " ".join(s for s, _, _ in true[:8])
    rels = [st.formula for st in cand["_plan"].steps if st.formula]
    return "Relations that may help: " + "; ".join(rels) + "."


def insight_hint(cand, failed_step) -> str:
    """Names the kind of step, never the result: written by code from the step and one
    of its listed mistakes."""
    if "_fact" in cand:
        return (f"Judge each statement on its own against what you know about {_fact_source(cand).title}; "
                f"check every detail of a statement, not just its general idea.")
    steps = cand["_plan"].steps
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
        traps = list(dict.fromkeys(t.desc for st in cand["_plan"].steps for t in st.traps))
        out = stages.propose_inputs(adapter.config["display_name"], adapter.chain_text(cand["_plan"]),
                                    spec, refine=refine, errors=errors or None, traps=traps)
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


FRAGILE_TOL = 0.02     # an answer that rounding moves by more than this is not asked


def _stable_ask(adapter, cand, values, result, bb):
    """A JEE paper never asks for a number like e^(−34.1) = 1.5 × 10⁻¹⁵, which rounding the
    intermediates moves by several per cent; it asks the quantity before it (here Eₐ). While
    the answer's rounding tolerance exceeds FRAGILE_TOL, drop the chain's last step and ask
    the previous step's result with the same inputs. Returns (cand, values, result)."""
    while _is_numeric(result) and result.tolerance > FRAGILE_TOL and len(cand["txs"]) > 1:
        txs = cand["txs"][:-1]
        try:
            plan = adapter.plan(txs)
            vals = {s["key"]: values[s["key"]] for s in adapter.input_spec(plan)}
            new = adapter.compute(plan, vals)
        except (KeyError, EngineError):
            break
        print(f"  [engine] {answer_text(result)} moves ±{result.tolerance:.1%} with rounding; "
              f"asking the {plan.steps[-1].asks} instead")
        bb.note("shortened", dropped_tx=cand["txs"][-1], tolerance=result.tolerance)
        steps = plan.steps
        cand = {**cand, "txs": txs, "edges": cand["edges"][:-1], "nodes": cand["nodes"][:-1],
                "_plan": plan, "_steps": steps,
                "trap_ids": sorted({t.id for s in steps for t in s.traps}),
                "description": " → ".join(f"{s.asks} [{s.formula}]" for s in steps)}
        values, result = vals, new
    return cand, values, result


def _ask_options(plan, rng):
    final = plan.steps[-1]
    final_asks = (final.final[3] if final.final else final.asks)
    others = [s.asks for s in plan.steps[:-1] if s.asks and s.asks != final_asks]
    opts = list(dict.fromkeys([final_asks] + others + ["something else"]))
    shuffled = opts[:-1]
    rng.shuffle(shuffled)
    shuffled.append(opts[-1])
    return shuffled, shuffled.index(final_asks) + 1


def _stem_and_gate(adapter, cand, spec, values, scenario, result, bb, rng, previous=None, feedback=None,
                   solved=None):
    """Write the stem and pass the gate. Returns (stem, None) or (None, reason)."""
    plan = cand["_plan"]
    traps = [t["desc"] for t in result.traps]
    options, correct = _ask_options(plan, rng)
    fmt = adapter.answer_format(result) if hasattr(adapter, "answer_format") else None
    for attempt in range(GATE_RETRIES + 1):
        stem = stages.write_stem(adapter.config["display_name"], scenario, adapter.chain_text(plan), spec,
                                 values, result.constants, result.asks, result.unit, traps,
                                 previous=previous, feedback=feedback, solved=solved, answer_format=fmt)
        ext = stages.gate_extract(stem, spec, options, result.constants)
        g = gate.compare(spec, values, ext, correct, result.constants)
        if fmt and " ".join(fmt.split()) not in " ".join(stem.split()):
            g = {**g, "ok": False, "unreadable": False,
                 "mismatches": g["mismatches"] + [f"the question must end with this sentence, copied exactly: {fmt}"]}
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


def _is_numeric(result) -> bool:
    return isinstance(result.answer, (int, float)) and not isinstance(result.answer, bool)


def _eval_expression(expr):
    """Value of the member's set-up arithmetic. Verifiers often write a chain such as
    'exp(-(156070)/(8.314*550)) = exp(-34.13) ≈ 1.5e-15'; the first segment that is plain
    arithmetic is the set-up. None if no segment evaluates."""
    if expr is None:
        return None
    for seg in re.split(r"=|≈|≅|~|→", str(expr)):
        seg = seg.strip()
        if not seg:
            continue
        try:
            return answers.safe_eval(seg)
        except (ValueError, ZeroDivisionError, OverflowError, SyntaxError, TypeError):
            continue
    return None


def _text_match(result, final_answer, diag):
    """(matches, decided_by) for a final answer; diag is the verifier's diagnosis or None."""
    if answers.matches(result.answer, final_answer, result.kind, getattr(result, "tolerance", 0.01)):
        return True, "code"
    if _is_numeric(result) or result.kind == "letters" or final_answer is None:
        return False, "code"
    decided = answers.text_answers_match(result.answer, final_answer)
    if decided is not None or diag is None:
        return bool(decided), "code"
    eq = diag.get("answer_equivalent")
    if eq is None:                                   # older reply without the field
        eq = diag.get("verdict") in ("correct", "right_answer_wrong_reasoning")
    return bool(eq), "verifier"


def _grade(result, member, diag) -> dict:
    """Facts and judgement for one member, both kept (answer_matches is never overwritten).

    Numbers and option letters are matched by code only. A non-numeric answer is compared by
    code where its shape allows (formulas by element counts, nuclides, configurations, balanced
    equations, categories such as forward/backward or yes/no with synonyms); when code cannot
    tell, the verifier's narrow answer_equivalent field decides. match_by records which."""
    match, match_by = _text_match(result, member.get("final_answer"), diag)
    solved, slip_confirmed = False, None
    if match and diag["verdict"] in ("correct", "wrong"):
        # the final answer is within tolerance: a slip the verifier saw on the way (e.g. 29.52
        # against 29.79 L) did not change the result, so it counts as solved. Only a right
        # answer by a wrong or lucky route is not counted.
        solved = True
    elif not match and diag.get("failure_type") == "slip" or (not match and diag["verdict"] == "correct"):
        expr = diag.get("member_expression")
        value = _eval_expression(expr)
        slip_confirmed = value is not None and _is_numeric(result) and \
            answers.matches(result.answer, value, result.kind, getattr(result, "tolerance", 0.01))
        solved = bool(slip_confirmed)
    return {"answer_matches": match, "match_by": match_by, "verdict": diag["verdict"],
            "failure_type": diag.get("failure_type"), "slip_confirmed": slip_confirmed, "counts_as_solved": solved}


def _hint_solved(result, re_, stem, rtext, atext, hint):
    """Did the member solve it after the hint? Same rule as grading: code where it can decide,
    otherwise the verifier's answer_equivalent (returns that diagnosis too)."""
    ok, _ = _text_match(result, re_["final_answer"], None)
    if ok or _is_numeric(result) or result.kind == "letters" or \
            answers.text_answers_match(result.answer, re_["final_answer"]) is not None:
        return ok, None
    d = stages.verify_member(stem, rtext, atext, re_, after_hint=hint)
    return _text_match(result, re_["final_answer"], d)[0], d


def judge(adapter, cand, plan, values, result, stem, bb, log) -> dict:
    """Ladder → verifier → grading → hint tests. Returns one of:
       {"decision": "accept", ...} | {"decision": "too_easy", ...} | {"decision": "reword", "feedback"}
       | {"decision": "drop", "reason"}.  Raises Parked if a council call fails."""
    rtext, atext = trace_text(result), answer_text(result)

    def solve_and_grade(names):
        try:
            members = stages.council_solve(stem, names)
        except CouncilMemberFailed as e:
            raise Parked({"error": str(e)})
        with cf.ThreadPoolExecutor(max_workers=len(members)) as ex:
            diags = list(ex.map(lambda m: stages.verify_member(stem, rtext, atext, m), members))
        return [{**m, "diagnosis": d, **_grade(result, m, d)} for m, d in zip(members, diags)]

    # Ladder: the weakest model first; each next step is called only if every step below
    # failed. If the first step solves it, the question is too easy; otherwise the first step
    # that solves it (or none) is the difficulty label.
    graded = []
    for name, _ in models.LADDER:
        graded += solve_and_grade([name])
        if graded[-1]["counts_as_solved"]:
            break
    called = {g["name"] for g in graded}
    skipped = [n for n, _ in models.LADDER if n not in called]
    first_solver = next((g["name"] for g in graded if g["counts_as_solved"]), None)
    bb.note("council", members=graded, skipped=skipped, first_solver=first_solver)
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
    bottom = models.LADDER[0][0]
    if first_solver == bottom:
        print(f"    ladder: {bottom} solved it → too easy")
        return {"decision": "too_easy", "graded": graded, "n_correct": n_correct, "n_solved": n_solved,
                "skipped": skipped, "first_solver": first_solver}
    label = models.DIFFICULTY_LABELS.get(first_solver, "frontier")
    print(f"    ladder: {bottom} failed; first solved by {first_solver or 'no step'} → {label}")

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
            ok, _ = _hint_solved(result, re_, stem, rtext, atext, hint)
            hint_log.append({"member": g["name"], "hint": "clarification", "text": hint, "solved": ok,
                             "answer": re_["final_answer"]})
            print(f"    [hint] {g['name']}: clarification → {'solved (wording was the obstacle)' if ok else 'still wrong'}")
            if ok:
                bb.note("hints", tests=hint_log)
                return {"decision": "reword", "graded": graded,
                        "feedback": f"Solvers misread: {d.get('ambiguous_text')}. State it plainly: {d.get('clarification')}"}
            kind = "genuine_difficulty"

        if kind == "missing_knowledge":
            hint = knowledge_hint(cand)
            re_ = stages.solve_with_hint(g, stem, hint)
            ok, _ = _hint_solved(result, re_, stem, rtext, atext, hint)
            hint_log.append({"member": g["name"], "hint": "knowledge", "text": hint, "solved": ok,
                             "answer": re_["final_answer"]})
            print(f"    [hint] {g['name']}: knowledge → {'solved (recall)' if ok else 'still wrong'}")
            if ok:
                recall = True
                continue
            kind = "genuine_difficulty"

        # genuine difficulty: always confirmed with the code-written insight hint
        hint = insight_hint(cand, d.get("failed_step"))
        re_ = stages.solve_with_hint(g, stem, hint)
        ok, d_hint = _hint_solved(result, re_, stem, rtext, atext, hint)
        entry = {"member": g["name"], "hint": "insight", "text": hint, "solved": ok, "answer": re_["final_answer"]}
        if d_hint is not None:
            entry["judged_by_verifier"] = d_hint
        print(f"    [hint] {g['name']}: insight → {'solved (difficulty confirmed)' if ok else 'still wrong; verifier re-checks'}")
        if not ok:
            d2 = d_hint or stages.verify_member(stem, rtext, atext, re_, after_hint=hint)
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
            "recall": recall, "hints": hint_log, "skipped": skipped, "first_solver": first_solver,
            "difficulty_label": label}


def _solved_summary(graded) -> str:
    out = []
    for g in graded:
        if g["counts_as_solved"]:
            out.append(f"- {g['name']}: {str(g.get('working', ''))[:1200]}")
    return "\n".join(out) or "(none)"


def _fact_stem_and_gate(adapter, cand, bb, previous=None, feedback=None, solved=None):
    """Stem for a fact question; the gate is code: question sentence and options verbatim."""
    fq = cand["_fact"]
    src = _fact_source(cand)
    for attempt in range(GATE_RETRIES + 1):
        stem = stages.write_fact_stem(adapter.config["display_name"], src.title, fq.lead, fq.option_lines,
                                      previous=previous, feedback=feedback, solved=solved)
        g = gate.compare_fact(stem, fq)
        bb.note("gate", attempt=attempt + 1, stem=stem, ok=g["ok"], mismatches=g["mismatches"], unreadable=False)
        if g["ok"]:
            print(f"    gate passed (attempt {attempt + 1})")
            return stem, None
        print(f"    gate mismatch ({attempt + 1}/{GATE_RETRIES + 1}): {'; '.join(g['mismatches'])[:200]}")
        previous, feedback = stem, "Fix these problems: " + "; ".join(g["mismatches"])
    return None, "gate_failed"


def _fact_values(cand) -> dict:
    fq = cand["_fact"]
    return {"source": fq.source, "mode": fq.mode, "lead": fq.lead, "options": list(fq.options),
            "truth": list(fq.truth), "answer": fq.answer, "traps": list(fq.traps), "tx": list(fq.tx),
            "topic": fq.topic}


def _signature(adapter, cand, values):
    if adapter.kind == "facts":
        return dedup.signature(adapter.subject, [values["source"]], {"options": values["options"]})
    return dedup.signature(adapter.subject, cand["txs"], values)


def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Try up to MAX_CHAINS question ideas (chains, or fact sources for a fact adapter).
    Returns {"status": "accepted", "payload"} or {"status": "none"}. Raises Parked."""
    rng = rng or random.Random()
    facts = adapter.kind == "facts"
    cands = adapter.candidates(coverage, chapter, n=MAX_CHAINS * 4, exclude=bb.tried_edges())
    if not cands:
        print("  no question ideas available")
        return {"status": "none"}
    for chain_no, cand in enumerate(cands[:MAX_CHAINS], 1):
        label = f"FACT QUESTION: {cand['description']} ({cand['_fact'].mode})" if facts else \
            f"CHAIN {chain_no}: {' → '.join(cand['nodes'])}  (txs {cand['txs']})"
        print(f"\n╔═══ {label} ═══╗")
        bb.start_chain(cand)
        plan = cand.get("_plan")
        if facts:
            spec, scenario = [], ""
            values, result = _fact_values(cand), adapter.result(cand["_fact"])
            bb.note("inputs", values=values, answer=result.answer)
        else:
            spec = adapter.input_spec(plan)
            print("  [inputs] generator proposes values...")
            picked = _propose(adapter, cand, spec, bb, log)
            if picked is None:
                continue
            values, scenario, result = picked
            cand, values, result = _stable_ask(adapter, cand, values, result, bb)
            plan, spec = cand["_plan"], adapter.input_spec(cand["_plan"])
        print(f"  [engine] answer {answer_text(result)}; traps: {[t['id'] for t in result.traps]}")
        previous = feedback = solved = None
        while True:
            print(f"  [stem] round {bb.current['rounds']}: writing the question...")
            if facts:
                stem, why = _fact_stem_and_gate(adapter, cand, bb, previous=previous, feedback=feedback,
                                                solved=solved)
            else:
                stem, why = _stem_and_gate(adapter, cand, spec, values, scenario, result, bb, rng,
                                           previous=previous, feedback=feedback, solved=solved)
            if stem is None:
                log({"event": why, "chain": cand["edges"]})
                break
            sig = _signature(adapter, cand, values)
            dup = dedup.duplicate_of(sig)
            if dup:
                print(f"  [dedup] same inputs as accepted question {dup}; choosing new inputs")
                bb.note("duplicate", of=dup)
                decision = {"decision": "too_easy", "graded": []}
            else:
                print("  [council] closed-book solves (cheaper members first)...")
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
                previous, feedback, solved = stem, decision["feedback"], None
                continue
            solved = _solved_summary(decision["graded"])
            choice = stages.choose_refinement(stem, solved, adapter.refine_modes)
            bb.note("refine", **choice)
            print(f"  [refine] too easy → {choice['mode']}: {choice['feedback'][:140]}")
            if choice["mode"] == "reword":
                previous, feedback = stem, "Too easy: " + choice["feedback"]     # refiner rewrites (solved set)
                continue
            if facts:
                try:
                    cand = adapter.rebuild(cand)
                except EngineError:
                    break
                values, result = _fact_values(cand), adapter.result(cand["_fact"])
                bb.note("inputs", values=values, answer=result.answer)
            else:
                picked = _propose(adapter, cand, spec, bb, log,
                                  refine={"values": values, "summary": choice["feedback"], "working": solved})
                if picked is None:
                    break
                values, scenario, result = picked
                cand, values, result = _stable_ask(adapter, cand, values, result, bb)
                plan, spec = cand["_plan"], adapter.input_spec(cand["_plan"])
            print(f"  [engine] new answer {answer_text(result)}")
            previous = feedback = solved = None
    return {"status": "none"}
