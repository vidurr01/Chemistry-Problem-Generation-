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
PIPE = IP.with_naive(EDGES) + IP.variant_edges()     # the edges the pipeline draws from (graph + condition variants)


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

    def test_notes_found_in_the_2026_11_25_review(self):
        """Mechanisms, reasons and notes that name the product (from the graph's own condition texts)."""
        for raw, want in [("Addition-elimination.", ""), ("Exothermic reaction.", ""),
                          ("O₂, burning; ZnO called philosopher's wool", "O₂, burning"),
                          ("NaOH, fused; SiO₂ also dissolves as Na₂SiO₃", "NaOH, fused"),
                          ("H₂O; redox reaction (not hydrolysis, but included in text)", "H₂O"),
                          ("Hot water; cold water no reaction (protective oxide layer)", "Hot water"),
                          ("Electrolysis of molten NaCl with CaCl₂ to lower melting point",
                           "Electrolysis of molten NaCl with CaCl₂"),
                          ("Smelting at ~1300°C (above b.p. of Zn)", "Smelting at ~1300°C"),
                          ("Inert atmosphere (Ar) to avoid H₂ pickup", "Inert atmosphere (Ar)"),
                          # kept: real conditions, observations and process names
                          ("Controlled hydrolysis", "Controlled hydrolysis"), ("Acid treatment", "Acid treatment"),
                          ("pale yellow flame", "pale yellow flame"), ("Cyanide process", "Cyanide process"),
                          ("Slow hydrolysis", "Slow hydrolysis")]:
            self.assertEqual(IP._conditions(raw), want, raw)

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
            c = IP.draw(PIPE, rng)
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
        c = IP.draw(PIPE, random.Random(1))
        ids = {r["edge"]["id"] for r in c["_products"]["rows"]}
        rng = random.Random(1)
        for _ in range(30):
            d = IP.draw(PIPE, rng, tried=c["edges"], bad=ids)
            self.assertNotEqual(d["edges"], c["edges"])
            self.assertFalse(ids & {r["edge"]["id"] for r in d["_products"]["rows"]})

    def test_tried_as_the_pipeline_passes_it(self):
        from core.blackboard import Blackboard           # tried_edges() holds tuples (fixed 2026-11-25)
        bb = Blackboard("inorganic")
        c = IP.draw(PIPE, random.Random(1))
        bb.start_chain(c)
        self.assertNotEqual(IP.draw(PIPE, random.Random(1), tried=bb.tried_edges())["edges"], c["edges"])


class DesignedTrap(unittest.TestCase):
    """Redesign plan 2026-11-25, inorganic kind 1: every hidden-products question carries a designed trap."""

    def setUp(self):
        self.edges = IP.with_naive(EDGES) + IP.variant_edges()

    def test_variants_load_and_are_askable(self):
        v = IP.variant_edges()
        self.assertGreaterEqual(len(v), 10)
        for e in v:
            self.assertTrue(S.askable(e["to"]), e["to"])
            self.assertIsNotNone(IP._reaction(e), e["id"])
        naive = {e["id"]: e["naive"] for e in self.edges if e.get("naive")}
        self.assertEqual(naive.get("CuSO4_to_CuI_cuso"), "CuI2")

    def test_only_tempting_rivals(self):
        riv = IP.rivals(self.edges)
        co = [e for e in self.edges if e["from"] == "CO" and e["to"] == "COCl2"]
        if co:                                        # CO + Cl2 is no trap for CO + H2O
            self.assertNotIn("CO2", [s for s, _ in riv[co[0]["id"]]])
        self.assertIn("N2", [s for s, _ in riv["NH3_to_NO_nh"]])       # same reagents, another condition

    def test_every_draw_has_a_trap_that_moves_the_key(self):
        rng = random.Random(0)
        for _ in range(60):
            c = IP.draw(self.edges, rng)
            self.assertIsNotNone(c)
            self.assertGreaterEqual(len(c["_products"]["traps"]), IP.MIN_TRAP_ROWS)
            stem, res = IP.question(c)
            designed = [t for t in res.traps if t.get("designed")]
            self.assertTrue(designed)
            for t in designed:
                self.assertNotEqual(t["wrong_answer"], res.answer)
            for i, t in c["_products"]["traps"].items():   # the rival is never printed in its own reaction
                r = c["_products"]["rows"][i]
                prod = S.to_formula_charge(t["rival"])[0]
                self.assertIsNone(re.search(r"(?<![A-Za-z0-9(\[])" + re.escape(prod) + r"(?![A-Za-z0-9([])",
                                            IP._plain(r["text"])), f"{prod} printed in {r['text']}")


class Repeats(unittest.TestCase):
    def test_at_most_two_reactions_shared_with_an_accepted_question(self):
        """Live runs hp_8-10 repeated XeF₂, NO₂⁺, the CO shift and Al₄C₃."""
        first = IP.draw(PIPE, random.Random(3), prefer="geometry")
        asked = [frozenset(r["edge"]["id"] for r in first["_products"]["rows"])]
        rng = random.Random(4)
        for _ in range(20):
            c = IP.draw(PIPE, rng, prefer="geometry", asked=asked)
            if c is None:
                continue
            self.assertLessEqual(len({r["edge"]["id"] for r in c["_products"]["rows"]} & asked[0]), IP.MAX_SHARED)


class Check(unittest.TestCase):
    def setUp(self):
        self.c = IP.draw(PIPE, random.Random(4))
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


class Review20261125b(unittest.TestCase):
    """Second inorganic review of 2026-11-25: oxidation states and printed conditions."""

    def test_hydride_states(self):
        for sid, el, ox in (("B2H6", "B", 3), ("NaBH4", "B", 3), ("LiAlH4", "Al", 3), ("SiH4", "Si", 4),
                            ("H3BO3", "B", 3), ("PH3", "P", -3)):
            self.assertEqual(S.askable(sid)[f"oxidation_state:{el}"], ox, sid)

    def test_interhalogen_states(self):
        self.assertEqual(S.askable("ICl")["oxidation_state:Cl"], -1)
        self.assertEqual(S.askable("ICl")["oxidation_state:I"], 1)
        self.assertEqual(S.askable("ICl3")["oxidation_state:Cl"], -1)
        self.assertEqual(S.askable("IF7")["oxidation_state:I"], 7)

    def test_nickel_carbonyl(self):
        a = S.askable("Ni(CO)4")
        self.assertEqual((a["complex_geometry"], a["complex_hybridisation"], a["complex_magnetism"]),
                         ("tetrahedral", "sp3", "diamagnetic"))

    def test_ammonium_nitrate_has_no_average_n(self):
        self.assertNotIn("oxidation_state:N", S.askable("NH4NO3"))
        self.assertEqual(S.askable("NH4Cl")["oxidation_state:N"], -3)

    def test_leading_formula_keeps_case(self):
        self.assertEqual(IP.lead_lower("I₂ vapour"), "I₂ vapour")
        self.assertEqual(IP.lead_lower("Pt(II)"), "Pt(II)")
        self.assertEqual(IP.lead_lower("Room temperature"), "room temperature")

    def test_notes_leaks_and_repeats(self):
        self.assertEqual(IP._conditions("Pt(II), square planar."), "Pt(II)")
        self.assertEqual(IP._conditions("Acid medium; purple to colourless."), "Acid medium")
        self.assertEqual(IP._conditions("Cyanide process (McArthur-Forrest)"), "Cyanide process")
        self.assertEqual(IP._conditions("Fusion with KOH in air (or with KClO₃/KNO₃)"), "Fusion with KOH in air")
        self.assertEqual(IP.drop_repeated(["KI"], "excess KI"), [])
        self.assertIsNone(IP._reaction({"from": "HgCl2", "to": "Hg2Cl2", "reagents": [],
                                        "conditions": "Room temperature (white), boiling (black)."}))
        self.assertIsNone(IP._reaction({"from": "NaBr", "to": "Br-", "reagents": [], "conditions": ""}))


if __name__ == "__main__":
    unittest.main()
