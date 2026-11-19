"""Organic engine (core/engine/organic): pool, node classes, rules and their selectivity. Offline (RDKit).
Run: python -m unittest tests.test_engine_organic"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine.base import EngineError                       # noqa: E402
from core.engine.organic import edges, mol, pool, rules       # noqa: E402
from core.engine.organic.mol import canon, same               # noqa: E402

with open(os.path.join(ROOT, "knowledge", "reaction_graph.json"), encoding="utf-8") as _f:
    GRAPH = json.load(_f)
EDGE = {e["id"]: e for e in GRAPH["edges"]}


def run(edge_id, smiles):
    return rules.apply(EDGE[edge_id], smiles)


class Pool(unittest.TestCase):
    def test_formulas_match_molecule_constructor(self):
        with open(os.path.join(ROOT, "knowledge", "molecule_constructor.json"), encoding="utf-8") as f:
            mc = json.load(f)["nodes"]
        checked = 0
        for node, mols in mc.items():
            ours = dict(pool.POOL.get(node, []))
            for m in mols["molecules"]:
                if m["iupac"] in ours and m.get("formula"):
                    want = m["formula"]
                    got = mol.formula(ours[m["iupac"]])
                    if "Mg" in want or "N2Cl" in want:     # salts and Grignards are written differently
                        continue
                    self.assertEqual(got, want, f"{node}: {m['iupac']}")
                    checked += 1
        self.assertGreater(checked, 50)

    def test_every_pool_molecule_is_in_its_node(self):
        for node, mols in pool.POOL.items():
            for name, smi in mols:
                self.assertIn(node, mol.classes(smi), f"{name} ({smi})")


class Edges(unittest.TestCase):
    def test_every_edge_is_rule_concept_or_suspect(self):
        for e in GRAPH["edges"]:
            kinds = [e["id"] in rules.RULES, e["id"] in edges.CONCEPT, e["id"] in edges.SUSPECT]
            self.assertEqual(sum(kinds), 1, e["id"])

    def test_audit_clean(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import audit_organic
        rep = audit_organic.audit()
        self.assertEqual((rep["missing"], rep["no_molecule"], rep["wrong_class"], rep["crashed"]), ([], [], [], []))
        self.assertGreater(rep["rules"], 150)

    def test_suspect_edges_resolved(self):
        # the user's 2026-11-20 decisions: 20 deleted, 12 fixed with rules, 1 moved to the polymer lookups
        self.assertEqual(edges.SUSPECT, {})
        self.assertEqual(len(GRAPH["edges"]), 179)
        self.assertNotIn("ketone_to_phenol_h", EDGE)
        self.assertEqual(EDGE["vicinal_dihalide_to_alkyne_zndeltaexces"]["to"], "alkene")

    def test_fixed_edges(self):
        self.assertTrue(same(run("vicinal_dihalide_to_alkyne_zndeltaexces", "CC(Br)CBr").product, "C=CC"))
        self.assertTrue(same(run("aldehyde_to_substituted_benzene_naohaqueouss", "O=Cc1ccccc1").product, "OCc1ccccc1"))
        with self.assertRaises(EngineError):
            run("aldehyde_to_substituted_benzene_naohaqueouss", "CCC=O")         # α-H: aldol, not Cannizzaro
        self.assertTrue(same(run("ketone_to_lactone_diazomethane", "O=C1CCCCC1").product, "O=C1CCCCCC1"))
        self.assertTrue(same(run("substituted_benzene_to_phenol_1conch2so4de", "Oc1ccccc1").product,
                             "O=[N+]([O-])c1cc([N+](=O)[O-])c(O)c([N+](=O)[O-])c1"))
        self.assertTrue(same(run("amine_to_amine_heatsn2", "CCN").product, "CC[N+](C)(C)C"))


class Selectivity(unittest.TestCase):
    def test_markovnikov_and_trap(self):
        r = run("alkene_to_alkyl_halide_hx", "C=CC")
        self.assertTrue(same(r.product, "CC(C)Br"))
        self.assertTrue(same(r.traps["anti_markovnikov_product"], "CCCBr"))

    def test_zaitsev(self):
        r = run("alkyl_halide_to_alkene_alckoh", "CCC(C)(C)Br")
        self.assertTrue(same(r.product, "CC=C(C)C"))
        self.assertTrue(same(r.traps["hofmann_product"], "C=C(C)CC"))

    def test_bromination_selectivity(self):
        self.assertTrue(same(run("alkane_to_alkyl_halide_x", "CC(C)C").product, "CC(C)(C)Br"))

    def test_baeyer_villiger_migration(self):
        self.assertTrue(same(run("ketone_to_ester_mcpbametachl", "CC(=O)c1ccccc1").product, "CC(=O)Oc1ccccc1"))
        self.assertTrue(same(run("ketone_to_ester_mcpbametachl", "CC(C)C(C)=O").product, "CC(=O)OC(C)C"))

    def test_eas_directing(self):
        nit = "substituted_benzene_to_substituted_benzene_conchno3"
        self.assertTrue(same(run(nit, "Cc1ccccc1").product, "Cc1ccc([N+](=O)[O-])cc1"))
        self.assertTrue(same(run(nit, "O=[N+]([O-])c1ccccc1").product, "O=[N+]([O-])c1cccc([N+](=O)[O-])c1"))
        with self.assertRaises(EngineError):
            run(nit, "Oc1ccccc1")                    # over-reacts: not a single product

    def test_epoxide_opening(self):
        self.assertTrue(same(run("epoxide_to_alcohol_rnh", "CC1CO1").product, "CNCC(C)O"))       # less hindered
        self.assertTrue(same(run("epoxide_to_halohydrin_hx", "CC1(C)CO1").product, "CC(C)(Br)CO"))  # tertiary

    def test_diene_kinetic(self):
        r = run("diene_conjugated_to_alkyl_halide_hbr1eq", "C=CC=C")
        self.assertTrue(same(r.product, "C=CC(C)Br"))
        self.assertTrue(same(r.traps["1,4_adduct (thermodynamic)"], "CC=CCBr"))

    def test_reagent_limits(self):
        with self.assertRaises(EngineError):
            run("alkyl_halide_to_ether_rona", "CC(C)(C)Br")       # tertiary: E2, not Williamson
        with self.assertRaises(EngineError):
            rules._williamson("CC(C)(C)CBr")                       # neopentyl: no SN2
        with self.assertRaises(EngineError):
            run("ketone_to_alkyl_halide_i2", "CCC(=O)CC")          # no CH3CO: no iodoform
        self.assertEqual(canon(run("ketone_to_alkyl_halide_i2", "CC(C)=O").product), canon("IC(I)I"))

    def test_product_outside_end_node_refused(self):
        with self.assertRaises(EngineError):
            run("aldehyde_to_alkane_znhg", "O=Cc1ccccc1")          # toluene is not an alkane node member


class Classes(unittest.TestCase):
    def test_basic(self):
        self.assertIn("ketone", mol.classes("CC(C)=O"))
        self.assertIn("aldehyde", mol.classes("CC=O"))
        self.assertIn("ester", mol.classes("CCOC(C)=O"))
        self.assertNotIn("ether", mol.classes("CCOC(C)=O"))
        self.assertIn("amine", mol.classes("CNc1ccccc1"))
        self.assertIn("aniline", mol.classes("Nc1ccccc1"))
        self.assertTrue(same("OCC", "CCO"))


if __name__ == "__main__":
    unittest.main()
