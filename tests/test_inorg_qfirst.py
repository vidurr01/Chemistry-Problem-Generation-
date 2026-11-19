"""Inorganic question-first flow (core/pipeline/inorg_qfirst.py): the graph-walk draw, claims decided by code,
and one run end to end with scripted models. Offline. Run: python -m unittest tests.test_inorg_qfirst"""

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
from core.engine.inorganic import species as S                  # noqa: E402
from core.pipeline import inorg_qfirst as IQ, queues            # noqa: E402
from subject_config import get_subject_config                   # noqa: E402

CFG = get_subject_config("inorganic")


def _adapter():
    return SimpleNamespace(config=dict(CFG, display_name="Inorganic Chemistry"), subject="inorganic")


def _cand_with(sid_pred):
    """A real drawn chain whose products include a species matching sid_pred."""
    ad, rng = _adapter(), random.Random(0)
    for _ in range(3000):
        c = IQ.draw(ad, rng)
        hits = [s for s in c["_props"] if sid_pred(s, c["_props"][s])]
        if hits:
            return c, hits[0]
    raise AssertionError("no such chain")


class Draw(unittest.TestCase):
    def test_chains_are_connected_and_askable(self):
        ad, rng = _adapter(), random.Random(1)
        for _ in range(30):
            c = IQ.draw(ad, rng)
            self.assertTrue(IQ.CHAIN_MIN <= len(c["_path"]) <= IQ.CHAIN_MAX)
            for a, b in zip(c["_path"], c["_path"][1:]):
                self.assertEqual(a["to"], b["from"])              # one connected sequence
            self.assertTrue(c["_props"])                           # something code can compute
            self.assertTrue(all(p for p in c["_props"].values()))

    def test_graph_charges(self):
        self.assertEqual(S.to_formula_charge("C2O42-"), ("C2O4", -2))
        self.assertEqual(S.to_formula_charge("NO2-"), ("NO2", -1))
        self.assertEqual(S.to_formula_charge("Al3+"), ("Al", 3))
        self.assertEqual(S.to_formula_charge("[BeCl4]2-"), ("[BeCl4]", -2))
        self.assertEqual(S.askable("K4[Fe(CN)6]")["complex_unpaired"], 0)


class Evaluate(unittest.TestCase):
    def setUp(self):
        self.c, self.sid = _cand_with(lambda s, p: any(k.startswith("oxidation_state:") for k in p))
        self.prop = next(k for k in self.c["_props"][self.sid] if k.startswith("oxidation_state:"))
        self.val = self.c["_props"][self.sid][self.prop]

    def _q(self, fmt, rows, labels=None, stem="Compound X is formed. Which statements are correct?"):
        return {"stem": stem, "format": fmt, "labels": labels or {"X": self.sid}, "options": rows, "items": rows}

    def test_true_and_false_claims_by_code(self):
        rows = [{"text": "t", "species": "X", "property": self.prop, "value": self.val},
                {"text": "f1", "species": "X", "property": self.prop, "value": self.val + 1},
                {"text": "f2", "species": "X", "property": self.prop, "value": self.val + 2},
                {"text": "f3", "species": "X", "property": self.prop, "value": self.val - 1}]
        res, probs = IQ.evaluate(self.c, self._q("msq", rows))
        self.assertEqual(probs, [])
        self.assertEqual(res.answer, "A")
        self.assertEqual(res.kind, "letters")
        res, _ = IQ.evaluate(self.c, self._q("mcq_incorrect", [rows[0], rows[0], rows[0], rows[1]]))
        self.assertEqual(res.answer, "D")

    def test_count_and_rules(self):
        t = {"text": "t", "species": "X", "property": self.prop, "value": self.val}
        f = {"text": "f", "species": "X", "property": self.prop, "value": self.val + 3}
        res, probs = IQ.evaluate(self.c, self._q("count", [t, f, t, f, f]))
        self.assertEqual((probs, res.answer, res.kind), ([], 2, "count"))
        _, probs = IQ.evaluate(self.c, self._q("msq", [t, t, t, t]))                      # all true: rejected
        self.assertTrue(any("1 to 3 true" in p for p in probs))
        bad = dict(t, property="shape_of_the_moon")
        _, probs = IQ.evaluate(self.c, self._q("msq", [bad, t, f, f]))
        self.assertTrue(any("cannot be computed" in p for p in probs))
        _, probs = IQ.evaluate(self.c, self._q("msq", [t, f, f, f], stem=f"{self.sid} is formed. Which are correct?"))
        if len(self.sid) > 2:
            self.assertTrue(any("names the hidden species" in p for p in probs))


class EndToEnd(unittest.TestCase):
    """A whole inorganic run: draw -> designer -> writer -> code key -> ladder -> saved."""

    def setUp(self):
        import run_groundup_final as entry
        self.entry = entry
        self.tmp = tempfile.mkdtemp()
        self.cfg = dict(CFG, display_name="Inorganic Chemistry", output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))
        self.cand, self.sid = _cand_with(lambda s, p: any(k.startswith("oxidation_state:") for k in p))
        self.prop = next(k for k in self.cand["_props"][self.sid] if k.startswith("oxidation_state:"))
        self.val = self.cand["_props"][self.sid][self.prop]
        self.p = [mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
                  mock.patch.object(models, "key_is_set", lambda *a: True),
                  mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
                  mock.patch.object(queues, "_OUT", self.tmp),
                  mock.patch("tools.results.promote", lambda *a, **k: 0),
                  mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
                  mock.patch("core.pipeline.qf_design.design_problems", lambda d: None),
                  mock.patch("core.pipeline.qf_checks._level_floor", lambda: None),
                  mock.patch.object(IQ, "draw", lambda *a, **k: dict(self.cand))]
        for x in self.p:
            x.start()
        # the store's path was bound as a default argument at import: point it at the temporary store only
        # AFTER dedup.STORE is patched (built earlier, it kept the real outputs/ file and wrote a test entry there)
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
            return {"system": "a sequence", "hidden": {"X": self.sid}, "hidden_link": "X from the reagents",
                    "route": "identify X, judge", "student_must_notice": "the oxidation state",
                    "trap": "a wrong state", "given": "reagents", "asked": "statements about X", "format": "msq"}
        if role == "generator" and "Write ONE JEE Advanced" in user:
            rows = [{"text": f"opt{i}", "species": "X", "property": self.prop, "value": self.val + d}
                    for i, d in enumerate((0, 1, 2, -1))]
            return {"stem": "A sequence gives X. Which statements about X are correct?", "format": "msq",
                    "labels": {"X": self.sid}, "options": rows}
        if role == "council":
            slug = model
            bottom = models.LADDER[0][1]
            return {"working": "w", "answer": "B" if slug == bottom else "A",
                    "final_answer": "B" if slug == bottom else "A"}
        if role == "solution_writer" or role == "generator":
            return {"solution": "Step 1 ...", "hint": "h"}
        if role == "solution_checker":
            return {"ok": True, "problems": []}
        return {}

    def test_run_accepts_and_saves(self):
        with mock.patch.object(models, "ask_json", self.fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "inorganic", "--seed", "1"]):
            code = self.entry.main()
        self.assertEqual(code, 0)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            recs = json.load(f)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["answer"], "A")                          # computed by code
        self.assertEqual(r["subject"], "inorganic")
        self.assertEqual(len(r["options"]), 4)
        self.assertIn("(A) opt0", r["question"])


if __name__ == "__main__":
    unittest.main()
