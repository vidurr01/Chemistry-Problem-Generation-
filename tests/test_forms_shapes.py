"""
Trees and conditions through the engine and the pipeline layer, offline.

A tree is two branches merged by one step (core.engine.base.plan_tree); a condition is two
systems compared by forms.compare_step, asked for the input at which they are equal. Both are
ordinary ChainPlans, so run_chain, traps, tolerance, the gate spec and grading work unchanged.
"""

import dataclasses
import json
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.coverage import Coverage                              # noqa: E402
from core.engine import forms                                   # noqa: E402
from core.engine.base import EngineError, links, plan_tree, run_chain   # noqa: E402
from core.engine.physical import BRIDGES, step                  # noqa: E402
from core.pipeline import flow, forms_layer                     # noqa: E402
from core.pipeline.adapters import COMPARE_UNITS, CONDITION_UNITS, PhysicalAdapter   # noqa: E402

EQ = "SnO2 + C -> Sn + CO2"
SNO2 = {"s0.balanced_equation": EQ,
        "s0.formation_enthalpies": {"SnO2": -581.0, "C": 0, "Sn": 0, "CO2": -394.0},
        "s1.standard_entropies": {"SnO2": 56.0, "C": 6.0, "Sn": 52.0, "CO2": 210.0}}


class TreePlans(unittest.TestCase):
    def test_2020_P2_Q17_as_one_plan(self):
        """ΔH (Hess) and ΔS (entropies) as two branches, T = ΔH/ΔS merging them: 935 K. The
        equation both branches state is one given."""
        p = plan_tree([[step(139)], [step(131)]], step(133), {"delta_h": 0, "delta_s": 1})
        self.assertEqual(set(p.givens), set(SNO2))
        self.assertEqual(p.wiring[2], {"delta_h": ("step", (0, "delta_h")), "delta_s": ("step", (1, "delta_s"))})
        r = run_chain(p, SNO2)
        self.assertAlmostEqual(r.answer, 935, places=0)
        self.assertEqual([t["tx"] for t in r.trace], [139, 131, 133])

    def test_branch_traps_reach_the_answer(self):
        """A mistake in a branch changes the merged answer (traps run through the later
        branch and the final step)."""
        p = plan_tree([[step(139)], [step(131)]], step(132), {"delta_h": 0, "delta_s": 1})
        r = run_chain(p, {**SNO2, "s2.T": 298.0})
        self.assertTrue(r.traps)
        for t in r.traps:
            self.assertFalse(math.isclose(t["wrong_answer"], r.answer, rel_tol=0.01))

    def test_refuses_a_stated_value_another_branch_computes(self):
        with self.assertRaises(EngineError):
            plan_tree([[step(139)], [step(131)]], step(133), {"delta_h": 0, "delta_s": 0})

    def test_kb_of_a_solvent_is_not_a_base_constant(self):
        """ΔT_b = i K_b m handed its K_b to the pH steps (both called "Kb")."""
        for t in (176, 181, 183):
            self.assertFalse(links(step(262), step(t), BRIDGES), t)


class Conditions(unittest.TestCase):
    def _apply(self, plan, vals, unknown, shared=False, seed=1):
        spec = PhysicalAdapter.input_spec(plan)
        cand = {"_plan": plan, "_shape": {"kind": "condition", "unknown": unknown, "shared": shared}}
        return forms_layer.apply_form(None, cand, spec, vals, run_chain(plan, vals), random.Random(seed))

    def test_rms_speed_temperature(self):
        """O₂ at T has the rms speed of N₂ at the stated temperature: T comes back exactly
        as the value the generator chose, and is not stated."""
        p = forms.plan_condition([step(98)], [step(98)], "s0.temperature")
        vals = {"s0.temperature": 400.0, "s0.molar_mass": 32.0, "s1.temperature": 300.0, "s1.molar_mass": 28.0}
        spec, v2, r = self._apply(p, vals, "s0.temperature")
        self.assertEqual(r.form, "condition")
        self.assertAlmostEqual(r.answer, 400, delta=4)
        self.assertNotIn("s0.temperature", v2)
        self.assertEqual({s["key"] for s in spec}, set(v2))
        self.assertEqual(v2["s0.molar_mass"], 32.0)           # substances unchanged; a temperature was set
        self.assertEqual(v2["s1.molar_mass"], 28.0)
        self.assertAlmostEqual(r.trace[-1]["outputs"]["difference"], 0, places=6)
        self.assertNotIn(str(r.answer), r.stem_note)
        descs = [s["desc"] for s in spec]
        self.assertEqual(len(descs), len(set(descs)))           # "first system" / "second system"

    def test_degenerate_condition_refused(self):
        """π = iCRT for two solutions sharing T: equal at every T or at none."""
        p = forms.plan_condition([step(265)], [step(265)], "s0.T", "s0.T")
        vals = {"s0.molarity": 0.1, "s0.T": 300.0, "s0.vant_hoff_factor": 1.0,
                "s1.molarity": 0.05, "s1.vant_hoff_factor": 2.0}
        self.assertIsNone(self._apply(p, vals, "s0.T", shared=True))

    def test_avoid_does_not_remove_the_only_form(self):
        p = forms.plan_condition([step(98)], [step(98)], "s0.temperature")
        vals = {"s0.temperature": 400.0, "s0.molar_mass": 32.0, "s1.temperature": 300.0, "s1.molar_mass": 28.0}
        cand = {"_plan": p, "_shape": {"kind": "condition", "unknown": "s0.temperature"}}
        got = forms_layer.apply_form(None, cand, PhysicalAdapter.input_spec(p), vals, run_chain(p, vals),
                                     random.Random(0), avoid={"condition"})
        self.assertEqual(got[2].form, "condition")


class ShapedIdeas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from subject_config import get_subject_config
        cls.ad = PhysicalAdapter(get_subject_config("physical"), random.Random(4))
        cls.cands = []
        for _ in range(15):
            cls.cands += [c for c in cls.ad.candidates(Coverage(), n=12) if c.get("_shape")]

    def test_mix(self):
        kinds = [c["_shape"]["kind"] for c in self.cands]
        self.assertGreater(kinds.count("tree"), 20)
        self.assertGreater(kinds.count("condition"), 5)

    def test_each_idea_is_sound(self):
        ad = self.ad
        for c in self.cands:
            sh, plan = c["_shape"], c["_plan"]
            again = ad.plan(None, json.loads(json.dumps(sh)))          # rebuilt from a parked item
            self.assertEqual(set(again.givens), set(plan.givens))
            spec = ad.input_spec(plan)
            self.assertEqual([s["key"] for s in spec], list(plan.givens))
            text = ad.chain_text(plan)
            if sh["kind"] == "tree":
                self.assertIn("TREE", text)
                f = plan.steps[-1]
                for key, b in sh["feeds"].items():
                    end = plan.steps[plan.branches[b][1]]
                    self.assertEqual(key, end.final[0] if end.final else end.answer)    # a computed result
                    self.assertTrue(all(not s.domain or not f.domain or s.domain == f.domain for s in plan.steps))
            else:
                self.assertIn("TWO SYSTEMS", text)
                g = plan.givens[sh["unknown"]].param
                self.assertIn(g.unit, CONDITION_UNITS)
                self.assertIn(plan.steps[-1].unit, COMPARE_UNITS)
                descs = [s["desc"] for s in spec]
                self.assertEqual(len(descs), len(set(descs)), descs)
            self.assertEqual(len(c["txs"]), len(c["edges"]))

    def test_conditions_are_posable(self):
        for c in [c for c in self.cands if c["_shape"]["kind"] == "condition"]:
            self.assertTrue(self.ad._posable(c, tries=16, need=1))

    def test_shaped_idea_is_not_shortened(self):
        """A fragile answer shortens a chain by its last step; a tree has no such step to drop."""
        tree = next(c for c in self.cands if c["_shape"]["kind"] == "tree")
        fragile = dataclasses.make_dataclass("R", ["answer", "tolerance"])(1.0, 0.5)
        self.assertIs(flow._stable_ask(self.ad, tree, {}, fragile, None)[0], tree)


class Parked(unittest.TestCase):
    def test_form_result_round_trip(self):
        """A parked question is judged again as asked: its FormResult survives JSON."""
        import run_groundup_final as rg
        from subject_config import get_subject_config
        ad = PhysicalAdapter(get_subject_config("physical"), random.Random(1))
        shape = {"kind": "condition", "branches": [[98], [98]], "unknown": "s0.temperature", "unknown_b": None,
                 "shared": False}
        plan = ad.plan(None, shape)
        vals = {"s0.temperature": 400.0, "s0.molar_mass": 32.0, "s1.temperature": 300.0, "s1.molar_mass": 28.0}
        spec, v2, r = forms_layer.apply_form(ad, {"_plan": plan, "_shape": shape}, ad.input_spec(plan), vals,
                                             run_chain(plan, vals), random.Random(1))
        item = json.loads(json.dumps({"txs": [98, 98], "edges": ["a", "b"], "nodes": [], "chapters": [],
                                      "values": v2, "chain_values": vals, "shape": shape,
                                      "form_result": dataclasses.asdict(r)}, ensure_ascii=False))
        _, cand, plan2, r2 = rg._rebuild_parked(item, ad, {}, random.Random(1))
        self.assertEqual((r2.form, r2.answer, r2.asks, r2.unit), (r.form, r.answer, r.asks, r.unit))
        self.assertEqual(cand["_shape"], shape)


if __name__ == "__main__":
    unittest.main()
