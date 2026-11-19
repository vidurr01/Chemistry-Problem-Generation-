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

import dataclasses
import json
import math
import random
import re

from core import answers, dedup, models
from core.engine.base import EngineError, round_sig
from core.pipeline import forms_layer, gate, queues, stages
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
    vals = answers.numeric_values(result.answer)
    if vals is not None and len(vals) > 1:
        subs = getattr(result, "answer_substances", None) or [None] * len(vals)
        tus = answers.target_units({"unit": result.unit, "count": len(vals)})
        return ", ".join(f"{s + ': ' if s else ''}{v:g}{(' ' + u) if u else ''}" for v, s, u in zip(vals, subs, tus))
    u = f" {result.unit}" if result.unit else ""
    return f"{result.answer}{u}"


def stated_answer(result) -> str:
    """The answer the way the question asks for it: numbers to SIG_FIGS significant figures
    (the engine keeps 4, so 1.5376 is 1.538 internally but the question wants 1.54); whole
    numbers, text and letters as they are."""
    vals = answers.numeric_values(result.answer)
    if vals is None or getattr(result, "kind", "") in ("count", "posint", "integer"):
        return answer_text(result)
    fmt = lambda v: f"{round_sig(float(v), answers.SIG_FIGS):g}"
    if len(vals) > 1:
        subs = getattr(result, "answer_substances", None) or [None] * len(vals)
        tus = answers.target_units({"unit": result.unit, "count": len(vals)})
        return ", ".join(f"{s + ': ' if s else ''}{fmt(v)}{(' ' + u) if u else ''}" for v, s, u in zip(vals, subs, tus))
    return f"{fmt(vals[0])}{(' ' + result.unit) if result.unit else ''}"


def _shown(v):
    """A value as the solution should write it: 5 significant figures (3.60056627586 -> 3.6006)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
    return float(f"{v:.5g}") if v != int(v) or abs(v) >= 1e6 else int(v)


def trace_text(result) -> str:
    """The engine's steps for the solution writer: each distinct calculation once (a program that
    calls a formula again with the same inputs, or inside find(), repeated it: the solution then
    said 'reapplying ... the same substitution' four times, run of 2026-11-16), values to 5 figures."""
    lines, seen = [], set()
    for t in result.trace:
        key = json.dumps([t.get("tx"), {k: _shown(v) for k, v in t["inputs"].items()}], sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        ins = ", ".join(f"{k} = {_shown(v)}" for k, v in t["inputs"].items())
        outs = ", ".join(f"{k} = {_shown(v)}" for k, v in t["outputs"].items())
        lines.append(f"Step {len(lines) + 1}: {t['formula']}\n   with {ins}\n   gives {outs}")
    if result.constants:
        lines.append("Constants used: " + "; ".join(result.constants))
    if getattr(result, "form_note", ""):
        lines.append(result.form_note)
    stated, exact = stated_answer(result), answer_text(result)
    lines.append(f"Final answer: {stated}" + (f" (as the question asks; unrounded {exact})" if stated != exact else ""))
    return "\n".join(lines)


SOLUTION_REWRITES = 2       # a written solution with errors is rewritten at most twice


def _squash_text(s) -> str:
    return " ".join(answers.normalise_text(s).replace("*", "×").split())


def _grounded_error(err: dict, lines: list) -> bool:
    """A verifier error counts only if it points at the solution: its quote is in the text
    (nearly word for word), or it gives no quote but a line that exists."""
    import difflib
    quote = _squash_text(err.get("quote") or "")
    if not quote:
        n = err.get("line")
        return n is not None and 1 <= int(n) <= len(lines)
    text = [_squash_text(ln) for ln in lines]
    if any(quote in t for t in text):
        return True
    for t in text:
        blocks = difflib.SequenceMatcher(None, quote, t, autojunk=False).get_matching_blocks()
        if sum(b.size for b in blocks) >= 0.85 * len(quote):
            return True
    return False


def checked_solution(stem: str, result) -> tuple:
    """(solution, record). The solution writer drafts; code checks every calculation and that
    each step's result and the final answer appear; only a draft code finds clean goes to the
    mismatch verifier, which names each wrong step. Errors go back to the writer, at most
    SOLUTION_REWRITES times. Only a draft that passes both is returned; otherwise the solution
    is empty and the record says why (status: verified | failed_check | writer_failed |
    checker_failed). Never raises: the solution is display only."""
    from core import solution_check
    trace, ans = trace_text(result), stated_answer(result)
    history, draft, problems = [], None, None
    for attempt in range(SOLUTION_REWRITES + 1):
        try:
            draft = stages.write_solution(stem, trace, ans, previous=draft, problems=problems)
        except Exception as e:                                   # noqa: BLE001
            history.append({"attempt": attempt + 1, "error": f"writer: {type(e).__name__}: {str(e)[:160]}"})
            return "", {"status": "writer_failed", "attempts": attempt + 1, "history": history}
        problems = solution_check.code_problems(draft, result.trace, result.answer,
                                                getattr(result, "kind", "real"))
        entry = {"attempt": attempt + 1, "draft": draft, "code_problems": problems}
        if not problems:
            try:
                errs = stages.check_solution(stem, trace, ans, draft)
            except Exception as e:                               # noqa: BLE001
                entry["error"] = f"checker: {type(e).__name__}: {str(e)[:160]}"
                history.append(entry)
                return "", {"status": "checker_failed", "attempts": attempt + 1, "history": history}
            lines = [ln for ln in draft.splitlines() if ln.strip()]
            kept = [e for e in errs if _grounded_error(e, lines)]
            entry["verifier_errors"] = kept
            entry["ignored_errors"] = [e for e in errs if e not in kept]
            problems = [(f"Line {int(e['line'])}: " if e.get("line") is not None else "") +
                        (f"'{e['quote']}' — " if e.get("quote") else "") + e["problem"] for e in kept]
        history.append(entry)
        if not problems:
            return draft, {"status": "verified", "attempts": attempt + 1, "history": history}
    return "", {"status": "failed_check", "attempts": SOLUTION_REWRITES + 1, "history": history,
                "last_problems": problems}


def _fact_source(cand):
    """The fact table a question was built from: carried on the candidate (any subject), else the physical
    table of that id (candidates parked before 2026-11-19)."""
    if cand.get("_source") is not None:
        return cand["_source"]
    from core.engine.physical.facts_data import BY_ID
    if cand["nodes"][0] in BY_ID:
        return BY_ID[cand["nodes"][0]]
    from core.engine.inorganic.tables import BY_ID as INORG
    return INORG[cand["nodes"][0]]


def insight_hint(cand, failed_step) -> str:
    """Names the kind of step, never the result: written by code from the step and one
    of its listed mistakes."""
    if cand.get("_hint"):                          # a flow that writes its own hint (inorganic)
        return cand["_hint"]
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
        try:
            out = stages.propose_inputs(adapter.config["display_name"], adapter.chain_text(cand["_plan"]),
                                        spec, refine=refine, errors=errors or None, traps=traps)
        except ValueError as e:                  # unparseable or cut-off reply after retries
            bb.note("inputs_unusable", attempt=attempt + 1, error=str(e)[:300])
            print(f"    input proposal unusable ({attempt + 1}/{INPUT_TRIES}): {str(e)[:120]}")
            continue
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
    while _is_numeric(result) and result.tolerance > FRAGILE_TOL and len(cand["txs"]) > 1 \
            and not cand.get("_shape"):            # a tree or condition is not a chain to shorten
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


def _ask_options(plan, rng, asked=None):
    final = plan.steps[-1]
    chain_asks = (final.final[3] if final.final else final.asks)
    final_asks = asked or chain_asks              # a form may ask something else (an input, a ratio)
    others = [s.asks for s in plan.steps if s.asks and s.asks != final_asks]
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
    form = getattr(result, "form", "forward")
    options, correct = _ask_options(plan, rng, result.asks if form != "forward" else None)
    fmt = _answer_instruction(adapter, result)
    chain_text = adapter.chain_text(plan) + ("\n" + result.stem_note if getattr(result, "stem_note", "") else "")
    for attempt in range(GATE_RETRIES + 1):
        try:
            stem = stages.write_stem(adapter.config["display_name"], scenario, chain_text, spec,
                                     values, result.constants, result.asks, result.unit, traps,
                                     previous=previous, feedback=feedback, solved=solved, answer_format=fmt)
        except ValueError as e:                  # unparseable or cut-off reply: a failed gate attempt
            bb.note("gate", attempt=attempt + 1, stem=None, ok=False, mismatches=[f"unusable reply: {e}"[:300]],
                    unreadable=False)
            print(f"    stem reply unusable ({attempt + 1}/{GATE_RETRIES + 1}): {str(e)[:120]}")
            continue
        ext = stages.gate_extract(stem, spec, options, result.constants)
        g = gate.compare(spec, values, ext, correct, result.constants)
        if fmt and " ".join(fmt.split()) not in " ".join(stem.split()):
            g = {**g, "ok": False, "unreadable": False,
                 "mismatches": g["mismatches"] + [f"the question must end with this sentence, copied exactly: {fmt}"]}
        added = gate.computed_values(stem)
        if added:
            g = {**g, "ok": False, "unreadable": False,
                 "mismatches": g["mismatches"] + [f"the question gives a computed value that is not in the data, "
                                                  f"which reveals the method; remove it: {'; '.join(added)}"]}
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
    """One number or a list of numbers (several substances)."""
    return answers.numeric_values(result.answer) is not None


def _is_scalar(result) -> bool:
    v = answers.numeric_values(result.answer)
    return v is not None and len(v) == 1


def _answer_instruction(adapter, result):
    """The sentence the stem must end with, checked verbatim by the gate: the option list or
    form for a non-numeric answer (physical.ANSWER_FORMATS), the unit for a numeric one."""
    fmt = adapter.answer_format(result) if hasattr(adapter, "answer_format") else None
    if fmt is None and _is_numeric(result) and not _is_scalar(result):
        n = len(answers.numeric_values(result.answer))
        subs = getattr(result, "answer_substances", None) or []
        tus = answers.target_units({"unit": result.unit, "count": n})
        if len(set(tus)) == 1:
            order = f" in the order: {', '.join(subs)}" if subs else " in the order asked"
            fmt = (f"Give the {n} answers{(' in ' + tus[0]) if tus[0] else ''}, to {answers.SIG_FIGS} "
                   f"significant figures,{order}.")
        else:
            items = [f"{(subs[i] + ' ') if i < len(subs) else ''}in {u}" if u else (subs[i] if i < len(subs) else "unitless")
                     for i, u in enumerate(tus)]
            fmt = f"Give the {n} answers to {answers.SIG_FIGS} significant figures, in the order: {'; '.join(items)}."
    elif fmt is None and _is_numeric(result):
        if result.unit:
            fmt = f"Give the answer in {result.unit}, to {answers.SIG_FIGS} significant figures."
        elif result.kind in ("count", "posint", "integer"):
            fmt = "Give the answer as an integer."
        else:
            fmt = f"Give the answer to {answers.SIG_FIGS} significant figures."
    return fmt


def _code_match(result, member):
    """True / False when code can decide from the member's answer, None when it cannot.

    The usual case is a completed answer line: FINAL_VALUE is CALC_VALUE already converted
    to the asked unit by core.units, so a number is compared directly with the engine's.
    Without a usable line (the restate request failed too), a raw answer that code can still
    read is compared; anything else is left to the verifier's answer_equivalent."""
    tol = getattr(result, "tolerance", 0.01)
    fv = member.get("final_value")
    if fv is not None:
        if _is_numeric(result):
            return answers.values_match(answers.numeric_values(result.answer), fv, tol,
                                        getattr(result, "answer_substances", None), member.get("substance"))
        v = fv[0]
    else:
        v = member.get("final_answer")
        if v is None:
            return False
        if _is_numeric(result):
            ev = answers.numeric_values(result.answer)
            if len(ev) == 1:
                val = answers.numeric_value(v)
                return None if val is None else answers.values_match(ev, [val], tol)
            vals = answers.parse_numeric_answers(v)
            return None if vals is None else answers.values_match(ev, vals, tol)
    if result.kind == "letters":
        return answers.matches(result.answer, v, "letters")
    if answers.matches(result.answer, v, result.kind):
        return True
    return answers.text_answers_match(result.answer, v)


def _grade(result, member, diag=None) -> dict:
    """Solved = the member's answer matches the engine's, decided by CODE only (no verifier since
    2026-11-19: the author's decision; a hard question is rarely solved by wrong reasoning that lands on
    the right number, and the coder's program, not a judge, makes the key right). Numbers and option
    letters by value; a non-numeric answer where its shape allows (formulas, nuclides, configurations,
    balanced equations, categories with synonyms); an answer code cannot read counts as not matched.
    diag is ignored (kept so old callers and stored records still work)."""
    match = bool(_code_match(result, member))
    return {"answer_matches": match, "match_by": "code", "verdict": None, "failure_type": None,
            "slip_confirmed": None, "counts_as_solved": match}


NONSENSE_FACTOR = 1e3      # a numeric answer this many times too large or too small is no attempt


def _garbage(result, member) -> bool:
    """True if a member's attempt at a one-number question is not a real attempt: no number at
    all, or a number more than NONSENSE_FACTOR away from the engine's (a slip or a wrong method
    lands within that; 3.8 × 10²⁸ for 25.1 does not). Never True for a correct answer."""
    if member.get("answer_matches") or not _is_scalar(result):
        return False
    e = answers.numeric_values(result.answer)[0]
    fv = member.get("final_value")
    v = fv[0] if fv else answers.numeric_value(member.get("final_answer"))
    if v is None:
        return True
    if e == 0 or v == 0:
        return False
    r = abs(float(v) / float(e))
    return r > NONSENSE_FACTOR or r < 1 / NONSENSE_FACTOR


CONSENSUS_TOL = 0.02    # ladder answers within 2 % of each other count as the same answer


def _member_value(g):
    fv = g.get("final_value")
    if isinstance(fv, list) and fv and isinstance(fv[0], (int, float)):
        return float(fv[0])
    return answers.numeric_value(g.get("final_answer"))


def _consensus_against_key(result, graded):
    """The answer every ladder model called gave, when they agree with each other (within CONSENSUS_TOL), none
    matches the key, and it is not one of the engine's own trap answers (then they fell for a known trap and the
    question is genuinely hard). None otherwise. Replayed on the 21 questions judged by 2026-11-19: it holds the
    two with a wrong key (an engine step inverted on 14 Oct; a rounded n on 19 Nov) and nothing else."""
    if not _is_scalar(result):
        return None
    vals = [_member_value(g) for g in graded if not g.get("discarded_as_nonsense")]
    if len(vals) < 2 or any(v is None for v in vals):
        return None
    ref = vals[0]
    if not all(abs(v - ref) <= CONSENSUS_TOL * max(abs(v), abs(ref), 1e-300) for v in vals):
        return None
    for t in getattr(result, "traps", None) or []:
        w = t.get("wrong_answer") if isinstance(t, dict) else None
        if isinstance(w, (int, float)) and abs(w - ref) <= CONSENSUS_TOL * max(abs(w), abs(ref), 1e-300):
            return None                          # a known trap: hard, not a wrong key
    return ref


def judge(adapter, cand, plan, values, result, stem, bb, log) -> dict:
    """Ladder → grading by code → insight-hint tests (no verifier since 2026-11-19). Returns
       {"decision": "accept", ...} or {"decision": "too_easy", ...}. Raises Parked if a solver call fails
       at any point (the ladder, a hint re-solve): the question is not judged on a partial measurement,
       it is judged again on the next run."""
    try:
        return _judge(adapter, cand, plan, values, result, stem, bb, log)
    except CouncilMemberFailed as e:
        raise Parked({"error": str(e)}) from e


def _judge(adapter, cand, plan, values, result, stem, bb, log) -> dict:
    fmt = _answer_instruction(adapter, result)
    spec = answers.answer_spec(result.answer, result.kind, result.unit, fmt, getattr(result, "answer_substances", None))

    def solve_and_grade(names):
        return [{**m, **_grade(result, m)} for m in stages.council_solve(stem, names, spec)]

    # Ladder: the weakest model first; each next step is called only if every step below
    # failed. If the first step solves it, the question is too easy; otherwise the first step
    # that solves it (or none) is the difficulty label.
    graded = []
    bottom_unmeasured = False
    for i, (name, _) in enumerate(models.LADDER):
        graded += solve_and_grade([name])
        if i == 0 and _garbage(result, graded[-1]):
            # a nonsense answer (3.8 × 10²⁸ L for 25 L, run of 2026-11-16) says the bottom step broke,
            # not that the question is hard: ask once more, and if it is nonsense again, the bottom
            # step's failure does not count and the next step has to fail too
            print(f"    [{name}] answer {graded[-1]['final_answer']} is nonsense for this question; asking again")
            graded[-1]["discarded_as_nonsense"] = True
            graded += solve_and_grade([name])
            bottom_unmeasured = _garbage(result, graded[-1])
        if graded[-1]["counts_as_solved"]:
            break
    called = {g["name"] for g in graded}
    skipped = [n for n, _ in models.LADDER if n not in called]
    first_solver = next((g["name"] for g in graded if g["counts_as_solved"]), None)
    bb.note("council", members=graded, skipped=skipped, first_solver=first_solver)
    for g in graded:
        tag = "solved" if g["counts_as_solved"] else "failed"
        print(f"    [{g['name']}] {g['final_answer']} {g['unit']} → {tag}"
              + (f" (objected, {g['objection']['type']}: kept in the record)" if g.get("objection") else ""))

    held = _consensus_against_key(result, graded) if first_solver is None else None
    if held:
        qid = queues.add("ladder_consensus", adapter.subject, {
            "chain": cand["edges"], "txs": cand["txs"], "values": values, "stem": stem,
            "engine_answer": stated_answer(result), "consensus": held, "solver_code": getattr(result, "solver_code", None),
            "members": [{"name": g["name"], "answer": g["final_answer"]} for g in graded]})
        log({"event": "ladder_consensus", "chain": cand["edges"], "queue_id": qid, "consensus": held})
        print(f"    ✗ every ladder model gave {held} and the key is {stated_answer(result)}: held for review "
              f"({qid}); the key may be wrong")
        return {"decision": "drop", "reason": "ladder_consensus", "graded": graded}

    n_correct = sum(g["answer_matches"] for g in graded)
    n_solved = sum(g["counts_as_solved"] for g in graded)
    bottom = models.LADDER[0][0]
    if bottom_unmeasured and first_solver == models.LADDER[1][0]:
        print(f"    ladder: {bottom} gave nonsense twice, so its failure does not count; "
              f"{first_solver} solved it → too easy")
        return {"decision": "too_easy", "graded": graded, "n_correct": n_correct, "n_solved": n_solved,
                "skipped": skipped, "first_solver": first_solver, "bottom_unmeasured": True}
    if first_solver == bottom:
        print(f"    ladder: {bottom} solved it → too easy")
        return {"decision": "too_easy", "graded": graded, "n_correct": n_correct, "n_solved": n_solved,
                "skipped": skipped, "first_solver": first_solver}
    label = models.DIFFICULTY_LABELS.get(first_solver, "hard_advanced")
    jev_lvl = None
    if label == "advanced":
        # By the ladder's own calibration (models.LADDER; measured with phi-4 as the bottom step, Llama 3.3 70B
        # since 2026-11-17), "phi-4 fails, GLM solves" happens to 47 % of hard
        # Mains questions and 38 % of real Advanced ones: the ladder alone cannot tell them apart here. Jev's
        # level check, calibrated on real papers (tools/calibrate_level.py), decides; until it is calibrated
        # the label says the level is undecided. Acceptance does not change.
        from core.pipeline import qf_checks
        floor = qf_checks._level_floor(adapter.subject)
        if floor is None:
            label = "advanced_or_mains_hard"
        else:
            jev_lvl = qf_checks.jev_level(stem)
            label = "advanced_or_mains_hard" if jev_lvl is None else ("advanced" if jev_lvl >= floor else "mains_hard")
    print(f"    ladder: {bottom} failed; first solved by {first_solver or 'no step'} → {label}"
          + (f" (Jev level {jev_lvl:.2f})" if jev_lvl is not None else ""))

    # hint tests on every member that did not solve: the code-written insight hint names the kind of step
    # (never the result); solved after it = the difficulty was that step. Graded by code, like the ladder.
    recall, hint_log = False, []
    for g in graded:
        if g["counts_as_solved"] or g.get("discarded_as_nonsense"):
            continue
        hint = insight_hint(cand, None)
        re_ = stages.solve_with_hint(g, stem, hint, spec)
        ok = bool(_code_match(result, re_))
        hint_log.append({"member": g["name"], "hint": "insight", "text": hint, "solved": ok,
                         "answer": re_["final_answer"]})
        print(f"    [hint] {g['name']}: insight → {'solved (difficulty confirmed)' if ok else 'still wrong'}")
    bb.note("hints", tests=hint_log)
    return {"decision": "accept", "graded": graded, "n_correct": n_correct, "n_solved": n_solved,
            "recall": recall, "hints": hint_log, "skipped": skipped, "first_solver": first_solver,
            "difficulty_label": label, "jev_level": jev_lvl}


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
        try:
            stem = stages.write_fact_stem(adapter.config["display_name"], src.title, fq.lead, fq.option_lines,
                                          previous=previous, feedback=feedback, solved=solved)
        except ValueError as e:
            print(f"    stem reply unusable ({attempt + 1}/{GATE_RETRIES + 1}): {str(e)[:120]}")
            continue
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


def _apply_form(adapter, cand, spec, values, result, rng, bb, log, avoid=()):
    """forms_layer.apply_form, noted on the blackboard in full (a parked question is judged
    again with exactly this question: its stated values and the form's answer). None: the
    idea cannot be posed with these values (a condition with no unique answer)."""
    formed = forms_layer.apply_form(adapter, cand, spec, values, result, rng, avoid=avoid)
    if formed is None:
        print("  [form] the condition has no unique answer with these values; dropping this idea")
        bb.note("form_failed", shape=(cand.get("_shape") or {}).get("kind"))
        log({"event": "form_failed", "chain": cand["edges"]})
        return None
    spec, values, result = formed
    bb.note("form", form=result.form, answer=result.answer, detail=result.detail, values=values,
            result=dataclasses.asdict(result), shape=cand.get("_shape"))
    print(f"  [form] {result.form}: asks {result.asks}")
    return formed


def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Computed questions go question first (core/pipeline/qfirst.py) when the config sets
    question_first (run_groundup_final.py does, unless --flow engine); otherwise the engine-first flow below.

    Try up to MAX_CHAINS question ideas (chains, or fact sources for a fact adapter).
    Returns {"status": "accepted", "payload"} or {"status": "none"}. Raises Parked."""
    rng = rng or random.Random()
    if adapter.kind == "inorg_qfirst":
        from core.pipeline import inorg_qfirst      # inorganic: reaction-chain draw, claims checked by code
        return inorg_qfirst.run(adapter, coverage, bb, log, chapter=chapter, rng=rng)
    if adapter.kind == "org_qfirst":
        from core.pipeline import org_qfirst        # organic: molecule + reaction walk, RDKit rules, code options
        return org_qfirst.run(adapter, coverage, bb, log, chapter=chapter, rng=rng)
    if adapter.kind == "chains" and adapter.config.get("question_first", False):
        from core.pipeline import qfirst            # run_groundup_final.py sets it (default --flow question)
        return qfirst.run(adapter, coverage, bb, log, chapter=chapter, rng=rng)
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
            chain_values = values
            formed = _apply_form(adapter, cand, spec, values, result, rng, bb, log)
            if formed is None:
                continue
            spec, values, result = formed
        print(f"  [engine] answer {answer_text(result)}; traps: {[t['id'] for t in result.traps]}")
        previous = feedback = solved = None
        while True:
            # The duplicate check needs only the steps and the values, so it runs before any
            # model is paid to write, read or solve a question that is already accepted.
            sig = _signature(adapter, cand, values)
            dup = dedup.duplicate_of(sig)
            if dup:
                print(f"  [dedup] same inputs as accepted question {dup}; choosing new inputs")
                bb.note("duplicate", of=dup)
                stem, decision = None, {"decision": "too_easy", "graded": [], "reason": f"duplicate of {dup}"}
            else:
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
            if dup:                              # only new inputs make it a different question
                solved = None
                choice = {"mode": "new_inputs",
                          "feedback": "These exact values are already an accepted question: choose a "
                                      "different system and different values."}
            else:
                solved = _solved_summary(decision["graded"])
                try:
                    choice = stages.choose_refinement(stem, solved, adapter.refine_modes)
                except ValueError:
                    choice = {"mode": adapter.refine_modes[0],
                              "feedback": "Too easy: find the shortcut the solvers used and remove it."}
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
                spec = adapter.input_spec(cand["_plan"])
                picked = _propose(adapter, cand, spec, bb, log,
                                  refine={"values": chain_values, "summary": choice["feedback"], "working": solved})
                if picked is None:
                    break
                solved_form = getattr(result, "form", "forward")
                values, scenario, result = picked
                cand, values, result = _stable_ask(adapter, cand, values, result, bb)
                plan, spec = cand["_plan"], adapter.input_spec(cand["_plan"])
                chain_values = values
                # the form the solvers just beat is not used again for this chain's next round
                formed = _apply_form(adapter, cand, spec, values, result, rng, bb, log, avoid={solved_form})
                if formed is None:
                    break
                spec, values, result = formed
            print(f"  [engine] new answer {answer_text(result)}")
            previous = feedback = solved = None
    return {"status": "none"}
