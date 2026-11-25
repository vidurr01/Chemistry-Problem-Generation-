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
        pairs = set()
        for seed in range(200):
            c = IL.draw(random.Random(seed))
            L = c["_list"]
            props, values = L["properties"], L["values"]
            n, k = len(L["species"]), sum(L["truth"])
            self.assertTrue(IL.N_MIN <= n <= IL.N_MAX)
            self.assertEqual(len(set(L["species"])), n)
            self.assertTrue(2 <= k <= n - 2, (seed, k, n))              # never 0, 1 or all but one
            meets = {s: [R[s][p] == v for p, v in zip(props, values)] for s in L["species"]}
            for s, t in zip(L["species"], L["truth"]):                   # the key: both conditions, by code
                self.assertEqual(t, all(meets[s]))
            self.assertTrue(any(m == [True, False] for m in meets.values()), seed)   # half-right traps both ways
            self.assertTrue(any(m == [False, True] for m in meets.values()), seed)
            self.assertGreaterEqual(len(L["lookalikes"]), IL.MIN_LOOKALIKES)
            self.assertTrue(all(sum(meets[s]) == 1 for s in L["lookalikes"]))
            pairs.add(tuple(props))
            stem, res = IL.question(c)
            self.assertEqual(res.answer, k)
            self.assertEqual(res.kind, "count")
            self.assertIn(" and ", stem.split("the total number of species that ")[1])
        self.assertEqual(pairs, set(IL.PAIRS))

    def test_two_condition_stem(self):
        c = {"_list": {"properties": ["magnetism", "shape"], "values": ["paramagnetic", "tetrahedral"],
                       "species": ["[NiCl4]2-", "[Ni(CN)4]2-"], "truth": [True, False],
                       "computed": [["paramagnetic", "tetrahedral"], ["diamagnetic", "square planar"]]}}
        stem, res = IL.question(c)
        self.assertIn("the total number of species that are paramagnetic and have tetrahedral geometry is", stem)
        self.assertEqual(res.answer, 1)
        self.assertNotIn(("polarity", "shape"), IL.PAIRS)        # never two judgements in our table
        c["_list"].update(properties=["polarity", "hybridisation"], values=["polar", "sp3d"])
        self.assertIn("that are polar and have sp³d hybridisation of the central atom", IL.question(c)[0])

    def test_tried_lists_are_not_drawn_again(self):
        c = IL.draw(random.Random(7))
        again = IL.draw(random.Random(7), tried=set(c["edges"]))
        self.assertNotEqual(again["edges"], c["edges"])

    def test_tried_as_the_pipeline_passes_it(self):
        # the pipeline passes Blackboard.tried_edges(): tuples. Before 2026-11-25 nothing matched them.
        from core.blackboard import Blackboard
        bb = Blackboard("inorganic")
        c = IL.draw(random.Random(7))
        bb.start_chain(c)
        self.assertNotEqual(IL.draw(random.Random(7), tried=bb.tried_edges())["edges"], c["edges"])

    def test_stem(self):
        c = IL.draw(random.Random(3))
        stem, _ = IL.question(c)
        self.assertTrue(stem.startswith("Among "))
        self.assertIn("Give the answer as an integer.", stem)
        self.assertNotRegex(stem.splitlines()[0], r"[A-Za-z]\d")      # formulas printed with subscripts


class Spread(unittest.TestCase):
    def test_used_conditions_are_drawn_less(self):
        hot = "magnetism=paramagnetic&hybridisation=d2sp3"
        rng = random.Random(1)
        free = sum(IL.draw(rng)["edges"][0].split(":")[1] == hot for _ in range(200))
        rng = random.Random(1)
        busy = sum(IL.draw(rng, used={hot: 9})["edges"][0].split(":")[1] == hot for _ in range(200))
        self.assertLess(busy, free)


class SystemRepeats(unittest.TestCase):
    def test_same_species_with_another_lead_in_is_not_drawn(self):
        from core.pipeline import inorg_system as SY
        import tests.test_inorg_system as T
        asked = [frozenset({"N2", "NH3"})]
        rng, drawn = random.Random(2), 0
        for _ in range(60):
            c = SY.draw(T.G, rng, asked=asked)
            if c:
                drawn += 1
                self.assertLess(len({"N2", "NH3"} & set(c["_system"]["labels"])), 2)
        self.assertGreater(drawn, 0)

    def test_scheme_names_the_carried_element(self):
        from core.pipeline import inorg_system as SY
        self.assertEqual(SY.carrier({"from": "CO", "to": "CO2"}), "C")
        self.assertEqual(SY.carrier({"from": "NH3", "to": "N2"}), "N")
        self.assertEqual(SY.carrier({"from": "[Ag(CN)2]-", "to": "[Zn(CN)4]2-"}), "Zn")
        self.assertEqual(SY.carrier({"from": "KMnO4", "to": "K2MnO4"}), "Mn")


if __name__ == "__main__":
    unittest.main()
