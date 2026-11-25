"""
qfirst.py — the question-first flow for computed (chain) questions.

    3-5 formulas drawn truly at random from all engine steps (adapter.random_formulas; no
            graph, chain or coverage condition)
    random twist (inverse, two-state ratio or difference, simultaneous, condition)
    designer: three designs (situation, links, the non-obvious insight, wrong routes), the best kept
    writer: a NEW, hard question built on that design, in which all those formulas are needed,
            used with that twist, or "impossible" (then new formulas are drawn); every number is a
            blank [[name]] with a realistic range (or, for a value of the substance itself, a value)
            and a range for the answer; two real JEE Advanced questions with the same twist are shown
            for difficulty and style only, and code rejects a question too close to either of them
    coder 2 (Luna): a program solve() written from the question WITH ITS BLANKS, before any number
            is chosen, given only those engine steps (core/engine/sandbox.py); the blanks are its
            variables. A probe on values from the ranges sends a broken program back to it
    coder 1, the number step (code, no model): value sets drawn in the ranges are run through that
            program until one gives an answer in the answer range that rounding does not move by
            more than 2 %, that at least two typical mistakes change, and that uses every value;
            only then are the numbers printed in the question (pick_numbers)
    code checks: every formula's result changes the answer, no intermediate result stated,
            not a variant of the examples; then Jev's coherence check
    dedup → ladder → verifier → hints (flow.judge, unchanged)
    too easy / unclear → the question is rewritten (refinement loop: to be redesigned)

The engine still decides the answer: the program's chemistry is the engine's steps, run on
exactly the values the question prints. The ladder and the verifier check that answer against
independent solvers, as before.

Where each stage lives (this file runs them; see also docs/PIPELINE.md):
    qf_draw.py     1 draw        best_draw, formulas_fit, TWISTS, exemplars
    qf_design.py   2 design      design_question, design_problems (Jev, calibrated)
    qf_writer.py   3 write       write_question, BLANK_RULES, parse_values, blank_problems
    qf_checks.py   level check   level_problem (Jev, before any program)
    qf_coder.py    4 solve       solver_program (Luna writes the program from the blanks)
    qf_numbers.py  5 numbers     pick_numbers (code picks the values), filled_question, numbers_for
    qf_checks.py   6 checks      question_problems, coherence_problems (Jev), explain
    qf_text.py     helpers       how numbers print and are read back, novelty against past questions
    here           write_and_solve (stages 2-6 for one question), run (draw -> judge -> refine), rebuild_result
"""

from __future__ import annotations

import random

from core import dedup, models
from core.engine import sandbox
from core.pipeline.qf_shortcut import shortcut_problem  # noqa: E402
from core.engine.base import ChainResult
# Every stage's names, reachable as qfirst.<name> as before the split (this file, tools and tests use them).
from core.pipeline.qf_text import (  # noqa: F401, E402
    NGRAM, MAX_SHARED_NGRAMS, MAX_SHARED_VALUES, _SUP, _NUM, _num_text, _powers, stated_numbers, _scaled_equal,
    _trivial, _distinctive, _words, _profile, too_close_to_past, _SCI, _free_number, PLACEHOLDER, _fmt_number,
    _sig_digits, fill_template)
from core.pipeline.qf_draw import (  # noqa: F401, E402
    _ROOT, EXEMPLARS, TWISTS, _cache, exemplars, FIT_CANDIDATES, FIT_FLOOR, FIT_BATCHES, FIT_PARALLEL,
    _fit_floor, FIT_QUESTION, pick_best, best_draw, formulas_fit, formulas_text)
from core.pipeline.qf_design import (  # noqa: F401, E402
    design_question, DESIGN_GATES, DESIGN_COHERENCE_QUESTIONS, design_coherence, USED_SITUATIONS,
    SITUATION_CHARS, accepted_questions, used_situations, DESIGN_TRIES, design_problem, design_plan_text,
    design_problems)
from core.pipeline.qf_writer import (  # noqa: F401, E402
    WRITE_TRIES, BLANK_RULES, write_question, STANDARD_CONSTANTS, _RESERVED, _num, parse_values,
    blank_problems, constant_names, _typical, preview_text, previous_text, blank_names, blank_spec)
from core.pipeline.qf_checks import (  # noqa: F401, E402
    COHERENCE_REJECT_AT, MIN_TRAPS, _squash, unneeded, question_problems, trace_problems, COHERENCE_QUESTIONS,
    COHERENCE_PERCENTILE, LOOSER_PERCENTILE, _pct, _coherence_cuts, coherence_scores, coherence_problems,
    LEVELS, LEVEL_INSTRUCTIONS, _level_floor, jev_level, level_problem, _IMPOSSIBLE_VALUE, explain,
    _unused_by_name)
from core.pipeline.qf_coder import (  # noqa: F401, E402
    CODE_TRIES, write_program, _code_reply, coder_for, _coder_hint, named_values, exact_calls, _MISTAKES,
    coder_library, PROBE_TRIES, blank_lines, write_blank_program, _probe_problem, solver_program, program_for)
from core.pipeline.qf_numbers import (  # noqa: F401, E402
    FRAGILE_TOL, PICK_TRIES, PICK_TIMEOUT, numbers_problem, _numbers_problem, pick_numbers, filled_question,
    numbers_for)


# A garbled writer reply (cannot be read) or a blank-format slip (numbers not written as [[blanks]], found by code
# with an exact fix) is asked again this many times without counting as a draft: with one draft per draw it would
# otherwise throw away a design already paid for (~Rs 3.8). Rejections of the question itself end the draw.
# The two have separate counts (2026-11-24): a slip used to spend the garbled-reply retry, so a later garbled reply
# used up the second draft.
UNREADABLE_RETRIES = 2

MAX_DRAWS = 6           # formula draws per run (a draw the writer cannot make one question of is redrawn)


# A writer once ignored the placeholders and stated its own numbers, which did not agree (a negative
# equilibrium amount): a stem without them is sent back.
REQUIRE_PLACEHOLDERS = True


def make_result(run: dict, asks: str, unit: str, twist: str, code: str) -> ChainResult:
    res = ChainResult(answer=run["answer"], unit=unit, kind="real", asks=asks, trace=run["trace"],
                      traps=run["traps"], constants=run["constants"], tolerance=run["tolerance"])
    res.form = f"question_first:{twist}"
    res.detail = {"twist": twist, "givens": run["givens"], "depth": run["depth"]}
    res.form_note = (f"Asked: {asks}{(' (' + unit + ')') if unit else ''}. The steps above are the engine's "
                     f"formulas as a program applied them to the question's data.")
    res.solver_code = code
    return res


def write_and_solve(adapter, cand, twist, bb, rng, previous=None, feedback=None, solved=None):
    """A question that passes every code check: (stem, run, code, asks, unit, result, cand) where
    cand also holds the formulas the writer added; None if none did; IMPOSSIBLE if the writer
    says the formulas cannot make one question."""
    from types import SimpleNamespace
    from core.engine import physical as ph
    from core.pipeline import flow
    drawn = list(cand.get("drawn_txs") or cand["txs"])
    steps = [ph.step(t) for t in drawn]
    library = sandbox.library_doc(steps, list(ph.STEPS.values()))
    constants = list(dict.fromkeys(c for s in steps for c in s.constants))
    traps = list(dict.fromkeys(t.desc for s in steps for t in s.traps))
    accepted = accepted_questions(adapter.config)
    used = used_situations(accepted, cand.get("chapters", []))
    design = cand.get("_design")
    if design is None:                           # the first question for this draw: plan it first
        rejected = None
        for d_try in range(DESIGN_TRIES):
            # twist None: the designer chooses it, seeing every twist with one level example each
            examples = exemplars(twist, rng) if twist is not None else {t: exemplars(t, rng, 1) for t in TWISTS}
            try:
                design = design_question(adapter.config["display_name"], formulas_text(steps), twist, used=used,
                                         rejected=rejected, examples=examples, n_formulas=len(drawn))
            except ValueError as e:
                print(f"    design reply unusable ({str(e)[:100]}); writing without a design")
                design = {}
                break
            if "impossible" in design:
                bb.note("impossible", attempt=0, reason=design["impossible"], at="design")
                print(f"    designer: these formulas cannot make one question: {design['impossible'][:160]}")
                return IMPOSSIBLE
            if design.get("drop"):               # the designer left out ONE formula that did not fit (4-5 drawn)
                out_tx = drawn[design["drop"] - 1]
                drawn = [t for t in drawn if t != out_tx]
                steps = [ph.step(t) for t in drawn]
                library = sandbox.library_doc(steps, list(ph.STEPS.values()))
                constants = list(dict.fromkeys(c for s in steps for c in s.constants))
                traps = list(dict.fromkeys(t.desc for s in steps for t in s.traps))
                cand = {**cand, "txs": drawn, "drawn_txs": drawn, "_steps": steps,
                        "_plan": SimpleNamespace(steps=steps, constants=[], branches=())}
                if bb.current:
                    bb.current["chain"].update(txs=drawn, drawn_txs=drawn)
                bb.note("formula_left_out", tx=out_tx, by="designer")
                print(f"    designer left out formula {out_tx} ({ph.step(out_tx).asks}); {len(drawn)} remain")
            bb.note("design", try_=d_try + 1, **design)
            if design.get("insight"):
                print(f"  [design] {str(design.get('situation', ''))[:110]} | insight: {str(design['insight'])[:110]}")
            problem = design_problems(design) or (
                (design_coherence(design) or design_problem(design, library)) if DESIGN_GATES else None)
            if not problem:
                break
            bb.note("design_rejected", try_=d_try + 1, problem=problem)
            print(f"    design cannot be built with these formulas ({d_try + 1}/{DESIGN_TRIES}): {problem[:160]}")
            rejected = problem
        else:
            return IMPOSSIBLE                    # no design these formulas can compute: draw new ones
        cand = {**cand, "_design": design}
    if twist is None:                            # the designer's choice; without a design, a random one
        twist = (design or {}).get("twist") or rng.choice(sorted(TWISTS))
        print(f"  [twist] {twist} ({'chosen by the designer' if (design or {}).get('twist') else 'random: the designer named none'})")
        if bb.current:
            bb.current["chain"]["twist"] = twist
        bb.note("twist", twist=twist, by="designer" if (design or {}).get("twist") else "random")
    cand = {**cand, "twist": twist}
    unreadable = slips = 0
    attempt = -1
    while attempt + 1 < WRITE_TRIES:
        attempt += 1
        if over_budget(adapter.config.get("max_run_spend")):
            return None
        examples = exemplars(twist, rng)
        try:
            q = write_question(adapter.config["display_name"], formulas_text(steps), library, constants, twist,
                               examples, traps, previous=previous, feedback=feedback, solved=solved,
                               used=used, design=design or None)
        except ValueError as e:
            bb.note("question", attempt=attempt + 1, error=str(e)[:300])
            print(f"    question reply unusable ({str(e)[:120]})")
            if unreadable < UNREADABLE_RETRIES:  # a reply that cannot be read is a technical failure, not a
                unreadable += 1                  # rejected draft: asked again without using up the draft
                attempt -= 1
            continue
        if "impossible" in q:
            bb.note("impossible", attempt=attempt + 1, reason=q["impossible"])
            print(f"    writer: these formulas cannot make one question: {q['impossible'][:160]}")
            return IMPOSSIBLE
        stem, asks, unit = q["stem"], q["asks"], q["unit"]
        bb.note("question", attempt=attempt + 1, twist=twist, examples=[e["id"] for e in examples], **q)
        print(f"  [question] attempt {attempt + 1}: asks {asks}{(' (' + unit + ')') if unit else ''}")
        why = level_problem(q)               # Jev: is it JEE Advanced level? before any program is paid for
        if why:
            bb.note("question_rejected", attempt=attempt + 1, problems=[why], at="level")
            print(f"    question rejected ({attempt + 1}/{WRITE_TRIES}): {why[:220]}")
            previous, feedback, solved = previous_text(q), "Fix these problems: " + why, None
            continue
        blanks = REQUIRE_PLACEHOLDERS or bool(PLACEHOLDER.search(stem))
        probs = blank_problems(q) if blanks else []
        if probs:                                # fixed before any program is paid for
            bb.note("question_rejected", attempt=attempt + 1, problems=probs, at="blanks")
            print(f"    blanks need fixing: {'; '.join(probs)[:220]}")
            previous, feedback, solved = previous_text(q), "Fix these problems: " + "; ".join(probs), None
            if slips < UNREADABLE_RETRIES:       # a format slip (numbers not written as blanks), found by code
                slips += 1                       # with an exact fix: retried without using up the draft
                attempt -= 1
            continue
        if blanks:                               # coder 2 writes the program, the number step picks the numbers
            stem, run, code, why = numbers_for(q, drawn, bb, seed=rng.randrange(1 << 30), design=design or None)
        else:                                    # an old-style question that states its own numbers
            code, run, why = program_for(stem, asks, unit, {**cand, "drawn_txs": drawn}, bb, built=False)
        kept, extra, all_steps, full = drawn, [], steps, cand
        if run is not None:
            dropped = unneeded(drawn, run)
            kept = [t for t in drawn if t not in dropped]
            if dropped:
                print(f"    formulas {dropped} are not needed by this question: dropped ({len(kept)} remain)")
                bb.note("dropped_formulas", txs=dropped)
            # formulas outside the draw that the program called: fine, they are the graph's too
            extra = [t for t in run["called_txs"] if t not in drawn]
            all_steps = [ph.step(t) for t in kept] + [ph.step(t) for t in extra]
            full = {**cand, "txs": kept + extra, "drawn_txs": kept, "extra_txs": extra, "_steps": all_steps,
                    "_plan": SimpleNamespace(steps=all_steps, constants=[], branches=()),
                    "_q": q if blanks else None}
            if extra:
                print(f"    the program also used formulas {extra}")
        probs = [why] if run is None else question_problems(
            stem, run, kept, list(dict.fromkeys(c for s in all_steps for c in s.constants)), examples,
            accepted)
        if run is not None:
            left = [t for t in run.get("unused_steps") or () if t in kept]
            if left:                             # a drawn formula the program never called and that cannot go
                probs.append(f"the program never calls {', '.join(f'step_{t}' for t in left)}")
            probs += trace_problems(run, asks)   # K_c used as K_p, data that contradict, an unreal element
        if not probs:
            probs = coherence_problems(stem)     # only drafts that pass every code check are sent to Jev
        if not probs:                            # does the hidden step change the answer? (one coder call)
            sp = shortcut_problem(design, stem, code, run,
                                  {g["quote"]: g["value"] for g in run["givens"]} if blanks else None, bb)
            probs = [sp] if sp else []
        if probs:
            bb.note("question_rejected", attempt=attempt + 1, problems=probs)
            print(f"    question rejected ({attempt + 1}/{WRITE_TRIES}): {'; '.join(probs)[:220]}")
            previous = previous_text(q) if blanks else stem
            feedback, solved = "Fix these problems: " + "; ".join(explain(p, drawn) for p in probs), None
            continue
        result = make_result(run, asks, unit, twist, code)
        fmt = flow._answer_instruction(adapter, result)
        if fmt and " ".join(fmt.split()) not in " ".join(stem.split()):
            stem = stem.rstrip() + " " + fmt
        preset = {g["quote"]: g["value"] for g in run["givens"]} if blanks else None
        bb.note("qfirst", stem=stem, code=code, asks=asks, unit=unit, twist=twist, givens=run["givens"],
                answer=run["answer"], trace=run["trace"], traps=run["traps"], tolerance=run["tolerance"],
                constants=run["constants"], depth=run["depth"], extra_txs=extra, preset=preset,
                template=q["stem"] if blanks else None, ranges=q.get("ranges") if blanks else None,
                answer_range=q.get("answer_range") if blanks else None)
        if bb.current:
            bb.current["chain"].update(txs=full["txs"], drawn_txs=kept, extra_txs=extra)
        return stem, run, code, asks, unit, result, full
    return None


IMPOSSIBLE = "impossible"


def refine_round(cand, twist, stem, graded, used, rng, bb):
    """Too easy: the refiner decides which refine.CASES made it easy, code picks and applies
    them (a new twist, one more drawn formula) and returns (cand, twist, writer instructions);
    None when no case is left. `used` gains the picked cases."""
    from types import SimpleNamespace
    from core.engine import physical as ph
    from core.pipeline import refine
    drawn = list(cand.get("drawn_txs") or cand["txs"])
    unavailable = set(used)
    # never one more formula: it made questions longer, not harder (a back-titration bolted onto a photoelectric
    # question, 2026-11-25; real hard questions are short, with one hidden step)
    unavailable.add("too_few_steps")
    working = next((str(g.get("working") or "") for g in graded if g.get("counts_as_solved")), "")
    try:
        probs = refine.classify(stem, formulas_text([ph.step(t) for t in drawn]), working, unavailable)
    except Exception as e:                       # noqa: BLE001 - Jev unreachable or no key: pick at random
        print(f"    Jev unavailable ({str(e)[:80]}); choosing a case at random")
        probs = {}
    chosen = refine.pick(probs, unavailable, rng)
    if not chosen:
        return None
    used.update(chosen)
    twist_text, added = "", ""
    for cid in chosen:
        if cid in refine.TWIST_FOR:
            options = [t for t in refine.TWIST_FOR[cid] if t != twist] or list(refine.TWIST_FOR[cid])
            twist = rng.choice(options)
            twist_text = TWISTS[twist]
        if cid == "too_few_steps":
            new = rng.choice([t for t in sorted(ph.STEPS) if t not in drawn])
            drawn = drawn + [new]
            st = ph.step(new)
            added = f"{st.asks} — {st.formula}"
            steps = [ph.step(t) for t in drawn]
            cand = {**cand, "txs": drawn, "drawn_txs": drawn, "_steps": steps,
                    "_plan": SimpleNamespace(steps=steps, constants=[], branches=())}
    if twist_text or added:
        # the design was planned for the old twist and formulas: the writer kept getting it, so a new twist or
        # an added formula was written on a plan that did not have it. The next write plans a new design.
        cand = {k: v for k, v in cand.items() if k != "_design"}
    traps = list(dict.fromkeys(tr.desc for x in drawn for tr in ph.step(x).traps))
    fb = refine.instructions(chosen, probs, twist_text=twist_text, added=added, traps=traps)
    bb.note("refine", mode="too_easy", probabilities=probs, chosen=chosen, twist=twist, added=added, feedback=fb)
    print(f"  [refine] too easy because: {', '.join(chosen)}"
          + (f"; twist now {twist}" if twist_text else "") + (f"; added formula {added}" if added else ""))
    return cand, twist, fb


def rebuild_result(item: dict):
    """The result of a parked question-first item, recomputed by running its program again."""
    from core.engine.base import EngineError
    q = item["qfirst"]
    run = sandbox.evaluate(q["code"], item.get("drawn_txs") or item["txs"], any_step=True, preset=q.get("preset"))
    if not run.get("ok"):
        raise EngineError(f"the program no longer runs: {run.get('error')}")
    if q.get("preset"):                          # a blank question: its values are the program's variables
        run["givens"] = [{"value": v, "quote": k} for k, v in q["preset"].items()]
    return make_result(run, q["asks"], q["unit"], q["twist"], q["code"])


def over_budget(cap) -> bool:
    """True (and says so) once this run has spent `cap` US dollars: no new draw or round starts.
    A question already being judged is finished first."""
    if cap is not None and models.SPEND.total_cost >= cap:
        print(f"  ✗ this run has spent ${models.SPEND.total_cost:.4f}, the cap is ${cap:.2f} "
              f"(--max-run-spend); stopping")
        return True
    return False


def run(adapter, coverage, bb, log, chapter=None, rng=None) -> dict:
    """Like flow.run, question first. Returns {"status": "accepted", "payload"} or
    {"status": "none"}; raises flow.Parked."""
    from core.pipeline import flow
    rng = rng or random.Random()
    cap = adapter.config.get("max_run_spend")
    for draw in range(1, MAX_DRAWS + 1):
        if over_budget(cap):
            break
        cand = best_draw(adapter, chapter, bb, log)
        if cand is None:
            print("  no formula sets left")
            break
        twist = None                             # the designer chooses it (a refinement may fix it later)
        print(f"\n╔═══ DRAW {draw}: txs {cand['txs']} ({', '.join(cand['chapters'])}); twist: the designer's choice ═══╗")
        for s in cand["_steps"]:
            print(f"    {s.tx}: {s.asks} [{s.formula}]")
        bb.start_chain({**cand, "twist": twist})
        if cand.get("_fit") is not None:
            bb.note("formula_fit", p=cand["_fit"])
        made = write_and_solve(adapter, cand, twist, bb, rng)
        if made is None or made == IMPOSSIBLE:
            log({"event": "question_failed" if made is None else "formulas_impossible", "chain": cand["edges"],
                 "txs": cand["txs"], "twist": bb.current["chain"].get("twist")})
            continue
        stem, run_, code, asks, unit, result, cand = made
        twist = cand.get("twist") or twist
        print(f"  [engine] answer {flow.answer_text(result)}; traps: {[t['id'] for t in result.traps]}")
        used_cases: set = set()                 # refinement cases already applied to this question
        while True:
            values = {g["quote"]: g["value"] for g in run_["givens"]}
            sig = dedup.signature(adapter.subject, cand["txs"], values)
            dup = dedup.duplicate_of(sig)
            if dup:
                print(f"  [dedup] same as accepted question {dup}")
                bb.note("duplicate", of=dup)
                decision = {"decision": "too_easy", "graded": [], "reason": f"duplicate of {dup}"}
            else:
                print("  [council] closed-book solves (cheaper members first)...")
                decision = flow.judge(adapter, cand, cand["_plan"], values, result, stem, bb, log)
            log({"event": decision["decision"], "chain": cand["edges"], "round": bb.current["rounds"],
                 "stem": stem, "answer": result.answer, "reason": decision.get("reason"), "twist": twist,
                 "council": [{k: g.get(k) for k in ("name", "final_answer", "answer_matches", "counts_as_solved",
                                                    "verdict", "failure_type")} for g in decision.get("graded", [])]})
            if decision["decision"] == "accept":
                return {"status": "accepted", "payload": {
                    "cand": cand, "plan": cand["_plan"], "values": values, "scenario": f"question-first ({twist})",
                    "result": result, "stem": stem, "decision": decision, "sig": sig, "solver_code": code}}
            if decision["decision"] == "drop":
                break
            if over_budget(cap):
                break
            if bb.current["rounds"] >= flow.MAX_ROUNDS:
                print(f"  ✗ {flow.MAX_ROUNDS} refinements used; drawing new formulas")
                log({"event": "rounds_exhausted", "chain": cand["edges"]})
                break
            bb.current["rounds"] += 1
            if decision["decision"] == "reword":
                fb = decision["feedback"] + " Keep the situation, the blanks and their ranges."
                bb.note("refine", mode="reword", feedback=fb)
                print("  [refine] unclear wording → the writer rewrites it")
            elif dup:
                fb = "These exact values are already an accepted question: choose a new situation and values."
                bb.note("refine", mode="duplicate", feedback=fb)
                print("  [refine] duplicate → the writer chooses new values")
            else:
                ref = refine_round(cand, twist, stem, decision["graded"], used_cases, rng, bb)
                if ref is None:
                    print("  ✗ every refinement case has been used; drawing new formulas")
                    log({"event": "refinement_exhausted", "chain": cand["edges"]})
                    break
                cand, twist, fb = ref
            made = write_and_solve(adapter, cand, twist, bb, rng,
                                   previous=previous_text(cand["_q"]) if cand.get("_q") else stem, feedback=fb)
            if made is None or made == IMPOSSIBLE:
                break
            stem, run_, code, asks, unit, result, cand = made
            print(f"  [engine] new answer {flow.answer_text(result)}")
    return {"status": "none"}
