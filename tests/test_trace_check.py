"""trace_check.py and its use in flow._judge (docs/implementation_spec_2026-11-25.md §2-§3)."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from core import models
from core.pipeline import queues, trace_check
from tests.test_pipeline_offline import FakeModels, _Env


class Labels(unittest.TestCase):
    def test_trap_match(self):
        res = SimpleNamespace(traps=[{"id": "x", "wrong_answer": 1.91}])
        self.assertTrue(trace_check.trap_match(res, {"final_answer": "1.9 g"}))
        self.assertFalse(trace_check.trap_match(res, {"final_answer": "0.32 g"}))
        self.assertFalse(trace_check.trap_match(SimpleNamespace(traps=None), {"final_answer": "1.9"}))

    def test_quote_found(self):
        w = "24.4 close to Na 22.99.  So answer ~23.0 g/mol."
        self.assertTrue(trace_check.quote_found("24.4 close to Na 22.99. So answer", w))
        self.assertFalse(trace_check.quote_found("Na", w))                       # too short to prove anything
        self.assertFalse(trace_check.quote_found("the data contradict", w))

    def _check(self, reply):
        member = {"name": "granite", "final_answer": "23", "working": "24.4 close to Na 22.99. So answer ~23.0"}
        fake = (lambda *a, **k: reply) if not isinstance(reply, Exception) else mock.Mock(side_effect=reply)
        with mock.patch.object(models, "ask_json", fake):
            return trace_check.check_member("stem", "24.4", member)

    def test_check_member(self):
        self.assertEqual(self._check({"label": "question_flawed", "quote": "24.4 close to Na 22.99",
                                      "reason": "no alkali metal"})["label"], "question_flawed")
        self.assertEqual(self._check({"label": "slip", "quote": "not in the working at all",
                                      "reason": "x"})["label"], "unexplained")
        self.assertEqual(self._check({"label": "nonsense", "quote": "24.4 close to Na", "reason": "x"})["label"],
                         "unchecked")
        self.assertEqual(self._check(RuntimeError("503"))["label"], "unchecked")

    def test_label_failures_skips_solved(self):
        graded = [{"name": "a", "answer_matches": True, "counts_as_solved": True, "final_answer": "2"},
                  {"name": "b", "answer_matches": False, "counts_as_solved": False, "final_answer": "1.91",
                   "working": "w"}]
        res = SimpleNamespace(traps=[{"wrong_answer": 1.91}])
        with mock.patch.object(models, "ask_json", mock.Mock(side_effect=AssertionError("no call expected"))):
            trace_check.label_failures(res, "stem", "2", graded)
        self.assertNotIn("failure_label", graded[0])
        self.assertEqual(graded[1]["failure_label"], "trap")


class RateUnits(unittest.TestCase):
    """qf_checks.rate_unit_problems (spec §4.1): 022806's N₂O₄ ⇌ 2NO₂ with k_b printed in s⁻¹."""

    TRACE = [{"tx": 210, "inputs": {"rate_constant": 0.101, "kb": 1.63}, "outputs": {"equilibrium_constant": 0.062}}]
    STEM = ("Pure N₂O₄ is introduced at 2.30 atm and 303 K. For N₂O₄(g) ⇌ 2NO₂(g), the forward and reverse rate "
            "constants are 0.101 {u} and 1.63 {u2}, respectively. Find the temperature.")

    def test_flagged_when_orders_differ(self):
        from core.pipeline import qf_checks
        self.assertTrue(qf_checks.rate_unit_problems(self.STEM.format(u="s^-1", u2="s^-1"), self.TRACE))
        self.assertTrue(qf_checks.rate_unit_problems(self.STEM.format(u="s⁻¹", u2="s⁻¹"), self.TRACE))

    def test_not_flagged(self):
        from core.pipeline import qf_checks
        ok_units = self.STEM.format(u="s⁻¹", u2="atm⁻¹ s⁻¹")
        self.assertEqual(qf_checks.rate_unit_problems(ok_units, self.TRACE), [])
        same_sides = ("For A(g) ⇌ B(g) the forward and reverse rate constants are 0.101 s⁻¹ and 1.63 s⁻¹.")
        self.assertEqual(qf_checks.rate_unit_problems(same_sides, self.TRACE), [])
        self.assertEqual(qf_checks.rate_unit_problems(self.STEM.format(u="s⁻¹", u2="s⁻¹"), []), [])


class ObjectingModels(FakeModels):
    """Granite fails and objects that the data contradict (the 031247 case)."""

    def __call__(self, role, model, system, user, **kw):
        out = super().__call__(role, model, system, user, **kw)
        if role == "council" and model == models.LADDER[0][1]:
            out = dict(out, objection={"type": "chemistry", "detail": "the stated data contradict each other"})
        return out


class CheckerModels(FakeModels):
    """Granite fails; the trace checker answers with a fixed label quoting Granite's working."""

    def __init__(self, label, **kw):
        super().__init__(**kw)
        self.label = label

    def __call__(self, role, model, system, user, **kw):
        if role == "trace_checker":
            self.calls.append(role)
            return {"label": self.label, "quote": "n = 4.4/44 = 0.1 mol", "reason": "scripted"}
        return super().__call__(role, model, system, user, **kw)


class InPipeline(_Env, unittest.TestCase):
    def _answers(self):
        s = [x for _, x in models.LADDER]
        return {s[0]: "3.17", s[1]: "2.24", s[2]: "2.24"}      # 3.17: wrong, and not one of the engine's traps

    def _held(self):
        p = queues.path("question_flawed", "physical")
        return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []

    def test_objection_holds_the_question(self):
        fake = ObjectingModels(council_answers=self._answers(), verdicts={"2.24": {"verdict": "correct"}})
        self._run(fake)
        self.assertEqual(self._records(), [])
        held = self._held()
        self.assertTrue(held)
        self.assertEqual(held[0]["item"]["found_by"] if "item" in held[0] else held[0]["found_by"], "objection")
        self.assertNotIn("trace_checker", fake.calls)          # an objection holds without a checker call

    def test_flawed_label_holds_the_question(self):
        fake = CheckerModels("question_flawed", council_answers=self._answers(),
                             verdicts={"2.24": {"verdict": "correct"}})
        self._run(fake)
        self.assertEqual(self._records(), [])
        self.assertTrue(self._held())

    def test_slip_is_not_difficulty(self):
        fake = CheckerModels("slip", council_answers=self._answers(), verdicts={"2.24": {"verdict": "correct"}})
        self._run(fake)
        self.assertEqual(self._records(), [])                    # Granite's slip does not make it hard
        self.assertEqual(self._held(), [])

    def test_concept_is_accepted_and_saved(self):
        fake = CheckerModels("concept", council_answers=self._answers(), hint_answers={models.LADDER[0][1]: "2.24"},
                             verdicts={"2.24": {"verdict": "correct"}})
        self.assertEqual(self._run(fake), 0)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["council"][0]["failure_label"], "concept")


if __name__ == "__main__":
    unittest.main()


class InorganicTwins(unittest.TestCase):
    """I3 (live review 2026-11-26): refusing P4_to_PH3_p also refuses its duplicate P4_to_PH3_p_2."""

    def test_twins(self):
        import random
        import run_groundup_final as entry
        from core.pipeline import adapters, inorg_qfirst as IQ
        g = IQ._graph(adapters.InorganicAdapter(entry.get_subject_config("inorganic"), random.Random(1)))
        self.assertEqual(IQ._with_twins(g, {"P4_to_PH3_p"}), {"P4_to_PH3_p", "P4_to_PH3_p_2"})
        self.assertEqual(IQ._with_twins(g, {"P4_to_P4O10_p"}), {"P4_to_P4O10_p"})


class ProductOtherForm(unittest.TestCase):
    """inorg_products.other_form (live review 2026-11-26, round 2): the same product in another form is accepted only
    when the asked property cannot change."""

    def test_cases(self):
        from core.pipeline import inorg_products as P
        cases = [("Na2ZnO2", "Zn", "magnetism", "[Zn(OH)4]", -2, True),     # + 2 H2O, both d10 diamagnetic
                 ("BO2-", "B", "geometry", "NaBO2", 0, True),               # Na+ spectator, both linear
                 ("H2SO3", "S", "geometry", "SO2", 0, False),              # + H2O but pyramidal vs bent
                 ("NO2", "N", "geometry", "HNO2", 0, False),               # N +4 vs +3
                 ("H2O", "O", "geometry", "O2", 0, False),
                 ("Cu(OH)2", "Cu", "magnetism", "[Cu(NH3)4]SO4", 0, False)]  # a different product
        for ours, el, fam, f, q, want in cases:
            row = {"edge": {"to": ours}, "element": el, "family": fam}
            self.assertEqual(P.other_form(row, f, q), want, (ours, f))


class StyleExamples(unittest.TestCase):
    """style_examples (reviewer, 2026-11-26): real stems for wording only; a copied run of words is caught."""

    def test_stems_and_copy_check(self):
        import random
        from core.pipeline import style_examples as SE
        ex = SE.stems("organic", "msq", random.Random(1))
        self.assertEqual(len(ex), 3)
        self.assertIsNotNone(SE.copied("Intro. " + ex[0], ex))
        self.assertIsNone(SE.copied("Which of the following statement(s) is(are) correct about compound S?", ex))
        self.assertIn("WORDING AND STYLE ONLY", SE.block(ex))
        self.assertEqual(SE.block([]), "")


class OrganicDecorativeStep(unittest.TestCase):
    """O1 (live review 2026-11-26): round 1's Q --NaI--> R --NaCN--> S; NaCN on Q gives the same S, so R is decoration."""

    def test_round1_nai_step(self):
        import random
        import run_groundup_final as entry
        from core.pipeline import adapters, org_qfirst as OQ
        g = OQ._graph(adapters.OrganicAdapter(entry.get_subject_config("organic"), random.Random(1)))
        steps = [("Q", "P", "ketone_to_ester_mcpbametachl"), ("R", "Q", "alkyl_halide_to_alkyl_halide_nai"),
                 ("S", "R", "alkyl_halide_to_nitrile_nacn"), ("T", "Q", "alkyl_halide_to_nitro_compound_agno2silvern")]
        comps, order = {"P": {"smiles": OQ.canon("CC(=O)c1ccc(CCBr)cc1"), "parent": None, "edge": None}}, ["P"]
        for lab, par, eid in steps:
            e = g["edges"][eid]
            comps[lab] = {"smiles": OQ.canon(OQ.R.apply(e, comps[par]["smiles"]).product), "parent": par, "edge": e}
            order.append(lab)
        self.assertEqual(OQ.decorative_steps(comps, order), ["R"])
        del comps["S"], comps["R"]                                    # without the NaI step nothing is decorative
        self.assertEqual(OQ.decorative_steps(comps, ["P", "Q", "T"]), [])
