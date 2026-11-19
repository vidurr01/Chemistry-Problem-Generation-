"""Run the question-first pipeline ONE STAGE AT A TIME (physical chemistry).

Each command runs one stage, prints everything it read and produced, and saves it, so the next
command continues from there and any stage can be rerun alone:

    python tools/step_by_step.py draw                 # 6 random formula sets, Jev picks the best
    python tools/step_by_step.py draw --txs 273,274,272,275 --twist inverse   # or choose them
    python tools/step_by_step.py design               # the designer plans the question
    python tools/step_by_step.py write                # the writer writes it, every number a [[blank]] with a range
    python tools/step_by_step.py solve                # coder 2 (Luna) writes the solving program from the blanks
    python tools/step_by_step.py numbers              # code picks the numbers in the ranges and runs the program
    python tools/step_by_step.py check                # code checks + Jev coherence
    python tools/step_by_step.py judge                # ladder + verifier (the expensive stage)
    python tools/step_by_step.py save                 # an accepted question → the question bank
    python tools/step_by_step.py solution             # write (again) the readable solution of the saved question
    python tools/step_by_step.py show                 # what is saved so far

To check the pipeline on a REAL JEE Advanced question instead of a new one (the writer only puts its
numbers into blanks; it is never saved to the question bank):

    python tools/step_by_step.py real                 # a random real question from data/jee_advanced
    python tools/step_by_step.py real --id 2018P1_Q8  # or this one
    then: solve (also checks the program on the real numbers against the official answer), numbers,
          check, judge

A failed stage saves its feedback; the next `write` gives it to the writer (a program that breaks on the
picked numbers goes back to `solve` instead). Add --coder MODEL to
try another coder. Every command prints what it cost. State: output/step_by_step/state.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.blackboard import Blackboard  # noqa: E402
from core.engine import physical as ph  # noqa: E402
from core.engine import sandbox  # noqa: E402
from core.pipeline import qfirst  # noqa: E402

STATE = os.path.join(ROOT, "output", "step_by_step", "state.json")
ORDER = ["draw", "design", "write", "solve", "numbers", "check", "judge", "save", "solution"]
# what a stage makes; a stage clears what the later ones made from the earlier state
LATER = ("feedback", "failed_at", "stem", "values", "code", "code_prev", "code_errors", "run", "checked",
         "decision", "judged", "judged_stem")


def load() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(state: dict):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)


def need(state, *keys):
    for k in keys:
        if k not in state:
            stage = {"txs": "draw", "design": "design", "q": "write", "code": "solve", "stem": "numbers",
                     "values": "numbers"}.get(k, k)
            sys.exit(f"✗ run `{stage}` first (nothing saved for {k!r})")


def adapter():
    from core.pipeline.adapters import adapter_for
    from subject_config import get_subject_config
    cfg = get_subject_config("physical")
    return adapter_for("physical", {**cfg, "question_first": True, "max_run_spend": None}, random.Random())


_EDGES = {}


def cand_of(state) -> dict:
    """The candidate as the pipeline holds it, with the graph's own edge ids (coverage counts them)."""
    if not _EDGES:
        _EDGES.update({t: e["id"] for t, e in adapter().edge_of_tx.items()})
    steps = [ph.step(t) for t in state["txs"]]
    return {"edges": sorted(_EDGES.get(t, f"tx{t}") for t in state["txs"]), "txs": list(state["txs"]),
            "drawn_txs": list(state["txs"]), "chapters": state.get("chapters", []),
            "nodes": list(dict.fromkeys(n for st in steps for n in (st.src, st.dst))),
            "trap_ids": sorted({t.id for st in steps for t in st.traps}), "description": "",
            "_steps": steps, "_plan": SimpleNamespace(steps=steps, constants=[], branches=())}


def board(state):
    bb = Blackboard("physical")
    bb.start_chain({k: v for k, v in cand_of(state).items() if not k.startswith("_")})
    return bb


def head(title):
    print(f"\n━━━ {title} " + "━" * max(0, 70 - len(title)))


def cost(before):
    print(f"\n[cost of this stage: ${models.SPEND.total_cost - before:.4f}]")


def fail(state, stage, why):
    """A stage failed: say so plainly and save the writer-facing feedback for the next `write`."""
    fb = qfirst.explain(why, state.get("txs"))
    state["feedback"] = "Fix these problems: " + fb
    state["failed_at"] = stage
    save(state)
    print(f"\n✗ {stage} FAILED: {why}")
    if fb != why:
        print(f"\n  what the writer will be told on the next `write`:\n  {fb}")
    if state.get("real"):
        print("\n(a real JEE Advanced question: this is where the pipeline would send its own question back to the "
              "writer; `real` takes another one)")
    else:
        print("\n→ next: `write` (rewrites the question with this feedback), or `draw` for new formulas")


# ── stages ────────────────────────────────────────────────────────────────────

def do_draw(state, args):
    if args.txs:
        txs = [int(x) for x in args.txs.split(",")]
        for t in txs:
            ph.step(t)                                   # fails loudly on an unknown formula
        chapters = sorted({ph._domain(t) for t in txs})
        fit = qfirst.formulas_fit([ph.step(t) for t in txs])
    else:
        ad = adapter()
        bb = Blackboard("physical")
        best = qfirst.best_draw(ad, None, bb, lambda rec: None)
        if best is None:
            sys.exit("✗ no formula set could be drawn")
        txs, chapters, fit = best["txs"], best["chapters"], best.get("_fit")
    twist = args.twist or random.choice(sorted(qfirst.TWISTS))
    state.clear()
    state.update({"txs": txs, "chapters": chapters, "twist": twist, "fit": fit})
    save(state)
    head("DRAW")
    print(f"formulas {txs} ({', '.join(chapters)}); twist {twist}; Jev fit "
          + (f"{fit:.0%}" if fit is not None else "unavailable"))
    print(qfirst.formulas_text([ph.step(t) for t in txs]))
    print("\n→ next: design")


def do_design(state, args):
    need(state, "txs")
    steps = [ph.step(t) for t in state["txs"]]
    library = sandbox.library_doc(steps, list(ph.STEPS.values()))
    ad = adapter()
    used = qfirst.used_situations(qfirst.accepted_questions(ad.config), state.get("chapters", []))
    head("DESIGN")
    if models.DESIGNER.startswith("google/gemini-3"):
        print(f"designer: {models.DESIGNER} (thinking level {models.GEMINI3_DESIGN_LEVEL or 'default (high)'}, "
              f"cap {models.GEMINI3_DESIGN_CAP} tokens)")
    elif models.router(models.DESIGNER) == "airouter":
        print(f"designer: {models.DESIGNER} on airouter (effort {models.AIROUTER_DESIGNER_EFFORT}, "
              f"cap {models.AIROUTER_DESIGN_CAP} tokens)")
    else:
        print(f"designer: {models.DESIGNER} (reasoning {models.DESIGNER_EFFORT})")
    design = qfirst.design_question(ad.config["display_name"], qfirst.formulas_text(steps), state["twist"],
                                    used=used, rejected=state.get("design_rejected"),
                                    examples=qfirst.exemplars(state["twist"], random.Random()))
    print(json.dumps(design, ensure_ascii=False, indent=2))
    if "impossible" in design:
        state.pop("design", None)
        save(state)
        print(f"\n✗ the designer says these formulas cannot make one question → `draw` again")
        return
    problem = qfirst.design_problems(design)          # Jev, calibrated (no calibration file: no check)
    if problem:
        print(f"\n✗ Jev finds the design incoherent: {problem}")
    elif qfirst.DESIGN_GATES:                          # the old uncalibrated gates (off)
        problem = qfirst.design_coherence(design)
        if problem:
            print(f"\n✗ Jev finds the plan incoherent: {problem}")
        else:
            print("\nJev: the plan is coherent")
            problem = qfirst.design_problem(design, library)
            if problem:
                print(f"✗ the feasibility check says a program cannot compute it: {problem}")
    if problem:
        state["design_rejected"] = problem
        state.pop("design", None)
        save(state)
        print("→ next: `design` again (it is told why), or `draw`")
        return
    state["design"] = design
    for k in ("design_rejected", "q") + LATER:
        state.pop(k, None)
    save(state)
    print("\n✓ design feasible → next: write")


def do_write(state, args):
    need(state, "txs")
    steps = [ph.step(t) for t in state["txs"]]
    library = sandbox.library_doc(steps, list(ph.STEPS.values()))
    constants = list(dict.fromkeys(c for s in steps for c in s.constants))
    traps = list(dict.fromkeys(t.desc for s in steps for t in s.traps))
    ad = adapter()
    used = qfirst.used_situations(qfirst.accepted_questions(ad.config), state.get("chapters", []))
    examples = qfirst.exemplars(state["twist"], random.Random())
    head("WRITE")
    if state.get("feedback"):
        print(f"feedback given to the writer: {state['feedback']}\n")
    q = qfirst.write_question(ad.config["display_name"], qfirst.formulas_text(steps), library, constants,
                              state["twist"], examples, traps,
                              previous=qfirst.previous_text(state["q"]) if state.get("q") else None,
                              feedback=state.get("feedback"), used=used, design=state.get("design"))
    print(json.dumps(q, ensure_ascii=False, indent=2))
    if "impossible" in q:
        print("\n✗ the writer says these formulas cannot make one question → `draw` again")
        return
    state["q"] = q
    for k in LATER:
        state.pop(k, None)
    save(state)
    print("\nas a reader sees it (each range blank at a typical value):\n" + qfirst.preview_text(q))
    probs = qfirst.blank_problems(q)
    if probs:
        return fail(state, "write", "; ".join(probs))
    if qfirst._level_floor() is None:
        print("\n(level check off: run tools/calibrate_level.py to turn it on)")
    else:
        why = qfirst.level_problem(q)
        if why:
            return fail(state, "write", why)
    print("\n✓ written → next: solve")


def do_solve(state, args):
    need(state, "txs", "q")
    probs = qfirst.blank_problems(state["q"])
    if probs:
        sys.exit(f"✗ the question's blanks have problems, so no program is written for it: {'; '.join(probs)}")
    head("SOLVE (coder 2 writes the program from the blanks, before any number is chosen)")
    print("question with blanks:\n" + state["q"]["stem"])
    if state.get("code_errors"):
        print(f"\nthe previous program failed on picked numbers; the coder is told: {state['code_errors']}")
    code, why = qfirst.solver_program(state["q"], state["txs"], board(state), previous=state.get("code_prev"),
                                      errors=state.get("code_errors"), seed=random.randrange(1 << 30),
                                      design=state.get("design"))
    if code is None:
        return fail(state, "solve", why)
    for k in ("code_prev", "code_errors", "stem", "values", "run", "checked", "decision", "judged", "judged_stem"):
        state.pop(k, None)
    state["code"] = code
    print("\nprogram:\n" + code)
    real_check(state, code)
    save(state)
    print("\n✓ the program runs on values from the ranges → next: numbers")


def do_numbers(state, args):
    need(state, "txs", "q", "code")
    q = state["q"]
    head("NUMBERS (code picks values in the ranges until the program's answer is right)")
    names, ranges, fixed = qfirst.blank_spec(q)
    print(f"ranges: {ranges}\nfixed values: {fixed}\nanswer_range: {q.get('answer_range')}\n")
    picked = qfirst.pick_numbers(q, state["code"], state["txs"], seed=random.randrange(1 << 30))
    if not picked.get("ok"):
        print(f"{picked.get('tries')} value sets tried; failures: {picked.get('counts')}")
        if picked.get("kind") in ("code", "timeout"):
            # the program ran on the probe's values but breaks on others: the coder's fault, not the writer's
            state.update({"code_prev": state.pop("code"),
                          "code_errors": [qfirst._probe_problem(picked, names)]})
            save(state)
            print(f"\n✗ numbers FAILED: the program breaks on other values: {picked.get('error')}"
                  f"\n→ next: `solve` (the coder rewrites the program with this error)")
            return
        return fail(state, "numbers", picked["why"])
    stem, givens = qfirst.filled_question(q, picked["values"])
    run = picked["run"]
    dropped = qfirst.unneeded(state["txs"], run)
    if dropped:
        state["txs"] = [t for t in state["txs"] if t not in dropped]
        print(f"formulas {dropped} are not needed by this question: dropped ({len(state['txs'])} remain)")
    state.update({"stem": stem, "values": picked["values"],
                  "run": {"answer": run["answer"], "answer_exact": run["answer_exact"], "givens": givens,
                          "traps": run["traps"], "tolerance": run["tolerance"], "called_txs": run["called_txs"]}})
    save(state)
    print(f"values ({picked['tries']} set{'s' if picked['tries'] != 1 else ''} tried): "
          + ", ".join(f"{g['quote']} = {g['value']}" for g in givens))
    print(f"\nthe question, filled in:\n{stem}\n\nanswer {run['answer']} {q['unit']} (rounding moves it "
          f"{run['tolerance']:.1%}); traps {[t['id'] for t in run['traps']]}")
    print("\n✓ numbers picked → next: check")


def rerun(state) -> dict:
    """The program run again on the question's values, with the givens as the pipeline reads them."""
    run = sandbox.evaluate(state["code"], state["txs"], any_step=True, preset=state.get("values"))
    if run.get("ok") and state.get("values"):
        run["givens"] = qfirst.filled_question(state["q"], state["values"])[1]
    return run


def do_check(state, args):
    need(state, "txs", "stem", "code", "values")
    head("CHECK (code checks, then Jev coherence)")
    run = rerun(state)
    if not run.get("ok"):
        return fail(state, "check", run.get("error"))
    steps = [ph.step(t) for t in state["txs"] + [t for t in run["called_txs"] if t not in state["txs"]]]
    constants = list(dict.fromkeys(c for s in steps for c in s.constants))
    probs = qfirst.question_problems(state["stem"], run, state["txs"], constants, (),
                                     qfirst.accepted_questions(adapter().config))
    left = [t for t in run.get("unused_steps") or () if t in state["txs"]]
    if left:
        probs.append(f"the program never calls {', '.join(f'step_{t}' for t in left)}")
    if probs:
        return fail(state, "check", "; ".join(probs))
    print("code checks passed")
    scores = qfirst.coherence_scores(state["stem"])
    if scores is not None:
        cur, loose = qfirst._coherence_cuts(), qfirst._coherence_cuts(qfirst.LOOSER_PERCENTILE)
        print("\nJev coherence (a fault is found at or above its cut-off):")
        for k in qfirst.COHERENCE_QUESTIONS:
            p = scores.get(k, 0)
            print(f"   {k:20} {p:5.0%}   current cut {cur[k]:.2f} → {'FAULT' if p >= cur[k] else 'ok':5}"
                  f"   looser cut {loose[k]:.2f} → {'FAULT' if p >= loose[k] else 'ok'}")
        verdicts = {name: not qfirst.coherence_problems(state["stem"], scores, pct)
                    for name, pct in (("current", None), ("looser", qfirst.LOOSER_PERCENTILE))}
        print(f"   → current cut-off: {'passes' if verdicts['current'] else 'rejects'};  "
              f"looser cut-off: {'passes' if verdicts['looser'] else 'rejects'}   (this run uses: {args.cut})")
        state.setdefault("coherence", {}).update(scores=scores, verdicts=verdicts)
    probs = [] if scores is None else qfirst.coherence_problems(
        state["stem"], scores, qfirst.LOOSER_PERCENTILE if args.cut == "looser" else None)
    if probs:
        return fail(state, "check", "; ".join(probs))
    state["checked"] = True
    save(state)
    print("Jev coherence passed\n\n✓ ready → next: judge (ladder + verifier; the expensive stage)")


def do_judge(state, args):
    need(state, "txs", "stem", "code", "values")
    from core.pipeline import flow
    head("JUDGE (ladder → verifier)")
    q = state["q"]
    run = rerun(state)
    if not run.get("ok"):
        return fail(state, "judge", run.get("error"))
    result = qfirst.make_result(run, q["asks"], q["unit"], state["twist"], state["code"])
    ad = adapter()
    stem = state["stem"]
    fmt = flow._answer_instruction(ad, result)
    if fmt and " ".join(fmt.split()) not in " ".join(stem.split()):
        stem = stem.rstrip() + " " + fmt
    values = {g["quote"]: g["value"] for g in run["givens"]}
    cand = cand_of(state)
    decision = flow.judge(ad, cand, cand["_plan"], values, result, stem, board(state), lambda rec: None)
    print(f"\ndecision: {decision['decision']}" + (f" — {decision.get('reason')}" if decision.get("reason") else ""))
    state["decision"] = decision["decision"]
    state["judged"] = json.loads(json.dumps(decision, ensure_ascii=False, default=str))
    state["judged_stem"] = stem
    save(state)
    if decision["decision"] == "accept":
        print("\n✓ ACCEPTED → next: save (writes it to the question bank)")
    elif decision["decision"] == "reword":
        state["feedback"] = (decision.get("feedback") or "") + " Keep the situation, the blanks and their ranges."
        save(state)
        print(f"\n→ the judges want clearer wording: {decision.get('feedback')}\n→ next: write")


def do_save(state, args):
    """The accepted question, saved exactly as the full pipeline saves it."""
    need(state, "txs", "stem", "code", "judged")
    if state.get("real"):
        sys.exit("✗ a real JEE Advanced question run as a check is never saved to the question bank")
    if state["judged"].get("decision") != "accept":
        sys.exit(f"✗ the last judge decision was {state['judged'].get('decision')!r}, not accept")
    import run_groundup_final as rg
    from core import dedup
    from subject_config import get_subject_config, load_coverage_for_subject
    head("SAVE")
    q = state["q"]
    run = rerun(state)
    if not run.get("ok"):
        sys.exit(f"✗ the program no longer runs: {run.get('error')}")
    result = qfirst.make_result(run, q["asks"], q["unit"], state["twist"], state["code"])
    extra = [t for t in run["called_txs"] if t not in state["txs"]]
    cand = {**cand_of(state), "txs": state["txs"] + extra, "extra_txs": extra}
    values = {g["quote"]: g["value"] for g in run["givens"]}
    cfg = {**get_subject_config("physical"), "question_first": True}
    payload = {"cand": cand, "plan": cand["_plan"], "values": values,
               "scenario": f"question-first ({state['twist']}), stage by stage", "result": result,
               "stem": state.get("judged_stem") or state["stem"], "decision": state["judged"],
               "sig": dedup.signature("physical", cand["txs"], values), "solver_code": state["code"]}
    dup = dedup.duplicate_of(payload["sig"])
    if dup:
        sys.exit(f"✗ the same as accepted question {dup}: not saved")
    bb = board(state)
    record = rg.save_accepted("physical", cfg, load_coverage_for_subject(cfg), payload, bb, lambda rec: None)
    state["saved_as"] = record["question_id"]
    save(state)


def do_solution(state, args):
    """The readable solution for the question saved last, written and checked again, and stored."""
    need(state, "code", "saved_as")
    from core.llm import write_json_atomic
    from core.pipeline import flow
    from subject_config import get_subject_config
    head("SOLUTION")
    cfg = get_subject_config("physical")
    with open(cfg["output_file"], encoding="utf-8") as f:
        records = json.load(f)
    rec = next((r for r in records if r.get("question_id") == state["saved_as"]), None)
    if rec is None:
        sys.exit(f"✗ {state['saved_as']} is not in {cfg['output_file']}")
    q = state["q"]
    run = rerun(state)
    if not run.get("ok"):
        sys.exit(f"✗ the program no longer runs: {run.get('error')}")
    result = qfirst.make_result(run, q["asks"], q["unit"], state["twist"], state["code"])
    solution, check = flow.checked_solution(rec["question"], result)
    print(solution or f"✗ no solution passed the checks ({check['status']}): {check.get('last_problems')}")
    if solution:
        rec["solution"], rec["solution_check"] = solution, check
        write_json_atomic(cfg["output_file"], records, ensure_ascii=False)
        try:
            from tools.results import promote
            promote(("physical",), quiet=True)
        except Exception as e:                   # noqa: BLE001
            print(f"[warn] results/ copy not updated: {e}")
        print(f"\n✓ solution stored in {state['saved_as']}")


# ── a real JEE Advanced question through the pipeline (a check of the pipeline, never saved) ─────────────

REAL_PROMPT = """Below is a real JEE Advanced chemistry question. Put it into our blank format WITHOUT changing
anything else: keep its wording, its situation and what it asks exactly; only replace each number it states
by a blank [[name]].

QUESTION:
{text}

{rules}
- For each range blank also give "original": the number the question states, in the unit written after the
  blank: {{"range": [low, high], "original": x}}. Choose each range around that value, wide enough to give
  other realistic questions (about half to twice the value, where that stays physical).
- "asks" and "unit" say exactly what the answer of the question as stated is (if it asks for x in
  "x × 10^-2", "asks" is x and "unit" is empty); "answer_range" is a realistic range for that answer.

Return JSON only:
{{"asks": "...", "unit": "...", "asked": "...", "values": {{"name": {{"range": [low, high], "original": x}},
"other_name": {{"value": x}}, ...}}, "answer_range": [low, high], "stem": "the question with every number as [[name]]"}}"""


# Database entries whose stored text does not fit their official answer: a check against them proves nothing.
# 2017P1_Q26: the stored text gives a cell constant of 1000 m⁻¹ and α = 0.01 and asks for Λ° in S m² mol⁻¹
# (0.0333 by hand); the official 6 belongs to the paper's own text (120 cm electrodes, pH 4, Z × 10²). The
# entry's own solution note says the numbers do not match. Found by `real` on 2026-11-18.
BROKEN_REAL = {"2017P1_Q26"}


def real_questions() -> list:
    """The real JEE Advanced physical questions whose formulas are all engine steps (as the coder's
    calibration uses them: numeric official answer, no figure), without the broken entries."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        from tools import calibrate_coder
    return [q for q in calibrate_coder.real_questions() if q["id"] not in BROKEN_REAL]


def do_real(state, args):
    qs = real_questions()
    if args.id:
        pick = next((q for q in qs if q["id"] == args.id), None)
        if pick is None:
            sys.exit(f"✗ {args.id} is not among the {len(qs)} usable real questions: {', '.join(q['id'] for q in qs)}")
    else:
        # at random, among the questions not tested yet (2026-11-18: two runs drew 2020P1_Q15, a 1-in-49 chance)
        done_file = os.path.join(ROOT, "output", "step_by_step", "real_tested.json")
        try:
            with open(done_file, encoding="utf-8") as f:
                done = set(json.load(f))
        except (OSError, ValueError):
            done = set()
        pool = [q for q in qs if q["id"] not in done] or qs
        pick = random.choice(pool)
        os.makedirs(os.path.dirname(done_file), exist_ok=True)
        with open(done_file, "w", encoding="utf-8") as f:
            json.dump(sorted(done | {pick["id"]}), f)
        print(f"picked at random from the {len(pool)} real questions not tested yet")
    txs = pick["txs"]
    head(f"REAL JEE ADVANCED QUESTION {pick['id']} (official answer {pick['answer']})")
    print(pick["text"])
    print(f"\nits formulas: {txs}\n" + qfirst.formulas_text([ph.step(t) for t in txs]))
    # as in the pipeline: blanks with problems go back to the writer, up to qfirst.WRITE_TRIES times
    prompt = REAL_PROMPT.format(text=pick["text"], rules=qfirst.BLANK_RULES)
    previous, probs = None, []
    for attempt in range(1, qfirst.WRITE_TRIES + 1):
        redo = "" if not previous else (f"\n\nYour previous version:\n{previous}\nwas sent back: "
                                        f"{'; '.join(probs)}. Fix it.")
        out = models.ask_json("generator", models.GENERATOR, "You prepare chemistry exam questions. Output JSON only.",
                              prompt + redo, max_tokens=6000, temperature=0.2, reasoning_effort="low",
                              retry_cut_off=False)
        if not str(out.get("stem") or "").strip():
            sys.exit(f"✗ the writer returned no question: {json.dumps(out, ensure_ascii=False)[:300]}")
        q = {k: (str(out.get(k)).strip() if out.get(k) is not None else "") for k in ("stem", "asks", "unit", "asked")}
        q.update(qfirst.parse_values(out))
        vals = out.get("values") if isinstance(out.get("values"), dict) else {}
        original = {k: v for k, v in q["fixed"].items()}
        for k in q["ranges"]:
            spec = vals.get(k) if isinstance(vals.get(k), dict) else {}
            x = qfirst._num(spec.get("original"))
            if x is not None:
                original[k] = x
        print(f"\nin blanks (writer attempt {attempt}):\n" + json.dumps(q, ensure_ascii=False, indent=2))
        print(f"\nthe real numbers: {original}")
        probs = qfirst.blank_problems(q)
        if not probs:
            break
        print(f"\n✗ the blanks have problems; as in the pipeline, the writer is sent back "
              f"({attempt}/{qfirst.WRITE_TRIES}): {'; '.join(probs)}")
        previous = qfirst.previous_text(q)
    state.clear()
    state.update({"txs": txs, "chapters": sorted({ph._domain(t) for t in txs}), "twist": "real", "q": q,
                  "real": {"id": pick["id"], "official": pick["answer"], "text": pick["text"], "original": original}})
    save(state)
    if probs:
        print(f"\n✗ after {qfirst.WRITE_TRIES} tries the blanks still have problems: the pipeline would give up on "
              f"this question and draw new formulas. `real` takes another one")
        return
    missing = [n for n in qfirst.blank_names(q) if n not in original]
    if missing:
        print(f"\n(no real number for {', '.join(missing)}: the official answer cannot be checked)")
    if qfirst._level_floor() is not None:
        score = qfirst.jev_level(pick["text"])
        if score is not None:
            floor = qfirst._level_floor()
            print(f"\nJev level of the real question: {score:.2f} (floor {floor:.2f}: "
                  f"{'passes' if score >= floor else 'Jev would send it back'})")
    print("\n→ next: solve")


def real_check(state, code) -> None:
    """The program run on the real question's own numbers, against the official answer."""
    real = state.get("real")
    if not real:
        return
    names = qfirst.blank_names(state["q"])
    if any(n not in real["original"] for n in names):
        print("\n(the official answer cannot be checked: not every blank has its real number)")
        return
    run = sandbox.evaluate(code, state["txs"], any_step=True, preset={n: real["original"][n] for n in names})
    if not run.get("ok"):
        print(f"\n✗ on the real numbers the program fails: {run.get('error')}")
        real["check"] = "fails"
        return
    from tools.calibrate_coder import matches
    got, official = run["answer_exact"], real["official"]
    ok = matches(got, official)
    real["check"] = "right" if ok else "wrong"
    real["program_answer"] = got
    print(f"\non the real question's numbers the program gives {got:.6g}; official answer {official} "
          + ("✓ (the pipeline's answer key is right)" if ok else "✗"))
    if not ok and got and float(official):
        ratio = got / float(official)
        k = round(math.log10(abs(ratio))) if ratio else 0
        if ratio > 0 and k and abs(math.log10(ratio) - k) < 0.01:
            print(f"   it differs by exactly 10^{k}: the answer's form (x × 10^n, a unit) was read differently")


def do_show(state, args):
    print(json.dumps(state, ensure_ascii=False, indent=2, default=str) if state else "nothing saved yet")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=ORDER + ["real", "show"])
    ap.add_argument("--id", help="real: the real JEE Advanced question to use, e.g. 2018P1_Q8")
    ap.add_argument("--cut", choices=["current", "looser"], default="current",
                    help="check: Jev coherence cut-offs (both verdicts are printed; this one decides)")
    ap.add_argument("--txs", help="draw: choose the formulas, e.g. 273,274,272,275")
    ap.add_argument("--twist", choices=sorted(qfirst.TWISTS), help="draw: choose the twist")
    ap.add_argument("--coder", help="OpenRouter model for the coder this time")
    ap.add_argument("--designer", help="OpenRouter model for the design step this time")
    ap.add_argument("--thinking", type=int, help="design: thinking tokens this time (0 = thinking off)")
    ap.add_argument("--effort", choices=["low", "medium", "high"], help="design on airouter: effort this time")
    ap.add_argument("--cap", type=int, help="design on airouter: reply cap in tokens this time")
    args = ap.parse_args()
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    if args.coder:
        models.CODER = args.coder
    if args.designer:
        models.DESIGNER = args.designer
    if args.effort:
        models.AIROUTER_DESIGNER_EFFORT = models.GEMINI3_DESIGN_LEVEL = args.effort
    if args.cap:
        models.AIROUTER_DESIGN_CAP = models.GEMINI3_DESIGN_CAP = args.cap
    if args.thinking is not None:
        models.DESIGNER_THINKING = args.thinking
        models.DESIGNER_EFFORT = f"{args.thinking} thinking tokens" if args.thinking else "thinking off"
    state = load()
    before = models.SPEND.total_cost
    try:
        globals()["do_" + args.stage](state, args)
    finally:
        cost(before)


if __name__ == "__main__":
    main()
