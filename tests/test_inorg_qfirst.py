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
    def test_blocked_edges_never_drawn(self):
        """Wrong and condition-dependent edges (graph audit of 2026-11-24) are gone for both paths."""
        blocked = IQ.blocked_edges()
        self.assertIn("Na_to_Na2O_na", blocked)
        self.assertEqual(len(blocked), 28)
        g = IQ._graph(_adapter())
        self.assertFalse(blocked & set(g["edges"]))
        self.assertFalse(blocked & {e["id"] for es in g["out"].values() for e in es})

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
                  mock.patch("core.pipeline.inorg_system.MEMORY_PATH", os.path.join(self.tmp, "sysmem.json")),
                  mock.patch("tools.results.promote", lambda *a, **k: 0),
                  mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
                  mock.patch("core.pipeline.qf_design.design_problems", lambda d, *a, **k: None),
                  mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: None),
                  mock.patch.object(IQ, "draw", lambda *a, **k: dict(self.cand)),
                  mock.patch.object(IQ, "LIST_SHARE", 0),                  # the reaction-chain path
                  mock.patch.object(IQ, "PRODUCTS_SHARE", 0),
                  mock.patch.object(IQ, "SYSTEM_SHARE", 0)]
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

    def test_species_list_question_end_to_end(self):
        """A "how many species" draw: built and keyed by code, judged by the ladder, saved."""
        from core.pipeline import inorg_list as IL
        cand = IL.draw(random.Random(2))
        want = sum(cand["_list"]["truth"])
        bottom = models.LADDER[0][1]

        def fake(role, model, system, user, **kw):
            if role in ("designer", "generator") and "Write ONE" in user:
                raise AssertionError("a list question needs no designer or writer")
            if role == "council":
                a = str(want + 1) if model in (bottom, models.LADDER[1][1]) else str(want)   # medium-hard
                return {"working": "w", "answer": a, "final_answer": a}
            return self.fake(role, model, system, user, **kw)
        with mock.patch.object(IQ, "LIST_SHARE", 1), mock.patch.object(IL, "draw", lambda *a, **k: dict(cand)),                 mock.patch.object(models, "ask_json", fake),                 mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "inorganic", "--seed", "1"]):
            self.assertEqual(self.entry.main(), 0)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            r = json.load(f)[0]
        self.assertEqual(int(r["answer"]), want)
        self.assertIn("the total number of", r["question"])

    def _system_run(self, glm_solves, bottom_solves=False):
        from core.pipeline import inorg_system as SY
        rng = random.Random(4)
        while True:
            cand = SY.draw(IQ._graph(_adapter()), rng)
            if SY.build(cand, random.Random(1)) is not None:
                break
        want = SY.build(cand, random.Random(1))[1].answer
        bottom, glm = models.LADDER[0][1], models.LADDER[1][1]

        def fake(role, model, system, user, **kw):
            if role == "generator" and "Rewrite these inorganic reactions" in user:
                return {"stem": "no letters here"}                      # refused: the scheme is used
            if role == "step_checker":
                self.checker_prompts.append(user)
                return {"species": [{"letter": L, "formula": s, "charge": 0}
                                    for s, L in cand["_system"]["labels"].items()]}
            if role == "council":
                # a readable wrong answer (an unreadable one is asked again, never a failure)
                wrong = ("A" if want != "A" else "B") if isinstance(want, str) else str(int(want) + 3)
                a = wrong if (model == bottom and not bottom_solves) or (model == glm and not glm_solves) \
                    else str(want)
                return {"working": "w", "answer": a, "final_answer": a}
            return self.fake(role, model, system, user, **kw)
        draws = iter([dict(cand)] + [None] * 20)
        self.system_cand, self.checker_prompts = cand, []
        with mock.patch.object(IQ, "SYSTEM_SHARE", 1), mock.patch.object(SY, "draw", lambda *a, **k: next(draws)), \
                mock.patch.object(SY, "build", lambda c, r, form=None, _b=SY.build: _b(c, random.Random(1), form)), \
                mock.patch.object(models, "ask_json", fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "inorganic", "--seed", "1"]):
            self.entry.main()
        return want

    def test_reaction_system_question_end_to_end(self):
        """Letters confirmed blind, key by code, GLM fails, the top step solves: saved, worded like the paper."""
        want = self._system_run(glm_solves=False)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            r = json.load(f)[0]
        self.assertEqual(str(r["answer"]), str(want))
        self.assertIn("Consider the following reactions (unbalanced):", r["question"])
        self.assertNotIn("product containing", r["question"])

    def test_glm_solving_a_system_question_is_accepted(self):
        """Since the real-question measurement (2026-11-25) GLM only labels: Granite failing is the bar."""
        self._system_run(glm_solves=True)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)
        from core.pipeline import inorg_system as SY        # Granite did not solve it: not remembered as easy
        self.assertEqual(SY.load_memory()["bottom_solved"], {})

    def test_an_unreadable_answer_is_held_not_failed(self):
        """Granite answering garbage every time: the question is held for the next run, never 'Granite failed'."""
        from core.pipeline import inorg_system as SY
        rng = random.Random(4)
        cand = SY.draw(IQ._graph(_adapter()), rng)
        bottom = models.LADDER[0][1]
        calls = []

        def fake(role, model, system, user, **kw):
            if role == "generator" and "Rewrite these inorganic reactions" in user:
                return {"stem": "no letters here"}
            if role == "step_checker":
                return {"species": [{"letter": L, "formula": s, "charge": 0}
                                    for s, L in cand["_system"]["labels"].items()]}
            if role == "council":
                calls.append(model)
                if model == bottom:
                    return {"working": "w", "answer": "[TYPE: chemistry] [CALC_VALUE:]",
                            "final_answer": "[TYPE: chemistry] [CALC_VALUE:]"}
                return {"working": "w", "answer": "A", "final_answer": "A"}
            return self.fake(role, model, system, user, **kw)
        draws = iter([dict(cand)] + [None] * 20)
        with mock.patch.object(IQ, "SYSTEM_SHARE", 1), mock.patch.object(SY, "draw", lambda *a, **k: next(draws)), \
                mock.patch.object(models, "ask_json", fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "inorganic", "--seed", "1"]):
            self.entry.main()
        n = calls.count(bottom)                                             # asked again, then held (and the
        self.assertTrue(n >= 1 + IQ.REASKS and n % (1 + IQ.REASKS) == 0, n)  # pipeline's own recheck repeats it)
        self.assertNotIn(models.LADDER[1][1], calls)                       # never treated as "Granite failed"
        self.assertFalse(os.path.exists(self.cfg["output_file"])
                         and json.load(open(self.cfg["output_file"], encoding="utf-8")))

    def test_an_accepted_system_is_not_accepted_again(self):
        """Review #13: the signature held the random letters and statements, so the same system could be saved
        twice. Now the second draw of it stops before anything is paid (no rewrite, no letter check)."""
        self._system_run(glm_solves=False)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)
        self._system_run(glm_solves=False)                  # the same system again, new letters and statements
        self.assertEqual(self.checker_prompts, [])
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)), 1)

    def test_list_signature_ignores_letters_and_order(self):
        from core.pipeline import inorg_list as IL
        c = IL.draw(random.Random(4))
        again = dict(c, _list=dict(c["_list"], species=list(reversed(c["_list"]["species"]))))
        a = _adapter()
        self.assertEqual(IQ._signature(a, c, "species_list"), IQ._signature(a, again, "species_list"))
        self.assertNotEqual(IQ._signature(a, c, "species_list"),
                            IQ._signature(a, IL.draw(random.Random(5)), "species_list"))

    def test_letter_check_never_sees_the_options(self):
        """Review #9: a true option ("the oxidation state of Cr in Q is +3") would tell the checker the answer."""
        self._system_run(glm_solves=False)
        self.assertEqual(len(self.checker_prompts), 1)
        p = self.checker_prompts[0]
        self.assertIn("Consider the following reactions (unbalanced):", p)
        for leak in ("(A)", "(B)", "Choose the correct", "Give the answer"):
            self.assertNotIn(leak, p)

    def test_glm_solving_stops_before_level_check_and_hints(self):
        """Review #7: flow.judge used to go on to a 2nd Jev call and hint re-solves, then the result was dropped."""
        from core.pipeline import qf_checks, stages
        jev, hints = [], []
        with mock.patch.object(IQ, "TOO_EASY_SOLVERS", ("glm-5.3-flash",)), \
                mock.patch.object(qf_checks, "_level_floor", lambda *a, **k: 1.0), \
                mock.patch.object(qf_checks, "jev_level", lambda text: jev.append(text) or 2.0), \
                mock.patch.object(stages, "solve_with_hint", lambda *a, **k: hints.append(a) or {}):
            self._system_run(glm_solves=True)
        self.assertEqual(len(jev), 1)                       # the gate before the ladder only
        self.assertEqual(hints, [])
        self.assertFalse(os.path.exists(self.cfg["output_file"])
                         and json.load(open(self.cfg["output_file"], encoding="utf-8")))

    def test_flow_judge_unchanged_for_other_subjects(self):
        """The stop is an inorganic wrapper around the blackboard; flow.judge's own code is not touched."""
        import inspect
        from core.pipeline import flow
        src = inspect.getsource(flow._judge)
        self.assertNotIn("TOO_EASY", src)
        self.assertIn("solve_with_hint", src)

    def test_granite_solved_system_is_remembered(self):
        from core.pipeline import inorg_system as SY
        self._system_run(glm_solves=True, bottom_solves=True)
        mem = SY.load_memory()["bottom_solved"]
        self.assertEqual(list(mem), self.system_cand["edges"])
        self.assertEqual(mem[self.system_cand["edges"][0]]["solver"], models.LADDER[0][0])

    def test_memory_feeds_the_next_draw(self):
        """A later run: the remembered system is 'tried' and the unconfirmed reaction 'bad' before drawing."""
        from core.blackboard import Blackboard
        from core.pipeline import inorg_system as SY
        SY._remember("bottom_solved", "system:a,b", {"solver": "granite-4.2-8b"})
        SY._remember("unconfirmed_edges", "e1", {"graph": "X", "checker": "Y"})
        seen = {}

        def fake_draw(graph, rng, tried=(), bad=(), asked=()):
            seen.update(tried=tried, bad=bad, asked=asked)
            return None
        with mock.patch.object(SY, "draw", fake_draw):
            IQ._system_question(_adapter(), random.Random(1), Blackboard("inorganic"), lambda e: None, 1)
        self.assertIn(("system:a,b",), seen["tried"])
        self.assertIn("e1", seen["bad"])

    def _products_run(self, checker_agrees):
        from core.pipeline import inorg_products as IP
        with open(self.cfg["graph_path"], encoding="utf-8") as f:
            edges = json.load(f)["edges"]
        cand = IP.draw(edges, random.Random(2))
        rows = cand["_products"]["rows"]
        want = sum(cand["_products"]["truth"])
        bottom = models.LADDER[0][1]
        calls = []

        def fake(role, model, system, user, **kw):
            if role in ("designer", "generator") and "Write ONE" in user:
                raise AssertionError("a hidden-products question needs no designer or writer")
            if role == "step_checker":
                calls.append(user)
                prods = [{"n": i + 1, "formula": r["edge"]["to"], "charge": 0} for i, r in enumerate(rows)]
                if not checker_agrees:
                    prods[0]["formula"] = "XeF4"
                return {"products": prods}
            if role == "council":
                a = str(want + 1) if model in (bottom, models.LADDER[1][1]) else str(want)   # medium-hard
                return {"working": "w", "answer": a, "final_answer": a}
            return self.fake(role, model, system, user, **kw)
        draws = iter([dict(cand)] + [None] * 10)
        with mock.patch.object(IQ, "PRODUCTS_SHARE", 1),                 mock.patch.object(IP, "draw", lambda *a, **k: next(draws)),                 mock.patch.object(models, "ask_json", fake),                 mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "inorganic", "--seed", "1"]):
            self.entry.main()
        return cand, want, calls

    def test_hidden_products_question_end_to_end(self):
        """Reactions with hidden products: checked blind, keyed by code, judged by the ladder, saved."""
        cand, want, calls = self._products_run(checker_agrees=True)
        self.assertEqual(len(calls), 1)
        with open(self.cfg["output_file"], encoding="utf-8") as f:
            r = json.load(f)[0]
        self.assertEqual(int(r["answer"]), want)
        self.assertIn("product containing", r["question"])

    def test_product_check_disagreement_drops_the_question(self):
        self._products_run(checker_agrees=False)
        self.assertFalse(os.path.exists(self.cfg["output_file"])
                         and json.load(open(self.cfg["output_file"], encoding="utf-8")))


class CalibrationPerSubject(unittest.TestCase):
    """Each subject reads its own calibration files; one without them gets no calibrated check, never
    physical's numbers (until 2026-11-19 every loader hard-coded *_physical.json)."""

    def setUp(self):
        from core.pipeline import qf_draw
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, "knowledge"))
        for kind, body in (("level", {"threshold": 2.8}), ("fit", {"threshold": 0.5}),
                           ("design_coherence", {"thresholds": {"glued_parts": 0.1}}),
                           ("coherence", {"thresholds": {"glued_parts": 0.2}})):
            with open(os.path.join(self.tmp.name, "knowledge", f"{kind}_calibration_physical.json"), "w") as f:
                json.dump(body, f)
        self.root = mock.patch.object(qf_draw, "_ROOT", self.tmp.name)
        self.root.start()

    def tearDown(self):
        self.root.stop()
        self.tmp.cleanup()

    def test_physical_reads_its_own_files(self):
        from core.pipeline import qf_checks, qf_draw
        self.assertEqual(qf_checks._level_floor("physical"), 2.8)
        self.assertEqual(qf_draw._fit_floor("physical"), 0.5)
        self.assertEqual(qf_checks._coherence_cuts(subject="physical")["glued_parts"], 0.2)

    def test_inorganic_never_borrows_physical(self):
        from core.pipeline import qf_checks, qf_design, qf_draw
        self.assertIsNone(qf_checks._level_floor("inorganic"))
        self.assertIsNone(qf_draw._fit_floor("inorganic"))
        self.assertEqual(qf_checks._coherence_cuts(subject="inorganic")["glued_parts"],
                         qf_checks.COHERENCE_REJECT_AT)
        with mock.patch("core.pipeline.refine.jev_decide", side_effect=AssertionError("Jev called")):
            self.assertIsNone(qf_design.design_problems({"system": "x"}, "inorganic"))

    def test_inorganic_reads_its_own_file_once_written(self):
        from core.pipeline import qf_checks
        with open(os.path.join(self.tmp.name, "knowledge", "level_calibration_inorganic.json"), "w") as f:
            json.dump({"threshold": 1.9}, f)
        self.assertEqual(qf_checks._level_floor("inorganic"), 1.9)


if __name__ == "__main__":
    unittest.main()
