"""The inorganic "hidden products" count question (core/pipeline/inorg_products.py)."""

import json
import os
import random
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import models                              # noqa: E402
from core.engine.inorganic import species as S       # noqa: E402
from core.pipeline import inorg_products as IP       # noqa: E402
from subject_config import get_subject_config          # noqa: E402

with open(get_subject_config("inorganic")["graph_path"], encoding="utf-8") as _f:
    EDGES = json.load(_f)["edges"]


class Parts(unittest.TestCase):
    def test_pretty(self):
        self.assertEqual(IP.pretty("Cr2O72-"), "Cr₂O₇²⁻")
        self.assertEqual(IP.pretty("MnO4-"), "MnO₄⁻")
        self.assertEqual(IP.pretty("Cu(OH)2"), "Cu(OH)₂")

    def test_reaction_text(self):
        e = {"from": "Na2B4O7", "to": "BF3", "reagents": ["Na₂B₄O₇", "Borax", "HF", "H₂SO₄"],
             "conditions": "Heating."}
        self.assertEqual(IP._reaction(e), "Na₂B₄O₇, HF, H₂SO₄, heating")
        self.assertIsNone(IP._reaction({"from": "H2O", "to": "H2", "reagents": ["M", "H2O"], "conditions": ""}))

    def test_notes_are_not_printed_as_conditions(self):
        """Live run 7 printed "werner's study"; mechanisms and uses are notes, not conditions."""
        for raw, want in [("Werner's study.", ""), ("Heating; commercial method.", "Heating"),
                          ("Trace alkali, push-pull mechanism.", "Trace alkali"),
                          ("50-100°C (used in baking powder).", "50-100°C"),
                          ("Room temperature, via SN2 mechanism.", "Room temperature"),
                          ("Activated Fe catalyst, 380-450°C, 200 atm", "Activated Fe catalyst, 380-450°C, 200 atm")]:
            self.assertEqual(IP._conditions(raw), want, raw)
        e = {"from": "CoCl3", "to": "[Co(NH3)6]Cl3", "reagents": ["CoCl₃", "NH₃"], "conditions": "Werner's study."}
        self.assertEqual(IP._reaction(e), "CoCl₃, NH₃")

    def test_named_element(self):
        self.assertEqual(IP.focus("K2MnO4", "metal_ion_magnetism"), "Mn")
        self.assertEqual(IP.focus("K4[Fe(CN)6]", "complex_magnetism"), "Fe")
        self.assertEqual(IP.focus("NO", "mo_magnetism"), "N")
        self.assertEqual(IP.focus("O2", "mo_magnetism"), "O")
        self.assertIsNone(IP.focus("H2", "mo_magnetism"))         # "the product containing H" names nothing
        self.assertEqual(IP.focus("H2SO4", "central_shape"), "S")
        self.assertEqual(IP.focus("XeF4", "shape"), "Xe")

    def test_same_species(self):
        self.assertTrue(IP.same_species("MnO42-", "MnO4", -2))
        self.assertTrue(IP.same_species("MnO42-", "MnO4^2-", 0))
        self.assertTrue(IP.same_species("[BeCl4]2-", "[BeCl4]2−", -2))      # U+2212 minus (graph audit)
        self.assertTrue(IP.same_species("K4[Fe(CN)6]", "K₄[Fe(CN)₆]", 0))
        self.assertFalse(IP.same_species("MnO42-", "MnO4", -1))
        self.assertFalse(IP.same_species("Cu(OH)2", "[Cu(NH3)4]SO4", 0))
        self.assertFalse(IP.same_species("CuO", None, None))

    def test_another_form_of_the_same_product(self):
        """The blind checker may name the ion of a salt or the entity of a complex: same answer, so agreed
        (live run 4 lost five draws to K4[Fe(CN)6] vs [Fe(CN)6]4- and the like); a different product is not."""
        def row(to, el, fam):
            return {"edge": {"to": to}, "element": el, "family": fam}
        for r, f, c, want in [(row("K4[Fe(CN)6]", "Fe", "magnetism"), "[Fe(CN)6]", -4, True),
                              (row("CuSO4", "Cu", "magnetism"), "Cu2+", 2, True),
                              (row("SrCrO4", "Cr", "magnetism"), "CrO4^2-", -2, True),
                              (row("K[Ag(CN)2]", "Ag", "magnetism"), "[Ag(CN)2]", -1, True),
                              (row("NO2", "N", "geometry"), "NO", 0, False),
                              (row("Fe(SCN)3", "Fe", "magnetism"), "[Fe(SCN)]", 2, False),
                              (row("Cu(OH)2", "Cu", "magnetism"), "[Cu(NH3)4]SO4", 0, False),
                              (row("[Co(NH3)4Cl2]Cl", "Co", "magnetism"), "[Co(NH3)6]Cl3", 0, False),
                              (row("FeCl2", "Fe", "magnetism"), "FeCl3", 0, False)]:
            self.assertEqual(IP.same_answer(r, f, c), want, f"{r['edge']['to']} vs {f}")


class Draw(unittest.TestCase):
    def test_fair_questions_that_never_print_a_product(self):
        rng = random.Random(0)
        for _ in range(100):
            c = IP.draw(EDGES, rng)
            self.assertIsNotNone(c)
            D = c["_products"]
            n, k = len(D["rows"]), sum(D["truth"])
            self.assertTrue(IP.N_MIN <= n <= IP.N_MAX)
            self.assertTrue(2 <= k <= n - 2)                      # never 0, 1 or all
            self.assertEqual(len({r["edge"]["to"] for r in D["rows"]}), n)
            self.assertGreaterEqual(len(c["chapters"]), 2)
            stem, res = IP.question(c)
            self.assertEqual(res.answer, k)
            for r in D["rows"]:
                prod = S.to_formula_charge(r["edge"]["to"])[0]
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9(\[])" + re.escape(prod) + r"(?![A-Za-z0-9([])",
                                            IP._plain(r["text"])), f"{prod} printed in {r['text']}")

    def test_no_shape_asked_of_ionic_or_polymeric_solids(self):
        pool = IP._pool(EDGES)
        for fam in ("geometry", "hybridisation"):
            self.assertFalse({r["edge"]["to"] for r in pool[fam]} & {"PbCl2", "SnCl2", "AlCl3", "BeCl2", "Al(OH)3"})
            self.assertFalse({r["edge"]["to"].split("·")[0] for r in pool[fam]} & IP.NO_SHAPE)       # the audit's rulings
        self.assertNotIn("AsH3", {r["edge"]["to"] for r in pool["hybridisation"]})
        mag = {r["edge"]["to"] for r in pool["magnetism"]}
        self.assertIn("[Cu(NH3)4]SO4·H2O", mag)                  # d9: paramagnetic stays askable

    def test_bad_and_tried_are_left_out(self):
        c = IP.draw(EDGES, random.Random(1))
        ids = {r["edge"]["id"] for r in c["_products"]["rows"]}
        rng = random.Random(1)
        for _ in range(30):
            d = IP.draw(EDGES, rng, tried=c["edges"], bad=ids)
            self.assertNotEqual(d["edges"], c["edges"])
            self.assertFalse(ids & {r["edge"]["id"] for r in d["_products"]["rows"]})


class Check(unittest.TestCase):
    def setUp(self):
        self.c = IP.draw(EDGES, random.Random(4))
        self.rows = self.c["_products"]["rows"]

    def test_agreement_and_one_difference(self):
        prods = [{"n": i + 1, "formula": r["edge"]["to"], "charge": 0} for i, r in enumerate(self.rows)]
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"products": prods}):
            self.assertEqual(IP.check(self.c), [])
        prods[2] = {"n": 3, "formula": "XeF4", "charge": 0}
        with mock.patch.object(models, "ask_json", lambda *a, **k: {"products": prods}):
            bad = IP.check(self.c)
        self.assertEqual([b["edge"] for b in bad], [self.rows[2]["edge"]["id"]])

    def test_a_failed_call_never_passes(self):
        with mock.patch.object(models, "ask_json", side_effect=RuntimeError("down")):
            self.assertEqual(len(IP.check(self.c)), len(self.rows))


if __name__ == "__main__":
    unittest.main()
