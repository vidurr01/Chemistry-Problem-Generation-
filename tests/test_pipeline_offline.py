"""End-to-end pipeline runs with scripted model replies (no API calls, no cost).

Run:  python -m unittest tests.test_pipeline_offline
"""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import run_groundup_final as entry
from core import dedup, models
from core.pipeline import adapters, gate, queues

CHAIN = [1, 4]          # mass -> moles -> gas volume at 1 atm, 273 K (answer 2.24 L for 4.4 g CO2)


class FakeModels:
    """Scripted replies keyed on the role and on what the prompt asks for."""

    def __init__(self, council_answers, hint_answers=None, verdicts=None, refine_mode="reword", fail_council=False):
        self.council_answers = council_answers          # model slug -> final answer
        self.hint_answers = hint_answers or {}           # model slug -> answer after a hint
        self.verdicts = verdicts or {}                   # answer string -> verifier dict
        self.refine_mode = refine_mode
        self.fail_council = fail_council
        self.calls = []

    def __call__(self, role, model, system, user, **kw):
        self.calls.append(role)
        if role in ("generator", "refiner") and "invent a concrete" in user:
            return {"coherent": True, "scenario": "carbon dioxide gas",
                    "values": {"s0.mass": 4.4, "s0.molar_mass": 44}}
        if role in ("generator", "refiner") and "Write one JEE" in user:
            return {"stem": "4.4 g of CO2 (molar mass 44 g mol⁻¹) is collected. Taking the molar volume "
                            "at 1 atm and 273 K as 22.4 L, find the volume of the gas in L."}
        if role in ("generator", "refiner") and "too easy" in user:
            return {"mode": self.refine_mode, "feedback": "hide the molar volume cue"}
        if role in ("generator", "refiner") and "misread" in user:
            return {"hint": "The volume is asked at 1 atm and 273 K."}
        if role == "extractor":
            section = user.split("What does the question ask for?")[1].split("3) For each constant")[0]
            opts = dict(re.findall(r"^(\d+)\. (.+)$", section, re.M))
            asked = next(int(k) for k, v in opts.items() if v.startswith("volume of the gas"))
            n_const = user.count("molar volume of an ideal gas")
            return {"values": {"s0.mass": 4.4, "s0.molar_mass": 44}, "asked": asked,
                    "constants_stated": [True] * max(1, n_const)}
        if role == "council":
            if self.fail_council and model == models.LADDER[2][1]:
                raise RuntimeError("503 provider overloaded")
            hinted = "A teacher adds this hint" in user
            ans = (self.hint_answers if hinted else self.council_answers)[model]
            return {"working": f"n = 4.4/44 = 0.1 mol; V = ... = {ans}", "final_answer": ans, "unit": "L",
                    "objection": None}
        if role == "verifier":
            ans = re.search(r"STUDENT'S FINAL ANSWER: (\S+)", user).group(1)
            return self.verdicts.get(ans, {"verdict": "wrong", "failure_type": "genuine_difficulty",
                                           "failed_step": 2, "reasoning": "used the wrong molar volume"})
        if role == "solution_writer":
            return {"solution": "n = 0.1 mol; V = 0.1 × 22.4 = 2.24 L."}
        raise AssertionError(f"unexpected call: {role}")


class _Env:
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = entry.get_subject_config("physical")
        self.cfg = dict(cfg, output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))
        self.patches = [
            mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
            mock.patch.object(models, "key_is_set", lambda: True),
            mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
            mock.patch.object(queues, "_OUT", self.tmp),
            mock.patch("tools.results.promote", lambda *a, **k: 0),
            mock.patch.object(adapters.PhysicalAdapter, "candidates", self._fixed_candidates),
            mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
        ]
        for p in self.patches:
            p.start()
        # the dedup default argument was bound at import time
        self.dd = [mock.patch.object(dedup.duplicate_of, "__defaults__", (dedup.STORE,)),
                   mock.patch.object(dedup.record, "__defaults__", (dedup.STORE,))]
        for p in self.dd:
            p.start()

    def tearDown(self):
        for p in self.dd + self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _fixed_candidates(self_adapter, coverage, chapter=None, n=6, exclude=()):
        plan = self_adapter.plan(CHAIN)
        cand = {"edges": [f"e{t}" for t in CHAIN], "nodes": ["mass", "moles", "gas_volume"],
                "chapters": ["Stoichiometry"], "txs": CHAIN, "trap_ids": [], "weight": 1.0,
                "description": "", "_steps": plan.steps, "_plan": plan}
        return [] if tuple(cand["edges"]) in exclude else [cand]

    def _run(self, fake, kind="chains"):
        with mock.patch.object(models, "ask_json", fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "physical", "--seed", "1",
                                                "--kind", kind]):
            return entry.main()

    def _records(self):
        if not os.path.exists(self.cfg["output_file"]):
            return []
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            return json.load(f)



class FakeFactModels:
    """Fact questions: the generator copies the options; members answer with letters taken
    from the key that the engine stored (read back from the stem's TRUE/FALSE trace)."""

    def __init__(self, member_letters):
        self.member_letters = member_letters      # slug -> function(answer_letters) -> reply
        self.calls = []

    def __call__(self, role, model, system, user, **kw):
        self.calls.append(role)
        if role in ("generator", "refiner") and "multiple-choice question" in user:
            lead = user.split("copy this question sentence\nEXACTLY:\n")[1].split("\n")[0]
            opts = user.split("with their letters:\n")[1].split("\n\nDo not add")[0]
            return {"stem": f"Consider the following.\n{lead}\n{opts}"}
        if role in ("generator", "refiner") and "too easy" in user:
            return {"mode": "new_inputs", "feedback": "use other statements"}
        if role == "council":
            return {"working": "checked each statement", "final_answer": self.member_letters[model](self.key),
                    "unit": "", "objection": None}
        if role == "verifier":
            from core.engine.facts import letters_of
            ans = letters_of(re.search(r"STUDENT'S FINAL ANSWER: (.*)", user).group(1))
            return {"verdict": "correct"} if ans == self.key else \
                {"verdict": "wrong", "failure_type": "genuine_difficulty", "failed_step": 1}
        if role == "solution_writer":
            return {"solution": "Each statement checked."}
        raise AssertionError(f"unexpected call: {role}")


class PipelineOffline(_Env, unittest.TestCase):
    """Ladder order: models.LADDER = [llama-3.3-70b, glm-5.3-flash, gpt-6-luna]."""

    def test_accepts_and_labels_by_first_solver(self):
        slugs = [s for _, s in models.LADDER]
        fake = FakeModels(
            council_answers={slugs[0]: "2.45", slugs[1]: "2.24", slugs[2]: "2.24"},
            hint_answers={slugs[0]: "2.24"},
            verdicts={"2.24": {"verdict": "correct"}})
        self.assertEqual(self._run(fake), 0)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["answer"], 2.24)
        self.assertEqual((r["difficulty_label"], r["ladder_first_solver"]), ("advanced", models.LADDER[1][0]))
        self.assertEqual((r["council_n_called"], r["council_skipped"]), (2, [models.LADDER[2][0]]))
        self.assertEqual(r["tags"]["knowledge"], "closed_book")
        self.assertEqual(len(r["hint_tests"]), 1)                       # only the failed step
        self.assertEqual(fake.calls.count("council"), 2 + 1)            # two steps + one hint re-solve
        self.assertTrue(r["solution"])
        self.assertTrue(os.path.exists(dedup.STORE))

    def test_confirmed_slip_at_the_bottom_counts_as_solved(self):
        slugs = [s for _, s in models.LADDER]
        fake = FakeModels(
            council_answers={slugs[0]: "22.4", slugs[1]: "2.24", slugs[2]: "2.24"},
            verdicts={"2.24": {"verdict": "correct"},
                      "22.4": {"verdict": "wrong", "failure_type": "slip", "member_expression": "0.1*22.4"}},
            refine_mode="reword")
        self.assertEqual(self._run(fake), 0)        # the bottom step solves (slip confirmed) -> too easy -> dropped
        self.assertEqual(self._records(), [])
        self.assertEqual(fake.calls.count("council"), 1 * 4)

    def test_too_easy_until_rounds_run_out(self):
        slugs = [s for _, s in models.LADDER]
        fake = FakeModels(council_answers={s: "2.24" for s in slugs}, verdicts={"2.24": {"verdict": "correct"}})
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(self._records(), [])
        # original + 3 refinements; the bottom step solves each time, so no step above it is called
        self.assertEqual(fake.calls.count("council"), 1 * 4)
        # each too-easy round: the refiner chooses and rewrites; the first draft is the generator's
        self.assertEqual(fake.calls.count("refiner"), 3 * 2)
        self.assertEqual(fake.calls.count("generator"), 2)              # inputs + first stem

    def test_ladder_climbs_to_the_top(self):
        slugs = [s for _, s in models.LADDER]
        fake = FakeModels(
            council_answers={slugs[0]: "2.45", slugs[1]: "1.12", slugs[2]: "2.24"},
            hint_answers={slugs[0]: "2.24", slugs[1]: "2.24"},
            verdicts={"2.24": {"verdict": "correct"},
                      "1.12": {"verdict": "wrong", "failure_type": "slip", "member_expression": "0.05*22.4"}})
        self.assertEqual(self._run(fake), 0)
        r = self._records()[0]
        self.assertEqual((r["difficulty_label"], r["council_n_called"], r["council_skipped"]), ("hard_advanced", 3, []))
        by = {c["name"]: c for c in r["council"]}
        self.assertFalse(by[models.LADDER[1][0]]["slip_confirmed"])     # 0.05*22.4 ≠ 2.24
        self.assertEqual(len(r["hint_tests"]), 2)

    def test_no_step_solves_is_frontier(self):
        slugs = [s for _, s in models.LADDER]
        fake = FakeModels(
            council_answers={s: "2.45" for s in slugs},
            hint_answers={s: "2.24" for s in slugs},
            verdicts={"2.24": {"verdict": "correct"}})
        self.assertEqual(self._run(fake), 0)
        r = self._records()[0]
        self.assertEqual((r["difficulty_label"], r["ladder_first_solver"], r["council_n_solved"]), ("frontier", None, 0))

    def test_council_failure_parks_then_recheck_accepts(self):
        slugs = [s for _, s in models.LADDER]
        answers = {slugs[0]: "2.45", slugs[1]: "2.45", slugs[2]: "2.24"}
        verdicts = {"2.24": {"verdict": "correct"}}
        # the top step (called because both lower steps failed) is unreachable -> parked
        self.assertEqual(self._run(FakeModels(answers, answers, verdicts, fail_council=True)), entry.EXIT_COUNCIL_FAILED)
        with open(self.cfg["pending_file"], encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)
        self.assertEqual(self._run(FakeModels(answers, {slugs[0]: "2.24", slugs[1]: "2.24"}, verdicts)), 0)
        self.assertEqual(len(self._records()), 1)
        with open(self.cfg["pending_file"], encoding="utf-8") as f:
            self.assertEqual(json.load(f), [])

    def test_harder_question_prompts(self):
        from core.pipeline import stages
        seen = {}
        def capture(role, model, system, user, **kw):
            seen[role] = user
            return {"coherent": True, "values": {}, "stem": "x"}
        with mock.patch.object(models, "ask_json", capture):
            stages.propose_inputs("Physical Chemistry", "chain", [], traps=["uses log₁₀ without 2.303"])
            self.assertIn("uses log₁₀ without 2.303", seen["generator"])
            self.assertIn("shortcut or approximation would mislead", seen["generator"])
            stages.write_stem("Physical Chemistry", "s", "chain", [], {}, [], "k", "s⁻¹", [])
            self.assertIn("never name the law, equation or method", seen["generator"])


class FactQuestions(_Env, unittest.TestCase):
    def _fixed_candidates(self, *a, **k):          # facts use the real candidate builder
        raise AssertionError("not used")

    def setUp(self):
        super().setUp()
        self.patches[5].stop()                      # restore the real PhysicalAdapter.candidates (unused here)
        from core.pipeline import adapters as ad
        real = ad.PhysicalFactsAdapter.result

        def capture(fq, _real=real):
            self.fake.key = fq.answer
            return _real(fq)
        self.cap = mock.patch.object(ad.PhysicalFactsAdapter, "result", staticmethod(capture))
        self.cap.start()

    def tearDown(self):
        self.cap.stop()
        self.patches[5].start()
        super().tearDown()

    def test_fact_question_accepted_with_letters(self):
        slugs = [s for _, s in models.LADDER]
        wrong = lambda key: "ABCD".replace(key[0], "")[0]          # a single wrong letter
        # bottom step wrong, middle step right -> accepted, labelled "advanced"
        self.fake = FakeFactModels({slugs[0]: wrong, slugs[1]: lambda key: " and ".join(key), slugs[2]: wrong})
        self.assertEqual(self._run(self.fake, kind="facts"), 0)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["question_kind"], "fact")
        self.assertEqual(len(r["options"]), 4)
        self.assertEqual((r["council_n_solved"], r["difficulty_label"]), (1, "advanced"))
        self.assertNotIn("extractor", self.fake.calls)                  # the fact gate is code only


class Grading(unittest.TestCase):
    """Smoke test 1: 'Yes' to 'determine whether a precipitate forms' was graded as a failure."""
    def _res(self, answer, kind):
        from types import SimpleNamespace
        return SimpleNamespace(answer=answer, kind=kind)

    def test_text_answers_matched_by_code(self):
        from core.pipeline import flow
        g = flow._grade(self._res("precipitate forms", "text"), {"final_answer": "Yes"}, {"verdict": "correct"})
        self.assertEqual((g["answer_matches"], g["counts_as_solved"], g["match_by"]), (True, True, "code"))
        g = flow._grade(self._res("forward", "text"), {"final_answer": "backward"},
                        {"verdict": "correct", "answer_equivalent": True})     # code decides, not the verifier
        self.assertEqual((g["answer_matches"], g["match_by"]), (False, "code"))

    def test_verifier_field_decides_what_code_cannot(self):
        from core.pipeline import flow
        r = self._res("ion 1 precipitates first", "text")
        g = flow._grade(r, {"final_answer": "Cl⁻ first"}, {"verdict": "correct", "answer_equivalent": True})
        self.assertEqual((g["answer_matches"], g["counts_as_solved"], g["match_by"]), (True, True, "verifier"))
        g = flow._grade(r, {"final_answer": "Br⁻ first"}, {"verdict": "wrong", "answer_equivalent": False})
        self.assertEqual((g["answer_matches"], g["match_by"]), (False, "verifier"))

    def test_text_answer_shapes(self):
        from core.answers import text_answers_match as m
        cases = [
            ("precipitate forms", "Yes, AgCl precipitates", True), ("precipitate forms", "No", False),
            ("no precipitate", "No precipitate will form since Q < Ksp", True),
            ("forward", "shifts to the right", True), ("forward", "towards the reactants", False),
            ("no shift", "no effect on the equilibrium", True), ("backward", "reverse direction", True),
            ("isotopes", "They are isotopes", True), ("isobars", "isotones", False),
            ("Th-234", "²³⁴₉₀Th", True), ("Th-234", "234Th", True), ("Th-234", "Pa-234", False),
            ("CH2O", "CH₂O", True), ("CH2O", "C6H12O6", False), ("AgCl", "AgCl(s)", True),
            ("1s2 2s2 2p6", "1s²2s²2p⁶", True), ("3d", "3d orbital", True), ("3d", "4f", False),
            ("not allowed", "Not possible: l must be less than n", True),
            ("2H2 + O2 -> 2H2O", "4H2 + 2O2 -> 4H2O", True), ("2H2 + O2 -> 2H2O", "H2 + O2 -> H2O2", False),
        ]
        for engine, member, want in cases:
            self.assertEqual(m(engine, member), want, (engine, member))
        self.assertIsNone(m("ion 1 precipitates first", "chloride first"))
        self.assertTrue(m("at equilibrium", "The system is already at equilibrium"))
        self.assertTrue(m("at equilibrium", "no net reaction"))
        self.assertIsNone(m("forward", "the system at equilibrium shifts forward"))     # ambiguous -> verifier
        self.assertFalse(m("precipitate forms", "No precipitate forms"))

    def test_every_text_step_has_an_answer_format(self):
        from types import SimpleNamespace
        from core.engine.physical import ANSWER_FORMATS, STEPS
        from core.pipeline.adapters import PhysicalAdapter
        text_steps = {tx for tx, st in STEPS.items() if st.kind == "text"}
        self.assertEqual(text_steps - set(ANSWER_FORMATS), set())
        fmt = PhysicalAdapter.answer_format(SimpleNamespace(answer="forward", trace=[{"tx": 161}]))
        self.assertEqual(fmt, "Answer with exactly one of: forward, backward, no shift.")
        self.assertIsNone(PhysicalAdapter.answer_format(SimpleNamespace(answer=2.24, trace=[{"tx": 4}])))

    def test_matching_answer_with_a_slip_on_the_way_counts(self):
        """Run 4: 29.52 L against 29.79 L (inside tolerance) was labelled a slip and not counted."""
        from core.pipeline import flow
        r = self._res(29.79, "positive")
        g = flow._grade(r, {"final_answer": "29.52"}, {"verdict": "wrong", "failure_type": "slip"})
        self.assertTrue(g["counts_as_solved"])
        g = flow._grade(r, {"final_answer": "29.79"}, {"verdict": "right_answer_wrong_reasoning"})
        self.assertFalse(g["counts_as_solved"])

    def test_numbers_stay_code_matched(self):
        from core.pipeline import flow
        g = flow._grade(self._res(2.24, "positive"), {"final_answer": "3.1"}, {"verdict": "correct"})
        self.assertFalse(g["answer_matches"])
        self.assertEqual(g["match_by"], "code")

    def test_value_formatting(self):
        from core.pipeline.stages import _fmt_value
        self.assertEqual(_fmt_value(4e-05), "4 × 10⁻⁵")
        self.assertEqual(_fmt_value(1.725e-10), "1.725 × 10⁻¹⁰")
        self.assertEqual(_fmt_value(0.0591), "0.0591")
        self.assertEqual(_fmt_value(100.0), "100.0")


class SmokeTest3(unittest.TestCase):
    """Smoke test 3 accepted a question 2/3 members really solved: a blank reply counted as a
    failure, and an answer off only by rounding e^(-34.1) counted as wrong."""

    def setUp(self):
        self.ad = adapters.PhysicalAdapter(entry.get_subject_config("physical"))

    def test_tolerance_widens_only_when_rounding_moves_the_answer(self):
        from core import answers
        r = self.ad.compute(self.ad.plan([205, 213, 215]), {
            "s0.initial_concentration": 0.06, "s0.concentration": 0.015, "s0.time": 2400.0,
            "s1.T1": 430.0, "s1.k2": 0.00402, "s1.T2": 450.0, "s2.T": 550.0})
        self.assertGreater(r.tolerance, 0.015)
        self.assertLessEqual(r.tolerance, 0.10)
        self.assertTrue(answers.matches(r.answer, "1.51e-15", r.kind, r.tolerance))
        for t in r.traps:                                   # no trap inside the tolerance
            self.assertFalse(answers.matches(r.answer, str(t["wrong_answer"]), r.kind, r.tolerance))
        r2 = self.ad.compute(self.ad.plan(CHAIN), {"s0.mass": 4.4, "s0.molar_mass": 44})
        self.assertEqual(r2.tolerance, 0.01)

    def test_slip_expression_chain(self):
        from core.pipeline import flow
        v = flow._eval_expression("exp(-(8.314*1.940/1.0336e-4)/(8.314*550)) = exp(-156070/4572.7) ≈ exp(-34.13)")
        self.assertAlmostEqual(v / 1.5109e-15, 1.0, places=3)
        self.assertIsNone(flow._eval_expression("the student used the wrong value"))

    def test_blank_council_reply_is_asked_again(self):
        from core.pipeline import stages
        replies = iter([{"working": "", "final_answer": None},
                        {"working": "k = ...", "final_answer": "2.24", "unit": "L"}])
        with mock.patch.object(models, "ask_json", lambda *a, **k: next(replies)):
            out = stages._solve("x/y", "stem")
        self.assertEqual(out["final_answer"], "2.24")
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"working": "", "final_answer": None}):
            with self.assertRaises(ValueError):
                stages._solve("x/y", "stem")

    def test_fragile_answer_asks_the_previous_step(self):
        from core.pipeline import flow
        from core.blackboard import Blackboard
        plan = self.ad.plan([205, 213, 215])
        values = {"s0.initial_concentration": 0.06, "s0.concentration": 0.015, "s0.time": 2400.0,
                  "s1.T1": 430.0, "s1.k2": 0.00402, "s1.T2": 450.0, "s2.T": 550.0}
        cand = {"edges": ["a", "b", "c"], "nodes": ["rate_law", "k", "Ea", "fraction"], "chapters": ["Kinetics"],
                "txs": [205, 213, 215], "trap_ids": [], "weight": 1.0, "description": "", "_plan": plan,
                "_steps": plan.steps}
        bb = Blackboard("physical")
        bb.start_chain(cand)
        cand2, vals2, r2 = flow._stable_ask(self.ad, cand, values, self.ad.compute(plan, values), bb)
        self.assertEqual(cand2["txs"], [205, 213])
        self.assertEqual(r2.trace[-1]["dst"], "activation_energy")
        self.assertAlmostEqual(r2.answer, 156.1, places=0)
        self.assertNotIn("s2.T", vals2)
        self.assertLessEqual(r2.tolerance, flow.FRAGILE_TOL)
        self.assertEqual(len(cand2["edges"]), 2)
        self.assertEqual(len(cand2["nodes"]), 3)

    def test_shared_trap_descriptions_name_the_step(self):
        r = self.ad.compute(self.ad.plan([205, 213, 215]), {
            "s0.initial_concentration": 0.06, "s0.concentration": 0.015, "s0.time": 2400.0,
            "s1.T1": 430.0, "s1.k2": 0.00402, "s1.T2": 450.0, "s2.T": 550.0})
        descs = [t["desc"] for t in r.traps]
        self.assertEqual(len(descs), len(set(descs)))
        self.assertTrue(any("activation energy" in d for d in descs))

    def test_solution_structure_is_flattened(self):
        from core.pipeline.stages import _solution_text
        txt = _solution_text({"step1": {"description": "Find k.", "calculation": "k = ln4/2400"},
                              "final_answer": "1.5e-15"})
        self.assertEqual(txt.splitlines()[0], "Step 1:")
        self.assertIn("k = ln4/2400", txt)
        self.assertTrue(txt.endswith("Final answer: 1.5e-15"))
        self.assertEqual(_solution_text(" plain text "), "plain text")

    def test_answer_under_another_key_is_read(self):
        """Qwen3.8-Flash replied {"answer": 100.1} with its working only in the reasoning trace."""
        from core.pipeline import stages
        with mock.patch.object(models, "ask_json",
                               lambda *a, **k: {"answer": 100.1, "_reasoning": "k = ... so 100.1"}):
            out = stages._solve("qwen/qwen3.8-flash", "stem")
        self.assertEqual(out["final_answer"], 100.1)
        self.assertIn("reasoning trace", out["working"])
        with mock.patch.object(models, "ask_json",
                               lambda *a, **k: {"solution": "steps", "result": "2.24", "unit": "L"}):
            out = stages._solve("x/y", "stem")
        self.assertEqual((out["final_answer"], out["working"]), ("2.24", "steps"))

    def test_json_with_latex_backslashes(self):
        from core.llm import parse_json
        self.assertEqual(parse_json(r'x {"stem": "\Delta G for \ce{H2O}", "n": 1} y'),
                         {"stem": r"\Delta G for \ce{H2O}", "n": 1})
        self.assertEqual(parse_json(r'{"q": "keep \"this\" and \\ that"}')["q"], 'keep "this" and \\ that')


class GateCompare(unittest.TestCase):
    SPEC = [{"key": "s0.mass", "desc": "mass", "unit": "g", "kind": "positive"},
            {"key": "s0.eq", "desc": "equation", "unit": "", "kind": "text"}]
    VALUES = {"s0.mass": 4.4, "s0.eq": "2H2 + O2 -> 2H2O"}

    def test_exact_match_passes(self):
        g = gate.compare(self.SPEC, self.VALUES, {"values": {"s0.mass": "4.40", "s0.eq": "2 H2 + O2 → 2 H2O"},
                                                  "asked": 2, "constants_stated": [True]}, 2, ["c"])
        self.assertTrue(g["ok"], g)

    def test_wrong_value_missing_constant_and_wrong_question(self):
        g = gate.compare(self.SPEC, self.VALUES, {"values": {"s0.mass": 4.5, "s0.eq": "H2 + O2 -> H2O"},
                                                  "asked": 1, "constants_stated": [False]}, 2, ["c"])
        self.assertFalse(g["ok"])
        self.assertEqual(len(g["mismatches"]), 4)

    def test_unreadable(self):
        self.assertTrue(gate.compare(self.SPEC, self.VALUES, {"asked": 1}, 1, [])["unreadable"])


if __name__ == "__main__":
    unittest.main()
