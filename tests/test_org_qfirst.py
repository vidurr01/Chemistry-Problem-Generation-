"""Organic question-first flow (core/pipeline/org_qfirst.py) and the property functions it checks claims with
(core/engine/organic/props.py): tree draws, the code key, and one run end to end with scripted models. Offline.
Run: python -m unittest tests.test_org_qfirst"""

import json
import os
import random
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dedup, models                                  # noqa: E402
from core.engine.organic import props as OP                     # noqa: E402
from core.engine.organic import rules as R                      # noqa: E402
from core.engine.organic.labels import REAGENT_LABEL            # noqa: E402
from core.engine.organic.mol import classes                     # noqa: E402
from core.pipeline import org_qfirst as OQ, queues              # noqa: E402
from subject_config import get_subject_config                   # noqa: E402

CFG = get_subject_config("organic")


def _adapter():
    return SimpleNamespace(config=dict(CFG, display_name="Organic Chemistry"), subject="organic")


class Props(unittest.TestCase):
    def a(self, s):
        return OP.askable(s)

    def test_stereo(self):
        self.assertEqual((self.a("CC(O)C(C)O")["stereocentres"], self.a("CC(O)C(C)O")["stereoisomers"]), (2, 3))  # meso
        self.assertTrue(self.a("CC=CC")["geometrical_isomerism"])
        self.assertFalse(self.a("C=CC")["geometrical_isomerism"])

    def test_tests(self):
        self.assertTrue(self.a("CCO")["iodoform_test"])
        self.assertTrue(self.a("CC=O")["iodoform_test"])
        self.assertFalse(self.a("CCCO")["iodoform_test"])
        self.assertTrue(self.a("O=Cc1ccccc1")["tollens_test"])
        self.assertFalse(self.a("O=Cc1ccccc1")["fehling_test"])
        self.assertTrue(self.a("O=Cc1ccccc1")["dnp_test"])
        self.assertEqual(self.a("CC(C)(C)O")["lucas_test"], "immediate turbidity")
        self.assertEqual(self.a("CNC")["amine_class"], "secondary")
        self.assertEqual(self.a("Oc1ccccc1")["pi_bonds"], 3)

    def test_compare(self):
        self.assertTrue(OP.compare("stereoisomers", 3, "3"))
        self.assertTrue(OP.compare("iodoform_test", True, "positive"))
        self.assertTrue(OP.compare("structure", "CCO", "OCC"))
        self.assertTrue(OP.compare("molecular_formula", "C2H6O", "C2H6O"))
        self.assertFalse(OP.compare("functional_group", ["alcohol"], "ketone"))


class Draw(unittest.TestCase):
    def test_tree_draws(self):
        ad, rng = _adapter(), random.Random(0)
        for _ in range(10):
            c = OQ.draw(ad, rng)
            self.assertIsNotNone(c)
            n = len(c["_order"]) - 1
            self.assertTrue(OQ.STEPS_MIN <= n <= OQ.STEPS_MAX, n)
            parents = [c["_comps"][k]["parent"] for k in c["_order"][1:]]
            self.assertTrue(any(parents.count(p) >= 2 for p in parents))                # a branch point
            for k in c["_order"][1:]:
                comp = c["_comps"][k]
                self.assertIn(comp["edge"]["to"], classes(comp["smiles"]))
            self.assertNotIn("[", OQ.scheme_text(c).split("\n")[0])

    def test_every_rule_has_a_label(self):
        self.assertEqual(set(R.RULES), set(REAGENT_LABEL))

    def test_evaluate_claims(self):
        c = OQ.draw(_adapter(), random.Random(3))
        lab = c["_order"][-1]
        f = c["_props"][lab]["molecular_formula"]
        claims = [{"text": "t", "compound": lab, "property": "molecular_formula", "value": f},
                  {"text": "f", "compound": lab, "property": "molecular_formula", "value": "C99H1"},
                  {"text": "f", "compound": "P", "property": "stereocentres", "value": "7"},
                  {"text": "f", "compound": "P", "property": "rings", "value": "9"}]
        res, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": claims})
        self.assertEqual(probs, [])
        self.assertEqual(res.answer, "A")
        _, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": claims[1:]})
        self.assertTrue(probs)
        res, probs = OQ.evaluate(c, {"format": "integer", "lead": "", "ask": "How many?",
                                     "claims": [{"compound": lab, "property": "stereoisomers"}]})
        self.assertEqual(res.answer, c["_props"][lab]["stereoisomers"])


class StartPicker(unittest.TestCase):
    """core/pipeline/org_start.py: the model invents the start, the engine checks it (2026-11-23)."""

    def test_engine_check(self):
        from core.pipeline import org_start as S
        ok, why, _ = S.check_start(_adapter(), "CCC", random.Random(1))
        self.assertFalse(ok)                                       # too small, one group
        ok, why, _ = S.check_start(_adapter(), "CCCCCCO", random.Random(1))
        self.assertFalse(ok)
        self.assertIn("only 1", why)                               # one group the reagents act on
        ok, why, st = S.check_start(_adapter(), "C=CCC(O)c1ccc(Br)cc1", random.Random(1))
        self.assertTrue(ok, why)
        self.assertTrue(OQ.STEPS_MIN <= st["scheme_steps"] <= OQ.STEPS_MAX)

    def test_draw_from_given_start_uses_every_group(self):
        c = OQ.draw(_adapter(), random.Random(3), start=("x", "CC(=O)CCC(=O)OCC"), attempts=300)
        self.assertIsNotNone(c)
        self.assertEqual(c["_start"][1], "CCOC(=O)CCC(C)=O")
        self.assertTrue(any(c["_comps"][k]["parent"] is not None for k in c["_order"][1:]))

    def test_refused_then_accepted_with_name_check(self):
        from core.pipeline import org_start as S
        replies = iter([{"name": "ethanol", "smiles": "CCO"},                                   # engine refuses
                        {"name": "1-(4-bromophenyl)but-3-en-1-ol", "smiles": "C=CCC(O)c1ccc(Br)cc1"}])
        prompts = []

        def fake(role, model, system, user, **kw):
            if role == "name_checker":
                return {"smiles": "OC(CC=C)c1ccc(Br)cc1"}         # same molecule, written differently
            prompts.append(user)
            return next(replies)
        with mock.patch.object(models, "ask_json", fake):
            p = S.pick_start(_adapter(), random.Random(1))
        self.assertEqual(p["tries"], 2)
        self.assertIn("was refused", prompts[1])                   # the picker is told why

    def test_name_mismatch_refused(self):
        from core.pipeline import org_start as S

        def fake(role, model, system, user, **kw):
            if role == "name_checker":
                return {"smiles": "C=CCC(O)c1ccc(Cl)cc1"}         # the name says chloro
            return {"name": "1-(4-chlorophenyl)but-3-en-1-ol", "smiles": "C=CCC(O)c1ccc(Br)cc1"}
        with mock.patch.object(models, "ask_json", fake):
            self.assertIsNone(S.pick_start(_adapter(), random.Random(1)))

    def test_no_exam_question_in_prompt(self):
        from core.pipeline import org_start as S
        seen = []

        def fake(role, model, system, user, **kw):
            seen.append(user)
            return {}
        with mock.patch.object(models, "ask_json", fake):
            S.pick_start(_adapter(), random.Random(1))
        self.assertTrue(seen)
        self.assertFalse(any("JEE" in u or "jee_advanced" in u for u in seen))


class EndToEnd(unittest.TestCase):
    """A whole organic run: tree draw -> designer -> writer claims -> code key -> ladder -> saved."""

    def setUp(self):
        import run_groundup_final as entry
        self.entry = entry
        self.tmp = tempfile.mkdtemp()
        self.cfg = dict(CFG, output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))
        self.cand = OQ.draw(_adapter(), random.Random(5))
        self.lab = self.cand["_order"][-1]
        self.p = [mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
                  mock.patch.object(models, "key_is_set", lambda *a: True),
                  mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
                  mock.patch.object(queues, "_OUT", self.tmp),
                  mock.patch("tools.results.promote", lambda *a, **k: 0),
                  mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
                  mock.patch("core.pipeline.qf_design.design_problems", lambda d, *a, **k: None),
                  mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: None),
                  mock.patch.object(OQ, "draw", lambda *a, **k: dict(self.cand)),
                  mock.patch("core.pipeline.org_start.pick_start",
                             lambda *a, **k: {"name": "propane", "smiles": "CCC", "why": "", "stats": {}, "tries": 1})]
        for x in self.p:
            x.start()
        store = dedup.STORE
        self.assertIn(self.tmp, str(store))
        self.p += [mock.patch.object(dedup.duplicate_of, "__defaults__", (store,)),
                   mock.patch.object(dedup.record, "__defaults__", (store,))]
        for x in self.p[-2:]:
            x.start()

    def tearDown(self):
        for x in reversed(self.p):
            x.stop()

    def fake(self, role, model, system, user, **kw):
        if role == "designer":
            return {"system": "a scheme", "hidden": {"Q": "an intermediate"}, "hidden_link": "each compound",
                    "route": "follow the scheme", "student_must_notice": "the branch", "trap": "a wrong formula",
                    "given": "the scheme", "asked": "formulas", "format": "msq"}
        if role == "generator" and "Write ONE JEE Advanced" in user:
            f = self.cand["_props"][self.lab]["molecular_formula"]
            claims = [{"text": f"{self.lab} is {f}", "compound": self.lab, "property": "molecular_formula", "value": f},
                      {"text": "wrong", "compound": self.lab, "property": "molecular_formula", "value": "C99H1"},
                      {"text": "wrong", "compound": "P", "property": "rings", "value": "9"},
                      {"text": "wrong", "compound": "P", "property": "stereocentres", "value": "7"}]
            return {"lead": "Consider the scheme.", "ask": "Which statements are correct?", "claims": claims}
        if role == "council":
            ans = "B" if model == models.LADDER[0][1] else "A"
            return {"working": "w", "answer": ans, "final_answer": ans}
        if role in ("solution_writer", "generator"):
            return {"solution": "Step 1 ...", "hint": "h"}
        if role == "solution_checker":
            return {"ok": True, "problems": []}
        return {}

    def test_run_accepts_and_saves(self):
        with mock.patch.object(models, "ask_json", self.fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            code = self.entry.main()
        self.assertEqual(code, 0)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            recs = json.load(f)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["subject"], "organic")
        self.assertEqual(r["answer"], "A")                          # computed by code
        self.assertIn("P = ", r["question"])                        # the scheme is printed by code


    def test_below_level_floor_is_dropped(self):
        # organic level check (knowledge/level_calibration_organic.json): below the floor, no ladder, nothing saved
        with mock.patch.object(models, "ask_json", self.fake),                 mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: 1.85),                 mock.patch("core.pipeline.qf_checks.jev_level", lambda *a, **k: 1.2),                 mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            self.entry.main()
        self.assertFalse(os.path.exists(self.cfg["output_file"]) and json.load(open(self.cfg["output_file"])))


if __name__ == "__main__":
    unittest.main()
