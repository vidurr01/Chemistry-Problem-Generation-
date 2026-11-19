"""Organic question-first flow (core/pipeline/org_qfirst.py): the draw, code-made options and key, the stem checks,
and one run end to end with scripted models. Offline. Run: python -m unittest tests.test_org_qfirst"""

import json
import os
import random
import re
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dedup, models                                  # noqa: E402
from core.engine.organic.mol import canon, classes              # noqa: E402
from core.pipeline import org_qfirst as OQ, queues              # noqa: E402
from subject_config import get_subject_config                   # noqa: E402

CFG = get_subject_config("organic")


def _adapter():
    return SimpleNamespace(config=dict(CFG, display_name="Organic Chemistry"), subject="organic")


class Draw(unittest.TestCase):
    def test_draws_are_computed_chains_with_code_options(self):
        ad, rng = _adapter(), random.Random(0)
        for _ in range(10):
            c = OQ.draw(ad, rng)
            self.assertIsNotNone(c)
            self.assertGreaterEqual(len(c["_path"]), OQ.CHAIN_MIN)
            self.assertIn(c["_path"][-1]["to"], classes(c["_final"]))       # the product is in the end node
            self.assertGreaterEqual(len(c["_wrong"]), 3)
            self.assertNotIn(canon(c["_final"]), c["_wrong"])
            self.assertTrue(any("selectivity" in w for w in c["_wrong"].values()))

    def test_evaluate_key_and_stem_checks(self):
        c = OQ.draw(_adapter(), random.Random(3))
        name = c["_start"][0]
        res, probs = OQ.evaluate(c, {"stem": f"{name} is treated in turn with the reagents; X, Y; Z is"}, random.Random(1))
        self.assertEqual(probs, [])
        self.assertEqual(len(res.options), 4)
        self.assertEqual(res.options["ABCD".index(res.answer)], c["_final"])
        _, probs = OQ.evaluate(c, {"stem": f"{name} gives {c['_final']}"}, random.Random(1))
        self.assertTrue(any("shows a product" in p for p in probs))
        _, probs = OQ.evaluate(c, {"stem": "some compound is treated"}, random.Random(1))
        self.assertTrue(any("starting compound" in p for p in probs))


class EndToEnd(unittest.TestCase):
    """A whole organic run: draw -> designer -> writer -> code options and key -> ladder -> saved."""

    def setUp(self):
        import run_groundup_final as entry
        self.entry = entry
        self.tmp = tempfile.mkdtemp()
        self.cfg = dict(CFG, output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))
        self.cand = OQ.draw(_adapter(), random.Random(5))
        self.p = [mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
                  mock.patch.object(models, "key_is_set", lambda *a: True),
                  mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
                  mock.patch.object(queues, "_OUT", self.tmp),
                  mock.patch("tools.results.promote", lambda *a, **k: 0),
                  mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
                  mock.patch("core.pipeline.qf_design.design_problems", lambda d, *a, **k: None),
                  mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: None),
                  mock.patch.object(OQ, "draw", lambda *a, **k: dict(self.cand))]
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

    def _key(self, text):
        for letter, smi in re.findall(r"\(([ABCD])\) (\S+)", text):
            if canon(smi) == canon(self.cand["_final"]):
                return letter
        return "A"

    def fake(self, role, model, system, user, **kw):
        if role == "designer":
            return {"system": "a sequence", "hidden": {"X": "step 1 product"}, "hidden_link": "X from the reagents",
                    "route": "each step", "student_must_notice": "the selectivity", "trap": "the other isomer",
                    "given": "start and reagents", "asked": "the final product"}
        if role == "generator" and "Write the STEM" in user:
            return {"stem": f"{self.cand['_start'][0]} is treated with the reagents in order, giving X and then Z. Z is"}
        if role == "council":
            right = self._key(user)
            ans = "D" if right != "D" else "C"
            ans = right if model != models.LADDER[0][1] else ans
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
        self.assertEqual(len(r["options"]), 4)
        keyed = r["options"]["ABCD".index(r["answer"])]
        self.assertEqual(canon(re.sub(r"^\([ABCD]\)\s*", "", keyed)), canon(self.cand["_final"]))   # key by code


if __name__ == "__main__":
    unittest.main()
