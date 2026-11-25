"""Trace checks (qf_checks.trace_problems) on the 13 traced physical questions accepted on 2026-11-25: the
three found wrong by hand are caught, the ten found right are not."""
import json
import os
import unittest

from core.pipeline.qf_checks import trace_problems, answer_real_problems

DATA = os.path.join(os.path.dirname(__file__), "data", "physical_traces_20261125.json")
WRONG = {"GEN_20261125T022806": "K_c", "GEN_20261125T031247": "contradict",
         "GEN_20261125T041311": "alkali metal"}


class TraceChecks(unittest.TestCase):
    def setUp(self):
        with open(DATA, encoding="utf-8") as f:
            self.qs = json.load(f)

    def test_wrong_ones_caught(self):
        for qid, word in WRONG.items():
            q = self.qs[qid]
            probs = trace_problems(q, q["asks"])
            self.assertTrue(probs and word in probs[0], (qid, probs))

    def test_right_ones_pass(self):
        for qid, q in self.qs.items():
            if qid not in WRONG:
                self.assertEqual(trace_problems(q, q["asks"]), [], qid)

    def test_real_element(self):
        self.assertEqual(answer_real_problems("the atomic mass of the alkali metal M", 39.1), [])
        self.assertTrue(answer_real_problems("the atomic mass of the alkaline earth metal", 39.1))
        self.assertEqual(answer_real_problems("the atomic mass of the metal", 55.8), [])
        self.assertEqual(answer_real_problems("the molar mass of the gas", 24.4), [])


if __name__ == "__main__":
    unittest.main()


class ShortcutCheck(unittest.TestCase):
    """qf_shortcut: the hidden step must change the answer (run 2 of 2026-11-25: 0.3% apart, accepted)."""

    def _check(self, reply, key=2.0):
        from unittest import mock
        from core import models
        from core.pipeline import qf_shortcut
        design = {"hidden_step": "x changes", "trap": "keeps x fixed"}
        with mock.patch.object(models, "ask_json", lambda *a, **k: reply), mock.patch("builtins.print"):
            return qf_shortcut.shortcut_problem(design, "Q", "def solve():\n    return a * 2\n", {"answer": key},
                                                {"a": 1.0})

    def test_close_shortcut_rejected(self):
        self.assertIn("does not change the answer", self._check({"code": "def solve():\n    return a * 2.01\n"}))

    def test_far_shortcut_passes(self):
        self.assertIsNone(self._check({"code": "def solve():\n    return a * 3\n"}))

    def test_same_method_rejected_and_broken_shortcut_skipped(self):
        self.assertIn("does not change the solution", self._check({"same": "the step is never reached here"}))
        self.assertIsNone(self._check({"code": "def solve():\n    return undefined_name\n"}))
        self.assertIsNone(self._check({"code": "x"}, key=None))
