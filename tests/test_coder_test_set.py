"""The real-JEE test set of the coder check (tools/calibrate_coder.py): its curation holds (no API calls).

Run:  python -m unittest tests.test_coder_test_set
"""

import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import calibrate_coder as cc  # noqa: E402


class TestSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qs = {q["id"]: q for q in cc.real_questions()}

    def test_incomplete_and_wrongly_keyed_questions_are_left_out(self):
        for qid in cc.EXCLUDED:
            self.assertNotIn(qid, self.qs, qid)
        self.assertEqual(len(self.qs), 44)

    def test_rounded_constants_restated_with_the_engines(self):
        q = self.qs["2018P2_Q10"]
        self.assertIn("R = 8.314 J K−1 mol−1", q["text"])
        self.assertNotIn("R = 8 J", q["text"])
        self.assertTrue(cc.matches(math.log(0.01) - 100000 / (8.314 * 1250), q["answer"]))
        q = self.qs["2023P1_Q9"]
        self.assertIn("R = 0.0821 L atm", q["text"])
        self.assertTrue(cc.matches(1250 * 0.0821, q["answer"]))
        with self.assertRaises(ValueError):                         # a changed source text is said, not skipped
            cc._adapt("2023P1_Q9", "a text without the constant", "100")

    def test_the_tables_eight_questions_are_all_still_usable(self):
        self.assertEqual([qid for qid in cc.PAPER_SET if qid in self.qs], cc.PAPER_SET)


if __name__ == "__main__":
    unittest.main()
