"""
Question forms through the pipeline layer (core/pipeline/forms_layer.py), offline.

Every form is applied to real engine chains with sampled inputs: what the question states must
match the gate's spec, the hidden input must never be stated, the stem writer's note must never
contain the answer, grading must read the answer, and the trace must say how the form uses the
chain. A gate round trip and a ladder grading round trip close the loop.
"""

import math
import random
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from core import answers                                         # noqa: E402
from core.engine.base import EngineError, run_chain              # noqa: E402
from core.pipeline import flow, forms_layer, gate                # noqa: E402
from core.pipeline.adapters import PhysicalAdapter               # noqa: E402
from tests.engine_samples import sample_values                   # noqa: E402

SAMPLE_CHAINS = 160


def _chains():
    import audit_engine
    rng = random.Random(3)
    all_ = [c for c in audit_engine.chains() if len(c[0]) >= 1]
    rng.shuffle(all_)
    return all_[:SAMPLE_CHAINS]


class FormsOnRealChains(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = {"inverse": [], "two_state": [], "simultaneous": []}
        rng = random.Random(7)
        for chain, plan in _chains():
            spec = PhysicalAdapter.input_spec(plan)
            for _ in range(4):
                try:
                    values = sample_values(plan, rng)
                    base = run_chain(plan, values)
                except EngineError:
                    continue
                for kind, builder in forms_layer.BUILDERS.items():
                    try:
                        got = builder(plan, spec, dict(values), base, random.Random(1))
                    except Exception as e:  # noqa: BLE001
                        raise AssertionError(f"{kind} crashed on {[s.tx for s in chain]}: {e!r}")
                    if got:
                        cls.built[kind].append((chain, plan, spec, values, base, got))
                break

    def test_each_form_fits_many_chains(self):
        n = {k: len({tuple(s.tx for s in c) for c, *_ in v}) for k, v in self.built.items()}
        print(f"\n  forms built on {SAMPLE_CHAINS} sampled chains: {n}")
        self.assertGreater(n["inverse"], 40)
        self.assertGreater(n["two_state"], 40)
        self.assertGreater(n["simultaneous"], 5)

    def test_invariants(self):
        for kind, items in self.built.items():
            for chain, plan, spec, values, base, (fspec, fvalues, r) in items:
                txs = [s.tx for s in chain]
                keys = [s["key"] for s in fspec]
                self.assertEqual(len(keys), len(set(keys)), (kind, txs))
                for k in keys:
                    self.assertIn(k, fvalues, (kind, txs, k))
                self.assertEqual(r.form, kind)
                self.assertTrue(isinstance(r.answer, (int, float)) and math.isfinite(r.answer), (kind, txs))
                # the stem writer's note never contains the answer (as a number; stated values may
                # coincide with it, e.g. a ratio of 2 and a stated factor of 2, which is fine)
                from core.solution_check import numbers_in
                stated_nums = [float(x) for x in fvalues.values() if isinstance(x, (int, float))]
                note = r.stem_note
                for name in [s["desc"] for s in spec] + [st.asks for st in plan.steps]:
                    note = note.replace(name, " ")          # names like "cell 2", "T₂" carry digits
                for x in numbers_in(note):
                    if math.isclose(x, r.answer, rel_tol=1e-3):
                        self.assertTrue(any(math.isclose(x, y, rel_tol=1e-3) for y in stated_nums),
                                        (kind, txs, r.stem_note))
                if kind == "inverse":
                    h = r.detail["hidden"]
                    self.assertNotIn(h, fvalues, (txs, h))
                    self.assertTrue(math.isclose(r.answer, values[h], rel_tol=3e-3), (txs, r.answer, values[h]))
                if kind == "simultaneous":
                    for h in r.detail["unknowns"]:
                        self.assertNotIn(h, fvalues)
                spec_a = answers.answer_spec(r.answer, r.kind, r.unit, None)
                self.assertEqual(spec_a["type"], "number")
                text = flow.trace_text(r)
                self.assertIn("FORM", text)
                for t in r.traps:
                    self.assertFalse(math.isclose(t["wrong_answer"], r.answer, rel_tol=0.01), (kind, txs, t))

    def test_gate_round_trip(self):
        """An extraction that reads back exactly the stated values passes the gate; one that
        states the hidden input as well is caught by the stem prompt's spec (the gate only
        knows stated keys), and a changed stated result is a mismatch."""
        for kind, items in self.built.items():
            for chain, plan, spec, values, base, (fspec, fvalues, r) in items[:25]:
                ext = {"values": dict(fvalues), "asked": 1, "constants_stated": [True] * len(r.constants)}
                self.assertTrue(gate.compare(fspec, fvalues, ext, 1, r.constants)["ok"], (kind, [s.tx for s in chain]))
                if "result" in fvalues:
                    bad = {**ext, "values": {**fvalues, "result": fvalues["result"] * 1.1}}
                    self.assertFalse(gate.compare(fspec, fvalues, bad, 1, r.constants)["ok"])

    def test_grading_round_trip(self):
        """A solver line with the form's answer (in another unit where one exists) is graded as
        a match; a trap's wrong answer is not."""
        for kind, items in self.built.items():
            for chain, plan, spec, values, base, (fspec, fvalues, r) in items[:25]:
                spec_a = answers.answer_spec(r.answer, r.kind, r.unit, None)
                line = f"[TYPE: t] [CALC_VALUE: {r.answer!r}] [CALC_UNIT: {r.unit or 'none'}] [SUBSTANCE: null]"
                done = answers.complete_answer(answers.parse_answer_line(line), spec_a)
                self.assertTrue(done["ok"], (kind, line, done.get("reason")))
                self.assertTrue(flow._code_match(r, {"final_value": done["final_value"], "final_answer": done["render"]}))
                for t in r.traps[:2]:
                    line = f"[TYPE: t] [CALC_VALUE: {t['wrong_answer']!r}] [CALC_UNIT: {r.unit or 'none'}] [SUBSTANCE: null]"
                    done = answers.complete_answer(answers.parse_answer_line(line), spec_a)
                    self.assertFalse(flow._code_match(r, {"final_value": done["final_value"],
                                                         "final_answer": done["render"]}), (kind, t))


class Wiring(unittest.TestCase):
    """flow.run applies a form after the inputs, and the stem/gate stage and the ladder receive
    the form's spec, stated values and result; on a too-easy round the next form differs."""

    def test_run_uses_the_form(self):
        from unittest import mock
        from core.engine.base import plan_chain
        from core.engine.physical import step
        from core.pipeline import stages
        plan = plan_chain([step(262)])
        values = {"s0.molality": 0.5, "s0.Kb": 0.52, "s0.vant_hoff_factor": 1.0}
        cand = {"edges": ["e"], "nodes": ["molality", "delta_T"], "chapters": ["Dilute Solutions"], "txs": [262],
                "trap_ids": [], "weight": 1.0, "description": "x", "_steps": plan.steps, "_plan": plan}
        adapter = types.SimpleNamespace(kind="chains", subject="physical", refine_modes=("new_inputs", "reword"),
                                        config={"display_name": "Physical Chemistry"},
                                        candidates=lambda *a, **k: [cand], input_spec=PhysicalAdapter.input_spec,
                                        compute=lambda p, v: run_chain(p, v), plan=lambda txs: plan,
                                        chain_text=PhysicalAdapter.chain_text)
        seen = {"gate": [], "judge": []}

        def fake_stem(adapter_, cand_, spec, vals, scenario, result, bb, rng, **kw):
            seen["gate"].append((spec, vals, result))
            return "stem", None

        rounds = iter([{"decision": "too_easy", "graded": []}, {"decision": "accept", "graded": [], "n_correct": 0,
                                                              "n_solved": 0}])

        def fake_judge(adapter_, cand_, plan_, vals, result, stem, bb, log):
            seen["judge"].append(result)
            return next(rounds)

        bb = types.SimpleNamespace(tried_edges=lambda: set(), start_chain=lambda c: None, note=lambda *a, **k: None,
                                   current={"rounds": 0})
        with mock.patch.object(flow, "_propose", lambda *a, **k: (dict(values), "scenario", run_chain(plan, values))), \
                mock.patch.object(flow, "_stem_and_gate", fake_stem), mock.patch.object(flow, "judge", fake_judge), \
                mock.patch.object(stages, "choose_refinement", lambda *a: {"mode": "new_inputs", "feedback": "harder"}), \
                mock.patch.object(flow.dedup, "duplicate_of", lambda sig: None), mock.patch("builtins.print"):
            out = flow.run(adapter, None, bb, lambda e: None, rng=random.Random(5))
        self.assertEqual(out["status"], "accepted")
        r1, r2 = seen["judge"]
        self.assertIn(r1.form, ("inverse", "two_state", "simultaneous"))
        self.assertNotEqual(r1.form, r2.form)                       # the beaten form is not reused
        for spec, vals, r in seen["gate"]:
            self.assertEqual({s["key"] for s in spec}, set(vals))
        self.assertIs(out["payload"]["result"], r2)


class Choice(unittest.TestCase):
    def test_avoid_and_fallback(self):
        """apply_form never returns a form it was told to avoid; with every form avoided (or
        none fitting) it returns the forward chain unchanged."""
        from core.engine.base import plan_chain
        from core.engine.physical import step
        plan = plan_chain([step(262)])
        spec = PhysicalAdapter.input_spec(plan)
        values = {"s0.molality": 0.5, "s0.Kb": 0.52, "s0.vant_hoff_factor": 1.0}
        base = run_chain(plan, values)
        cand = {"_plan": plan}
        for seed in range(20):
            s2, v2, r = forms_layer.apply_form(None, cand, spec, values, base, random.Random(seed), avoid={"inverse"})
            self.assertNotEqual(r.form, "inverse")
        s2, v2, r = forms_layer.apply_form(None, cand, spec, values, base, random.Random(0),
                                           avoid={"inverse", "two_state", "simultaneous"})
        self.assertEqual((r.form, r.answer, v2), ("forward", base.answer, values))


if __name__ == "__main__":
    unittest.main()
