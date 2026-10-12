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
        if role == "generator" and "invent a concrete" in user:
            return {"coherent": True, "scenario": "carbon dioxide gas",
                    "values": {"s0.mass": 4.4, "s0.molar_mass": 44}}
        if role == "generator" and "Write one JEE" in user:
            return {"stem": "4.4 g of CO2 (molar mass 44 g mol⁻¹) is collected. Taking the molar volume "
                            "at 1 atm and 273 K as 22.4 L, find the volume of the gas in L."}
        if role == "generator" and "too easy" in user:
            return {"mode": self.refine_mode, "feedback": "hide the molar volume cue"}
        if role == "generator" and "misread" in user:
            return {"hint": "The volume is asked at 1 atm and 273 K."}
        if role == "extractor":
            section = user.split("What does the question ask for?")[1].split("3) For each constant")[0]
            opts = dict(re.findall(r"^(\d+)\. (.+)$", section, re.M))
            asked = next(int(k) for k, v in opts.items() if v.startswith("volume of the gas"))
            n_const = user.count("molar volume of an ideal gas")
            return {"values": {"s0.mass": 4.4, "s0.molar_mass": 44}, "asked": asked,
                    "constants_stated": [True] * max(1, n_const)}
        if role == "council":
            if self.fail_council and model == models.COUNCIL[2][1]:
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


class PipelineOffline(unittest.TestCase):
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

    def _run(self, fake):
        with mock.patch.object(models, "ask_json", fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "physical", "--seed", "1"]):
            return entry.main()

    def _records(self):
        if not os.path.exists(self.cfg["output_file"]):
            return []
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            return json.load(f)

    def test_accepts_when_failures_are_confirmed(self):
        slugs = [s for _, s in models.COUNCIL]
        fake = FakeModels(
            council_answers={slugs[0]: "2.24", slugs[1]: "2.45", slugs[2]: "1.12"},
            hint_answers={slugs[1]: "2.24", slugs[2]: "1.12"},
            verdicts={"2.24": {"verdict": "correct"},
                      "1.12": {"verdict": "wrong", "failure_type": "slip", "member_expression": "0.05*22.4"}})
        self.assertEqual(self._run(fake), 0)
        recs = self._records()
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["answer"], 2.24)
        self.assertEqual((r["council_n_correct"], r["council_n_solved"]), (1, 1))
        self.assertEqual(r["tags"]["knowledge"], "closed_book")
        by = {c["name"]: c for c in r["council"]}
        self.assertFalse(by[models.COUNCIL[2][0]]["slip_confirmed"])     # 0.05*22.4 ≠ 2.24
        self.assertEqual(len(r["hint_tests"]), 2)
        self.assertTrue(r["solution"])
        self.assertTrue(os.path.exists(dedup.STORE))

    def test_confirmed_slip_counts_as_solved(self):
        slugs = [s for _, s in models.COUNCIL]
        fake = FakeModels(
            council_answers={slugs[0]: "2.24", slugs[1]: "2.45", slugs[2]: "22.4"},
            hint_answers={slugs[1]: "2.45"},
            verdicts={"2.24": {"verdict": "correct"},
                      "22.4": {"verdict": "wrong", "failure_type": "slip", "member_expression": "0.1*22.4"}},
            refine_mode="reword")
        self.assertEqual(self._run(fake), 0)        # 2 solved -> too easy every round -> dropped
        self.assertEqual(self._records(), [])

    def test_too_easy_until_rounds_run_out(self):
        slugs = [s for _, s in models.COUNCIL]
        fake = FakeModels(council_answers={s: "2.24" for s in slugs}, verdicts={"2.24": {"verdict": "correct"}})
        self.assertEqual(self._run(fake), 0)
        self.assertEqual(self._records(), [])
        self.assertEqual(fake.calls.count("council"), 3 * 4)        # original + 3 refinements

    def test_council_failure_parks_then_recheck_accepts(self):
        slugs = [s for _, s in models.COUNCIL]
        answers = {slugs[0]: "2.24", slugs[1]: "2.45", slugs[2]: "2.45"}
        verdicts = {"2.24": {"verdict": "correct"}}
        self.assertEqual(self._run(FakeModels(answers, answers, verdicts, fail_council=True)), entry.EXIT_COUNCIL_FAILED)
        with open(self.cfg["pending_file"], encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)
        self.assertEqual(self._run(FakeModels(answers, {slugs[1]: "2.24", slugs[2]: "2.24"}, verdicts)), 0)
        self.assertEqual(len(self._records()), 1)
        with open(self.cfg["pending_file"], encoding="utf-8") as f:
            self.assertEqual(json.load(f), [])


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
