"""The inorganic "one reaction system, products as letters" question (core/pipeline/inorg_system.py)."""

import os
import random

import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import models                              # noqa: E402
from core.pipeline import inorg_qfirst as IQ         # noqa: E402
from core.pipeline import inorg_system as SY         # noqa: E402
from subject_config import get_subject_config         # noqa: E402

AD = SimpleNamespace(config=dict(get_subject_config("inorganic")), subject="inorganic")
G = IQ._graph(AD)


def _questions(n, seed=0):
    rng, out = random.Random(seed), []
    while len(out) < n:
        c = SY.draw(G, rng)
        q = SY.question(c, rng, polish=False)
        if q is not None:
            out.append((c, q))
    return out


class Facts(unittest.TestCase):
    def test_known_species(self):
        f = {(fam, v) for fam, _k, v, _e in SY.facts("K4[Fe(CN)6]")}
        self.assertIn(("magnetism", "diamagnetic"), f)
        self.assertIn(("hybrid", "d2sp3"), f)
        self.assertIn(("oxidation", 2), f)

    def test_audit_exclusions_hold(self):
        self.assertFalse([x for x in SY.facts("PbCl2") if x[0] in ("geometry", "hybrid")])
        self.assertFalse([x for x in SY.facts("PH3") if x[0] == "hybrid"])
        self.assertFalse([x for x in SY.facts("CO2") if x[0] == "basicity"])    # not an acid
        self.assertFalse([x for x in SY.facts("CrO5") if x[0] == "oxidation"])  # was keyed "+10" (true: +6)

    def test_traps(self):
        rng = random.Random(0)
        self.assertEqual(SY._wrong("hybrid", "complex_hybridisation", "d2sp3", rng, el_is_metal=True), "sp3d2")
        self.assertEqual(SY._wrong("hybrid", "hybridisation", "sp3", rng, el_is_metal=False), "sp2")  # no dsp2 on N
        self.assertEqual(SY._wrong("moment", "complex_spin_only_moment", 0.0, rng), 2.83)

    def test_false_values_are_never_impossible(self):
        # review #10: d12, 7 unpaired electrons, Mn +9 were offered; anyone rules those out without chemistry
        for seed in range(50):
            rng = random.Random(seed)
            self.assertLessEqual(SY._wrong("d", "complex_d_electrons", 10, rng), 10)
            self.assertLessEqual(SY._wrong("d", "metal_ion_d_electrons", 9, rng), 10)
            self.assertLessEqual(SY._wrong("unpaired", "complex_unpaired", 5, rng), 5)
            self.assertLessEqual(SY._wrong("unpaired", "metal_ion_unpaired", 4, rng), 5)
            self.assertLessEqual(SY._wrong("unpaired", "mo_unpaired", 2, rng), 2)
            self.assertLessEqual(SY._wrong("oxidation", "oxidation_state:Mn", 7, rng, el="Mn"), 7)
            self.assertLessEqual(SY._wrong("oxidation", "oxidation_state:Cr", 6, rng, el="Cr"), 6)
            self.assertGreaterEqual(SY._wrong("oxidation", "complex_oxidation_state", 1, rng, el="Ag"), 0)
            self.assertIn(SY._wrong("oxidation", "complex_oxidation_state", 0, rng, el="Ni"), (1, 2))  # Ni(CO)4

    def test_every_false_statement_in_drawn_questions_is_possible(self):
        import re
        sup = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
        for _c, (_stem, res, _form, _prose) in _questions(80, seed=12):
            for t in res.trace:
                if "statement" not in t["inputs"]:
                    continue                                          # a numerical question has no statements
                s = t["inputs"]["statement"]
                d = re.search(r"a d([⁰¹²³⁴⁵⁶⁷⁸⁹]+) configuration", s)
                if d:
                    self.assertLessEqual(int(d.group(1).translate(sup)), 10, s)
                u = re.search(r"has (\d+) unpaired", s)
                if u:
                    self.assertLessEqual(int(u.group(1)), 5, s)
                o = re.search(r"oxidation state of (\w+) in <\w+> is \+?(-?\d+)", s)
                if o:
                    from core.engine.inorganic import species as S
                    self.assertTrue(0 <= int(o.group(2)) <= S._max_ox(o.group(1)), s)


class Draw(unittest.TestCase):
    def test_questions_read_like_the_paper(self):
        for c, (stem, res, form, prose) in _questions(40):
            D = c["_system"]
            letters = set(D["labels"].values())
            self.assertFalse(letters & set("ABCD"), "letters must not clash with the options")
            self.assertEqual(SY.leaks(c, stem), [], stem)                    # no product named
            self.assertNotIn("product containing", stem)
            for e in D["steps"]:
                self.assertTrue(SY._usable(e))
            if form == "msq":
                self.assertEqual(len(res.options), 4)
                cats = [SY.CATEGORY[SY.FAMILY.get(t["dst"], "oxidation")] for t in res.trace]
                self.assertGreaterEqual(len(set(cats)), 2, res.options)      # mixed properties
                want = "".join("ABCD"[i] for i, t in enumerate(res.trace) if t["outputs"]["statement true"])
                self.assertEqual(res.answer, want)
                self.assertTrue(1 <= len(res.answer) <= 4)
            for L in letters:                                                # every letter is in the stem
                self.assertRegex(stem, r"(?<![A-Za-z])" + L + r"(?![a-z])")

    def test_tried_systems_not_repeated(self):
        rng = random.Random(3)
        c = SY.draw(G, rng)
        for _ in range(20):
            self.assertNotEqual(SY.draw(G, rng, tried=c["edges"])["edges"], c["edges"])

    def test_every_draw_can_make_its_question(self):
        # live run 11 lost 3 of 10 draws to "no four mixed statements"; draw() now checks msq_fits first
        rng = random.Random(11)
        for i in range(150):
            c = SY.draw(G, rng)
            self.assertIsNotNone(SY.build(c, random.Random(i), form="msq"), c["description"])

    def test_run_11_systems_are_not_drawn(self):
        self.assertFalse(SY.msq_fits({"P": SY.facts("K[Ag(CN)2]"), "Q": SY.facts("AgCl")}))   # AgCl: one fact
        self.assertFalse(SY.msq_fits({"P": SY.facts("SO2"), "Q": SY.facts("Cr2(SO4)3")}))      # 2 kinds + 1 (all electrons)
        self.assertTrue(SY.msq_fits({"X": SY.facts("XeF4"), "Y": SY.facts("H3PO4")}))
        # POCl3 and H3PO4: sp3 and tetrahedral are one fact each (no lone pair), so only 2 + 2 judgements of
        # which two are the same kind: not four different statements (batch 2026-11-25)
        self.assertFalse(SY.msq_fits({"X": SY.facts("POCl3"), "Y": SY.facts("H3PO4")}))

    def test_a_fork_has_one_key_whatever_its_order(self):
        # run 11 drew "Ag -> K[Ag(CN)2], AgCl" and later "Ag -> AgCl, K[Ag(CN)2]" as two systems
        from core.blackboard import Blackboard
        rng = random.Random(5)
        seen = {}
        for _ in range(400):
            c = SY.draw(G, rng)
            ids = frozenset(e["id"] for e in c["_system"]["steps"])
            self.assertEqual(seen.setdefault(ids, c["edges"][0]), c["edges"][0])
        forks = [c for c in (SY.draw(G, random.Random(i)) for i in range(200)) if c["_system"]["shape"] == "fork"]
        self.assertTrue(forks)
        bb = Blackboard("inorganic")
        bb.start_chain(forks[0])
        tried = bb.tried_edges()
        for i in range(200):                                      # never drawn again, in either order
            d = SY.draw(G, random.Random(i), tried=tried)
            self.assertNotEqual({e["id"] for e in d["_system"]["steps"]},
                                {e["id"] for e in forks[0]["_system"]["steps"]})

    def test_disagreements_kept_failed_calls_not(self):
        import tempfile
        c = SY.draw(G, random.Random(3))
        (sid1, L1), (sid2, L2) = list(c["_system"]["labels"].items())[:2]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "mem.json")
            kept = SY.remember_unconfirmed(c, [{"letter": L1, "graph": sid1, "checker": '{"formula": "Q"}'},
                                               {"letter": L2, "graph": sid2, "checker": "error: 503"}], path)
            mem = SY.load_memory(path)["unconfirmed_edges"]
        step = {e["to"]: e["id"] for e in c["_system"]["steps"]}
        self.assertEqual(kept, [step[sid1]])
        self.assertEqual(set(mem), {step[sid1]})                     # a failed call says nothing: not kept
        self.assertEqual(mem[step[sid1]]["checker"], '{"formula": "Q"}')

    def test_letters_are_never_an_element_of_the_system(self):
        # review #11: "M + H2O -> N" in nitrogen chemistry, "PCl5 + H2O -> P"
        rng = random.Random(3)
        for _ in range(300):
            c = SY.draw(G, rng)
            D = c["_system"]
            els = SY._elements(D["start"], D["steps"])
            self.assertFalse(set(D["labels"].values()) & els, SY.scheme(c))

    def test_letter_sets_for_n_and_p(self):
        n_chain = [{"to": "NO", "reagents": ["O₂"]}, {"to": "NO2", "reagents": ["O₂"]}, {"to": "HNO3", "reagents": ["H₂O"]}]
        self.assertNotIn("LMN", SY.letter_sets("NH3", n_chain, 3))
        p_chain = [{"to": "POCl3", "reagents": ["H₂O"]}, {"to": "H3PO4", "reagents": ["H₂O"]}]
        sets = SY.letter_sets("PCl5", p_chain, 2)
        self.assertNotIn("PQ", sets)
        self.assertIn("GR", sets)

    def test_salt_and_ion_of_one_complex_agree(self):
        # live run 12: Na[Ag(CN)2] for [Ag(CN)2]- was counted as a disagreement
        self.assertTrue(SY.same_entity("[Ag(CN)2]-", "Na[Ag(CN)2]", 0))
        self.assertTrue(SY.same_entity("K4[Fe(CN)6]", "[Fe(CN)6]4-", -4))
        self.assertFalse(SY.same_entity("[Ag(CN)2]-", "[Au(CN)2]-", -1))
        self.assertFalse(SY.same_entity("[Zn(CN)4]2-", "Ag", 0))
        c = {"_system": {"labels": {"[Ag(CN)2]-": "G"}, "facts": {"G": SY.facts("[Ag(CN)2]-")},
                         "steps": [{"id": "e1", "from": "Ag2S", "to": "[Ag(CN)2]-"}]}}
        sp = [{"letter": "<G>", "formula": "Na[Ag(CN)₂]", "charge": 0}]
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"species": sp}):
            self.assertEqual(SY.check_letters(c, "text"), [])

    def test_steps_after_a_misread_letter_are_not_blamed(self):
        # live run 12: C + Al2O3 + N2 -> W (CO; the checker said AlN), then W -> X (COCl2), X -> Y (urea)
        steps = [{"id": "a", "from": "C", "to": "CO"}, {"id": "b", "from": "CO", "to": "COCl2"},
                 {"id": "c", "from": "COCl2", "to": "NH2CONH2"}]
        c = {"_system": {"labels": {"CO": "W", "COCl2": "X", "NH2CONH2": "Y"}, "steps": steps}}
        bad = [{"letter": "W", "graph": "CO", "checker": "AlN"}, {"letter": "X", "graph": "COCl2", "checker": "AlCl3"},
               {"letter": "Y", "graph": "NH2CONH2", "checker": "x"}]
        self.assertEqual([e["id"] for e, _ in SY.blamed_steps(c, bad)], ["a"])
        bad2 = [{"letter": "X", "graph": "COCl2", "checker": "AlCl3"}]          # W read right: X's step is blamed
        self.assertEqual([e["id"] for e, _ in SY.blamed_steps(c, bad2)], ["b"])
        fork = {"_system": {"labels": {"CO": "W", "CO2": "X"}, "steps": [
            {"id": "f1", "from": "C", "to": "CO"}, {"id": "f2", "from": "C", "to": "CO2"}]}}
        two = [{"letter": "W", "graph": "CO", "checker": "?"}, {"letter": "X", "graph": "CO2", "checker": "?"}]
        self.assertEqual([e["id"] for e, _ in SY.blamed_steps(fork, two)], ["f1", "f2"])   # both from the start
        self.assertEqual(SY.blamed_steps(fork, [dict(two[0], checker="error: 503")]), [])

    def test_tried_as_the_pipeline_passes_it(self):
        # Blackboard.tried_edges() holds tuples; before 2026-11-25 the string key never matched them
        from core.blackboard import Blackboard
        bb = Blackboard("inorganic")
        c = SY.draw(G, random.Random(3))
        bb.start_chain(c)
        self.assertNotEqual(SY.draw(G, random.Random(3), tried=bb.tried_edges())["edges"], c["edges"])


class LetterCheck(unittest.TestCase):
    def setUp(self):
        self.c, (self.stem, *_rest) = _questions(1, seed=7)[0]

    def test_agree_and_differ(self):
        sp = [{"letter": L, "formula": s, "charge": 0} for s, L in self.c["_system"]["labels"].items()]
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"species": sp}):
            self.assertEqual(SY.check_letters(self.c, self.stem), [])
        sp[0] = dict(sp[0], formula="XeF4")
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"species": sp}):
            self.assertEqual([b["letter"] for b in SY.check_letters(self.c, self.stem)], [sp[0]["letter"]])

    def test_opening_is_the_reactions_only(self):
        for c, (stem, res, form, prose) in _questions(20, seed=9):
            self.assertTrue(stem.startswith(res.opening + "\n"))
            self.assertNotRegex(res.opening, r"\([A-D]\)|Choose|Give the answer|total number|magnetic moment of")
            for L in c["_system"]["labels"].values():                   # every letter still there to identify
                self.assertRegex(res.opening, r"(?<![A-Za-z])" + L + r"(?![a-z])")

    def test_failed_call_never_passes(self):
        with mock.patch.object(models, "ask_json", side_effect=RuntimeError("down")):
            self.assertEqual(len(SY.check_letters(self.c, self.stem)), len(self.c["_system"]["labels"]))

    def test_polish_that_names_a_product_is_refused(self):
        sid = next(iter(self.c["_system"]["labels"]))
        leaky = {"stem": "Something gives " + sid + " and " + " ".join(self.c["_system"]["labels"].values())}
        with mock.patch.object(models, "ask_json", lambda *a, **k: leaky):
            self.assertIsNone(SY.polish_stem(self.c))

    def test_polish_must_keep_the_angle_brackets(self):
        # the author, 2026-11-25: <N> is a species to work out, N is nitrogen; a bare letter is refused
        letters = list(self.c["_system"]["labels"].values())
        tagged = "Heating gives a salt " + " and then ".join(f"<{L}>" for L in letters) + "."
        bare = "Heating gives a salt " + " and then ".join(letters) + "."
        half = tagged + f" The salt {letters[0]} is then heated."
        for text, ok in ((tagged, True), (bare, False), (half, False)):
            with mock.patch.object(models, "ask_json", lambda *a, _t=text, **k: {"stem": _t}):
                self.assertEqual(SY.polish_stem(self.c) is not None, ok, text)

    def test_polish_that_explains_is_refused(self):
        # run 11: "Reaction of X with H2O via an addition-elimination pathway yields a compound Y"
        letters = " then ".join(f"<{L}>" for L in self.c["_system"]["labels"].values())
        for extra, ok in (("", True), (" via an addition-elimination pathway", False),
                          (" because the oxide is amphoteric", False), (" through a nucleophilic attack", False)):
            text = f"Heating gives {letters}{extra}."
            with mock.patch.object(models, "ask_json", lambda *a, _t=text, **k: {"stem": _t}):
                self.assertEqual(SY.polish_stem(self.c) is not None, ok, text)

    def test_polish_that_names_or_colours_is_refused(self):
        letters = " then ".join(f"<{L}>" for L in self.c["_system"]["labels"].values())
        for extra, ok in (("", True), (", which leads to a salt", True), (" (potassium manganate)", False),
                          (", a green salt", False), (", a white precipitate", False), (" as sodium chloride", False)):
            text = f"Heating gives {letters}{extra}."
            with mock.patch.object(models, "ask_json", lambda *a, _t=text, **k: {"stem": _t}):
                self.assertEqual(SY.polish_stem(self.c) is not None, ok, text)

    def test_words_already_in_the_scheme_are_allowed(self):
        c = {"_system": {"labels": {"NO": "X"}, "steps": [
            {"from": "NH3", "to": "NO", "reagents": ["O₂"], "conditions": "Pt catalyst, red hot"}]}}
        self.assertEqual(SY.named_or_coloured(c, "NH₃ is oxidised over red hot Pt to <X>."), [])
        self.assertEqual(SY.named_or_coloured(c, "Ammonia is oxidised to a brown gas <X>."), ["ammonia", "brown"])

    def test_shape_statement_wording(self):
        self.assertEqual(SY._text("<X>", "geometry", "shape", "octahedral", "S"), "<X> has an octahedral shape")
        self.assertEqual(SY._text("<X>", "geometry", "shape", "T-shaped", "Cl"), "<X> is T-shaped")
        self.assertEqual(SY._text("<X>", "geometry", "shape", "bent", "O"), "<X> has a bent shape")
        # A/B 2026-11-25: "the geometry around S in H2SO3 is tetrahedral" read as the electron-pair arrangement
        self.assertEqual(SY._text("<R>", "geometry", "central_shape", "trigonal pyramidal", "S"),
                         "<R> has a trigonal pyramidal shape around S")
        self.assertEqual(SY._text("<M>", "geometry", "complex_geometry", "octahedral", "Co"),
                         "The geometry around Co in <M> is octahedral")      # a metal: no lone pair, no ambiguity

    def test_false_statements_use_the_rival_product(self):
        # S -> SO2 -> H2SO3: the same SO2 with an oxidant gives H2SO4, whose S is tetrahedral
        D = {"labels": {"SO2": "G", "H2SO3": "R"},
             "facts": {"G": SY.facts("SO2"), "R": SY.facts("H2SO3")},
             "rivals": {"R|geometry": ("tetrahedral", "H2SO4")}}
        seen = False
        for seed in range(40):
            made = SY._msq(D, random.Random(seed))
            for tr in made[1].trace:
                if tr["outputs"].get("trap"):
                    seen = True
                    self.assertIn("tetrahedral shape around S", tr["inputs"]["statement"])
                    self.assertFalse(tr["outputs"]["statement true"])
        self.assertTrue(seen)

    def test_reword_some_keeps_only_faithful_rewrites(self):
        c, (stem, res, form, prose) = next((c, q) for c, q in _questions(30, seed=4) if q[2] == "msq")
        before = list(res.options)
        calls = []

        import re

        def fake(*a, **k):
            listed = re.findall(r"(?m)^\d+\. (.*)$", a[3].split("Options:")[1])
            calls.append(len(listed))
            outs = []
            for line in listed:
                outs.append("In other words, " + line)               # faithful, and not a copy
            if len(outs) == 2:
                outs[1] = outs[1].replace("<", "[")                    # unfaithful: tag lost
            return {"options": outs}
        with mock.patch.object(models, "ask_json", fake):
            kept = SY.reword_some(c, res, random.Random(2))
        changed = [i for i in range(4) if res.options[i] != before[i]]
        self.assertTrue(1 <= calls[0] <= SY.REWORD_MAX)                      # one or two, never all four
        self.assertEqual(len(changed), kept)
        self.assertEqual(kept, 1)
        for i in changed:
            self.assertTrue(res.options[i].startswith("In other words, "))

    def test_checker_may_answer_with_brackets(self):
        sp = [{"letter": f"<{L}>", "formula": s, "charge": 0} for s, L in self.c["_system"]["labels"].items()]
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"species": sp}):
            self.assertEqual(SY.check_letters(self.c, self.stem), [])

    def test_every_letter_is_written_in_brackets(self):
        for c, (stem, res, form, prose) in _questions(60, seed=21):
            for L in c["_system"]["labels"].values():
                self.assertIn(f"<{L}>", res.opening)
            self.assertEqual(SY.bare_letters(c, stem.replace("(A)", "").replace("(B)", "").replace("(C)", "")
                                             .replace("(D)", "")), [], stem)


class MediumHard(unittest.TestCase):
    def test_glm_only_labels_now(self):
        # real-question measurement, 2026-11-25: "Granite fails" is the bar; GLM solving is "advanced", accepted
        self.assertEqual(IQ.TOO_EASY_SOLVERS, ())
        self.assertEqual(IQ._medium_hard({"decision": "accept", "first_solver": "glm-5.3-flash"})["decision"], "accept")
        with mock.patch.object(IQ, "TOO_EASY_SOLVERS", ("glm-5.3-flash",)):     # the switch still works
            d = IQ._medium_hard({"decision": "accept", "first_solver": "glm-5.3-flash"})
        self.assertEqual(d["decision"], "too_easy")


class MeasuredLadder(unittest.TestCase):
    """Granite answers three times (majority decides); an unreadable answer is asked again, never a failure."""

    def _solver(self, replies, kind="letters", key="AC"):
        res = SimpleNamespace(answer=key, kind=kind, unit="", tolerance=0.001)
        it = iter(replies)
        calls = []

        def solve(stem, names, spec):
            calls.append(names[0])
            return [{"name": names[0], "final_answer": next(it), "final_value": None}]
        return IQ._measured_solver(res, solve), calls

    def test_fails_only_if_right_at_most_once_in_five(self):
        bottom = IQ.models.LADDER[0][0]
        for replies, solved, n_calls in ((["AC", "B", "AC"], True, 3),          # 2nd right answer: solved, stop
                                         (["AC", "B", "D", "B", "B"], False, 5),  # 1 of 5 right: fails
                                         (["B", "B", "B", "B"], False, 4),        # 4 wrong: decided, stop
                                         (["B", "AC", "B", "B", "AC"], True, 5)):  # 2 of 5 right: borderline, not hard
            measured, calls = self._solver(replies)
            m = measured("stem", [bottom], None)[0]
            self.assertEqual(m["final_answer"] == "AC", solved, replies)
            self.assertEqual(len(calls), n_calls, replies)

    def test_unreadable_is_asked_again(self):
        bottom = IQ.models.LADDER[0][0]
        measured, calls = self._solver(["[TYPE: chemistry] [CALC_VALUE:]", "AC", "AC", "B"])
        self.assertEqual(measured("stem", [bottom], None)[0]["bottom_tries"], "2/2")
        self.assertEqual(len(calls), 3)                       # one re-ask, then two right: solved

    def test_still_unreadable_is_held(self):
        from core.pipeline.stages import CouncilMemberFailed
        measured, _ = self._solver(["??"] * 5)
        with self.assertRaises(CouncilMemberFailed):
            measured("stem", [IQ.models.LADDER[1][0]], None)

    def test_other_steps_answer_once(self):
        measured, calls = self._solver(["AC"])
        self.assertEqual(measured("stem", [IQ.models.LADDER[1][0]], None)[0]["final_answer"], "AC")
        self.assertEqual(len(calls), 1)

    def test_shared_judge_untouched(self):
        """Organic and physical keep GLM-solved questions as "advanced" (flow.judge is not changed)."""
        self.assertEqual(models.DIFFICULTY_LABELS["glm-5.3-flash"], "advanced")
        import inspect
        from core.pipeline import flow
        self.assertNotIn("TOO_EASY_SOLVERS", inspect.getsource(flow))


if __name__ == "__main__":
    unittest.main()
