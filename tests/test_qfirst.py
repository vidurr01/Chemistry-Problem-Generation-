"""Question-first flow (core/pipeline/qfirst.py): random formulas, the solve() sandbox, the checks
and full runs with scripted model
replies (no API calls, no cost).

Run:  python -m unittest tests.test_qfirst
"""

import json
import math
import os
import random
import re
import shutil
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import run_groundup_final as entry
from core import dedup, models
from core.engine import sandbox
from core.engine.base import links, plan_chain, roles_consistent
from core.engine import physical as ph
from core.pipeline import adapters, qf_checks, qf_draw, qfirst, queues

CHAIN = [117, 357, 130]        # isothermal reversible work -> heat -> ΔS of the surroundings
STEM = ("Two 2.00 mol samples of argon (Ar), each at 300 K and 5.00 L, expand isothermally and reversibly, "
        "one to 12.0 L and the other to 20.0 L. By how much does the entropy change of the surroundings for the "
        "first expansion exceed that for the second? (Given: R = 8.314 J K⁻¹ mol⁻¹)")
CODE = '''
def solve():
    n = given(2.00, "Two 2.00 mol samples")
    T = given(300, "at 300 K")
    V1 = given(5.00, "and 5.00 L")
    Va = given(12.0, "one to 12.0 L")
    Vb = given(20.0, "the other to 20.0 L")
    def dS(V2):
        w = step_117(n=n, T=T, V1=V1, V2=V2)
        q = step_357(work=w["work"])
        return step_130(heat=q["heat"], T=w["T"])["entropy_change"]
    return dS(Va) - dS(Vb)
'''
ANSWER = 2.00 * 8.314 * 0.5108256         # nR ln(20/12) = 8.494 J K⁻¹
# drawn 117, 130 and 1 (n = m/M); the program also calls 357 (q = −w), which is not drawn
STEM_MASS = STEM.replace("Two 2.00 mol samples of argon (Ar)", "Two 79.90 g samples of argon (Ar)").replace(
    "(Given: R", "(Given: molar mass of Ar = 39.95 g mol⁻¹; R")
CODE_MASS = CODE.replace('    n = given(2.00, "Two 2.00 mol samples")',
                         '    n = step_1(mass=given(79.90, "Two 79.90 g samples"), '
                         'molar_mass=given(39.95, "molar mass of Ar = 39.95 g mol⁻¹"))["moles"]')


class Sandbox(unittest.TestCase):
    def test_runs_and_reports(self):
        r = sandbox.evaluate(CODE, CHAIN)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertAlmostEqual(r["answer"], ANSWER, delta=0.01)
        self.assertEqual(r["depth"], 3)
        self.assertEqual(r["unused_steps"], [])
        self.assertEqual(len(r["givens"]), 5)
        self.assertEqual(len(r["trace"]), 6)                       # each step twice (two samples)
        self.assertGreaterEqual(len(r["traps"]), 2)
        self.assertIn("R = 8.314 J K⁻¹ mol⁻¹", r["constants"])

    def test_inverse_with_solve_for_records_only_the_final_evaluation(self):
        code = '''
def solve():
    target = given(-11.5, "-11.5")
    def f(V2):
        w = step_117(n=2.0, T=300, V1=5.0, V2=V2)
        q = step_357(work=w["work"])
        return step_130(heat=q["heat"], T=w["T"])["entropy_change"] - target
    return solve_for(f, 5.0001, 500)
'''
        r = sandbox.evaluate(code, CHAIN)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertAlmostEqual(r["answer"], 5.0 * 2.718281828 ** (11.5 / (2 * 8.314)), delta=0.01)
        self.assertEqual(len(r["trace"]), 3)

    def test_a_step_whose_result_is_ignored_is_found(self):
        code = CODE.replace("    return dS(Va) - dS(Vb)",
                            "    step_130(heat=100.0, T=T)\n"
                            "    w1 = step_117(n=n, T=T, V1=V1, V2=Va)['work']\n"
                            "    w2 = step_357(work=step_117(n=n, T=T, V1=V1, V2=Vb)['work'])['heat']\n"
                            "    return w1 + w2")
        r = sandbox.evaluate(code, CHAIN)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["irrelevant_steps"], [130])
        self.assertEqual(sandbox.evaluate(CODE, CHAIN)["irrelevant_steps"], [])

    def test_any_graph_formula_with_any_step_but_nothing_else(self):
        code = CODE.replace('    n = given(2.00, "Two 2.00 mol samples")',
                            '    n = step_1(mass=given(79.90, "79.90 g"), molar_mass=39.95)["moles"]')
        self.assertFalse(sandbox.evaluate(code, CHAIN)["ok"])                  # step_1 is not drawn
        r = sandbox.evaluate(code, CHAIN, any_step=True)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["called_txs"], [1, 117, 357, 130])
        self.assertFalse(sandbox.evaluate("def solve():\n    return step_99999()", CHAIN, any_step=True)["ok"])

    def test_forbidden_code_never_runs(self):
        for code in ("import os\ndef solve():\n    return 1",
                     "def solve():\n    return ().__class__",
                     "def solve():\n    return open('x')",
                     "def solve():\n    return step_1(mass=1, molar_mass=1)['moles']",   # not a chain step
                     "x = 1"):
            r = sandbox.evaluate(code, CHAIN)
            self.assertFalse(r["ok"], code)

    def test_interpreter_internals_are_unreachable(self):
        # a generator's frame led to the sandbox module's globals and builtins.open (2026-11-18)
        escapes = (
            "def solve():\n    g = (g.gi_frame.f_back.f_back.f_globals for _ in [1])\n"
            "    return float(len(list(g)[0]['builtins'].open('README.md').read()))",
            "def solve():\n    try:\n        1 / 0\n    except Exception as e:\n        return e.tb_frame",
            "def solve():\n    f = lambda: 1\n    return f.co_consts",
            "def solve():\n    return float(len('{0.__globals__}'.format(given)))",
            "def solve():\n    return float(len(str.format_map('{x}', {'x': 1})))",
        )
        for code in escapes:
            self.assertTrue(sandbox.check_code(code, CHAIN), code)
            r = sandbox.evaluate(code, CHAIN)
            self.assertFalse(r["ok"], code)
            self.assertIn("is not allowed", r["error"], code)
        # ordinary arithmetic and math attributes still pass
        self.assertEqual(sandbox.check_code("def solve():\n    return math.fabs(math.floor(-2.5))", CHAIN), [])

    def test_timeout(self):
        r = sandbox.evaluate("def solve():\n    while True:\n        pass", CHAIN, timeout=3)
        self.assertFalse(r["ok"])
        self.assertIn("did not finish", r["error"])

    def test_a_step_feeding_a_discrete_answer_still_matters(self):
        # coordination number from a radius ratio: 0.1 % changes nothing, a factor of 2 does
        code = """
def solve():
    r_minus = given(220, "220 pm")
    m = step_1(mass=given(66.45, "66.45 g"), molar_mass=given(132.9, "132.9 g"))["moles"]
    r_plus = m * 334.0
    return step_278(cation_radius=r_plus, anion_radius=r_minus)["coordination_number"]
"""
        r = sandbox.evaluate(code, [1, 278])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["irrelevant_steps"], [])

    def test_solve_for_finds_the_root_outside_a_poor_bracket(self):
        code = CODE.replace("    return dS(Va) - dS(Vb)",
                            "    target = given(-11.5, \"-11.5\")\n"
                            "    return solve_for(lambda v: dS(v) - target, 600, 900)")   # root ≈ 10 L, outside
        stem = STEM + " -11.5"
        r = sandbox.evaluate(code, CHAIN)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertAlmostEqual(r["answer"], 5.0 * 2.718281828 ** (11.5 / (2 * 8.314)), delta=0.05)

    def test_impossible_value_is_explained_to_the_writer(self):
        text = qfirst.explain("step_41: must be between 0 and 100, got 72264.0")
        self.assertIn("data are inconsistent", text)
        self.assertEqual(qfirst.explain("the program runs too long"), "the program runs too long")
        unused = qfirst.explain("the program never calls step_1; the question states 912 but the program never takes it")
        self.assertIn("does not need the formula 'amount (in mol) of the compound: n = m / M'", unused)
        self.assertIn("the question states 912, which no formula uses: remove that number", unused)
        self.assertIn("'packing fraction",
                      qfirst.explain("the result of 'packing fraction' does not change the answer", [275, 273]))

    def test_formula_limits_reach_the_designer_and_writer(self):
        text = qfirst.formulas_text([ph.step(54)])
        self.assertIn("ONLY for these cases", text)
        self.assertIn("MnO2 with concentrated HCl", text)

    def test_a_variable_named_like_a_step_is_allowed(self):
        code = CODE.replace("    return dS(Va) - dS(Vb)", "    step_117_result = dS(Va) - dS(Vb)\n    return step_117_result")
        self.assertTrue(sandbox.evaluate(code, CHAIN)["ok"])
        self.assertFalse(sandbox.evaluate("def solve():\n    return step_1(mass=1, molar_mass=1)['moles']", CHAIN)["ok"])

    def test_an_impossible_result_names_the_units(self):
        code = ("def solve():\n    return step_41(equivalents=25.0, back_titrated_equivalents=5.0, "
                "equivalent_mass=60.0, sample_mass=1.66)['percent_purity']")      # meq passed as eq
        r = sandbox.evaluate(code, [41])
        self.assertFalse(r["ok"])
        self.assertIn("equivalents in eq", r["error"])
        self.assertIn("meq, not eq", r["error"])

    def test_positional_call_is_explained(self):
        r = sandbox.evaluate("def solve():\n    return step_117(1, 300, 1, 2)['work']", CHAIN)
        self.assertIn("keyword arguments only", r["error"])
        self.assertIn("step_117(n=..., T=..., V1=..., V2=...)", r["error"])

    def test_step_input_errors_go_back_to_the_coder(self):
        r = sandbox.evaluate("def solve():\n    return step_117(n=1, T=300, V1=1)['work']", CHAIN)
        self.assertIn("missing inputs ['V2']", r["error"])
        r = sandbox.evaluate("def solve():\n    return step_117(n=1, T=300, V1=1, V2=2, P=1)['work']", CHAIN)
        self.assertIn("unknown inputs", r["error"])

    def test_step_code_is_the_engines_own(self):
        src = sandbox.step_source(119)
        self.assertIn("def _adiabatic_rev(v):", src)
        self.assertIn("Step(tx=119", src)
        self.assertNotIn("_adiabatic_rev_trap(v)", src)                 # the trap's code is left out

    def test_library_doc_names_inputs_and_outputs(self):
        doc = sandbox.library_doc([ph.step(t) for t in CHAIN], list(ph.STEPS.values()))
        self.assertIn("step_117(...)", doc)
        self.assertIn("V2: final volume [L", doc)
        self.assertIn("'entropy_change'", doc)


class Checks(unittest.TestCase):
    def setUp(self):
        self.run = sandbox.evaluate(CODE, CHAIN)

    def test_clean_question_passes(self):
        self.assertEqual(qfirst.question_problems(STEM, self.run, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"]), [])

    def test_built_numbers_skip_the_solvers_formula_and_trap_checks(self):
        # numbers built by the engine: its number program already checked both
        lazy = dict(self.run, irrelevant_steps=list(CHAIN), traps=[])
        self.assertTrue(qfirst.question_problems(STEM, lazy, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"]))
        self.assertEqual(qfirst.question_problems(STEM, lazy, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"], built=True), [])

    def test_stated_intermediate_goes_to_the_writer(self):
        stem = STEM.replace("first expansion", "first expansion (in which the gas absorbs 4367 J)")
        probs = qfirst.question_problems(stem, self.run, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"])
        self.assertTrue(any("result the solution has to compute" in p for p in probs))

    def test_missing_constant_and_a_formula_that_does_not_matter(self):
        probs = qfirst.question_problems(STEM.replace("8.314", "8.3"), dict(self.run, irrelevant_steps=[130]),
                                         CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"])
        self.assertTrue(any("does not change the answer" in p for p in probs))
        self.assertTrue(any("state this constant" in p for p in probs))

    def test_past_question_is_not_new(self):
        past = ("On dissolving 0.5 g of a non-volatile non-ionic solute to 39 g of benzene, its vapour pressure "
                "decreases from 650 mm Hg to 640 mm Hg. The depression of freezing point of benzene (in K) upon "
                "addition of the solute is")
        examples = [{"id": "2019P1_Chem_Q14", "text": past}, {"id": "other", "text": STEM}]
        self.assertIn("2019P1_Chem_Q14", qfirst.too_close_to_past(past, [], examples[:1]))
        self.assertIsNone(qfirst.too_close_to_past(STEM, [2.0, 300, 5.0, 12.0, 20.0], examples[:1]))
        self.assertIsNone(qfirst.too_close_to_past(past, [], []))           # only the examples shown count
        copied = "Dissolving 0.732 g of urea in 41.63 g of water at 23.76 °C ..."
        self.assertIn("reuses 3 values", qfirst.too_close_to_past(
            copied, [0.732, 41.63, 23.76], [{"id": "ex", "text": "0.732 g, 41.63 g and 23.76 mm Hg"}]))

    def test_numbers_are_read_as_an_exam_writes_them(self):
        self.assertEqual(qfirst.stated_numbers("4.2 × 10⁻⁵ M, −3.1 kJ, H2O, CO₂, 1.5e-3"),
                         [4.2e-05, -3.1, 0.0015])

    def test_every_twist_has_examples(self):
        for t in qfirst.TWISTS:
            self.assertGreaterEqual(len(qfirst.exemplars(t, random.Random(0))), 2, t)


class RandomChains(unittest.TestCase):
    def test_chains_are_3_to_5_linked_steps_drawn_uniformly(self):
        a = adapters.PhysicalAdapter(entry.get_subject_config("physical"), random.Random(3))
        chains = a.all_chains()
        self.assertGreater(len(chains), 1000)
        for txs in random.Random(0).sample(chains, 200):
            st = [ph.step(t) for t in txs]
            self.assertTrue(3 <= len(st) <= 5 and len(set(txs)) == len(txs))
            self.assertTrue(all(x.dst == y.src and links(x, y, ph.BRIDGES) for x, y in zip(st, st[1:])))
            self.assertTrue(roles_consistent(st))
            plan_chain(st)
        c = a.random_chain()
        self.assertIn(tuple(c["txs"]), set(chains))
        self.assertIsNone(a.random_chain(exclude={tuple(a.edge_of_tx[t]["id"] for t in txs) for txs in chains}))


class RandomFormulas(unittest.TestCase):
    def test_formula_count_connected_steps(self):
        a = adapters.PhysicalAdapter(entry.get_subject_config("physical"), random.Random(5))
        seen, linked = set(), 0
        lo, hi = adapters.FORMULAS_MIN, adapters.FORMULAS_MAX
        for _ in range(300):
            c = a.random_formulas()
            self.assertTrue(lo <= len(c["txs"]) <= hi and len(set(c["txs"])) == len(c["txs"]))
            self.assertEqual([s.tx for s in c["_plan"].steps], c["txs"])
            seen |= set(c["txs"])
            st = c["_steps"]
            linked += all(x.dst == y.src for x, y in zip(st, st[1:]))
            q = lambda t: {ph.step(t).src, ph.step(t).dst}
            for i, t in enumerate(c["txs"][1:], 1):            # each shares a quantity with an earlier one
                self.assertTrue(q(t) & set().union(*(q(x) for x in c["txs"][:i])), c["txs"])
        self.assertGreater(len(seen), 200)                 # of 311: the first formula comes from anywhere
        self.assertLess(linked, 100)                       # no chain condition (two formulas sharing a quantity
                                                           # often line up by chance: 52 of 300)
        c = a.random_formulas(chapter="Solid State")
        self.assertTrue(all(ph._domain(t) == "Solid State" for t in c["txs"]))
        self.assertIsNone(a.random_formulas(chapter="no such chapter"))


class Refinement(unittest.TestCase):
    """refine.py: Jev decides why a question was easy; code picks and applies the cases."""

    def _cand(self, txs=CHAIN):
        steps = [ph.step(t) for t in txs]
        return {"edges": ["e"], "nodes": [], "chapters": [], "txs": list(txs), "trap_ids": [],
                "_steps": steps, "_plan": SimpleNamespace(steps=steps, constants=[], branches=())}

    def _bb(self):
        from core.blackboard import Blackboard
        bb = Blackboard("physical")
        bb.start_chain({"edges": ["e"], "txs": CHAIN})
        return bb

    def test_pick_takes_the_likeliest_unused_case(self):
        from core.pipeline import refine
        probs = {c: {"p": 0.1, "evidence": ""} for c in refine.CASES}
        probs.update({"cue_word": {"p": 0.9, "evidence": ""}, "ready_data": {"p": 0.8, "evidence": ""},
                      "trivial_units": {"p": 0.7, "evidence": ""}})
        self.assertEqual(refine.pick(probs, set()), ["cue_word"])
        self.assertEqual(refine.pick(probs, {"cue_word"}), ["ready_data"])
        low = refine.pick(probs, {"cue_word", "ready_data", "trivial_units"})
        self.assertEqual(len(low), 1)                                  # none ≥ 0.6: the single likeliest
        self.assertEqual(refine.pick({}, set(refine.CASES)), [])         # nothing left
        # Jev's own choice is applied even when the probabilities rank another case higher (it was logged as
        # "Jev's pick" while the other case was applied)
        marked = {**probs, "trivial_units": {"p": 0.7, "evidence": "", "chosen": True}}
        self.assertEqual(refine.pick(marked, set()), ["trivial_units"])
        self.assertEqual(refine.pick(marked, {"trivial_units"}), ["cue_word"])   # used: back to the likeliest

    def test_jev_decides_and_the_writer_gets_each_cases_instruction(self):
        jev = {"cue_word": 0.92, "plugin_order": 0.81, "ready_data": 0.2}
        with mock.patch("core.pipeline.refine.jev_choose", _choose(lambda q: jev.get(q, 0.05))) as _:
            used = set()
            cand, twist, fb = qfirst.refine_round(self._cand(), "two_state_ratio", STEM, [], used, random.Random(0),
                                                  self._bb())
        self.assertEqual(used, {"cue_word"})                          # only the likeliest case
        self.assertIn("Remove every word that names a law", fb)
        self.assertNotIn("straight plug-in", fb)                       # no other case's instruction
        with mock.patch("core.pipeline.refine.jev_choose", _choose(lambda q: jev.get(q, 0.05))):
            cand, twist, fb = qfirst.refine_round(self._cand(), "two_state_ratio", STEM, [], used, random.Random(0),
                                                  self._bb())
        self.assertEqual(used, {"cue_word", "plugin_order"})          # next round: the next case
        self.assertIn(twist, ("inverse", "condition"))                 # plugin order -> work backwards
        self.assertIn(qfirst.TWISTS[twist], fb)
        self.assertTrue(fb.startswith("Your earlier question was solved easily"))

    def test_never_draws_one_more_formula(self):
        """2026-11-25: an added formula made questions longer, not harder; too_few_steps is never offered."""
        before = self._cand()
        with mock.patch("core.pipeline.refine.jev_choose", _choose(lambda q: 0.95 if q == "too_few_steps" else 0.1)):
            used = set()
            cand, _, fb = qfirst.refine_round(before, "inverse", STEM, [], used, random.Random(1), self._bb())
        self.assertNotIn("too_few_steps", used)
        self.assertEqual(cand.get("drawn_txs") or cand["txs"], before.get("drawn_txs") or before["txs"])
        self.assertNotIn("One more formula has been added", fb)

    def test_a_new_twist_or_formula_drops_the_old_design(self):
        """The design is planned for one twist and one formula set: a refinement that changes either must not
        hand the writer the old plan; one that only changes the wording keeps it."""
        designed = {**self._cand(), "_design": {"situation": "argon expanding at 300 K"}}
        for case, keeps in (("cue_word", True), ("plugin_order", False)):
            with mock.patch("core.pipeline.refine.jev_choose", _choose(lambda q, c=case: 0.95 if q == c else 0.0)):
                cand, _, _ = qfirst.refine_round(designed, "two_state_ratio", STEM, [], set(), random.Random(1),
                                                 self._bb())
            self.assertEqual("_design" in cand, keeps, case)

    def test_jev_unreachable_falls_back_to_a_random_case(self):
        with mock.patch.object(models, "key_is_set", lambda *a: False):
            used = set()
            out = qfirst.refine_round(self._cand(), "inverse", STEM, [], used, random.Random(2), self._bb())
        self.assertEqual(len(used), 1)
        self.assertIsNotNone(out)

    def test_jev_request_shape(self):
        from core.pipeline import refine
        sent = {}

        class Resp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.body

        def fake_urlopen(req, timeout=0):
            sent.update(json.loads(req.data.decode()))
            sent["auth"] = req.headers.get("Authorization")
            crit = sent["questions"]["pick"]["criteria"]
            probs = {k: 1 / len(crit) for k in crit}
            return Resp(json.dumps({"answers": {"pick": {"type": "choice", "choice": next(iter(crit)),
                                                         "confidence": 0.5, "probabilities": probs}},
                                    "usage": {"input_tokens": 1000}}).encode())
        with mock.patch.object(models, "key_is_set", lambda *a: True), mock.patch.object(models, "api_key", lambda *a: "k"), \
                mock.patch("urllib.request.urlopen", fake_urlopen):
            with mock.patch("builtins.print"):
                probs = refine.classify(STEM, "formulas", "working", {"cue_word"})
        self.assertEqual(sent["model"], models.route_model(models.JEV_MODEL))
        self.assertEqual(sent["auth"], "Bearer k")
        self.assertEqual(list(sent["questions"]), ["pick"])           # one choice question
        self.assertEqual(sent["questions"]["pick"]["type"], "choice")
        self.assertNotIn("cue_word", sent["questions"]["pick"]["criteria"])   # used cases are not offered
        self.assertEqual(set(probs), set(refine.CASES) - {"cue_word"})


class DesignCheck(unittest.TestCase):
    DESIGN = {"system": "PCl5 <=> PCl3 + Cl2 at 500 K", "hidden_link": "Kc numerically equals P(PCl5)",
              "route": "...", "given": "Kp, T, mass", "asked": "V (L)"}

    def test_no_calibration_no_check(self):
        with mock.patch("builtins.open", side_effect=OSError), \
                mock.patch("core.pipeline.refine.jev_decide", side_effect=AssertionError("Jev must not be asked")):
            self.assertIsNone(qfirst.design_problems(self.DESIGN))

    def test_calibrated_cuts_flag_an_arbitrary_condition(self):
        cal = json.dumps({"thresholds": {"invented_relation": 0.3, "glued_parts": 0.3, "arbitrary_condition": 0.3}})
        p = {"invented_relation": 0.1, "glued_parts": 0.07, "arbitrary_condition": 0.71}
        with mock.patch("builtins.open", mock.mock_open(read_data=cal)), \
                mock.patch("core.pipeline.refine.jev_decide", return_value=p):
            why = qfirst.design_problems(self.DESIGN)
        self.assertIn("arbitrary condition", why)
        self.assertNotIn("glues", why)
        self.assertIn("Kc numerically equals P(PCl5)", qfirst.design_plan_text(self.DESIGN))


class FindWholeNumber(unittest.TestCase):
    def test_find_gives_a_whole_number_input(self):
        # x in AxBy from Λ° = xλ₊ + yλ₋: bisection gave 1.0000000000000002, refused by the step (2026-11-17)
        code = ("def solve():\n"
                "    lp = given(100.0, 'λ+ = 100')\n"
                "    lm = given(75.0, 'λ- = 75')\n"
                "    x = find(step_250, 'cations_per_unit', result=250.0, ionic_conductivity=lp,\n"
                "             anion_conductivity=lm, anions_per_unit=2)\n"
                "    return x\n")
        run = sandbox.evaluate(code, [250])
        self.assertTrue(run["ok"], run.get("error"))
        self.assertEqual(run["answer_exact"], 1)
        bad = code.replace("result=250.0", "result=260.0")
        self.assertIn("no whole number", sandbox.evaluate(bad, [250])["error"])

    def test_a_derived_input_may_be_given_itself(self):
        # steps 65/66 compute electron_energy from Z; giving electron_energy itself was refused as "unknown"
        # while leaving both out asked for it (fit A/B run of 2026-11-19: 2 of 10 draws died going back and forth)
        by_z = "def solve():\n    return step_66(n=3, lower_level=2, Z=1)['wavelength']\n"
        by_e = "def solve():\n    return step_66(n=3, lower_level=2, electron_energy=-13.6 / 9)['wavelength']\n"
        a, b = sandbox.evaluate(by_z, [66]), sandbox.evaluate(by_e, [66])
        self.assertTrue(a["ok"] and b["ok"], (a.get("error"), b.get("error")))
        self.assertAlmostEqual(a["answer_exact"], b["answer_exact"], places=6)      # Hα, ~656 nm
        neither = sandbox.evaluate("def solve():\n    return step_65(n=3, lower_level=2)['photon_energy']\n", [65])
        self.assertIn("give 'electron_energy', or ['Z']", neither["error"])
        doc = sandbox.library_doc([ph.step(65)])
        self.assertIn("electron_energy: REQUIRED", doc)

    def test_solve_for_gives_a_whole_number_unknown(self):
        # run of 2026-11-15: 6 lines and a smallest photon of 0.306 eV; solve_for over n bisected to
        # 2.0000000000000004, which steps 68/69 refuse, and 9 programs failed. Levels 5 → 2: n1 = 2.
        code = ("def solve():\n"
                "    IE = given(13.6, '13.6 eV')\n"
                "    lines = given(6, '6 lines')\n"
                "    E_min = given(0.306, '0.306 eV')\n"
                "    def gap(n1):\n"
                "        n2 = solve_for(lambda x: step_68(upper_level=x, final_level=n1,\n"
                "                       sample='a sample of many atoms')['spectral_line_count'] - lines, n1 + 1, n1 + 10)\n"
                "        return (step_69(ionization_energy=IE, n=n2)['electron_energy']\n"
                "                - step_69(ionization_energy=IE, n=n2 - 1)['electron_energy'] - E_min)\n"
                "    return solve_for(gap, 1, 6)\n")
        run = sandbox.evaluate(code, [68, 69])
        self.assertTrue(run["ok"], run.get("error"))
        self.assertEqual(run["answer_exact"], 2)
        bad = code.replace("E_min = given(0.306, '0.306 eV')", "E_min = given(0.5, '0.5 eV')")
        self.assertIn("no whole number", sandbox.evaluate(bad, [68, 69])["error"])


class Router(unittest.TestCase):
    def tearDown(self):
        models._OPENROUTER_OUT.clear()
        models._NOT_ON_OPENROUTER.clear()

    def test_a_model_openrouter_lacks_goes_to_airouter(self):
        class Bad(Exception):
            status_code = 400

        calls = []

        def fake_call_json(create, parse, **k):
            calls.append(models.router("mistralai/mistral-large-4"))
            if len(calls) == 1:
                raise Bad("mistralai/mistral-large-4 is not a valid model ID")
            return {"ok": True}
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "ar-test", "OPENROUTER_KEY": "or-test"}), \
                mock.patch.object(models, "call_json", fake_call_json):
            self.assertEqual(models.ask_json("t", "mistralai/mistral-large-4", "s", "u"), {"ok": True})
        self.assertEqual(calls, ["openrouter", "airouter"])

    def test_airouter_names_and_address(self):
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "ar-test", "OPENROUTER_KEY": ""}):
            self.assertEqual(models.router(), "airouter")
            self.assertEqual(models.route_model("z-ai/glm-5.3-flash"), "zai/glm-5.3-flash")
            self.assertEqual(models.route_model("typesafe/jev-1.14"), "typesafe-ai/jev-1.14.0")
            self.assertEqual(models.route_model("openai/gpt-6-luna"), "openai/gpt-6-luna")
            self.assertEqual(models.decisions_url(), "https://api.airouter.in/v1/decisions")
            self.assertEqual(models.router("microsoft/phi-4"), "openrouter")          # not on airouter
            self.assertEqual(models.route_model("mistralai/devstral-2512"), "alibaba/qwen3-coder-next")  # stand-in
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "", "OPENROUTER_KEY": "or-test"}):
            self.assertEqual(models.router(), "openrouter")
            self.assertEqual(models.route_model("z-ai/glm-5.3-flash"), "z-ai/glm-5.3-flash")

    def test_openrouter_first_then_airouter_once_out_of_credit(self):
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "ar-test", "OPENROUTER_KEY": "or-test"}), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()), \
                mock.patch("builtins.print") as said:
            self.assertEqual(models.router("openai/gpt-6-luna"), "openrouter")
            self.assertTrue(models.openrouter_out())
            self.assertEqual(models.router("openai/gpt-6-luna"), "airouter")
            self.assertEqual(models.router("microsoft/phi-4"), "openrouter")
            # a second call that got the same 402 (in flight at the same time) also moves to airouter
            self.assertTrue(models.openrouter_out())
            self.assertEqual(said.call_count, 1)                                      # said once
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "", "OPENROUTER_KEY": "or-test"}), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()):
            self.assertFalse(models.openrouter_out())                                 # nowhere to go

    def test_parallel_calls_that_get_402_all_move_to_airouter(self):
        """Several calls in flight get the 402 together; every one is repeated on airouter (before, only
        the first was, and the others crashed the run)."""
        class Out(Exception):
            status_code = 402
        served = []

        def create(*a, **kw):
            served.append(kw.get("where"))
            if kw.get("where") == "openrouter":
                raise Out("Error code: 402 - insufficient credits")
            return {"ok": True}

        def fake_call_json(make, parse, **kw):
            return make()

        def fake_client(where=None):
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: create(where=where, **kw))))
        from concurrent.futures import ThreadPoolExecutor
        with mock.patch.dict(os.environ, {"AIROUTER_KEY": "ar-test", "OPENROUTER_KEY": "or-test"}), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()), \
                mock.patch.object(models, "_client", fake_client), \
                mock.patch.object(models, "call_json", fake_call_json), \
                mock.patch.object(models.SPEND, "add", lambda *a: None), mock.patch("builtins.print"):
            gate_ = threading.Barrier(4)

            def one(_):
                gate_.wait()
                return models.ask_json("council", "openai/gpt-6-luna", "s", "u")
            with ThreadPoolExecutor(4) as ex:
                outs = list(ex.map(one, range(4)))
        self.assertEqual(outs, [{"ok": True}] * 4)
        self.assertEqual(served.count("airouter"), 4)


class Construction(unittest.TestCase):
    def test_fill_keeps_figures_and_refuses_the_asked_value(self):
        t = "[[n]] mol at [[T]] K, R = [[R]], E = [[E]]"
        self.assertEqual(qfirst.fill_template(t, {"n": 2.0, "T": 300.0, "R": 8.314}, {"E": 0.71234}, "x"),
                         "2.00 mol at 300 K, R = 8.314, E = 0.7123")
        with self.assertRaises(ValueError):
            qfirst.fill_template("find [[x]]", {}, {}, "x")
        with self.assertRaises(ValueError):
            qfirst.fill_template("[[y]]", {}, {}, "x")

    def test_free_values_as_a_model_writes_them(self):
        for text, want in [("5.0 × 10⁻³", 5.0e-3), ("1.2 x 10^-5", 1.2e-5), ("300 K", 300.0),
                           ("6.022 × 10²³", 6.022e23), ("−0.44", -0.44), ("2.00", 2.0)]:
            self.assertAlmostEqual(qfirst._free_number(text) / want, 1.0, places=9, msg=text)
        self.assertIsNone(qfirst._free_number("about"))


ENTROPY = ("def solve():\n"
           "    def dS(V2):\n"
           "        w = step_117(n=n, T=T, V1=V1, V2=V2)['work']\n"
           "        q = step_357(work=w)['heat']\n"
           "        return step_130(heat=q, T=T)['entropy_change']\n"
           "    return dS(Va) - dS(Vb)\n")
RANGES = {"n": (0.5, 5.0, False), "T": (250.0, 600.0, False), "V1": (1.0, 8.0, False), "Va": (10.0, 20.0, False),
          "Vb": (21.0, 40.0, False)}
BLANK_STEM = ("Two [[n]] mol samples of argon (Ar), each at [[T]] K and [[V1]] L, expand isothermally and reversibly, "
              "one to [[Va]] L and the other to [[Vb]] L. By how much does the entropy change of the surroundings "
              "for the first expansion exceed that for the second? (Given: R = [[R]] J K⁻¹ mol⁻¹)")
BLANK_Q = {"stem": BLANK_STEM, "asks": "difference of the entropy changes of the surroundings", "unit": "J K⁻¹",
           "asked": "d", "ranges": RANGES, "fixed": {"R": 8.314}, "answer_range": [0.1, 1000.0]}


class Blanks(unittest.TestCase):
    """The writer's blanks: ranges, fixed values, the answer range, and what goes back to the writer."""

    def test_values_parse_into_ranges_fixed_values_and_counts(self):
        q = qfirst.parse_values({"values": {"m": {"range": [0.5, 2.5]}, "M": {"value": 55.85},
                                            "n": {"range": [2, 5], "whole": True}, "T": {"range": [250, 600]},
                                            "k": {"range": ["1e-5", "5e-4"]}, "bad": {"range": [3, 1]},
                                            "R": {"value": "8.314"}, "z": {"range": [1.5, 4], "whole": True}},
                                 "answer_range": [1, 100]})
        self.assertEqual(q["ranges"]["m"], (0.5, 2.5, False))
        self.assertEqual(q["ranges"]["n"], (2, 5, True))                 # marked whole: a count
        self.assertEqual(q["ranges"]["T"], (250.0, 600.0, False))        # whole ends alone: not a count
        self.assertAlmostEqual(q["ranges"]["k"][0], 1e-5)
        self.assertEqual(q["fixed"], {"M": 55.85, "R": 8.314})
        self.assertEqual(q["answer_range"], (1.0, 100.0))
        self.assertEqual(q["bad_values"], ["bad", "z"])
        self.assertEqual(qfirst.constant_names(q["fixed"]), ["R"])

    def test_a_stem_with_plain_numbers_is_sent_back(self):
        self.assertIn("placeholder", qfirst.blank_problems({"stem": "2.00 mol of gas at 300 K. Find V."})[0])

    def test_a_missing_range_the_asked_blank_and_a_reserved_name_go_back(self):
        q = {"stem": "[[m]] g and [[T]] K and [[math]] give [[V]]", "asked": "V", "ranges": {"m": (1.0, 2.0, False)},
             "fixed": {"math": 3.0}}
        why = "; ".join(qfirst.blank_problems(q))
        self.assertIn("[[V]]", why)
        self.assertIn("no range or value for [[T]]", why)
        self.assertIn("choose other names for math", why)
        self.assertEqual(qfirst.blank_problems(BLANK_Q), [])
        # every name the program already has: built-ins it may call, the calculator, dunder names
        for name in ("list", "sorted", "calculate", "zip", "__x"):
            q = {"stem": f"[[{name}]] g of gas", "asked": "V", "fixed": {name: 3.0}}
            self.assertIn(f"choose other names for {name}", "; ".join(qfirst.blank_problems(q)), name)

    def test_a_power_of_ten_beside_a_blank_or_in_the_unit_goes_back(self):
        for stem, unit in (("light of frequency [[nu0]] × 10¹⁴ Hz falls", "eV"),
                           ("light of frequency [[nu0]] Hz falls", "× 10¹⁴ Hz"),
                           ("a rate of [[k]] x 10^-3 s⁻¹", "s")):
            q = {"stem": stem, "asked": "x", "unit": unit, "ranges": {"nu0": (5.0, 6.0, False), "k": (1.0, 2.0, False)}}
            self.assertIn("power of ten", "; ".join(qfirst.blank_problems(q)), stem)
        fine = {"stem": "light of frequency [[nu0]] Hz falls on a metal with 10 atoms", "asked": "KE", "unit": "eV",
                "ranges": {"nu0": (5e14, 8e14, False)}}
        self.assertEqual(qfirst.blank_problems(fine), [])

    def test_the_reader_sees_a_typical_value_of_each_range(self):
        q = {"stem": "[[m]] g, [[n]] half-lives, M = [[M]], [[x]]",
             "ranges": {"m": (1.0, 3.0, False), "n": (2, 4, True)}, "fixed": {"M": 55.85}}
        self.assertEqual(qfirst.preview_text(q), "2.00 g, 3 half-lives, M = 55.85, …")

    def test_values_are_drawn_in_range_to_three_figures_counts_whole(self):
        for seed in range(20):
            v = sandbox.sample_values({"n": (2, 5, True), "m": (1.0, 2.0, False), "c": (1e-5, 1e-3, False)},
                                      {"M": 55.85}, random.Random(seed))
            self.assertIsInstance(v["n"], int)
            self.assertTrue(2 <= v["n"] <= 5)
            for k, (lo, hi) in (("m", (1.0, 2.0)), ("c", (1e-5, 1e-3))):
                self.assertTrue(lo <= v[k] <= hi, (k, v[k]))
                self.assertEqual(v[k], float(f"{v[k]:.3g}"))
            self.assertEqual(v["M"], 55.85)

    def test_a_rewrite_sees_the_blanks_and_their_ranges(self):
        text = qfirst.previous_text(BLANK_Q)
        self.assertIn("[[Va]]", text)
        self.assertIn('"Va": {"range": [10.0, 20.0]}', text)
        self.assertIn('"R": {"value": 8.314}', text)
        # a count keeps its whole-number mark, and parses back as a count
        q = {**BLANK_Q, "ranges": {**BLANK_Q["ranges"], "Va": (2, 6, True)}}
        text = qfirst.previous_text(q)
        self.assertIn('"Va": {"range": [2, 6], "whole": true}', text)
        spec = json.loads(text.split("Its values: ")[1].split("\n")[0])
        self.assertEqual(qfirst.parse_values({"values": spec})["ranges"]["Va"], (2, 6, True))


class SpeciesNames(unittest.TestCase):
    def test_states_and_subscripts_do_not_matter(self):
        from core.engine import physical as ph
        eq = "CH4(g) + CO2(g) → 2CO(g) + 2H2(g)"
        out = ph.step(13).fn({"balanced_equation": eq, "reactant_A": "CH4(g)", "moles": 2.0,
                              "reactant_B": "CO₂", "moles_B": 1.5})
        self.assertEqual(out["limiting_reagent"], "CO₂")
        self.assertEqual(ph.step(12).fn({"balanced_equation": eq, "known_species": "CH₄(g)", "moles_known": 2.0,
                                         "target_species": "H2(g)", "element": "H"})["moles"], 4.0)


class PresetValues(unittest.TestCase):
    def test_the_questions_values_are_variables_of_the_program(self):
        code = ("def solve():\n"
                "    w = step_92(P=P_wet_H2, aqueous_tension=aq)\n"
                "    return w['pressure'] if 'pressure' in w else list(w.values())[0]\n")
        out = sandbox.evaluate(code, [92], preset={"P_wet_H2": 1.02, "aq": 0.031})
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(out["answer_exact"], 0.989, places=6)
        self.assertEqual(out["inputs_unused"], [])


class FormulaFit(unittest.TestCase):
    def test_pick_best_ranks_and_survives_a_down_jev(self):
        self.assertEqual(qfirst.pick_best(["a", "b", "c"], [0.2, 0.45, 0.3]), "b")
        self.assertEqual(qfirst.pick_best(["a", "b"], [None, None]), "a")
        self.assertEqual(qfirst.pick_best(["a", "b"], [None, 0.1]), "b")
        self.assertIsNone(qfirst.pick_best([], []))


class FindAndClean(unittest.TestCase):
    def test_find_runs_a_formula_backwards_and_the_chain_round_trips(self):
        fwd = ("def solve():\n"
               "    a = step_173(dissociation_constant=Ka, concentration=C)['degree_of_dissociation']\n"
               "    lam = find(step_251, 'molar_conductivity', result=a, limiting_molar_conductivity=L0)\n"
               "    kappa = find(step_248, 'conductivity', result=lam, molarity=C)\n"
               "    return find(step_247, 'resistance', result=kappa, cell_constant=G)\n")
        out = sandbox.evaluate(fwd, [173, 251, 248, 247], preset={"Ka": 1.8e-5, "C": 0.02, "L0": 390.5, "G": 1.2})
        self.assertTrue(out["ok"], out)
        R = out["answer_exact"]
        inv = ("def solve():\n"
               f"    R = given({R!r}, 'R')\n"
               "    def f(C):\n"
               "        k = step_247(resistance=R, cell_constant=1.2)['conductivity']\n"
               "        lam = step_248(conductivity=k, molarity=C)['molar_conductivity']\n"
               "        a1 = step_251(molar_conductivity=lam, limiting_molar_conductivity=390.5)['degree_of_dissociation']\n"
               "        return a1 - step_173(dissociation_constant=1.8e-5, concentration=C)['degree_of_dissociation']\n"
               "    return solve_for(f, 1e-3, 1)\n")
        r = sandbox.evaluate(inv, [173, 251, 248, 247])
        self.assertTrue(r["ok"], r.get("error"))
        self.assertAlmostEqual(r["answer_exact"], 0.02, places=6)

    def test_find_names_the_inputs_when_wrong(self):
        code = "def solve():\n    return find(step_247, 'ohms', result=0.01, cell_constant=1.0)\n"
        self.assertIn("its inputs are ['resistance', 'cell_constant']", sandbox.evaluate(code, [247])["error"])

    def test_subscripts_in_names_are_read_but_kept_in_quotes(self):
        self.assertEqual(sandbox.clean_code("CO₂ = given(2, 'CO₂ gas')"), "CO2 = given(2, 'CO₂ gas')")


class DesignCoherence(unittest.TestCase):
    def test_an_incoherent_plan_is_named_and_a_down_jev_never_blocks(self):
        from core.pipeline import refine
        d = {"situation": "FeO(s) + CO ⇌ Fe(s) + CO2 and 2CO + O2 ⇌ 2CO2", "links": "the same K_p governs both",
             "asked": "p(CO2)"}
        with mock.patch.object(refine, "jev_decide", lambda *a, **k: {"invented_relation": 0.8, "glued_parts": 0.1,
                                                                       "vague": 0.6}):
            why = qfirst.design_coherence(d)
        self.assertIn("one reaction's K used for another", why)
        self.assertIn("one definite reaction", why)
        with mock.patch.object(refine, "jev_decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))):
            self.assertIsNone(qfirst.design_coherence(d))


class DropUnneeded(unittest.TestCase):
    def test_unneeded_formulas_are_dropped_while_three_remain(self):
        run = {"unused_steps": [5], "irrelevant_steps": [4]}
        self.assertEqual(qfirst.unneeded([1, 2, 3, 4, 5], run), [4, 5])
        self.assertEqual(qfirst.unneeded([1, 2, 4, 5], run), [])          # only 2 would remain: rejected instead

VDW_STEM = ("A supercritical extraction vessel contains 1.00 mol of carbon dioxide gas confined to a volume of 0.250 L at a temperature of 300 K. Under low-pressure expansion experiments, this gas exhibits a Boyle temperature of 1025 K and a second virial coefficient of -0.1034 L mol⁻¹ at 300 K. Assuming the fluid obeys the van der Waals equation of state, calculate the reduced pressure of the gas inside the vessel.\n(Given: R = 0.0821 L atm K⁻¹ mol⁻¹)")
VDW_CHEAT = 'def solve():\n    n = given(1.00, "1.00 mol of carbon dioxide gas")\n    V = given(0.250, "a volume of 0.250 L")\n    T = given(300, "a temperature of 300 K")\n    T_B = given(1025, "a Boyle temperature of 1025 K")\n    B = given(-0.1034, "a second virial coefficient of -0.1034 L mol⁻¹ at 300 K")\n    R = 0.0821\n    def calculate_a(T_B, b):\n        return T_B * b * R\n    def calculate_b(B, T, a):\n        return B + a / (R * T)\n    b = solve_for(lambda x: calculate_b(B, T, calculate_a(T_B, x)) - x, 0.01, 0.2)\n    a = calculate_a(T_B, b)\n    P_c = step_107(a=a, b=b, which="P_c")["critical_constants"]\n    T_c = step_107(a=a, b=b, which="T_c")["Tc"]\n    P = (n * R * T) / (V - n * b) - (a * n ** 2) / (V ** 2)\n    P_r = step_108(Tc=T_c, Pc=P_c, T=T, P=P, which="reduced pressure")["reduced_state"]\n    step_106(a=a, b=b)\n    step_105(a=a, b=b, T=T)\n    step_103(P=P, V=V, T=T, n=n, b=b)\n    return P_r\n'
VDW_HONEST = 'def solve():\n    n = given(1.00, "1.00 mol of carbon dioxide gas")\n    V = given(0.250, "a volume of 0.250 L")\n    T = given(300, "a temperature of 300 K")\n    TB = given(1025, "a Boyle temperature of 1025 K")\n    B = given(-0.1034, "a second virial coefficient of -0.1034 L mol⁻¹ at 300 K")\n    R = given(0.0821, "R = 0.0821")\n    def mismatch(b):\n        a = find(step_106, \'a\', result=TB, b=b)\n        return step_105(a=a, b=b, T=T)[\'virial_coefficient\'] - B\n    b = solve_for(mismatch, 0.01, 0.2)\n    a = find(step_106, \'a\', result=TB, b=b)\n    P = find(step_103, \'P\', result=a, V=V, T=T, n=n, b=b)\n    c = step_107(a=a, b=b, which=\'P_c\')\n    return step_108(Tc=c[\'Tc\'], Pc=c[\'Pc\'], T=T, P=P, which=\'reduced pressure\')[\'reduced_state\']\n'


class DummyCalls(unittest.TestCase):
    def test_typed_formulas_with_dummy_calls_are_found_irrelevant(self):
        txs = [107, 106, 108, 105, 103]
        run = sandbox.evaluate(VDW_CHEAT, txs, any_step=True)
        self.assertTrue(run["ok"], run.get("error"))
        self.assertIn(103, run["irrelevant_steps"])                   # called, result thrown away

    def test_a_formula_on_both_sides_of_a_ratio_matters(self):
        # t(1/8)/t(1/10) from one first-order law (2012P1_Q36): scaling both calls cancels, one call does not
        code = ("def solve():\n"
                "    h = given(10.0, 'half-life 10 min')\n"
                "    t8 = step_209(half_life=h, fraction_remaining=0.125)\n"
                "    t10 = step_209(half_life=h, fraction_remaining=0.1)\n"
                "    return t8[ANS] / t10[ANS]\n").replace("ANS", repr(ph.step(209).answer))
        run = sandbox.evaluate(code, [209])
        self.assertTrue(run["ok"], run.get("error"))
        self.assertAlmostEqual(run["answer_exact"], math.log(8) / math.log(10), places=4)
        self.assertEqual(run["irrelevant_steps"], [])

    def test_results_given_beside_the_answer_count(self):
        txs = [107, 106, 108, 105, 103]
        run = sandbox.evaluate(VDW_HONEST, txs, any_step=True)
        self.assertTrue(run["ok"], run.get("error"))
        self.assertEqual(run["irrelevant_steps"], [])                 # 107 used through its Tc and Pc
        self.assertAlmostEqual(run["answer_exact"], 0.8418, delta=0.002)


class Escalation(unittest.TestCase):
    def test_last_try_goes_to_the_strong_coder_and_cheap_one_is_capped(self):
        with mock.patch("builtins.print"), mock.patch.object(models, "CODER", "mistralai/codestral-2508"), \
                mock.patch.object(models, "CODER_STRONG", "openai/gpt-6-luna"):
            self.assertEqual(qfirst.coder_for(0, False), models.CODER)
            self.assertEqual(qfirst.coder_for(qfirst.CODE_TRIES - 1, False), models.CODER_STRONG)
            self.assertEqual(qfirst.coder_for(1, True), models.CODER_STRONG)
        with mock.patch("builtins.print"), mock.patch.object(models, "CODER_STRONG", None):
            self.assertEqual(qfirst.coder_for(qfirst.CODE_TRIES - 1, True), models.CODER)      # no escalation
        self.assertEqual(models.coder_tokens("mistralai/codestral-2508"), 4000)
        self.assertEqual(models.coder_tokens("openai/gpt-6-luna"), 12000)

    def test_built_numbers_are_not_called_inconsistent(self):
        p = "step_106: input a (van der Waals a) must be > 0, got -2.55"
        self.assertIn("data are inconsistent", qfirst.explain(p))
        built = qfirst.explain(p, [106], consistent=True)
        self.assertNotIn("data are inconsistent", built)
        self.assertIn("Your numbers are consistent", built)


def _choose(score):
    """A stand-in for refine.jev_choose: probabilities over the offered cases, summing to 1."""
    def f(state, instructions, criteria, role="refiner"):
        raw = {k: max(score(k), 1e-9) for k in criteria}
        tot = sum(raw.values())
        probs = {k: v / tot for k, v in raw.items()}
        best = max(probs, key=probs.get)
        return {"choice": best, "confidence": probs[best], "probabilities": probs}
    return f


class JevChoice(unittest.TestCase):
    def test_one_choice_request_over_the_unused_cases(self):
        from core.pipeline import refine
        sent = {}

        def post(state, questions, role):
            sent.update(questions)
            return {"pick": {"type": "choice", "choice": "plugin_order", "confidence": 0.7,
                             "probabilities": {"plugin_order": 0.7, "ready_data": 0.2, "trivial_units": 0.1}}}

        with mock.patch.object(refine, "_jev_post", post), mock.patch("builtins.print"):
            probs = refine.classify("stem", "formulas", "working", {"cue_word"})
        q = sent["pick"]
        self.assertEqual(q["type"], "choice")
        self.assertNotIn("cue_word", q["criteria"])                   # a used case is not offered
        self.assertEqual(len(q["criteria"]), len(refine.CASES) - 1)
        self.assertEqual(refine.pick(probs, {"cue_word"}), ["plugin_order"])


class CoderReplies(unittest.TestCase):
    def test_a_copied_placeholder_is_not_a_reason(self):
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"cannot": "the reason"}):
            with self.assertRaises(ValueError):
                qfirst.write_program("stem", "x", "", "lib")
        real = "The question gives no temperature for the second state, so B cannot be evaluated."
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"cannot": real}):
            self.assertEqual(qfirst.write_program("stem", "x", "", "lib"), {"cannot": real})
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"code": "def solve():\n    return 1", "cannot": real}):
            self.assertIn("code", qfirst.write_program("stem", "x", "", "lib"))


class FitFloor(unittest.TestCase):
    def test_the_floor_is_the_calibrated_one(self):
        """The floor comes from the calibration on real JEE Advanced sets (0.504, which 79 % of them reach); a
        hard-coded 0.60 turned away a third of real sets and ~97 % of random draws (2026-11-19)."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge",
                            "fit_calibration_physical.json")
        with open(path, encoding="utf-8") as f:
            cal = json.load(f)
        self.assertIsNone(qf_draw.FIT_FLOOR)
        self.assertEqual(qf_draw._fit_floor(), float(cal["threshold"]))
        real = [r["p"] for r in cal["real"]]
        self.assertGreaterEqual(sum(p >= qf_draw._fit_floor() for p in real) / len(real), 0.75)

    def test_another_batch_under_the_floor_and_the_best_seen_is_written(self):
        from types import SimpleNamespace
        from core.engine import physical as ph
        n = {"i": 0}

        def draw(chapter=None, exclude=()):
            n["i"] += 1
            t = [1 + n["i"] % 50, 60 + n["i"] % 30, 100 + n["i"] % 40]
            return {"txs": t, "_steps": [ph.step(x) for x in t if x in ph.STEPS] or [ph.step(1)]}
        import threading
        lock = threading.Lock()

        def safe(it):
            def f(steps, quiet=False):
                with lock:
                    x = next(it)
                __import__("time").sleep(0.05)               # a Jev call takes time: queued sets can be cancelled
                return x
            return f
        calls = {"n": 0}
        seq = iter([0.1, 0.2, 0.15, 0.3, 0.05, 0.12] + [0.25, 0.6, 0.1, 0.2, 0.3, 0.1] + [0.9] * 6)

        def counted(it):
            def g():
                for x in it:
                    calls["n"] += 1
                    yield x
            return g()
        scores = counted(seq)
        ad = SimpleNamespace(random_formulas=draw)
        bb = SimpleNamespace(tried_edges=lambda: set())
        with mock.patch.object(qf_draw, "_fit_floor", lambda *a, **k: 0.5), \
                mock.patch.object(qf_draw, "formulas_fit", safe(scores)), mock.patch("builtins.print"):
            best = qfirst.best_draw(ad, None, bb, lambda rec: None)
        self.assertEqual(best["_fit"], 0.6)                                     # second batch reached it
        self.assertLessEqual(calls["n"], 12)                                    # no third batch
        scores2 = iter([0.1] * 18)
        with mock.patch.object(qf_draw, "_fit_floor", lambda *a, **k: 0.5), mock.patch.object(qf_draw, "FIT_BATCHES", 3), \
                mock.patch.object(qf_draw, "formulas_fit", safe(scores2)), mock.patch("builtins.print"):
            best = qfirst.best_draw(ad, None, bb, lambda rec: None)
        self.assertIsNotNone(best)                                             # never stalls


class FindForgiving(unittest.TestCase):
    """The three ways coders misused find() in the run of 2026-11-16 (vapour density / Kp / ΔG°)."""

    def _run(self, body, txs):
        return sandbox.evaluate("def solve():\n" + body, txs)

    def test_the_output_name_works_as_result(self):
        out = self._run("    return find(step_247, 'resistance', conductivity=0.0024, cell_constant=1.2)\n", [247])
        self.assertTrue(out["ok"], out)
        self.assertAlmostEqual(out["answer_exact"], 500.0, places=3)

    def test_a_wrong_input_name_is_said_at_once(self):
        out = self._run("    return find(step_247, 'resistance', result=0.0024, cell_k=1.2)\n", [247])
        self.assertIn("unknown inputs ['cell_k']", out["error"])
        self.assertIn("result=<value of conductivity>", out["error"])
        self.assertNotIn("no value of", out["error"])

    def test_a_missing_result_shows_how_to_call_it(self):
        out = self._run("    return find(step_247, 'resistance', cell_constant=1.2)\n", [247])
        self.assertIn("give the known result as result=", out["error"])


class NumberSearch(unittest.TestCase):
    """Coder 1, the number step: code picks the values in the writer's ranges (no model)."""

    def test_a_good_set_in_range_printed_exactly_as_it_was_run(self):
        out = sandbox.search_numbers(ENTROPY, CHAIN, RANGES, {}, seed=1, timeout=60)
        self.assertTrue(out["ok"], out)
        v = out["values"]
        for k, (lo, hi, _) in RANGES.items():
            self.assertTrue(lo <= v[k] <= hi, k)
        self.assertGreaterEqual(len(out["run"]["traps"]), 2)
        self.assertLessEqual(out["run"]["tolerance"], 0.02)
        self.assertEqual(out["run"]["inputs_unused"], [])
        self.assertEqual(sorted(out["run"]["inputs_irrelevant"]), ["T", "V1"])   # they cancel out: allowed
        stem, givens = qfirst.filled_question({"stem": "[[n]] mol, [[T]] K, [[V1]] L, [[Va]] L, [[Vb]] L",
                                               "asked": "d"}, v)
        self.assertEqual([float(x) for x in re.findall(r"[\d.]+", stem)], [v[k] for k in RANGES])
        self.assertEqual([g["quote"] for g in givens], list(RANGES))
        again = sandbox.evaluate(ENTROPY, CHAIN, preset={g["quote"]: g["value"] for g in givens})
        self.assertAlmostEqual(again["answer_exact"], out["run"]["answer_exact"], places=12)

    def test_an_answer_range_never_reached_says_where_the_answers_fell(self):
        out = sandbox.search_numbers(ENTROPY, CHAIN, RANGES, {}, answer_range=(1e6, 2e6), seed=1, tries=20,
                                     timeout=60)
        self.assertEqual((out["ok"], out["kind"]), (False, "answer_range"))
        self.assertLess(out["answers_seen"][1], 1e6)
        why = qfirst.numbers_problem(out, {"unit": "J K⁻¹", "answer_range": [1e6, 2e6]}, CHAIN)
        self.assertIn("never inside your answer_range [1000000.0, 2000000.0]", why)

    def test_the_furthest_failure_is_reported_not_the_most_frequent(self):
        # 2017P1_Q26 (real run): sets outside the answer range were the majority, the ones inside all failed the
        # typical-mistake check, and the writer was told its answers were "never inside" the range
        out = sandbox.search_numbers(ENTROPY, CHAIN, RANGES, {}, answer_range=(0.1, 6.0), min_traps=3, seed=1,
                                     tries=60, timeout=60)
        self.assertGreater(out["counts"]["answer_range"], out["counts"]["traps"])
        self.assertEqual(out["kind"], "traps")
        why = qfirst.numbers_problem(out, {"unit": "J K⁻¹", "answer_range": [0.1, 6.0]}, CHAIN)
        self.assertIn("typical mistakes change the answer", why)
        self.assertIn("gave an answer outside your answer_range", why)
        self.assertNotIn("never inside", why)

    def test_a_value_never_read_or_assigned_to_is_caught_before_any_run(self):
        out = sandbox.search_numbers(ENTROPY, CHAIN, {**RANGES, "Q": (1.0, 2.0, False)}, {}, seed=1, timeout=60)
        self.assertEqual((out["ok"], out["kind"], out["error"], out["tries"]), (False, "value_unused", "Q", 0))
        out = sandbox.search_numbers(ENTROPY.replace("    def dS(V2):", "    T = 300\n    def dS(V2):"), CHAIN,
                                     RANGES, {}, seed=1, timeout=60)
        self.assertEqual(out["kind"], "code")
        self.assertIn("assigns to T", out["error"])
        out = sandbox.search_numbers(ENTROPY, CHAIN, RANGES, {"R": 8.314}, exempt=("R",), seed=1, timeout=60)
        self.assertTrue(out["ok"], out)                                  # a stated constant the steps hold

    def test_a_value_read_but_feeding_nothing_is_unused(self):
        code = ENTROPY.replace("    return dS(Va) - dS(Vb)\n", "    x = Q * 2\n    return dS(Va) - dS(Vb)\n")
        out = sandbox.search_numbers(code, CHAIN, {**RANGES, "Q": (1.0, 2.0, False)}, {}, seed=1, timeout=60)
        self.assertEqual((out["kind"], out["error"]), ("value_unused", "Q"))

    def test_a_faked_use_is_seen_through_and_only_picked_values_must_matter(self):
        # 2020P1_Q15 (real): Luna wrote (P / P) * (T / T) to "use" 1 bar and 298 K; moving P = 1 to 0 crashed
        # the program, which was taken as "P matters"
        fake = ENTROPY.replace("    return dS(Va) - dS(Vb)\n", "    return (dS(Va) - dS(Vb)) * (P / P) * (Tb / Tb)\n")
        for P in (1, 1.0):
            run = sandbox.evaluate(fake, CHAIN, preset={"n": 2.0, "T": 300.0, "V1": 5.0, "Va": 12.0, "Vb": 20.0,
                                                        "P": P, "Tb": 298.0})
            self.assertTrue(run["ok"], run)
            self.assertEqual(sorted(run["inputs_unused"]), ["P", "Tb"], P)
        # a picked (range) value the answer does not use is rejected; a fixed one may be background
        out = sandbox.search_numbers(fake, CHAIN, {**RANGES, "P": (0.5, 2.0, False)}, {"Tb": 298.0},
                                     exempt=("Tb",), seed=1, timeout=60)
        self.assertEqual((out["kind"], out["error"].split(",")[0]), ("value_unused", "P"))
        q = {**BLANK_Q, "stem": BLANK_STEM + " All at [[P_bg]] bar.", "fixed": {"R": 8.314, "P_bg": 1.0}}
        picked = qfirst.pick_numbers(q, ENTROPY, CHAIN, seed=1)
        self.assertTrue(picked["ok"], picked.get("why"))
        self.assertIn("All at 1.00 bar.", qfirst.filled_question(q, picked["values"])[0])

    def test_a_count_the_formulas_pin_still_counts_as_used(self):
        # every change of the value breaks the program: it cannot be changed, so it is taken as used
        code = "def solve():\n    if N != 8:\n        raise ValueError('a cube has 8 corners')\n    return N * x\n"
        run = sandbox.evaluate(code, [], preset={"N": 8, "x": 2.0})
        self.assertTrue(run["ok"], run)
        self.assertEqual(run["inputs_unused"], [])

    def test_a_broken_program_stops_early(self):
        code = ENTROPY.replace("return dS(Va) - dS(Vb)", "return dS(Va) - dS(Vb) + undefined_name")
        out = sandbox.search_numbers(code, CHAIN, RANGES, {}, seed=1, timeout=60)
        self.assertEqual(out["kind"], "code")
        self.assertLessEqual(out["tries"], 3)

    def test_each_failure_is_said_to_the_writer_in_its_terms(self):
        q = {"unit": "pm", "answer_range": [1, 10]}
        self.assertIn("too sensitive to rounding", qfirst.numbers_problem({"kind": "fragile", "error": "3.1%"}, q, CHAIN))
        self.assertIn(f"at least {qfirst.MIN_TRAPS}", qfirst.numbers_problem({"kind": "traps", "error": "sign"}, q, CHAIN))
        self.assertIn("[[Q]]", qfirst.numbers_problem({"kind": "value_unused", "error": "Q"}, q, CHAIN))
        msg = qfirst.numbers_problem({"kind": "engine", "error": "step_106: input a must be > 0, got -2"}, q, CHAIN)
        self.assertIn("physically impossible", msg)
        self.assertEqual(qfirst.explain(msg, CHAIN), msg)                 # passed on as it is


class SolverProgram(unittest.TestCase):
    """Coder 2 writes the program from the blanks; a probe on values from the ranges checks it first."""

    @staticmethod
    def _coder(replies):
        replies, prompts = list(replies), []

        def fake(role, model, system, user, **kw):
            assert role == "coder", role
            prompts.append(user)
            return replies.pop(0) if len(replies) > 1 else replies[0]
        return fake, prompts

    def _solve(self, q, replies):
        fake, prompts = self._coder(replies)
        with mock.patch.object(models, "ask_json", fake), mock.patch("builtins.print"):
            code, why = qfirst.solver_program(q, CHAIN, mock.Mock(), seed=1)
        return code, why, prompts

    def test_the_coder_sees_blanks_and_an_ignored_value_goes_back_to_it(self):
        code, why, prompts = self._solve(BLANK_Q, [{"code": ENTROPY.replace("dS(Vb)", "dS(30.0)")},
                                                   {"code": ENTROPY}])
        self.assertEqual((code.strip(), why), (ENTROPY.strip(), None))
        self.assertIn("- Vb  ← ", prompts[0])
        self.assertIn("[[Vb]]", prompts[0])
        self.assertIn("- R  ← ", prompts[0])
        self.assertIn("(a constant", prompts[0])
        self.assertIn("never uses Vb", prompts[1])

    def test_a_drawn_formula_left_out_goes_back_to_the_coder(self):
        skip = ("def solve():\n"
                "    w = step_117(n=n, T=T, V1=V1, V2=Va)['work'] - step_117(n=n, T=T, V1=V1, V2=Vb)['work']\n"
                "    return -step_357(work=w)['heat'] / T\n")
        code, why, prompts = self._solve(BLANK_Q, [{"code": skip}, {"code": ENTROPY}])
        self.assertEqual(code.strip(), ENTROPY.strip())
        self.assertIn("never calls step_130", prompts[1])

    def test_the_coder_sees_the_design_route_and_trap(self):
        # run of 2026-11-18: without the design the key took the gas volume as the whole flask, the design's trap
        design = {"system": "a rigid flask with Mg and NaHSO4 solution",
                  "route": "the ideal gas equation with the available volume V_flask - V_sol",
                  "student_must_notice": "the injected liquid occupies part of the flask",
                  "trap": "assuming the gas occupies the entire volume of the flask"}
        fake, prompts = self._coder([{"code": ENTROPY}])
        with mock.patch.object(models, "ask_json", fake), mock.patch("builtins.print"):
            qfirst.numbers_for(BLANK_Q, CHAIN, mock.Mock(), seed=1, design=design)
        self.assertIn("THE QUESTION'S DESIGN", prompts[0])
        for text in design.values():
            self.assertIn(text, prompts[0])
        _, _, plain = self._solve(BLANK_Q, [{"code": ENTROPY}])   # no design: no design block
        self.assertNotIn("THE QUESTION'S DESIGN", plain[0])

    def test_cannot_goes_to_the_writer(self):
        code, why, _ = self._solve(BLANK_Q, [{"cannot": "the question never says which expansion is reversible"}])
        self.assertIsNone(code)
        self.assertIn("a solver could not solve it", why)

    def test_twice_no_value_set_runs_is_the_fault_of_the_ranges(self):
        q = {**BLANK_Q, "ranges": {**RANGES, "V1": (-8.0, -1.0, False)}}
        code, why, prompts = self._solve(q, [{"code": ENTROPY}])
        self.assertIsNone(code)
        self.assertIn("your ranges", why)
        self.assertEqual(len(prompts), 2)

    def test_numbers_for_fills_the_question_with_the_values_the_program_ran_on(self):
        fake, _ = self._coder([{"code": ENTROPY}])
        with mock.patch.object(models, "ask_json", fake), mock.patch("builtins.print"):
            stem, run, code, why = qfirst.numbers_for(BLANK_Q, CHAIN, mock.Mock(), seed=1)
        self.assertIsNone(why, why)
        self.assertNotIn("[[", stem)
        self.assertIn("R = 8.314 J", stem)
        v = {g["quote"]: g["value"] for g in run["givens"]}
        self.assertIn(f"Two {qfirst._fmt_number(v['n'])} mol", stem)
        self.assertAlmostEqual(run["answer_exact"], v["n"] * 8.314 * math.log(v["Vb"] / v["Va"]), delta=0.01)
        self.assertTrue(0.1 <= run["answer_exact"] <= 1000)


class PowersRead(unittest.TestCase):
    def test_each_power_is_one_number(self):
        cases = {"10⁻³ M": [0.001], "10^-3 M": [0.001], "3 × 10⁻³ M": [0.003], "4.20 × 10⁻⁵": [4.2e-5],
                 "2⁶ = 64": [64.0, 64.0], "2^6": [64.0], "(1/2)³": [0.125], "(1/2)^3": [0.125],
                 "Fe³⁺ and 0.10 M": [0.1], "25.0 cm³": [25.0], "K⁻¹ mol⁻¹, 8.314": [8.314],
                 "a 2.00 × 10² mL flask": [200.0], "k = A e^(−Ea/RT)": []}
        for text, want in cases.items():
            got = qfirst.stated_numbers(text)
            self.assertEqual(len(got), len(want), text)
            for g, w in zip(got, want):
                self.assertAlmostEqual(g, w, places=9, msg=text)
        self.assertAlmostEqual(qfirst.stated_numbers("e¹²")[0], math.exp(12), places=3)
        self.assertAlmostEqual(qfirst.stated_numbers("exp(12)")[0], math.exp(12), places=3)

    def test_counts_print_as_whole_numbers(self):
        self.assertEqual(qfirst.fill_template("after [[n]] half-lives, [[m]] g", {"n": 6, "m": 2.0}, {}, "x"),
                         "after 6 half-lives, 2.00 g")


class EveryFormulaMatters(unittest.TestCase):
    def test_a_called_formula_whose_result_changes_nothing_is_named_for_the_writer(self):
        code = ("def solve():\n"
                "    k = step_247(resistance=R_cell, cell_constant=G)['conductivity']\n"
                "    lam = step_248(conductivity=k, molarity=M)['molar_conductivity']\n"
                "    step_105(a=1.0, b=0.04, T=300)\n"
                "    return lam\n")
        run = sandbox.evaluate(code, [247, 248, 105], preset={"R_cell": 500.0, "G": 1.2, "M": 0.01})
        self.assertTrue(run["ok"], run)
        self.assertEqual(run["irrelevant_steps"], [105])
        probs = qfirst.question_problems("x", run, [247, 248, 105], [])
        self.assertIn("does not need the formula 'second virial coefficient",
                      qfirst.explain(probs[0], [247, 248, 105]))


class TokenBudgets(unittest.TestCase):
    def test_every_coder_call_has_the_coders_budget(self):
        seen = []

        def ask(role, model, system, user, **kw):
            seen.append((role, model, kw.get("max_tokens")))
            return {"feasible": True, "problem": ""}
        with mock.patch.object(models, "ask_json", ask):
            qfirst.design_problem({"situation": "s", "links": "l", "asked": "a"}, "lib")
        self.assertEqual(seen[0][2], models.coder_tokens(models.CODER))
        self.assertGreaterEqual(seen[0][2], 4000)


class LevelCheck(unittest.TestCase):
    Q = {"stem": "A [[m]] g sample gives [[V]] L of gas. Find M.", "free": {"m": 2.5}, "derived": ["V"]}

    def test_the_reader_sees_the_writers_values_and_dots_for_the_rest(self):
        self.assertEqual(qfirst.preview_text(self.Q), "A 2.50 g sample gives … L of gas. Find M.")

    def test_off_until_calibrated_then_below_the_floor_goes_back_to_the_writer(self):
        with mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: None):
            self.assertIsNone(qfirst.level_problem(self.Q))                 # no calibration: never blocks
        with mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: 2.8), \
                mock.patch.object(qf_checks, "jev_level", lambda text: 1.4), mock.patch("builtins.print"):
            why = qfirst.level_problem(self.Q)
        self.assertIn("JEE Main", why)
        self.assertIn("non-obvious", why)
        with mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: 2.8), \
                mock.patch.object(qf_checks, "jev_level", lambda text: 3.3), mock.patch("builtins.print"):
            self.assertIsNone(qfirst.level_problem(self.Q))
        with mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: 2.8), \
                mock.patch.object(qf_checks, "jev_level", lambda text: None):
            self.assertIsNone(qfirst.level_problem(self.Q))                 # Jev down: never blocks

    def test_score_request_shape(self):
        from core.pipeline import refine
        sent = {}

        def post(state, questions, role):
            sent.update(questions)
            return {"level": {"type": "score", "score": 3.2, "confidence": 0.6,
                              "probabilities": {"0": 0, "1": 0.05, "2": 0.15, "3": 0.35, "4": 0.45}}}
        with mock.patch.object(refine, "_jev_post", post):
            out = refine.jev_score({"exam_question": "q"}, qfirst.LEVEL_INSTRUCTIONS, qfirst.LEVELS)
        self.assertEqual(sent["level"]["type"], "score")
        self.assertEqual(sent["level"]["criteria"], qfirst.LEVELS)                # lowest level first
        self.assertEqual(out["score"], 3.2)
        self.assertAlmostEqual(sum(out["probabilities"].values()), 1.0)


class CoherenceCuts(unittest.TestCase):
    def test_each_fault_has_its_own_calibrated_cut(self):
        from core.pipeline import refine
        p = {"invented_relation": 0.30, "glued_parts": 0.30, "arbitrary_condition": 0.30}
        with mock.patch.object(refine, "jev_decide", lambda *a, **k: p):
            with mock.patch.object(qf_checks, "_coherence_cuts", lambda *a, **k: {k: 0.5 for k in qfirst.COHERENCE_QUESTIONS}):
                self.assertEqual(qfirst.coherence_problems("q"), [])                 # 30 % < 50 %
            with mock.patch.object(qf_checks, "_coherence_cuts", lambda *a, **k: {"invented_relation": 0.25, "glued_parts": 0.9,
                                                                       "arbitrary_condition": 0.9}):
                probs = qfirst.coherence_problems("q")
        self.assertEqual(len(probs), 1)
        self.assertIn("invented relation", probs[0])

    def test_without_a_calibration_file_the_old_cut_applies(self):
        with mock.patch("builtins.open", side_effect=OSError):
            self.assertEqual(qfirst._coherence_cuts(), {k: qfirst.COHERENCE_REJECT_AT for k in qfirst.COHERENCE_QUESTIONS})


class HonestLabels(unittest.TestCase):
    """GLM first: the ladder alone cannot tell hard Mains from Advanced; the calibrated level check decides."""

    def _label(self, floor, level):
        from core.pipeline import flow
        captured = {}
        with mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: floor), \
                mock.patch.object(qf_checks, "jev_level", lambda text: level), mock.patch("builtins.print"):
            # the labelling lines of flow._judge, run on their own
            label = models.DIFFICULTY_LABELS.get("glm-5.3-flash", "hard_advanced")
            if label == "advanced":
                f = qf_checks._level_floor()
                if f is None:
                    label = "advanced_or_mains_hard"
                else:
                    lv = qf_checks.jev_level("q")
                    label = "advanced_or_mains_hard" if lv is None else ("advanced" if lv >= f else "mains_hard")
        return label

    def test_labels(self):
        self.assertEqual(self._label(None, None), "advanced_or_mains_hard")
        self.assertEqual(self._label(2.8, 3.4), "advanced")
        self.assertEqual(self._label(2.8, 2.1), "mains_hard")
        self.assertEqual(self._label(2.8, None), "advanced_or_mains_hard")

    def test_flow_uses_the_same_rule(self):
        import inspect
        from core.pipeline import flow
        src = inspect.getsource(flow._judge)
        self.assertIn('"advanced" if jev_lvl >= floor else "mains_hard"', src)


class Budget(unittest.TestCase):
    def test_a_run_stops_at_its_spending_cap(self):
        with mock.patch.object(models.SPEND, "by_role", {"x": {"cost": 0.13}}):
            self.assertTrue(qfirst.over_budget(0.12))
            self.assertFalse(qfirst.over_budget(0.20))
            self.assertFalse(qfirst.over_budget(None))


class Coherence(unittest.TestCase):
    def setUp(self):
        # fixed cut-offs: these tests check the logic, not whatever knowledge/coherence_calibration_physical.json holds
        p = mock.patch.object(qf_checks, "_coherence_cuts", lambda *a, **k: {k: 0.5 for k in qfirst.COHERENCE_QUESTIONS})
        p.start()
        self.addCleanup(p.stop)

    GLUED = ("... In a separate gas-phase equilibrium, ΔG° is related to the percentage purity P of the sample and "
             "the number of peaks N in the radial distribution curve by ΔG° = −(P × N × 100) J mol⁻¹ ...")

    def test_invented_relation_is_rejected(self):
        with mock.patch("core.pipeline.refine.jev_decide",
                        lambda state, qs, role="": {"invented_relation": 0.93, "glued_parts": 0.81}):
            probs = qfirst.coherence_problems(self.GLUED)
        self.assertEqual(len(probs), 2)
        self.assertIn("invented relation", probs[0])

    def test_arbitrary_condition_is_rejected(self):
        with mock.patch("core.pipeline.refine.jev_decide",
                        lambda state, qs, role="": {"invented_relation": 0.2, "glued_parts": 0.2,
                                                    "arbitrary_condition": 0.88}):
            probs = qfirst.coherence_problems("... until the heat absorbed equals 1.20% of the electrical energy ...")
        self.assertEqual(len(probs), 1)
        self.assertIn("arbitrary condition", probs[0])

    def test_given_exponential_is_a_giveaway(self):
        from core.pipeline import gate
        self.assertEqual(gate.computed_values("(Given: e^2.3214 = 10.19; ln 2 = 0.693)"), ["e^2.3214 = 10.19"])

    def test_real_chemistry_passes(self):
        with mock.patch("core.pipeline.refine.jev_decide",
                        lambda state, qs, role="": {"invented_relation": 0.04, "glued_parts": 0.1,
                                                    "arbitrary_condition": 0.05}):
            self.assertEqual(qfirst.coherence_problems(STEM), [])

    def test_jev_unreachable_never_blocks(self):
        def down(*a, **k):
            raise RuntimeError("no network")
        with mock.patch("core.pipeline.refine.jev_decide", down):
            self.assertEqual(qfirst.coherence_problems(STEM), [])

    def test_writer_is_told_never_to_invent_a_relation(self):
        seen = {}

        def fake(role, model, system, user, **kw):
            seen["prompt"] = user
            return {"stem": STEM, "asks": "x", "unit": ""}
        with mock.patch.object(models, "ask_json", fake):
            qfirst.write_question("Physical Chemistry", "Formula 1: …", "", [], "inverse", [], [])
        self.assertIn("NEVER INVENT A RELATION", seen["prompt"])


class OwnQuestions(unittest.TestCase):
    """New questions are checked against our own accepted ones, and the writer is told which
    situations are already used on the same chapters."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "out.json")
        recs = [{"question_id": "GEN_A", "question_kind": "chain", "chapters": ["Thermodynamics"],
                 "question": STEM + " Give the answer in J K⁻¹, to 3 significant figures."},
                {"question_id": "GEN_F", "question_kind": "fact", "chapters": ["Thermodynamics"], "question": "facts"},
                {"question_id": "GEN_B", "question_kind": "chain", "chapters": ["Ionic Equilibrium"],
                 "question": "A 0.0250 M solution of formic acid ..."}]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(recs, f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_accepted_questions_and_situations(self):
        acc = qfirst.accepted_questions({"output_file": self.path})
        self.assertEqual([q["id"] for q in acc], ["GEN_A", "GEN_B"])          # fact questions left out
        self.assertNotIn("Give the answer", acc[0]["text"])
        used = qfirst.used_situations(acc, ["Thermodynamics", "Thermochemistry"])
        self.assertEqual(len(used), 1)
        self.assertTrue(used[0].startswith("Two 2.00 mol samples of argon"))
        self.assertEqual(qfirst.accepted_questions({"output_file": os.path.join(self.tmp, "none.json")}), [])

    def test_a_repeat_of_our_own_question_is_rejected(self):
        acc = qfirst.accepted_questions({"output_file": self.path})
        run = sandbox.evaluate(CODE, CHAIN)
        probs = qfirst.question_problems(STEM, run, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"], (), acc)
        self.assertTrue(any("repeats our own accepted question" in p and "GEN_A" in p for p in probs))
        self.assertEqual(qfirst.question_problems(STEM, run, CHAIN, ["R = 8.314 J K⁻¹ mol⁻¹"], (), acc[1:]), [])

    def test_writer_sees_the_used_situations(self):
        seen = {}

        def fake(role, model, system, user, **kw):
            seen["prompt"] = user
            return {"stem": STEM, "asks": "x", "unit": ""}
        with mock.patch.object(models, "ask_json", fake):
            qfirst.write_question("Physical Chemistry", "Formula 1: …", "", [], "inverse", [], [],
                                  used=["Two 2.00 mol samples of argon (Ar) ..."])
        self.assertIn("SITUATIONS ALREADY USED", seen["prompt"])
        self.assertIn("Two 2.00 mol samples of argon", seen["prompt"])


class FakeQModels:
    """Writer, coder, ladder and verifier replies for the question-first flow."""

    def __init__(self, council, stems=None, codes=None, fail_council=False, impossible_first=False):
        self.impossible_first = impossible_first
        self.council = council                       # slug -> answer
        self.stems = list(stems or [STEM])           # successive writer replies
        self.codes = list(codes or [CODE])           # successive coder replies
        self.fail_council = fail_council
        self.calls = []

    def __call__(self, role, model, system, user, **kw):
        self.calls.append(role)
        self.prompts = getattr(self, "prompts", []) + [(role, user)]
        if role == "designer":
            if self.impossible_first:
                self.impossible_first = False
                return {"impossible": "a Bohr orbit and an osmotic pressure share no system"}
            return {"designs": [{"situation": "two argon samples expanding at 300 K", "links": "w -> q -> ΔS_surr",
                                 "insight": "ΔS_surr depends only on the volume ratio", "asked": "difference (J K⁻¹)",
                                 "wrong_answers": "log10; sign", "twist": "two_state_difference"}], "best": 0}
        if role in ("generator", "refiner") and "Write ONE new numerical question" in user:
            stem = self.stems.pop(0) if len(self.stems) > 1 else self.stems[0]
            return {"stem": stem, "asks": "difference of the entropy changes of the surroundings",
                    "unit": "J K⁻¹", "solution_outline": "...", "how_it_differs": "..."}
        if role == "coder" and "Could a program compute" in user:
            ok = not getattr(self, "infeasible", 0)
            self.infeasible = max(0, getattr(self, "infeasible", 0) - 1)
            return {"feasible": ok, "problem": "" if ok else "step_54 only covers MnO2/HCl and Cl2/alkali"}
        if role == "coder":
            code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
            return {"code": code, "cannot": None}
        if role == "council":
            if self.fail_council and model == models.LADDER[2][1]:
                raise RuntimeError("503 provider overloaded")
            hinted = "A teacher adds this hint" in user
            ans = "8.49" if hinted else self.council[model]
            return {"working": f"ΔS = nR ln(20/12) = {ans}",
                    "answer": f"[TYPE: thermodynamics] [CALC_VALUE: {ans}] [CALC_UNIT: J K⁻¹] [SUBSTANCE: null]",
                    "objection": None}
        if role == "verifier":
            ans = re.search(r"STUDENT'S FINAL ANSWER: (\S+)", user).group(1)
            return {"verdict": "correct"} if ans.startswith("8.49") else \
                {"verdict": "wrong", "failure_type": "genuine_difficulty", "failed_step": 1}
        if role == "solution_checker":
            return {"errors": []}
        if role == "solution_writer":
            return {"solution": "ΔS_surr = −q/T = w/T; difference = nR ln(20/12) = 8.49 J K⁻¹."}
        raise AssertionError(f"unexpected call: {role}")


class QuestionFirstFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        cfg = entry.get_subject_config("physical")
        self.cfg = dict(cfg, output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))

        self.draws = 0
        self.drawn = CHAIN

        def fixed(self_adapter, chapter=None, exclude=()):
            self.draws += 1
            steps = [ph.step(t) for t in self.drawn]
            cand = {"edges": [f"e{t}_{self.draws}" for t in self.drawn], "nodes": [steps[0].src] + [s.dst for s in steps],
                    "chapters": ["Thermodynamics"], "txs": list(self.drawn), "trap_ids": [], "description": "",
                    "_steps": steps, "_plan": SimpleNamespace(steps=steps, constants=[], branches=())}
            return None if tuple(cand["edges"]) in exclude else cand

        self.patches = [
            mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
            mock.patch.object(models, "key_is_set", lambda *a: True),
            mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
            mock.patch.object(queues, "_OUT", self.tmp),
            mock.patch("tools.results.promote", lambda *a, **k: 0),
            mock.patch.object(adapters.PhysicalAdapter, "random_formulas", fixed),
            mock.patch.object(qfirst, "REQUIRE_PLACEHOLDERS", False),
            mock.patch.object(qf_draw, "FIT_CANDIDATES", 1),            # self.draws counts writing draws
            mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: None),   # tests never call Jev's level check
            mock.patch.object(qfirst, "coherence_problems", lambda stem, *a, **k: []),
            # never reach the real Jev from a test (the .env key is real): unavailable unless a test says
            mock.patch("core.pipeline.refine.jev_decide", self._jev_down),
            mock.patch("core.pipeline.refine.jev_choose", self._jev_down),
            mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
        ]
        for p in self.patches:
            p.start()
        self.dd = [mock.patch.object(dedup.duplicate_of, "__defaults__", (dedup.STORE,)),
                   mock.patch.object(dedup.record, "__defaults__", (dedup.STORE,))]
        for p in self.dd:
            p.start()

    @staticmethod
    def _jev_down(*a, **k):
        raise RuntimeError("Jev is not called in tests")

    def tearDown(self):
        for p in self.dd + self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, fake):
        with mock.patch.object(models, "ask_json", fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "physical", "--seed", "1",
                                                "--kind", "chains"]):
            return entry.main()

    def _records(self):
        if not os.path.exists(self.cfg["output_file"]):
            return []
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            return json.load(f)

    def _ladder(self, bottom="9.31"):
        s = [x for _, x in models.LADDER]
        return {s[0]: bottom, s[1]: "8.49", s[2]: "8.49"}

    def test_accepted_with_the_program_as_the_answer_key(self):
        fake = FakeQModels(self._ladder())
        self.assertEqual(self._run(fake), 0)
        r = self._records()
        self.assertEqual(len(r), 1)
        r = r[0]
        self.assertEqual(r["generation_mode"], "question_first")
        self.assertAlmostEqual(r["answer"], ANSWER, delta=0.01)
        self.assertIn("step_117", r["engine"]["solver_code"])
        self.assertTrue(r["engine"]["form"].startswith("question_first:"))
        self.assertTrue(r["question"].endswith("to 3 significant figures."))
        self.assertEqual(r["difficulty_label"], "advanced_or_mains_hard")   # level check not calibrated here
        self.assertEqual(fake.calls.count("coder"), 1)                 # one program (no design gates)

    def test_design_step_runs_once_and_the_writer_builds_on_it(self):
        fake = FakeQModels(self._ladder())
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(fake.calls.count("designer"), 1)
        writer = [u for r, u in fake.prompts if r == "generator" and "Write ONE new numerical question" in u]
        self.assertIn("by WRITING UP the design below", writer[0])
        self.assertIn("ΔS_surr depends only on the volume ratio", writer[0])        # the insight reaches it
        self.assertIn("two argon samples expanding at 300 K", writer[0])           # and the system
        self.assertNotIn("Real JEE Advanced questions with this twist", writer[0])  # no examples: the design has the level
        designer = [u for r, u in fake.prompts if r == "designer"][0]
        self.assertIn("HIDDEN LINK", designer)
        self.assertNotIn("[[", designer)                                          # no format rules for the designer
        self.assertNotIn("solution_outline", writer[0])                 # the writer's output is trimmed

    def test_the_designer_chooses_the_twist_and_the_writer_uses_it(self):
        fake = FakeQModels(self._ladder())
        self.assertEqual(self._run(fake), 0)
        designer = [u for r, u in fake.prompts if r == "designer"][0]
        self.assertIn("CHOOSE the one twist", designer)
        for t in qfirst.TWISTS:                                      # every twist is offered
            self.assertIn(f"- {t}: ", designer)
        writer = [u for r, u in fake.prompts if r == "generator" and "Write ONE new numerical question" in u]
        self.assertIn(qfirst.TWISTS["two_state_difference"], writer[0])   # the designer's choice
        for t, text in qfirst.TWISTS.items():
            if t != "two_state_difference":
                self.assertNotIn(text, writer[0])

    def test_the_designer_may_leave_out_one_of_four_formulas(self):
        """28 draws (2026-11-19): half died at design, often because one random formula did not fit. With 4-5
        drawn the designer may leave ONE out; with 3 it may not; a bad number is ignored."""
        from core.pipeline import qf_design
        reply = {"system": "s", "route": "r", "asked": "a", "twist": "inverse", "drop": 2}
        seen = []

        def fake(role, model, system, user, **kw):
            seen.append(user)
            return dict(reply)
        with mock.patch.object(models, "ask_json", fake), mock.patch("builtins.print"):
            four = qf_design.design_question("Physical Chemistry", "F", None, examples={}, n_formulas=4)
            three = qf_design.design_question("Physical Chemistry", "F", None, examples={}, n_formulas=3)
            reply["drop"] = 7
            bad = qf_design.design_question("Physical Chemistry", "F", None, examples={}, n_formulas=4)
        self.assertEqual((four["drop"], three["drop"], bad["drop"]), (2, None, None))
        self.assertIn("you may leave it out", seen[0])
        self.assertNotIn("you may leave it out", seen[1])                     # 3 formulas: never

    def test_a_left_out_formula_is_gone_before_writing(self):
        from core.engine import physical as ph
        from core.pipeline import qf_design
        txs = [117, 357, 130, 23]
        cand = {"edges": [f"e{t}" for t in txs], "txs": txs, "drawn_txs": txs, "chapters": [],
                "_steps": [ph.step(t) for t in txs]}
        design = {"system": "two argon samples", "situation": "two argon samples", "route": "w -> q -> dS",
                  "asked": "dS", "twist": "two_state_difference", "drop": 4}
        writer_prompts = []

        def write(*a, **k):
            writer_prompts.append(a[1])
            raise ValueError("stop here")                    # only the writer's input is under test
        bb = mock.Mock(current=None)
        with mock.patch.object(qfirst, "design_question", lambda *a, **k: dict(design)), \
                mock.patch.object(qfirst, "design_problems", lambda d, *a, **k: None), \
                mock.patch.object(qfirst, "DESIGN_GATES", False), \
                mock.patch.object(qfirst, "write_question", write), \
                mock.patch.object(qfirst, "accepted_questions", lambda c: []), \
                mock.patch.object(qfirst, "WRITE_TRIES", 1), mock.patch("builtins.print"):
            qfirst.write_and_solve(SimpleNamespace(config={"display_name": "Physical Chemistry"}), cand, None, bb,
                                   random.Random(1))
        self.assertGreaterEqual(len(writer_prompts), 1)              # an unreadable reply is asked again
        self.assertNotIn(ph.step(23).asks, writer_prompts[0])                # formula 4 (tx 23) is gone
        self.assertIn(ph.step(117).asks, writer_prompts[0])

    def test_a_cut_off_design_is_finished_not_lost(self):
        """Run of 2026-11-19: ~7000 tokens of thinking, then the design cut off after 1202 characters ($0.09 lost).
        One finish-it call gets the partial text and the thinking, and the design is kept."""
        from core.llm import CutOffError
        from core.pipeline import qf_design
        partial = '{"twist": "inverse", "system": "a defected fcc metal M", "route": "Formula 1: Z = 5; Formula 2'
        calls = []

        def fake(role, model, system, user, **kw):
            calls.append((user, kw))
            if len(calls) == 1:
                raise CutOffError("reply cut off at the output limit", partial=partial, reasoning="plan: Z = 5 ...")
            return {"twist": "inverse", "system": "a defected fcc metal M", "route": "Formula 1: Z = 5; Formula 2: a",
                    "asked": "M (g mol^-1)"}
        with mock.patch.object(models, "ask_json", fake), mock.patch("builtins.print"):
            d = qf_design.design_question("Physical Chemistry", "Formula 1: ...", None, examples={})
        self.assertEqual((d["system"], d["twist"]), ("a defected fcc metal M", "inverse"))
        self.assertEqual(len(calls), 2)
        finish, kw = calls[1]
        self.assertIn(partial, finish)                                  # it finishes what it wrote
        self.assertIn("plan: Z = 5", finish)                             # with its own thinking
        self.assertEqual((kw["max_tokens"], kw["reasoning_effort"]), (qf_design.FINISH_CAP, "low"))

    def test_a_cut_off_reply_carries_what_was_written(self):
        from core import llm
        msg = SimpleNamespace(content='{"system": "half a des', reasoning="the plan", model_extra={})
        resp = SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="length")], model="m")
        with mock.patch.object(llm, "_log_unparseable"):
            with self.assertRaises(llm.CutOffError) as cm:
                llm.call_json(lambda: resp, llm.parse_json, retry_cut_off=False)
        self.assertEqual((cm.exception.partial, cm.exception.reasoning), ('{"system": "half a des', "the plan"))

    def test_a_design_without_a_twist_is_kept_and_a_random_twist_used(self):
        from core.pipeline import qf_design
        reply = {"system": "two argon samples", "route": "w -> q -> ΔS", "asked": "ΔS (J K⁻¹)"}
        with mock.patch.object(models, "ask_json", lambda *a, **k: dict(reply)), mock.patch("builtins.print"):
            d = qf_design.design_question("Physical Chemistry", "Formula 1: ...", None, examples={})
            fixed = qf_design.design_question("Physical Chemistry", "Formula 1: ...", "inverse", examples=[])
        self.assertEqual(d["system"], "two argon samples")           # the paid-for design is kept
        self.assertNotIn("twist", d)                                 # write_and_solve then picks one at random
        self.assertEqual(fixed["twist"], "inverse")                  # a fixed twist (a refinement) stays

    def test_one_design_per_draw_a_rejected_design_means_new_formulas(self):
        self.patches.append(mock.patch.object(qfirst, "DESIGN_GATES", True))
        self.patches[-1].start()
        fake = FakeQModels(self._ladder())
        fake.infeasible = 1                                         # the first design is rejected
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(self.draws, 2)                             # not redesigned: a new draw
        self.assertEqual(fake.calls.count("designer"), 2)
        self.assertEqual(len(self._records()), 1)

    def test_infeasible_design_is_redesigned_before_any_writing(self):
        self.patches.append(mock.patch.object(qfirst, "DESIGN_GATES", True))
        self.patches[-1].start()
        self.patches.append(mock.patch.object(qfirst, "DESIGN_TRIES", 2))    # the redesign mechanism
        self.patches[-1].start()
        fake = FakeQModels(self._ladder())
        fake.infeasible = 1                                         # the first design cannot be computed
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(fake.calls.count("designer"), 2)
        second = [u for r, u in fake.prompts if r == "designer"][1]
        self.assertIn("An earlier design was rejected", second)
        self.assertIn("step_54 only covers", second)
        self.assertEqual(len(self._records()), 1)

    def test_formulas_no_design_can_use_are_redrawn(self):
        self.patches.append(mock.patch.object(qfirst, "DESIGN_GATES", True))
        self.patches[-1].start()
        self.patches.append(mock.patch.object(qfirst, "DESIGN_TRIES", 2))
        self.patches[-1].start()
        fake = FakeQModels(self._ladder())
        fake.infeasible = 2                                         # both designs fail: new formulas
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(self.draws, 2)

    def test_nonsense_bottom_answer_is_asked_again_then_does_not_count(self):
        s = [x for _, x in models.LADDER]
        fake = FakeQModels({s[0]: "3.81e+28", s[1]: "8.49", s[2]: "8.49"})
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(self._records(), [])                           # GLM solved: too easy, never "advanced"
        self.assertGreaterEqual(fake.calls.count("council"), 3)

    def test_coder_provider_down_does_not_crash_the_run(self):
        class Down(FakeQModels):
            def __call__(self, role, model, system, user, **kw):
                if role == "coder":
                    self.calls.append(role)
                    raise RuntimeError("502 Provider returned error")
                return super().__call__(role, model, system, user, **kw)
        fake = Down(self._ladder())
        self.assertEqual(self._run(fake), 0)                         # no crash: no question this run
        self.assertEqual(self._records(), [])

    def test_coder_call_names_a_fallback_model(self):
        seen = {}

        def fake(role, model, system, user, **kw):
            seen.update(kw)
            return {"code": CODE}
        with mock.patch.object(models, "ask_json", fake):
            qfirst.write_program(STEM, "x", "J K⁻¹", "lib")
        self.assertEqual(tuple(seen["fallbacks"]), models.CODER_FALLBACKS)

    def test_the_best_scored_formula_set_is_written(self):
        from core.pipeline import refine
        fake = FakeQModels(self._ladder())
        roles = []

        def jev(state, questions, role="refiner"):
            roles.append(role)
            if role == "formula_fit":
                return {"one_situation": 0.2}
            raise RuntimeError("Jev down")

        with mock.patch.object(refine, "jev_decide", jev):
            self._run(fake)
        self.assertGreaterEqual(roles.count("formula_fit"), 1)
        self.assertIn("designer", fake.calls)                         # a low score never stops the writing

    class Blank(FakeQModels):
        """The writer gives blanks with ranges; coder 2 writes ENTROPY; the ladder and the verifier answer
        from the numbers the question prints."""
        PICK = re.compile(r"Two ([\d.]+) mol samples of argon \(Ar\), each at ([\d.]+) K and ([\d.]+) L, expand "
                          r"isothermally and reversibly, one to ([\d.]+) L and the other to ([\d.]+) L")

        def __call__(self, role, model, system, user, **kw):
            if role in ("generator", "refiner") and "Write ONE new numerical question" in user:
                self.calls.append(role)
                self.prompts = getattr(self, "prompts", []) + [(role, user)]
                self.writes = getattr(self, "writes", 0) + 1
                if self.writes == 1 and getattr(self, "plain_first", False):
                    return {"stem": STEM, "asks": "the difference", "unit": "J K⁻¹", "asked": "d"}
                return {"stem": BLANK_STEM, "asks": "difference of the entropy changes of the surroundings",
                        "unit": "J K⁻¹", "asked": "d", "answer_range": [0.1, 1000],
                        "values": {**{k: {"range": [lo, hi]} for k, (lo, hi, _) in RANGES.items()},
                                   "R": {"value": 8.314}}}
            if role == "coder":
                self.calls.append(role)
                return {"code": ENTROPY}
            if role == "council":
                self.calls.append(role)
                if self.fail_council and model == models.LADDER[2][1]:
                    raise RuntimeError("503 provider overloaded")
                n, T, V1, Va, Vb = (float(x) for x in self.PICK.search(user).groups())
                self.correct = n * 8.314 * math.log(Vb / Va)
                bottom = model in getattr(self, "wrong", {models.LADDER[0][1]}) and "A teacher adds this hint" not in user
                ans = f"{self.correct * (1.5 if bottom else 1):.4g}"
                return {"working": "...", "objection": None,
                        "answer": f"[TYPE: x] [CALC_VALUE: {ans}] [CALC_UNIT: J K⁻¹] [SUBSTANCE: null]"}
            if role == "verifier":
                self.calls.append(role)
                ans = float(re.search(r"STUDENT'S FINAL ANSWER: ([-\d.eE+]+)", user).group(1))
                return {"verdict": "correct"} if abs(ans - self.correct) <= 0.01 * self.correct else \
                    {"verdict": "wrong", "failure_type": "genuine_difficulty", "failed_step": 1}
            if role == "solution_writer":
                return {"solution": f"ΔS_surr(1) − ΔS_surr(2) = nR ln(V_b/V_a) = {self.correct:.4g} J K⁻¹."}
            return super().__call__(role, model, system, user, **kw)

    def test_blanks_then_program_then_numbers(self):
        fake = self.Blank(self._ladder())
        fake.plain_first = True
        with mock.patch.object(qfirst, "REQUIRE_PLACEHOLDERS", True):
            self.assertEqual(self._run(fake), 0)
        self.assertEqual(fake.writes, 2)                               # numbers written out: sent back once
        self.assertEqual(fake.calls.index("coder"), fake.calls.index("generator") + 2)   # no coder for the first
        r = self._records()[0]
        self.assertNotIn("[[", r["question"])
        self.assertIn("R = 8.314 J", r["question"])
        n, T, V1, Va, Vb = (float(x) for x in self.Blank.PICK.search(r["question"]).groups())
        for x, k in zip((n, T, V1, Va, Vb), RANGES):
            self.assertTrue(RANGES[k][0] <= x <= RANGES[k][1], k)
        self.assertAlmostEqual(r["answer"], n * 8.314 * math.log(Vb / Va), delta=0.01)
        self.assertEqual(r["engine"]["solver_code"].strip(), ENTROPY.strip())

    def test_a_parked_blank_question_is_rerun_on_its_own_values(self):
        with mock.patch.object(qfirst, "REQUIRE_PLACEHOLDERS", True):
            first = self.Blank(self._ladder(), fail_council=True)
            first.wrong = {models.LADDER[0][1], models.LADDER[1][1]}        # the top step is reached, and fails
            self.assertEqual(self._run(first), entry.EXIT_COUNCIL_FAILED)
            with open(self.cfg["pending_file"], encoding="utf-8") as f:
                pending = json.load(f)
            self.assertEqual(sorted(pending[0]["qfirst"]["preset"]), sorted(list(RANGES) + ["R"]))
            fake = self.Blank(self._ladder())
            fake.wrong = first.wrong
            self.assertEqual(self._run(fake), 0)
        self.assertNotIn("coder", fake.calls)                           # judged again, not rewritten
        r = self._records()[0]
        n, T, V1, Va, Vb = (float(x) for x in self.Blank.PICK.search(r["question"]).groups())
        self.assertAlmostEqual(r["answer"], n * 8.314 * math.log(Vb / Va), delta=0.01)

    def test_broken_program_is_rewritten_by_the_coder(self):
        bad = CODE.replace('    return dS(Va) - dS(Vb)', '    return step_117(n=n, T=T, V1=V1, V2=Va)["work"]')
        fake = FakeQModels(self._ladder(), codes=[bad, CODE])
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(len(self._records()), 1)
        self.assertEqual(fake.calls.count("coder"), 2)                 # a broken program, a good one

    def test_question_stating_an_intermediate_is_rewritten(self):
        leaky = STEM.replace("first expansion", "first expansion (in which the gas absorbs 4367 J)")
        fake = FakeQModels(self._ladder(), stems=[leaky, STEM])
        self.assertEqual(self._run(fake), 0)
        rec = self._records()[0]
        self.assertEqual(rec["question"].split(" Give the answer")[0], STEM)
        events = [e for c in rec["blackboard"] for e in c["events"] if e["stage"] == "question_rejected"]
        self.assertTrue(any("has to compute" in p for e in events for p in e["problems"]))

    def test_program_may_use_another_graph_formula(self):
        self.drawn = [117, 130, 1]                  # the program also needs 357 (q = −w) to connect them
        fake = FakeQModels(self._ladder(), stems=[STEM_MASS], codes=[CODE_MASS])
        self.assertEqual(self._run(fake), 0)
        r = self._records()[0]
        self.assertEqual(r["engine"]["txs"], [117, 130, 1, 357])
        self.assertEqual(r["engine"]["extra_txs"], [357])
        self.assertAlmostEqual(r["answer"], ANSWER, delta=0.01)

    def test_impossible_formulas_are_redrawn(self):
        fake = FakeQModels(self._ladder(), impossible_first=True)
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(len(self._records()), 1)
        self.assertEqual(self.draws, 2)

    def test_too_easy_is_rewritten_until_rounds_run_out(self):
        fake = FakeQModels(self._ladder(bottom="8.49"))
        wording = {"cue_word": 0.9, "ready_data": 0.8, "textbook_pattern": 0.7, "trivial_units": 0.65, "one_system": 0.4}
        with mock.patch("core.pipeline.refine.jev_choose", _choose(lambda q: wording.get(q, 0.0))):
            self.assertEqual(self._run(fake), 0)
        rewrites = [u for r, u in fake.prompts if r == "generator" and "REWRITE your earlier question" in u]
        self.assertTrue(any("Remove every word that names a law" in u for u in rewrites))
        self.assertTrue(any("Do not dress it up in a new setting" in u for u in rewrites))
        self.assertEqual(self._records(), [])
        # every draw: the first question and one rewrite per refinement round, all by the writer
        self.assertEqual(fake.calls.count("generator"), qfirst.MAX_DRAWS * 4)
        self.assertNotIn("refiner", fake.calls)                      # the decision is Jev's, not a chat model's

    def test_council_failure_parks_then_recheck_reruns_the_program(self):
        s = [x for _, x in models.LADDER]
        both_fail = {s[0]: "9.31", s[1]: "9.31", s[2]: "8.49"}
        self.assertEqual(self._run(FakeQModels(both_fail, fail_council=True)), entry.EXIT_COUNCIL_FAILED)
        with open(self.cfg["pending_file"], encoding="utf-8") as f:
            pending = json.load(f)
        self.assertEqual(len(pending), 1)
        self.assertIn("step_130", pending[0]["qfirst"]["code"])
        fake = FakeQModels(both_fail)
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(len(self._records()), 1)
        self.assertNotIn("coder", fake.calls)                           # judged again, not rewritten


class OneDraftPerDraw(unittest.TestCase):
    def test_two_drafts_and_unreadable_replies_do_not_count(self):
        """At most two drafts per draw (2026-11-22; one from 2026-11-19): drafts cost credits, so never more; a
        reply that cannot be read is a technical failure and is asked again without using up a draft."""
        from core.pipeline import qf_writer
        self.assertEqual(qf_writer.WRITE_TRIES, 2)
        self.assertGreaterEqual(qfirst.UNREADABLE_RETRIES, 1)

    def test_a_blank_slip_does_not_spend_the_unreadable_retry(self):
        """Review 2026-11-24: slips and garbled replies shared one count, so slip then garbled reply ended the
        draft. Now: slip (free), garbled (free), garbled (the draft) = 3 writer calls."""
        calls = []

        def write(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                return {"stem": "x is 5 mol", "asks": "x", "unit": ""}
            raise ValueError("garbled")
        bb = mock.Mock(current=None)
        with mock.patch.object(qfirst, "write_question", write), \
                mock.patch.object(qfirst, "level_problem", lambda q: None), \
                mock.patch.object(qfirst, "blank_problems", lambda q: ["write 5 as a blank"]), \
                mock.patch.object(qfirst, "accepted_questions", lambda c: []), \
                mock.patch.object(qfirst, "design_question", lambda *a, **k: {
                    "system": "argon", "situation": "argon", "route": "a -> b", "asked": "b",
                    "twist": "two_state_difference"}), \
                mock.patch.object(qfirst, "design_problems", lambda d, *a, **k: None), \
                mock.patch.object(qfirst, "DESIGN_GATES", False), \
                mock.patch.object(qfirst, "WRITE_TRIES", 1), \
                mock.patch.object(qfirst, "UNREADABLE_RETRIES", 1), mock.patch("builtins.print"):
            from core.engine import physical as ph
            txs = [117, 357]
            cand = {"edges": [f"e{t}" for t in txs], "txs": txs, "drawn_txs": txs, "chapters": [],
                    "_steps": [ph.step(t) for t in txs]}
            qfirst.write_and_solve(SimpleNamespace(config={"display_name": "Physical Chemistry"}), cand, "two_state_difference",
                                   bb, random.Random(1))
        self.assertEqual(len(calls), 3)


class NoRoundingInPrograms(unittest.TestCase):
    def test_a_rounded_computed_value_is_rejected(self):
        """Run of 2026-11-19: n = round(√(85.4/12.7)) = 3 slipped past the whole-number check of the formula and
        turned impossible stated data into a wrong key (88.61 for 85.4). A program may not round a computed value."""
        for expr in ("round(x)", "int(x / 2)", "math.floor(x)", "math.ceil(x)", "math.trunc(x)"):
            code = f"def solve():\n    x = given(2.59, 'n')\n    return {expr}\n"
            self.assertTrue(any("do not round" in p for p in sandbox.check_code(code, CHAIN)), expr)
        ok = "def solve():\n    return math.fabs(math.floor(-2.5)) + round(3.0)\n"           # written numbers: fine
        self.assertEqual(sandbox.check_code(ok, CHAIN), [])


if __name__ == "__main__":
    unittest.main()
