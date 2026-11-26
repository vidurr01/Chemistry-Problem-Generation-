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
        self.assertEqual(len(GRAPH["edges"]), 188)    # + 9 from the concept-book coverage audit (2026-11-26)
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

    def test_every_site_reacts(self):
        # live run 3 (GEN_20261119T215055): one of two identical groups reacted, so code's key was wrong
        self.assertTrue(same(run("alkyl_halide_to_nitrile_nacn", "ClCc1ccccc1CCl").product, "N#CCc1ccccc1CC#N"))
        self.assertTrue(same(run("alcohol_to_carboxylic_acid_kmno", "OCc1ccccc1CO").product, "OC(=O)c1ccccc1C(=O)O"))
        self.assertTrue(same(run("amine_to_alcohol_nano", "NCc1ccccc1CN").product, "OCc1ccccc1CO"))
        self.assertTrue(same(run("benzene_to_substituted_benzene_conchno", "c1ccccc1").product,
                             "O=[N+]([O-])c1ccccc1"))                                    # EAS: one substitution
        self.assertTrue(same(run("carboxylic_acid_to_carboxylic_acid_x", "CC(=O)O").product, "OC(=O)CBr"))
        with self.assertRaises(EngineError):
            run("alkyl_halide_to_nitrile_nacn", "ClC(Cl)Cl")                             # gem-polyhalide

    def test_product_outside_end_node_refused(self):
        with self.assertRaises(EngineError):
            run("aldehyde_to_alkane_znhg", "O=Cc1ccccc1")          # toluene is not an alkane node member


class Golden(unittest.TestCase):
    def test_every_trusted_edge_gives_its_checked_textbook_product(self):
        """tests/organic_golden.json: one hand-checked input -> product per edge drawn in live runs (2026-11-24)."""
        import json
        from core.engine.organic.scope import trusted
        with open(os.path.join(ROOT, "tests", "organic_golden.json"), encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        drawn = {e["id"] for e in GRAPH["edges"] if e["id"] in rules.RULES and trusted(e)}
        self.assertEqual(set(cases), drawn, "every drawn edge needs a checked case (and no stale ones)")
        for eid, (smiles, product) in cases.items():
            with self.subTest(eid):
                self.assertTrue(same(run(eid, smiles).product, product), f"{eid}: {smiles}")


class RuleBugs(unittest.TestCase):
    """Found while writing docs/organic_rule_scope.md (2026-11-22)."""

    def test_ketone_rules_keep_the_whole_molecule(self):
        # an unmapped [#6] made every ketone propan-2-ol (NaBH4) and propane (Wolff–Kishner)
        self.assertTrue(same(run("ketone_to_alcohol_nabh", "O=C1CCCCC1").product, "OC1CCCCC1"))
        self.assertTrue(same(run("ketone_to_alcohol_nabh", "CCC(C)=O").product, "CCC(C)O"))
        self.assertTrue(same(run("ketone_to_alkane_nhnh", "CCC(=O)CCC").product, "CCCCCC"))
        self.assertTrue(same(rules.RULES["ketone_to_alkane_nhnh"]("O=C1CCCCC1").product, "C1CCCCC1"))

    def test_carbylamine_needs_an_amine_not_an_amide(self):
        # selectivity audit 2026-11-24: butanamide gave an "isocyanide"
        for amide in ("CCCC(N)=O", "NC(=O)c1ccccc1"):
            with self.assertRaises(EngineError):
                run("amine_to_isocyanide_carbylaminetest", amide)
        self.assertTrue(same(run("amine_to_isocyanide_carbylaminetest", "CCCN").product, "CCC[N+]#[C-]"))
        self.assertTrue(same(run("amine_to_isocyanide_carbylaminetest", "Nc1ccccc1").product, "[C-]#[N+]c1ccccc1"))

    def test_hi_cleaves_open_chain_ethers_only(self):
        # selectivity audit 2026-11-24: propylene oxide and ethylene oxide gave CH3I
        for ring in ("CC1CO1", "C1CO1", "C1CCOC1"):
            with self.assertRaises(EngineError):
                run("ether_to_alkyl_halide_conchxhihbra", ring)
        self.assertTrue(same(run("ether_to_alkyl_halide_conchxhihbra", "COc1ccccc1").product, "CI"))

    def test_isocyanide_hydrolysis_gives_primary_amine(self):
        r = run("isocyanide_to_amine_hydrolysis", "CC[N+]#[C-]")
        self.assertTrue(same(r.product, "CCN"))
        self.assertIn("O=CO", r.coproducts)

    def test_every_ester_hydrolysed(self):
        self.assertTrue(same(run("ester_to_ester_aqnaoh", "CCOC(=O)CCC(=O)OCC").product, "O=C(O)CCC(=O)O"))
        with self.assertRaises(EngineError):        # two different acids: no single product
            rules.RULES["ester_to_carboxylic_acid_h3odiluteaci"]("CC(=O)OCC(=O)OC")


class Scope(unittest.TestCase):
    """Approved substrate scopes (docs/organic_rule_scope.md, 2026-11-22), stored in the graph."""

    def test_graph_matches_tool_and_names_exist(self):
        import subprocess
        from core.engine.organic.scope import GROUPS
        tool = os.path.join(ROOT, "tools", "apply_rule_scope.py")
        self.assertEqual(subprocess.run([sys.executable, tool, "--check"]).returncode, 0,
                         "graph scope differs from tools/apply_rule_scope.py: run it")
        for e in GRAPH["edges"]:
            fc = e.get("firing_condition") or {}
            for g in e["chemoselectivity"]["requires_absent"] + fc.get("requires", []) + fc.get("at_most_one", []):
                self.assertIn(g, GROUPS, e["id"])

    def test_refused_outside_scope(self):
        for eid, smi in [("alkyl_halide_to_grignard_mg", "OCCCCBr"),           # protic group kills RMgX
                         ("alkyl_halide_to_ether_rona", "CC(C)Br"),            # Williamson: 1° only
                         ("alkyl_halide_to_alkyl_halide_nai", "CC(C)(C)Br"),   # Finkelstein: no 3°
                         ("alcohol_to_aldehyde_pcc", "CC(O)CCO"),              # PCC also oxidises the 2° OH
                         ("aldehyde_to_alcohol_nabh", "CC(=O)CCC=O"),          # NaBH4 also reduces the ketone
                         ("alkene_to_alkyl_halide_hx", "C=CC(C)C"),            # cation would shift
                         ("alcohol_to_alkene_conchso", "CCCCO"),               # shift gives but-2-ene
                         ("benzene_to_ketone_rcocl", "N#Cc1ccccc1"),           # FC fails on deactivated rings
                         ("aryl_halide_to_phenol_naoh", "Cc1ccc(Cl)cc1"),      # benzyne: isomer mixture
                         ("epoxide_to_halohydrin_hx", "CC1CO1"),               # HX site not agreed
                         ("amine_to_alcohol_nano", "CCCN"),                    # cation rearranges
                         ("alkyl_halide_to_cycloalkane_mgmagnesiumm", "BrCCCCBr"),
                         ("phenol_to_aryl_halide_pclslowreact", "C=CCc1ccc(O)c(C=O)c1"),  # PCl5 takes CHO (run 6)
                         ("alkene_to_alcohol_ho", "O=CC1=CCCCC1=O"),          # enone: no Markovnikov (run 8)
                         ("alkene_to_alkyl_halide_hx", "C=CC(C)=O"),
                         ("aldehyde_to_cyanohydrin_hcn", "C=CC=O"),            # CN- adds 1,4
                         ("alcohol_to_alkyl_halide_socl", "CC(C)(O)CCO"),     # 3° OH eliminates (runs 16, 17)
                         ("alkyne_to_ketone_ho", "C#CC(C)=O")]:
            with self.assertRaises(EngineError, msg=eid):
                run(eid, smi)

    def test_kept_inside_scope(self):
        for eid, smi, want in [("alkyl_halide_to_ether_rona", "CCCBr", "CCCOC"),
                               ("alcohol_to_alkene_conchso", "CCCO", "C=CC"),           # 1,2-H shift, same alkene
                               ("alcohol_to_alkene_conchso", "CC(O)C(C)C", "CC=C(C)C"),
                               ("alcohol_to_carboxylic_acid_kmno", "OCc1ccccc1", "OC(=O)c1ccccc1"),
                               ("alkene_to_alkyl_halide_hx", "C=CCCC", "CCCC(C)Br"),
                               ("amine_to_alcohol_nano", "NCc1ccccc1", "OCc1ccccc1")]:
            self.assertTrue(same(run(eid, smi).product, want), eid)


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
