"""Organic question-first flow (core/pipeline/org_qfirst.py) and the property functions it checks claims with
(core/engine/organic/props.py): tree draws, the code key, and one run end to end with scripted models. Offline.
Run: python -m unittest tests.test_org_qfirst"""

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
from core.engine.base import EngineError                        # noqa: E402
from core.engine.organic import props as OP                     # noqa: E402
from core.engine.organic import rules as R                      # noqa: E402
from core.engine.organic.labels import REAGENT_LABEL            # noqa: E402
from core.engine.organic.mol import classes                     # noqa: E402
from core.pipeline import org_qfirst as OQ, queues              # noqa: E402
from subject_config import get_subject_config                   # noqa: E402

CFG = get_subject_config("organic")


def _adapter(output_file=os.path.join(os.path.dirname(__file__), "_no_such_output.json")):
    """No accepted questions by default: what the real output file has used up must not change the tests."""
    return SimpleNamespace(config=dict(CFG, display_name="Organic Chemistry", output_file=output_file),
                           subject="organic")


def hinge_claims(c) -> list:
    """An msq whose answer is A: (A) a decisive fact stated right, (B) and (C) other decisive facts stated as the
    wrong turn gives them, (D) plainly false. A, B and C hinge on a selectivity step; at most one filler (O2, live
    review 2026-11-26). StopIteration if the scheme has no three distinct decisive facts."""
    kinds = OP.PROPERTIES
    facts = []
    for lab, prop, right, wrong, how in c["_hinge"]:
        if kinds.get(prop) in ("number", "bool", "formula", "text"):
            facts.append((lab, prop, right, wrong, OQ._source(how)))
    f1 = facts[0]                                    # two decisive facts from DIFFERENT steps
    f2 = next(f for f in facts if f[4] != f1[4] and (f[0], f[1]) != (f1[0], f1[1]))
    f3 = next(f for f in facts if (f[0], f[1]) not in {(f1[0], f1[1]), (f2[0], f2[1])})
    (l1, p1, r1, _, _), (l2, p2, _, w2, _), (l3, p3, _, w3, _) = f1, f2, f3
    return [{"text": "a", "compound": l1, "property": p1, "value": str(r1)},
            {"text": "b", "compound": l2, "property": p2, "value": str(w2)},
            {"text": "c", "compound": l3, "property": p3, "value": str(w3)},
            {"text": "d", "compound": "P", "property": "rings", "value": "9"}]


class Props(unittest.TestCase):
    def a(self, s):
        return OP.askable(s)

    def test_tests_found_in_review(self):
        """2026-11-24: aldehydes decolourise Br2 water; amides give no carbylamine test; HCOOH reduces Fehling's;
        picric acid frees CO2 from NaHCO3 (p-nitrophenol does not)."""
        for s, k, want in [("CCC=O", "bromine_water_decolourised", True), ("CC(C)=O", "bromine_water_decolourised", False),
                           ("CCC(N)=O", "carbylamine_test", False), ("CCN", "carbylamine_test", True),
                           ("O=CO", "fehling_test", True), ("O=Cc1ccccc1", "fehling_test", False),
                           ("O=[N+]([O-])c1cc([N+](=O)[O-])c(O)c([N+](=O)[O-])c1", "nahco3_effervescence", True),
                           ("O=[N+]([O-])c1ccc(O)cc1", "nahco3_effervescence", False)]:
            self.assertEqual(self.a(s).get(k), want, f"{s} {k}")

    def test_stereo(self):
        self.assertEqual((self.a("CC(O)C(C)O")["stereocentres"], self.a("CC(O)C(C)O")["stereoisomers"]), (2, 3))  # meso
        for s in ("CC1CCC(=NO)CC1", "CC1CCC(C)CC1"):  # no chiral carbon (run 18: oxime ring C was counted)
            self.assertEqual(self.a(s)["stereocentres"], 0, s)
        self.assertEqual(self.a("COC(C)C1CCC(=NO)CC1")["stereocentres"], 1)
        self.assertTrue(self.a("CC=CC")["geometrical_isomerism"])
        self.assertFalse(self.a("C=CC")["geometrical_isomerism"])

    def test_tests(self):
        self.assertTrue(self.a("CCO")["iodoform_test"])
        self.assertTrue(self.a("CC=O")["iodoform_test"])
        self.assertFalse(self.a("CCCO")["iodoform_test"])
        self.assertTrue(self.a("O=Cc1ccccc1")["tollens_test"])
        self.assertFalse(self.a("O=Cc1ccccc1")["fehling_test"])
        self.assertTrue(self.a("O=Cc1ccccc1")["dnp_test"])
        self.assertEqual(self.a("CC(C)(C)O")["lucas_test"], "immediate turbidity")
        self.assertEqual(self.a("CNC")["amine_class"], "secondary")
        self.assertEqual(self.a("Oc1ccccc1")["pi_bonds"], 3)

    def test_compare(self):
        self.assertTrue(OP.compare("stereoisomers", 3, "3"))
        self.assertTrue(OP.compare("iodoform_test", True, "positive"))
        self.assertTrue(OP.compare("structure", "CCO", "OCC"))
        self.assertTrue(OP.compare("molecular_formula", "C2H6O", "C2H6O"))
        self.assertFalse(OP.compare("functional_group", ["alcohol"], "ketone"))


class Draw(unittest.TestCase):
    def test_tree_draws(self):
        ad, rng = _adapter(), random.Random(0)
        for _ in range(10):
            c = OQ.draw(ad, rng)
            self.assertIsNotNone(c)
            n = len(c["_order"]) - 1
            self.assertTrue(OQ.STEPS_MIN <= n <= OQ.STEPS_MAX, n)
            parents = [c["_comps"][k]["parent"] for k in c["_order"][1:]]
            self.assertTrue(any(parents.count(p) >= 2 for p in parents))                # a branch point
            for k in c["_order"][1:]:
                comp = c["_comps"][k]
                self.assertIn(comp["edge"]["to"], classes(comp["smiles"]))
            self.assertNotIn("[", OQ.scheme_text(c).split("\n")[0])

    def test_every_rule_has_a_label(self):
        self.assertEqual(set(R.RULES), set(REAGENT_LABEL))

    def test_evaluate_claims(self):
        # the first scheme with two printable decisive facts on different steps (scope changes alter what a
        # given seed draws, so the test does not pin one seed)
        for seed in range(3, 40):
            c = OQ.draw(_adapter(), random.Random(seed))
            try:
                claims = hinge_claims(c)
                break
            except StopIteration:
                continue
        else:
            self.fail("no scheme with two decisive facts in 37 draws")
        res, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": claims})
        self.assertEqual(probs, [])
        self.assertEqual(res.answer, "A")
        _, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": claims[1:]})
        self.assertTrue(probs)

    def test_statements_no_wrong_turn_changes_are_rejected(self):
        """Live run 6 (2026-11-24): one-step checks that no selectivity step decides make a Main-level question."""
        c = OQ.draw(_adapter(), random.Random(3))
        self.assertGreaterEqual(len({(h[0], h[1]) for h in c["_hinge"]}), OQ.MIN_HINGE)
        lab = c["_order"][-1]
        f = c["_props"][lab]["molecular_formula"]
        easy = [{"text": "t", "compound": "P", "property": "molecular_formula", "value": c["_props"]["P"]["molecular_formula"]},
                {"text": "f", "compound": lab, "property": "molecular_formula", "value": "C99H1"},
                {"text": "f", "compound": "P", "property": "stereocentres", "value": "7"},
                {"text": "f", "compound": "P", "property": "rings", "value": "9"}]
        _, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": easy})
        self.assertTrue(any("DECISIVE FACTS" in p for p in probs), probs)
        self.assertIn("DECISIVE FACTS", OQ.facts_text(c))

    def test_two_statements_on_one_step_count_once(self):
        """Live run 10 (2026-11-24): "S has NO2" and "T has NO2" both rested on the AgNO2 step: one decision."""
        for seed in range(60):
            c = OQ.draw(_adapter(), random.Random(seed))
            by = {}
            for lab, prop, right, wrong, how in c["_hinge"]:
                if OP.PROPERTIES.get(prop) in ("number", "bool", "formula", "text"):
                    by.setdefault(OQ._source(how), []).append((lab, prop, right, wrong))
            same = next((v for v in by.values() if len({(f[0], f[1]) for f in v}) >= 2), None)
            if same:
                break
        else:
            self.skipTest("no draw with two facts on one step")
        f1 = same[0]
        f2 = next(f for f in same if (f[0], f[1]) != (f1[0], f1[1]))
        if OQ.claim_sources(c, f1[0], f1[1], str(f1[2])) != OQ.claim_sources(c, f2[0], f2[1], str(f2[3])) or \
                len(OQ.claim_sources(c, f1[0], f1[1], str(f1[2]))) != 1:
            self.skipTest("these facts also depend on another step")
        claims = [{"text": "a", "compound": f1[0], "property": f1[1], "value": str(f1[2])},
                  {"text": "b", "compound": f2[0], "property": f2[1], "value": str(f2[3])},
                  {"text": "c", "compound": "P", "property": "stereocentres", "value": "7"},
                  {"text": "d", "compound": "P", "property": "rings", "value": "9"}]
        _, probs = OQ.evaluate(c, {"format": "msq", "lead": "x", "ask": "Which?", "claims": claims})
        self.assertTrue(any("DIFFERENT steps" in p for p in probs), probs)

    def test_integer_must_ask_a_decisive_number(self):
        found = None                                  # a number that two different wrong turns change (rare)
        for seed in range(200):
            c = OQ.draw(_adapter(), random.Random(seed))
            by = {}
            for h in c["_hinge"]:
                if h[1] in OQ._NUMERIC:
                    by.setdefault((h[0], h[1], h[2]), set()).add(OQ._source(h[4]))
            found = next((k for k, v in by.items() if len(v) >= OQ.MIN_HINGE), None)
            if found:
                break
        if not found:
            self.skipTest("no draw with a number two different steps decide")
        lab, prop, right = found
        res, probs = OQ.evaluate(c, {"format": "integer", "lead": "", "ask": "How many?",
                                     "claims": [{"compound": lab, "property": prop}]})
        self.assertEqual(probs, [])
        self.assertEqual(res.answer, right)
        _, probs = OQ.evaluate(c, {"format": "integer", "lead": "", "ask": "How many?",
                                   "claims": [{"compound": "P", "property": "rings"}]})   # P has no wrong turn
        self.assertTrue(any("DECISIVE FACTS" in p for p in probs), probs)


class StepCheck(unittest.TestCase):
    def test_verdicts(self):
        from core.pipeline import org_step_check as SC
        self.assertEqual(SC.verdict("CC(=O)Cl", {"product_smiles": "CC(=O)Cl.CCCl"}), "agree")   # by-product listed
        self.assertEqual(SC.verdict("CCO", {"product_smiles": "OCC"}), "agree")                  # same molecule
        self.assertEqual(SC.verdict("CCO", {"product_smiles": "CC=O"}), "disagree")
        self.assertEqual(SC.verdict("CCO", {"product_smiles": "", "no_single_product": True}), "disagree")
        self.assertEqual(SC.verdict("CCO", {"product_smiles": "not a smiles("}), "unparsed")
        self.assertEqual(SC.verdict("CCO", {"error": "timeout"}), "error")                       # never a pass

    def test_split_steps_need_a_clear_main_piece(self):
        """Live run 9 (2026-11-24): aryl acetate hydrolysis called acetic acid "S" (the phenol is the main piece)."""
        from core.pipeline import org_step_check as SC
        g = OQ._graph(_adapter())["edges"]
        for eid, s, ok in [("ester_to_ester_aqnaoh", "CC(=O)Oc1ccccc1", False),      # acetic acid + phenol
                           ("ester_to_ester_aqnaoh", "CCOC(=O)c1ccccc1", True),       # benzoic acid + ethanol
                           ("aldehyde_to_substituted_benzene_naohaqueouss", "O=Cc1ccccc1", False),  # Cannizzaro
                           ("ether_to_alkyl_halide_conchxhihbra", "COc1ccccc1", False)]:           # CH3I + phenol
            self.assertEqual(OQ._main_piece(R.apply(g[eid], s)), ok, eid)
        self.assertEqual(SC.verdict("CC(=O)O", {"product_smiles": "CC(=O)O.Oc1ccccc1"}), "disagree")
        self.assertEqual(SC.verdict("Oc1ccccc1", {"product_smiles": "CC(=O)O.Oc1ccccc1"}), "agree")

    def test_a_step_may_not_lose_most_of_the_skeleton(self):
        """Live run 10 (2026-11-24): HI 1 equiv on a methyl ether / acetal continued the scheme as "T = CH3I"."""
        e = OQ._graph(_adapter())["edges"]["ether_to_alkyl_halide_conchxhihbra"]
        for s in ("COCCC(=O)c1ccc(C=O)cc1", "COC(CC1=CCCCC1=O)OC"):
            self.assertIsNone(OQ._step({"out": {"x": [e]}}, "x", s, set(), random.Random(0)), s)

    def test_run9_holds_closed_by_scope(self):
        g = OQ._graph(_adapter())["edges"]
        for eid, s in [("substituted_benzene_to_carboxylic_acid_1naoh", "OCc1cc(CC2CO2)ccc1O"),   # epoxide opens
                       ("ether_to_alkyl_halide_conchxhihbra", "CC(O)COc1ccc(C(C)O)cc1"),         # HI takes the OH
                       ("alcohol_to_substituted_benzene_4methylbenze", "CC(O)COc1ccc(C(C)O)cc1")]:  # which OH?
            with self.assertRaises(EngineError, msg=eid):
                R.apply(g[eid], s)

    def test_run12_holds_closed_by_scope(self):
        """Live run 12 (2026-11-24): every scheme was held; these were the patterns."""
        g = OQ._graph(_adapter())["edges"]
        for eid, s in [("substituted_benzene_to_carboxylic_acid_1naoh", "C=CCc1ccc(O)c(C(OC)OC)c1"),  # H3O+ opens acetal
                       ("alkene_to_halohydrin_br", "C=CCc1ccc(OC)c(C(OC)OC)c1"),                       # Br2 water too
                       ("alkyl_halide_to_nitrile_nacn", "COC(=O)C(Br)C(Br)c1ccccc1"),                  # two different C-Br
                       ("alkyl_halide_to_nitrile_nacn", "CC(Br)CCCBr"),
                       ("aldehyde_to_acetal_roh2", "C=CCc1ccc(O)c(C=O)c1"),                            # dry HCl adds to C=C
                       ("ketone_to_carbene_methylenepho", "CC(=O)CCCOS(=O)(=O)c1ccc(C)cc1"),           # ylide vs OTs
                       ("alcohol_to_carbene_chndiazometh", "O=C1CCC(CCO)CC1"),                         # CH2N2/H+ + C=O
                       ("carboxylic_acid_to_ester_roh", "CC(CCC(=O)O)=NO")]:                            # Beckmann
            with self.assertRaises(EngineError, msg=f"{eid} {s}"):
                R.apply(g[eid], s)
        self.assertEqual(R.apply(g["alkyl_halide_to_nitrile_nacn"], "BrCCCCCCBr").product, "N#CCCCCCCC#N")  # equivalent

    def test_a_failed_call_is_not_a_pass(self):
        from core.pipeline import org_step_check as SC
        c = OQ.draw(_adapter(), random.Random(3))

        def boom(*a, **k):
            raise RuntimeError("network")
        with mock.patch.object(models, "ask_json", boom):
            bad = SC.check_scheme(c)
        self.assertEqual(len(bad), len(c["_order"]) - 1)
        self.assertTrue(all(b["verdict"] == "error" for b in bad))


class TrustedOnly(unittest.TestCase):
    def test_only_scoped_edges_are_drawn(self):
        """Live run 7 (2026-11-24): an edge with no scope (conc. H2SO4, 383 K) fired on a 2° benzylic alcohol."""
        from core.engine.organic.scope import trusted
        g = OQ._graph(_adapter())
        drawn = [e for es in g["out"].values() for e in es]
        self.assertTrue(drawn)
        self.assertTrue(all(trusted(e) for e in drawn))
        ids = {e["id"] for e in drawn}
        for left_out in ("alcohol_to_amine_al2o3450c", "alkyl_halide_to_ketone_dmsodimethyl",
                         "ester_to_ether_conchso", "ether_to_ester_co"):
            self.assertNotIn(left_out, ids)
        # the run-7 step now has a scope: simple 1° alcohols only
        with self.assertRaises(EngineError):
            R.apply(g["edges"]["alcohol_to_sulfonate_conchso"], "C=CCc1ccc(OC)c(C(C)O)c1")
        self.assertEqual(R.apply(g["edges"]["alcohol_to_sulfonate_conchso"], "CCO").product, "CCOS(=O)(=O)O")


class StartPicker(unittest.TestCase):
    """core/pipeline/org_start.py: the model invents the start, the engine checks it (2026-11-23)."""

    def test_engine_check(self):
        from core.pipeline import org_start as S
        ok, why, _ = S.check_start(_adapter(), "CCC", random.Random(1))
        self.assertFalse(ok)                                       # too small, one group
        ok, why, _ = S.check_start(_adapter(), "CCCCCCO", random.Random(1))
        self.assertFalse(ok)
        self.assertIn("only 1", why)                               # one group the reagents act on
        ok, why, st = S.check_start(_adapter(), "C=CCc1ccc(C(C)=O)cc1", random.Random(1))
        self.assertTrue(ok, why)
        self.assertTrue(OQ.STEPS_MIN <= st["scheme_steps"] <= OQ.STEPS_MAX)

    def test_used_up_reactions_do_not_count(self):
        """A start whose reactions are all used up (MAX_EDGE_USES) is refused and the menu leaves them out
        (batch 2026-11-26: such starts built no scheme, draw after draw)."""
        import tempfile
        from core.pipeline import org_start as S
        smi = "C=CCc1ccc(C(C)=O)cc1"
        g = OQ._graph(_adapter())
        from core.engine.organic.mol import classes
        edges = [e["id"] for n in classes(smi) for e in g["out"].get(n, [])]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump([{"engine": {"graph_edges": edges}}] * OQ.MAX_EDGE_USES, f)
            ok, why, _ = S.check_start(_adapter(out), smi, random.Random(1))
            self.assertFalse(ok)
            self.assertIn("only 0", why)
            menu = S._reaction_menu(g, OQ.overused_edges(_adapter(out)))
            self.assertNotIn("- alkene:", menu)

    def test_groups_that_react_together_are_refused(self):
        """2026-11-24 (runs 8, 12-14): starts whose groups react with each other gave the held schemes."""
        from core.pipeline import org_start as S
        for smi in ("CC(=O)c1ccc(O)c(CC=C)c1",       # o-allyl phenol: cyclises under Hg2+ (run 14)
                    "CC(=O)c1ccc(C=CC(C)O)cc1",      # allylic alcohol (run 14)
                    "O=C1CCCC=C1CO",                 # run 8's wrong question
                    "CC(O)(C#N)c1ccccc1",            # cyanohydrin
                    "NCC(C)Br"):                     # beta-bromoamine
            self.assertTrue(S.close_groups(smi), smi)
            ok, why, _ = S.check_start(_adapter(), smi, random.Random(1))
            self.assertFalse(ok)
            self.assertIn("react with each other", why)
        for smi in ("O=Cc1cc(CC=C)ccc1O",            # run 11's good start (salicyl type)
                    "O=C1CCC(C#CCCO)CC1",            # run 10's good start
                    "OC(=O)CCC(=O)O", "O=Cc1ccc(/C=C/C(=O)O)cc1", "C=Cc1ccc(O)cc1"):
            self.assertEqual(S.close_groups(smi), [], smi)

    def test_draw_from_given_start_uses_every_group(self):
        c = OQ.draw(_adapter(), random.Random(3), start=("x", "CC(=O)CCC(=O)OCC"), attempts=300)
        self.assertIsNotNone(c)
        self.assertEqual(c["_start"][1], "CCOC(=O)CCC(C)=O")
        self.assertTrue(any(c["_comps"][k]["parent"] is not None for k in c["_order"][1:]))

    def test_refused_then_accepted_with_name_check(self):
        from core.pipeline import org_start as S
        replies = iter([{"name": "ethanol", "smiles": "CCO"},                                   # engine refuses
                        {"name": "1-[4-(prop-2-en-1-yl)phenyl]ethan-1-one", "smiles": "C=CCc1ccc(C(C)=O)cc1"}])
        prompts = []

        def fake(role, model, system, user, **kw):
            if role == "name_checker":
                return {"smiles": "CC(=O)c1ccc(CC=C)cc1"}         # same molecule, written differently
            prompts.append(user)
            return next(replies)
        # the live outputs hold an accepted question from this very molecule: the test must not depend on them
        with mock.patch.object(models, "ask_json", fake), mock.patch.object(S, "_accepted_starts", lambda a: set()):
            p = S.pick_start(_adapter(), random.Random(1))
        self.assertEqual(p["tries"], 2)
        self.assertIn("was refused", prompts[1])                   # the picker is told why

    def test_name_mismatch_refused(self):
        from core.pipeline import org_start as S

        def fake(role, model, system, user, **kw):
            if role == "name_checker":
                return {"smiles": "CCC(=O)c1ccc(CC=C)cc1"}        # the name says propan-1-one
            return {"name": "1-[4-(prop-2-en-1-yl)phenyl]propan-1-one", "smiles": "C=CCc1ccc(C(C)=O)cc1"}
        with mock.patch.object(models, "ask_json", fake):
            self.assertIsNone(S.pick_start(_adapter(), random.Random(1)))

    def test_no_exam_question_in_prompt(self):
        from core.pipeline import org_start as S
        seen = []

        def fake(role, model, system, user, **kw):
            seen.append(user)
            return {}
        with mock.patch.object(models, "ask_json", fake):
            S.pick_start(_adapter(), random.Random(1))
        self.assertTrue(seen)
        self.assertFalse(any("JEE" in u or "jee_advanced" in u for u in seen))


class EndToEnd(unittest.TestCase):
    """A whole organic run: tree draw -> designer -> writer claims -> code key -> ladder -> saved."""

    def setUp(self):
        import run_groundup_final as entry
        self.entry = entry
        self.tmp = tempfile.mkdtemp()
        self.cfg = dict(CFG, output_file=os.path.join(self.tmp, "out.json"),
                        pending_file=os.path.join(self.tmp, "pending.json"),
                        coverage_state_file=os.path.join(self.tmp, "cov.json"))
        # the first scheme with two decisive facts on different steps (new edges change what a seed draws)
        for seed in range(5, 60):
            self.cand = OQ.draw(_adapter(), random.Random(seed))
            try:
                hinge_claims(self.cand)
                break
            except StopIteration:
                continue
        self.lab = self.cand["_order"][-1]
        self.p = [mock.patch.object(entry, "get_subject_config", lambda s: self.cfg),
                  mock.patch.object(models, "key_is_set", lambda *a: True),
                  mock.patch.object(dedup, "STORE", __import__("pathlib").Path(self.tmp, "seen.json")),
                  mock.patch.object(queues, "_OUT", self.tmp),
                  mock.patch("tools.results.promote", lambda *a, **k: 0),
                  mock.patch.object(entry, "compute_meta_tags_for_subject", lambda *a, **k: {"stub": True}),
                  mock.patch("core.pipeline.qf_design.design_problems", lambda d, *a, **k: None),
                  mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: None),
                  mock.patch.object(OQ, "draw", lambda *a, **k: dict(self.cand)),
                  mock.patch("core.pipeline.org_start.pick_start",
                             lambda *a, **k: {"name": "propane", "smiles": "CCC", "why": "", "stats": {}, "tries": 1})]
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

    def fake(self, role, model, system, user, **kw):
        if role == "designer":
            return {"system": "a scheme", "hidden": {"Q": "an intermediate"}, "hidden_link": "each compound",
                    "route": "follow the scheme", "student_must_notice": "the branch", "trap": "a wrong formula",
                    "given": "the scheme", "asked": "formulas", "format": "msq"}
        if role == "generator" and "Write ONE JEE Advanced" in user:
            return {"lead": "Consider the scheme.", "ask": "Which statements are correct?",
                    "claims": hinge_claims(self.cand)}
        if role == "step_checker":                              # the blind step check: agree unless told not to
            comps = self.cand["_comps"]
            for lab in self.cand["_order"][1:]:
                c = comps[lab]
                if f"substrate (SMILES): {comps[c['parent']]['smiles']}\n" in user and \
                        f"reagent and conditions: {REAGENT_LABEL[c['edge']['id']]}\n" in user:
                    if getattr(self, "checker_disagrees", False):
                        return {"product_smiles": "CCCCCCCCCC", "no_single_product": False, "reason": "other"}
                    return {"product_smiles": c["smiles"], "no_single_product": False, "reason": "same"}
            return {"product_smiles": "", "no_single_product": True, "reason": "unknown step"}
        if role == "council":
            ladder = [m for _, m in models.LADDER]
            if getattr(self, "nobody_solves", False):           # every model wrong, and not all the same
                ans = "BCD"[ladder.index(model) % 3] if model in ladder else "B"
            else:
                ans = "B" if model == ladder[0] else "A"
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
        self.assertEqual(r["answer"], "A")                          # computed by code
        self.assertIn("P = ", r["question"])                        # the scheme is printed by code

    def test_step_the_checker_does_not_confirm_holds_the_scheme(self):
        """2026-11-24: a step GPT-6 Luna (blind) does not confirm holds the scheme before any question is written."""
        self.checker_disagrees = True
        calls = []
        real = self.fake

        def spy(role, *a, **k):
            calls.append(role)
            return real(role, *a, **k)
        with mock.patch.object(models, "ask_json", spy), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            self.entry.main()
        self.assertFalse(os.path.exists(self.cfg["output_file"]) and json.load(open(self.cfg["output_file"])))
        held = queues.load("step_disagreement", "organic")
        self.assertTrue(held)
        self.assertEqual(len(held[0]["steps"]), len(self.cand["_order"]) - 1)
        self.assertNotIn("designer", calls)                     # nothing paid for after the check

    def test_one_picked_molecule_serves_several_schemes(self):
        """2026-11-24: the picker is most of a run's cost; up to SCHEMES_PER_START schemes per picked molecule."""
        self.checker_disagrees = True                           # every scheme held: the run uses all its draws
        picks = []

        def pick(*a, **k):
            picks.append(1)
            return {"name": "propane", "smiles": "CCC", "why": "", "stats": {}, "tries": 1}
        with mock.patch.object(models, "ask_json", self.fake), \
                mock.patch("core.pipeline.org_start.pick_start", pick), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            self.entry.main()
        self.assertEqual(len(picks), -(-OQ.MAX_DRAWS // OQ.SCHEMES_PER_START))   # 6 draws, 3 per molecule: 2 picks

    def test_unconfirmed_key_is_held_not_accepted(self):
        """2026-11-24: no ladder model reaches the code's key -> held for review (a wrong engine step looks
        exactly like a very hard question)."""
        self.nobody_solves = True
        with mock.patch.object(models, "ask_json", self.fake), \
                mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            self.entry.main()
        self.assertFalse(os.path.exists(self.cfg["output_file"]) and json.load(open(self.cfg["output_file"])))
        held = queues.load("unconfirmed_key", "organic")
        self.assertTrue(held)
        self.assertEqual(held[0]["engine_answer"], "A")


    def test_below_level_floor_is_dropped(self):
        # organic level check (knowledge/level_calibration_organic.json): below the floor, no ladder, nothing saved
        with mock.patch.object(models, "ask_json", self.fake),                 mock.patch("core.pipeline.qf_checks._level_floor", lambda *a, **k: 1.85),                 mock.patch("core.pipeline.qf_checks.jev_level", lambda *a, **k: 1.2),                 mock.patch.object(sys, "argv", ["run_groundup_final.py", "--subject", "organic", "--seed", "1"]):
            self.entry.main()
        self.assertFalse(os.path.exists(self.cfg["output_file"]) and json.load(open(self.cfg["output_file"])))


class Checkpoint(unittest.TestCase):
    """--resume (the author, 2026-11-25): a saved scheme is rebuilt exactly, with the design and question kept."""

    def test_save_and_rebuild(self):
        ad = _adapter()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(OQ, "CHECKPOINT", os.path.join(d, "cp.json")):
            for seed in range(5):
                c = OQ.draw(ad, random.Random(seed))
                OQ.save_checkpoint("question", c, design={"format": "msq"}, question={"ask": "x"})
                back, cp = OQ.load_checkpoint(ad)
                self.assertEqual(back["edges"], c["edges"])
                self.assertEqual({k: back["_comps"][k]["smiles"] for k in back["_order"]},
                                 {k: c["_comps"][k]["smiles"] for k in c["_order"]})
                self.assertEqual(back["_hinge"], c["_hinge"])
                self.assertEqual((cp["design"], cp["question"]), ({"format": "msq"}, {"ask": "x"}))
            OQ.clear_checkpoint()
            self.assertIsNone(OQ.load_checkpoint(ad))


if __name__ == "__main__":
    unittest.main()
