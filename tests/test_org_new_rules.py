"""Organic reactions added from the concept-book coverage audit (reviewer-approved, 2026-11-26): each rule's product,
its trap (the reaction a student confuses it with), and the cases it refuses."""

import json
import os
import unittest

from core.engine.base import EngineError
from core.engine.organic import rules as R
from core.engine.organic.mol import canon
from core.engine.organic.scope import trusted

GRAPH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge", "reaction_graph.json")

# edge id: [(start, product, {trap name: trap product})], [refused starts]
CASES = {
    "alkene_to_alcohol_bhthfhonaoh": ([("CC(C)=C", "CC(C)CO", {"markovnikov_product": "CC(C)(C)O"}),
                                       ("CCC=C", "CCCCO", {"markovnikov_product": "CCC(C)O"})], []),
    "acid_chloride_to_aldehyde_hpdbaso": ([("CCC(=O)Cl", "CCC=O", {"over_reduced_alcohol": "CCCO"})], []),
    "diol_to_ketone_conchso": ([("CC(C)(O)C(C)(C)O", "CC(=O)C(C)(C)C",
                                 {"double_dehydration_diene": "C=C(C)C(=C)C"})],
                               ["CC(C)(O)C(C)(O)c1ccccc1"]),            # two possible migrations: refused
    "alkene_to_alkyl_halide_cl773k": ([("C=CC", "C=CCCl", {"addition_dichloride": "CC(Cl)CCl"})],
                                      ["C=CCC"]),                       # allyl radical ends differ: refused
    "alcohol_to_ether_conchso413k": ([("CCO", "CCOCC", {"alkene_at_443K": "C=C"})], ["CC(C)O"]),
    "grignard_to_alkane_ho": ([("CC[Mg]Br", "CC", {})], ["Br[Mg]c1ccccc1"]),
    "sulfonate_to_nitrile_nacn": ([("CCCOS(=O)(=O)c1ccc(C)cc1", "CCCC#N", {"isocyanide": "[C-]#[N+]CCC"})], []),
    "sulfonate_to_alkyl_halide_nai": ([("CCCOS(=O)(=O)c1ccc(C)cc1", "CCCI", {})], []),
    "carboxylic_acid_to_alkane_kolbe": ([("CCC(=O)O", "CCCC", {"soda_lime_decarboxylation": "CC"})], []),
    # batch 2
    "alkyl_halide_to_amine_potassiumphthalimide": ([("CCCBr", "CCCN", {"secondary_amine_overalkylation": "CCCNCCC"})],
                                                   ["CC(C)Br"]),                # 2° halide: not modelled
    "amine_to_alkene_moistagoheat": ([("C[N+](C)(C)C(C)CC", "C=CCC", {"zaitsev_alkene": "CC=CC"})], ["CCCN"]),
    "alkyne_to_benzene_redhotfetube": ([("C#C", "c1ccccc1", {})], ["CC#C"]),
    "substituted_benzene_to_substituted_benzene_dilhsosteam": ([("Cc1ccc(S(=O)(=O)O)cc1", "Cc1ccccc1", {})], []),
    "ketone_to_carboxylic_acid_naohheathoo": ([("O=C(C(=O)c1ccccc1)c1ccccc1", "O=C(O)C(O)(c1ccccc1)c1ccccc1", {})],
                                              ["CC(=O)C(C)=O"]),                 # enolisable: aldol instead
    "alcohol_to_aldehyde_activatedmno": ([("OCC=CC", "CC=CC=O", {"acid_with_kmno4": "CC=CC(=O)O"})], ["CCCO"]),
    "alkyl_halide_to_ether_dryago": ([("CCBr", "CCOCC", {"alcohol_with_moist_ag2o": "CCO"})], []),
    "isocyanide_to_amine_hpt": ([("CC[N+]#[C-]", "CCNC", {"primary_amine_by_hydrolysis": "CCN"})], []),
    "aldehyde_to_alkyl_halide_naohaq": ([("O=CC(Cl)(Cl)Cl", "ClC(Cl)Cl", {})], ["CC=O"]),
    "carboxylic_acid_to_ketone_heatbaoh": ([("O=C(O)CCCCC(=O)O", "O=C1CCCC1", {})], ["O=C(O)CCCC(=O)O"]),
}


class NewOrganicRules(unittest.TestCase):
    def setUp(self):
        with open(GRAPH, encoding="utf-8") as f:
            self.edges = {e["id"]: e for e in json.load(f)["edges"]}

    def test_products_and_traps(self):
        for eid, (good, _bad) in CASES.items():
            for start, product, traps in good:
                r = R.apply(self.edges[eid], start)
                self.assertEqual(r.product, canon(product), (eid, start))
                for name, t in traps.items():
                    self.assertEqual(r.traps.get(name), canon(t), (eid, name))

    def test_refused(self):
        for eid, (_good, bad) in CASES.items():
            for start in bad:
                with self.assertRaises(EngineError, msg=(eid, start)):
                    R.apply(self.edges[eid], start)

    def test_edges_have_rules_and_scope(self):
        for eid in CASES:
            self.assertIn(eid, R.RULES)
            self.assertTrue(trusted(self.edges[eid]), eid)


if __name__ == "__main__":
    unittest.main()
