"""
run_groundup_final.py — generate one question for a subject (engine-first pipeline).

    walk the subject's knowledge graph → Blackboard → generator picks inputs → engine
    computes answer, trace and traps → generator writes the stem → chemistry gate →
    duplicate check → council of three closed-book solvers → mismatch verifier on every
    attempt → grading in code → hint tests → accept → readable solution

The answer key always comes from the engine (core/engine); models write, extract,
solve and diagnose, and every decision is made in code (core/pipeline/flow.py).

Exit codes: 0 done (accepted, or nothing accepted this run), 2 configuration problem
(key, graph, engine not wired for the subject, chapter), 3 a council call failed (the
question is parked and judged first on the next run), 4 an accepted question could
not be saved (parked).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from core import dedup, models
from core.blackboard import Blackboard
from core.engine.base import EngineError, round_sig
from core.llm import write_json_atomic
from core.pipeline import flow, stages
from core.pipeline.adapters import FACT_ADAPTERS, adapter_for
from subject_config import (compute_meta_tags_for_subject, get_subject_config, load_coverage_for_subject,
                            save_coverage)

EXIT_CONFIG_ERROR = 2
EXIT_COUNCIL_FAILED = 3
EXIT_SAVE_FAILED = 4
EXIT_NO_CREDITS = 5        # OpenRouter refused a call for lack of credits (HTTP 402)

# A parked question whose recheck fails this many times is put ON HOLD (on_hold_file, never judged
# automatically): every run judges parked questions first and stops when that fails, so one question that
# always fails (an unreadable reply from the same solver each time) blocked every later run for good. A
# failed call is not a wrong answer, so the question is kept, not dropped (the author, 2026-11-19).
MAX_RECHECK_FAILURES = 3


def on_hold_file(config) -> str:
    """outputs/on_hold_questions_<subject>.json, next to the pending file (never the same file)."""
    folder, base = os.path.split(config["pending_file"])
    base = base.replace("pending_questions_", "on_hold_questions_") if "pending_questions_" in base \
        else "on_hold_" + base
    return os.path.join(folder, base)


def _hold(config, pending, reason, log):
    """Moves pending[0] to the on-hold file with the reason, whole, and saves both files. Never a drop: it can
    be judged again with --rerun-held, also to see whether a code change fixed what stopped it."""
    item = pending.pop(0)
    hold = on_hold_file(config)
    held = _read(hold, [])
    held.append({**item, "held_at": datetime.now(timezone.utc).isoformat(), "hold_reason": reason})
    write_json_atomic(hold, held, ensure_ascii=False)
    write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
    print(f"  ✗ {item.get('pending_id')} is ON HOLD ({reason[:200]}) in {hold}; judge it again with --rerun-held")
    log({"event": "pending_on_hold", "pending_id": item.get("pending_id"), "reason": reason})


def rerun_held(config) -> int:
    """Moves every on-hold question back to the pending file with its failure count reset, so this run judges
    them first (to re-run them, or to see whether a code change fixed their error). Returns how many."""
    hold = on_hold_file(config)
    held = _read(hold, [])
    if not held:
        return 0
    pending = _read(config["pending_file"], [])
    for item in held:
        item = {k: v for k, v in item.items() if k not in ("recheck_failures", "held_at", "hold_reason")}
        item["rerun_from_hold_at"] = datetime.now(timezone.utc).isoformat()
        pending.append(item)
    write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
    write_json_atomic(hold, [], ensure_ascii=False)
    return len(held)


def _save_run_blackboard(subject, config, bb):
    """Every run's full Blackboard (all chains, rounds, attempts, diagnoses) goes to
    outputs/runs/, accepted or not, so each grading decision can be audited afterwards."""
    try:
        d = os.path.join(os.path.dirname(os.path.abspath(config["output_file"])), "runs")
        os.makedirs(d, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        with open(os.path.join(d, f"{stamp}_{subject}.json"), "w", encoding="utf-8") as f:
            json.dump({"subject": subject, "saved_at": stamp, "spend": models.SPEND.summary(),
                       "chains": bb.history()}, f, ensure_ascii=False, indent=1, default=str)
    except Exception as e:                                       # audit copy only: never blocks a run
        print(f"  [warn] could not save the run's Blackboard: {type(e).__name__}: {e}")


def _out_of_credits(err) -> bool:
    return getattr(err, "status_code", None) == 402 or "Error code: 402" in str(err)


def _credits_message():
    print("\n✗ OpenRouter is out of credits (HTTP 402). Add credits at https://openrouter.ai/settings/credits "
          "or raise the key's limit, then run again.")
    print(f"Spend this run: ${models.SPEND.total_cost:.4f}")


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _attempt_logger(config):
    path = os.path.splitext(config["output_file"])[0] + "_attempts.jsonl"

    def log(rec):
        rec = {"ts": datetime.now(timezone.utc).isoformat(), **rec}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    return log


def _unique_id(prefix, taken):
    base = f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    qid, n = base, 2
    while qid in taken:
        qid, n = f"{base}_{n}", n + 1
    return qid


def _taken_ids(config, subject):
    taken = {r.get("question_id") for r in _read(config["output_file"], [])}
    try:
        from tools.results import REJECTED_FILE, results_path
        taken |= {r.get("question_id") for r in _read(results_path(subject), [])}
        taken |= set(_read(REJECTED_FILE, {}))
    except Exception:
        pass
    return taken


# ── acceptance ───────────────────────────────────────────────────────────────

def build_record(subject, config, payload, bb):
    cand, result, decision = payload["cand"], payload["result"], payload["decision"]
    graded = decision["graded"]
    solution, solution_check = flow.checked_solution(payload["stem"], result)
    if solution_check["status"] != "verified":
        print(f"  [warn] solution {solution_check['status']}; saving without a readable solution")
    try:
        meta = compute_meta_tags_for_subject(
            config, question_text=payload["stem"], archetype_code=config["default_archetype_code"],
            solver_trace=next((g.get("working") for g in graded if g.get("working")), ""), fragility_weight=None)
        meta_error = None
    except Exception as e:
        meta, meta_error = None, f"{type(e).__name__}: {e}"
    trap_types = sorted({t["id"] for t in result.traps})
    record = {
        "question_id": _unique_id("GEN", _taken_ids(config, subject)),
        "generation_mode": "question_first" if getattr(result, "solver_code", None) else "engine_council",
        "question_kind": "fact" if "_fact" in cand else "chain",
        "subject": subject,
        "chapter": " → ".join(cand["chapters"]),
        "chapters": cand["chapters"],
        "archetype": config["default_archetype"],
        "archetype_code": config["default_archetype_code"],
        "question": payload["stem"],
        "answer": result.answer,
        "unit": result.unit,
        "answer_text": flow.stated_answer(result),
        "solution": solution,
        "solution_check": solution_check,
        "tags": {"knowledge": "recall" if decision.get("recall") else "closed_book", "trap_types": trap_types},
        "council_n_correct": decision["n_correct"],
        "council_n_solved": decision["n_solved"],
        "council_n_called": len(graded),
        "council_skipped": decision.get("skipped", []),
        "ladder_first_solver": decision.get("first_solver"),
        "difficulty_label": decision.get("difficulty_label"),
        "jev_level": decision.get("jev_level"),
        "council": [{k: g.get(k) for k in ("name", "model", "final_answer", "unit", "answer_matches", "match_by", "counts_as_solved",
                                           "verdict", "failure_type", "slip_confirmed", "objection", "diagnosis",
                                           "working")}
                    for g in graded],
        "hint_tests": decision.get("hints", []),
        "engine": {"txs": cand["txs"], "extra_txs": cand.get("extra_txs", []),
                   "graph_edges": cand["edges"], "graph_path": cand["nodes"],
                   "scenario": payload["scenario"], "givens": payload["values"], "constants": result.constants,
                   "trace": result.trace, "traps": result.traps, "asks": result.asks,
                   "shape": cand.get("_shape"),
                   "form": getattr(result, "form", "forward"), "form_detail": getattr(result, "detail", {}),
                   "form_note": getattr(result, "form_note", ""),
                   "solver_code": getattr(result, "solver_code", None)},
        **({"options": [f"({chr(65 + i)}) {o}" for i, o in enumerate(payload["values"]["options"])],
            "fact_mode": payload["values"]["mode"]} if "_fact" in cand else {}),
        "rounds": bb.current["rounds"],
        "meta_tags": meta,
        **({"meta_tags_error": meta_error} if meta_error else {}),
        "models": models.ROSTER,
        "served_by": {m: sorted(v) for m, v in models.SERVED.items()},   # router:model that really answered
        "spend": models.SPEND.summary(),
        "blackboard": bb.history(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.loads(json.dumps(record, ensure_ascii=False, default=str))


def save_accepted(subject, config, coverage, payload, bb, log):
    """Write the record (the only step whose failure means 'not accepted'), then the
    repairable extras: coverage, duplicate store, results/ copy, attempt log."""
    record = build_record(subject, config, payload, bb)
    existing = _read(config["output_file"], [])
    existing.append(record)
    write_json_atomic(config["output_file"], existing, ensure_ascii=False)

    def after(what, fn):
        try:
            fn()
        except Exception as e:
            print(f"  [warn] question saved, but updating {what} failed: {type(e).__name__}: {e}")

    def cov():
        coverage.on_acceptance(archetype=config["default_archetype_code"], chapter=record["chapter"],
                               edges=payload["cand"]["edges"], concepts=[str(t) for t in payload["cand"]["txs"]],
                               traps=record["tags"]["trap_types"])
        save_coverage(coverage, config)

    def promote():
        from tools.results import promote as _promote
        _promote((subject,), quiet=True)

    after("coverage", cov)
    after("the duplicate store", lambda: dedup.record(payload["sig"], record["question_id"], record["answer"]))
    after("results/", promote)
    after("the attempt log", lambda: log({"event": "accepted", "question_id": record["question_id"]}))
    print(f"\n✓ ACCEPTED {record['question_id']} — answer {record['answer_text']}; "
          f"difficulty {record['difficulty_label']} (first solved by {record['ladder_first_solver'] or 'no step'}); "
          f"tags {record['tags']}")
    print("=" * 60 + "\n" + record["question"] + "\n" + "=" * 60)
    return record


# ── parked questions ─────────────────────────────────────────────────────────

def park(config, item):
    pending = _read(config["pending_file"], [])
    item = {"pending_id": _unique_id("PENDING", {p.get("pending_id") for p in pending}),
            "parked_at": datetime.now(timezone.utc).isoformat(), **item}
    pending.append(item)
    write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
    return item["pending_id"]


def _rebuild_parked(item, chain_adapter, config, rng):
    """(adapter, cand, plan, result) for a parked question, recomputed from its inputs."""
    if item.get("kind") == "fact":
        from core.engine.facts import FactQuestion
        fa = adapter_for(item["subject"], config, rng, kind="facts")
        v = item["values"]
        fq = FactQuestion(source=v["source"], tx=tuple(v["tx"]), topic=v["topic"], mode=v["mode"], lead=v["lead"],
                          options=v["options"], truth=v["truth"], answer=v["answer"], traps=v["traps"])
        cand = {"edges": item["edges"], "nodes": item["nodes"], "chapters": item["chapters"], "txs": item["txs"],
                "trap_ids": [], "description": "", "_fact": fq}
        return fa, cand, None, fa.result(fq)
    if item.get("qfirst"):                       # question first: random formulas, run its program again
        from types import SimpleNamespace
        from core.pipeline.qfirst import rebuild_result
        plan = SimpleNamespace(steps=[chain_adapter.engine.step(t) for t in item["txs"]], constants=[], branches=())
        result = rebuild_result(item)
    elif item.get("form_result"):                # asked in a form: judged as that question
        from core.pipeline.forms_layer import FormResult
        plan = chain_adapter.plan(item["txs"], item.get("shape"))
        result = FormResult(**item["form_result"])
        chain_adapter.compute(plan, item["chain_values"])      # the chain itself still runs
    else:
        plan = chain_adapter.plan(item["txs"], item.get("shape"))
        result = chain_adapter.compute(plan, item["values"])
    cand = {"edges": item["edges"], "nodes": item["nodes"], "chapters": item["chapters"],
            "txs": item["txs"], "trap_ids": item.get("trap_ids", []), "_plan": plan,
            **({"_shape": item["shape"]} if item.get("shape") else {})}
    return chain_adapter, cand, plan, result


def recheck_pending(subject, config, adapter, coverage, log):
    """Judge parked questions (oldest first) before generating anything new.
    Returns 'accepted', 'failed', 'save_failed' or 'empty'."""
    pending = _read(config["pending_file"], [])
    while pending:
        item = pending[0]
        if "txs" not in item:                     # parked by the pre-engine pipeline: cannot be judged
            _hold(config, pending, "parked by the old pipeline (no formulas recorded)", log)
            continue
        print(f"\n╔═══ PENDING {item['pending_id']} — judging again ═══╗")
        try:
            item_adapter, cand, plan, result = _rebuild_parked(dict(item, subject=subject), adapter, config, adapter.rng)
        except (EngineError, KeyError, TypeError, NotImplementedError) as e:
            # kept, not dropped: a later engine fix may make it computable (--rerun-held tries again)
            _hold(config, pending, f"cannot recompute: {type(e).__name__}: {e}", log)
            continue
        bb = Blackboard(subject)
        bb.start_chain(cand)
        bb.current["rounds"] = item.get("rounds", 0)
        try:
            decision = flow.judge(item_adapter, cand, plan, item["values"], result, item["stem"], bb, log)
        except flow.Parked as p:
            item["recheck_failures"] = item.get("recheck_failures", 0) + 1
            item["last_error"] = p.item.get("error")
            if item["recheck_failures"] >= MAX_RECHECK_FAILURES:
                # not dropped and not judged: on hold in its own file (the author, 2026-11-19: a crash says
                # nothing about the question); runs carry on without it
                _hold(config, pending, f"{item['recheck_failures']} failed rechecks: {item['last_error']}", log)
                continue
            write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
            print(f"  ✗ council call failed again ({item['recheck_failures']}/{MAX_RECHECK_FAILURES}): "
                  f"{item['last_error']}")
            return "failed"
        if decision["decision"] == "accept":
            payload = {"cand": cand, "plan": plan, "values": item["values"], "scenario": item.get("scenario", ""),
                       "result": result, "stem": item["stem"], "decision": decision,
                       "sig": flow._signature(item_adapter, cand, item["values"])}
            try:
                save_accepted(subject, config, coverage, payload, bb, log)
            except Exception as e:
                print(f"  ✗ saving failed: {type(e).__name__}: {e}")
                return "save_failed"
            pending.pop(0)
            write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
            return "accepted"
        print(f"  not accepted on recheck ({decision['decision']}); removed from pending")
        log({"event": f"pending_{decision['decision']}", "pending_id": item["pending_id"]})
        pending.pop(0)
        write_json_atomic(config["pending_file"], pending, ensure_ascii=False)
    return "empty"


# ── main ─────────────────────────────────────────────────────────────────────

def parse_args():
    ap = argparse.ArgumentParser(description="Generate one JEE Advanced chemistry question (engine-first).")
    ap.add_argument("--subject", choices=["organic", "inorganic", "physical"], default="physical")
    ap.add_argument("--chapter", default=None,
                    help="restrict chains to one chapter of the subject's graph (default: whole graph)")
    ap.add_argument("--seed", type=int, default=None, help="random seed (chain and option order)")
    ap.add_argument("--max-run-spend", type=float, default=0.45,
                    help="question first: start no new draw or refinement round once the run has spent this "
                         "many US dollars (default 0.45, about Rs 40: room for 3-4 draws; 0 for no cap)")
    ap.add_argument("--flow", choices=["question", "engine"], default="question",
                    help="computed questions: question first (default) or the older engine-first flow")
    ap.add_argument("--kind", choices=["auto", "chains", "facts"], default="auto",
                    help="question kind; auto makes a fact (MCQ/MSQ) question in the subject's fact_share of runs")
    ap.add_argument("--designer", default=None,
                    help="OpenRouter model for the design step (default: core/models.py DESIGNER), "
                         "e.g. ~google/gemini-pro-latest")
    ap.add_argument("--coder", default=None,
                    help="OpenRouter model for the coder (default: core/models.py CODER), e.g. openai/gpt-6-luna")
    ap.add_argument("--rerun-held", action="store_true",
                    help="move every on-hold question (outputs/on_hold_questions_<subject>.json: its ladder calls "
                         "kept failing) back to be judged first this run, e.g. after a fix")
    return ap.parse_args()


def main():
    args = parse_args()
    if args.designer:                                # try another designer for one run
        models.DESIGNER = args.designer
        models.ROSTER["designer"] = args.designer
        print(f"Designer this run: {args.designer}")
    if args.coder:                                   # try another coder for one run (models.CODER is read per call)
        models.CODER = args.coder
        models.ROSTER["coder"] = args.coder
        print(f"Coder this run: {args.coder}")
    if not models.key_is_set():
        print("ERROR: OPENROUTER_KEY is not set to a real key in .env.")
        return EXIT_CONFIG_ERROR
    config = get_subject_config(args.subject)
    if not os.path.exists(config["graph_path"]):
        print(f"ERROR: {config['graph_path']} not found. Build it: python tools/build_graph.py --subject {args.subject}")
        return EXIT_CONFIG_ERROR
    rng = random.Random(args.seed)
    config = {**config, "question_first": args.flow == "question",
              "max_run_spend": args.max_run_spend or None}
    try:
        adapter = adapter_for(args.subject, config, rng)
    except NotImplementedError as e:
        print(f"ERROR: {e}.")
        return EXIT_CONFIG_ERROR
    kind = args.kind
    if kind == "auto":
        # a fact_share on a subject with no fact engine is ignored, not a configuration error
        wants_fact = rng.random() < config.get("fact_share", 0.0)
        kind = "facts" if wants_fact and args.subject in FACT_ADAPTERS else "chains"
    run_adapter = adapter
    if kind == "facts":
        try:
            run_adapter = adapter_for(args.subject, config, rng, kind="facts")
        except NotImplementedError as e:
            print(f"ERROR: {e}.")
            return EXIT_CONFIG_ERROR
    print(f"Question kind this run: {kind}")
    if args.chapter and args.chapter not in adapter.graph.chapters():
        print(f"ERROR: no chapter {args.chapter!r}. Chapters: {adapter.graph.chapters()}")
        return EXIT_CONFIG_ERROR

    log = _attempt_logger(config)
    coverage = load_coverage_for_subject(config)
    print(f"{config['display_name']}: {coverage.total_accepted()} accepted so far.")
    held = _read(on_hold_file(config), [])
    if args.rerun_held:
        n = rerun_held(config)
        print(f"{n} on-hold question(s) moved back to be judged first this run.")
    elif held:
        print(f"{len(held)} question(s) on hold in {on_hold_file(config)} (--rerun-held to judge them again).")

    status = recheck_pending(args.subject, config, adapter, coverage, log)
    if status in ("accepted", "failed", "save_failed"):
        print(f"\nSpend this run: ${models.SPEND.total_cost:.4f}")
        return {"accepted": 0, "failed": EXIT_COUNCIL_FAILED, "save_failed": EXIT_SAVE_FAILED}[status]

    bb = Blackboard(args.subject)
    try:
        try:
            outcome = flow.run(run_adapter, coverage, bb, log, chapter=args.chapter, rng=rng)
        finally:
            # every run, as its docstring says: parked and crashed runs were the ones not saved
            _save_run_blackboard(args.subject, config, bb)
    except Exception as e:
        if not isinstance(e, flow.Parked) and _out_of_credits(e):
            _credits_message()
            return EXIT_NO_CREDITS
        if not isinstance(e, flow.Parked):
            raise
        p = e
        cand = bb.current["chain"] if bb.current else {}
        last_inputs = bb.last("inputs") or {}
        last_gate = bb.last("gate") or {}
        last_form = bb.last("form") or {}          # the question as asked: its stated values and answer
        last_q = bb.last("qfirst")                 # question first: the question, its program and givens
        pid = park(config, {"error": p.item.get("error"), "kind": "fact" if kind == "facts" else "chain",
                            "txs": cand.get("txs"), "drawn_txs": cand.get("drawn_txs"), "edges": cand.get("edges"),
                            "nodes": cand.get("nodes"), "chapters": cand.get("chapters"),
                            "trap_ids": cand.get("trap_ids"),
                            "values": last_form.get("values", last_inputs.get("values")),
                            "chain_values": last_inputs.get("values"), "shape": last_form.get("shape"),
                            "form_result": last_form.get("result"),
                            "scenario": last_inputs.get("scenario"), "stem": last_gate.get("stem"),
                            **({"qfirst": {**{k: last_q[k] for k in ("code", "asks", "unit", "twist")},
                                           "preset": last_q.get("preset")},
                                "values": {g["quote"]: g["value"] for g in last_q["givens"]},
                                "stem": last_q["stem"]} if last_q else {}),
                            "rounds": bb.current["rounds"] if bb.current else 0})
        if _out_of_credits(p.item.get("error")):
            print(f"\n✗ Question parked as {pid}; it is judged first on the next run.")
            _credits_message()
            return EXIT_NO_CREDITS
        print(f"\n✗ A council call failed ({p.item.get('error')}). Question parked as {pid}; "
              f"it is judged first on the next run.")
        print(f"Spend this run: ${models.SPEND.total_cost:.4f}")
        return EXIT_COUNCIL_FAILED

    code = 0
    if outcome["status"] == "accepted":
        try:
            save_accepted(args.subject, config, coverage, outcome["payload"], bb, log)
        except Exception as e:
            print(f"✗ could not save the accepted question: {type(e).__name__}: {e}")
            code = EXIT_SAVE_FAILED
    else:
        print("\n✗ No question accepted this run.")
    print(f"\nSpend this run: ${models.SPEND.total_cost:.4f}  {json.dumps(round_sig(models.SPEND.summary()))}")
    return code


if __name__ == "__main__":
    sys.exit(main())
