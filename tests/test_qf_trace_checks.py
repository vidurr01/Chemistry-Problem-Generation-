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
