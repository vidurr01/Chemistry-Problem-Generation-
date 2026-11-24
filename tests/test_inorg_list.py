"""The inorganic "how many species in this list" question (core/pipeline/inorg_list.py)."""

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline import inorg_list as IL       # noqa: E402

R = IL.ROWS


class Values(unittest.TestCase):
    """Values a JEE key depends on, checked against the books."""

    def test_known_species(self):
        for sid, prop, want in [("[PdCl4]2-", "shape", "square planar"), ("[PdCl4]2-", "hybridisation", "dsp2"),
                                ("[Cu(CN)4]3-", "shape", "tetrahedral"), ("[Ni(CO)4]", "hybridisation", "sp3"),
                                ("XeF4", "shape", "square planar"), ("SOCl2", "hybridisation", "sp3"),
                                ("SiO4^4-", "shape", "tetrahedral"), ("SO2Cl2", "shape", "tetrahedral"),
                                ("[Co(en)3]3+", "magnetism", "diamagnetic"), ("[FeF6]3-", "magnetism", "paramagnetic"),
                                ("O2-", "magnetism", "paramagnetic"), ("O2^2-", "magnetism", "diamagnetic"),
                                ("BrF5", "polarity", "polar"), ("XeF2", "polarity", "non-polar")]:
            self.assertEqual(R[sid][prop], want, f"{sid} {prop}")

    def test_left_out_where_books_differ(self):
        self.assertIsNone(R["PH3"]["hybridisation"])                 # unhybridised in JEE (Drago)
        self.assertNotIn("polarity", R["XeF6"])
        self.assertNotIn("polarity", R["NH4+"])                      # ions: no dipole-moment claim
        self.assertNotIn("He2", R)                                   # bond order 0: does not exist
        self.assertNotIn("[Co(NH3)6]2+", R)

    def test_pretty(self):
        self.assertEqual(IL.pretty("SO4^2-"), "SO₄²⁻")
        self.assertEqual(IL.pretty("[Fe(CN)6]4-"), "[Fe(CN)₆]⁴⁻")
        self.assertEqual(IL.pretty("I3-"), "I₃⁻")
        self.assertEqual(IL.pretty("[Ni(CO)4]"), "[Ni(CO)₄]")


class Draw(unittest.TestCase):
    def test_every_draw_is_a_fair_list(self):
        props = set()
        for seed in range(200):
            c = IL.draw(random.Random(seed))
            L = c["_list"]
            n, k = len(L["species"]), sum(L["truth"])
            self.assertTrue(IL.N_MIN <= n <= IL.N_MAX)
            self.assertEqual(len(set(L["species"])), n)
            self.assertTrue(2 <= k <= n - 2, (seed, k, n))              # never 0, 1 or all but one
            for s, t in zip(L["species"], L["truth"]):                   # the key is the computed value
                self.assertEqual(t, R[s][L["property"]] == L["value"])
            self.assertGreaterEqual(len(L["lookalikes"]), IL.MIN_LOOKALIKES)
            self.assertTrue(all(not R[s][L["property"]] == L["value"] for s in L["lookalikes"]))
            if L["property"] != "polarity":
                self.assertGreaterEqual(len({R[s]["class"] for s in L["species"]}), 2)
            props.add(L["property"])
            stem, res = IL.question(c)
            self.assertEqual(res.answer, k)
            self.assertEqual(res.kind, "count")
        self.assertEqual(props, set(IL.PROPS))

    def test_tried_lists_are_not_drawn_again(self):
        c = IL.draw(random.Random(7))
        again = IL.draw(random.Random(7), tried=set(c["edges"]))
        self.assertNotEqual(again["edges"], c["edges"])

    def test_stem(self):
        c = IL.draw(random.Random(3))
        stem, _ = IL.question(c)
        self.assertTrue(stem.startswith("Among "))
        self.assertIn("Give the answer as an integer.", stem)
        self.assertNotRegex(stem.splitlines()[0], r"[A-Za-z]\d")      # formulas printed with subscripts


if __name__ == "__main__":
    unittest.main()
