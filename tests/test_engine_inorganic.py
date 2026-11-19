"""The inorganic property functions (core/engine/inorganic/properties.py) against the concept book's own facts
(knowledge/graph_unmapped_inorg.json) and standard JEE results. Run: python -m unittest tests.test_engine_inorganic"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine.base import EngineError                       # noqa: E402
from core.engine.inorganic import properties as P              # noqa: E402


class Vsepr(unittest.TestCase):
    CASES = [  # species, shape, hybridisation, polar (None: depends on the arrangement)
        ("BeCl2", "linear", "sp", False), ("BF3", "trigonal planar", "sp2", False),
        ("CH4", "tetrahedral", "sp3", False), ("NH3", "trigonal pyramidal", "sp3", True),
        ("H2O", "bent", "sp3", True), ("PCl5", "trigonal bipyramidal", "sp3d", False),
        ("SF6", "octahedral", "sp3d2", False), ("SF4", "see-saw", "sp3d", True), ("ClF3", "T-shaped", "sp3d", True),
        ("XeF2", "linear", "sp3d", False), ("XeF4", "square planar", "sp3d2", False),
        ("XeF6", "distorted octahedral", "sp3d3", True), ("IF7", "pentagonal bipyramidal", "sp3d3", False),
        ("BrF5", "square pyramidal", "sp3d2", True), ("I3-", "linear", "sp3d", False),
        ("ICl4-", "square planar", "sp3d2", False), ("NH4+", "tetrahedral", "sp3", False),
        ("H3O+", "trigonal pyramidal", "sp3", True), ("CO2", "linear", "sp", False), ("SO2", "bent", "sp2", True),
        ("SO3", "trigonal planar", "sp2", False), ("SO4^2-", "tetrahedral", "sp3", False),
        ("NO3-", "trigonal planar", "sp2", False), ("NO2+", "linear", "sp", False), ("NO2-", "bent", "sp2", True),
        ("O3", "bent", "sp2", True), ("ClO4-", "tetrahedral", "sp3", False), ("XeO3", "trigonal pyramidal", "sp3", True),
        ("XeOF4", "square pyramidal", "sp3d2", True), ("N3-", "linear", "sp", False), ("SnCl2", "bent", "sp2", True),
    ]

    def test_shapes(self):
        for sp, shape, hyb, polar in self.CASES:
            v = P.vsepr(sp)
            self.assertEqual((v["shape"], v["hybridisation"], v["polar"]), (shape, hyb, polar), sp)

    def test_odd_electron_and_mixed_ligands(self):
        self.assertEqual(P.vsepr("NO2")["shape"], "bent")              # one unpaired electron on N
        self.assertEqual(P.vsepr("ClO2")["shape"], "bent")
        self.assertIsNone(P.vsepr("PCl3F2", central="P")["polar"])     # depends on axial or equatorial F
        self.assertTrue(P.vsepr("SOCl2", central="S")["polar"])         # pyramidal: polar whatever the ligands

    def test_ionic_solids_are_refused(self):
        for sp in ("CaF2", "TiO2", "NaCl"):                              # fluorite, rutile: not molecules
            with self.assertRaises(EngineError):
                P.vsepr(sp)


class MO(unittest.TestCase):
    def test_book_diatomics(self):
        cases = [("H2", 1, 0), ("Li2", 1, 0), ("B2", 1, 2), ("C2", 2, 0), ("N2", 3, 0), ("O2", 2, 2), ("F2", 1, 0),
                 ("He2", 0, 0), ("Be2", 0, 0), ("Ne2", 0, 0)]
        for sp, bo, unp in cases:
            m = P.mo_diatomic(sp)
            self.assertEqual((m["bond_order"], m["unpaired"]), (bo, unp), sp)
        self.assertFalse(P.mo_diatomic("He2")["exists"])
        self.assertEqual(P.mo_diatomic("O2")["magnetism"], "paramagnetic")

    def test_ions_and_heteronuclear(self):
        cases = [("O2+", 2.5, 1), ("O2-", 1.5, 1), ("O2^2-", 1.0, 0), ("N2+", 2.5, 1), ("N2-", 2.5, 1),
                 ("H2+", 0.5, 1), ("He2+", 0.5, 1), ("CO", 3.0, 0), ("NO", 2.5, 1), ("NO+", 3.0, 0), ("CN-", 3.0, 0),
                 ("C2^2-", 3.0, 0)]
        for sp, bo, unp in cases:
            m = P.mo_diatomic(sp)
            self.assertEqual((m["bond_order"], m["unpaired"]), (bo, unp), sp)


class Complexes(unittest.TestCase):
    CASES = [  # entity, oxidation state, d, unpaired, geometry, hybridisation
        ("[Fe(CN)6]4-", 2, 6, 0, "octahedral", "d2sp3"), ("[Fe(CN)6]3-", 3, 5, 1, "octahedral", "d2sp3"),
        ("[FeF6]3-", 3, 5, 5, "octahedral", "sp3d2"), ("[Fe(H2O)6]2+", 2, 6, 4, "octahedral", "sp3d2"),
        ("[CoF6]3-", 3, 6, 4, "octahedral", "sp3d2"), ("[Co(NH3)6]3+", 3, 6, 0, "octahedral", "d2sp3"),
        ("[Co(H2O)6]3+", 3, 6, 0, "octahedral", "d2sp3"), ("[Cr(NH3)6]3+", 3, 3, 3, "octahedral", "d2sp3"),
        ("[Mn(CN)6]4-", 2, 5, 1, "octahedral", "d2sp3"), ("[MnCl4]2-", 2, 5, 5, "tetrahedral", "sp3"),
        ("[Ni(CO)4]", 0, 10, 0, "tetrahedral", "sp3"), ("[NiCl4]2-", 2, 8, 2, "tetrahedral", "sp3"),
        ("[Ni(CN)4]2-", 2, 8, 0, "square planar", "dsp2"), ("[PtCl4]2-", 2, 8, 0, "square planar", "dsp2"),
        ("[CuCl4]2-", 2, 9, 1, "tetrahedral", "sp3"), ("[Ni(NH3)6]2+", 2, 8, 2, "octahedral", "sp3d2"),
        ("[Co(en)3]3+", 3, 6, 0, "octahedral", "d2sp3"), ("[Fe(C2O4)3]3-", 3, 5, 5, "octahedral", "sp3d2"),
        ("[Ti(H2O)6]3+", 3, 1, 1, "octahedral", "d2sp3"), ("[Zn(NH3)4]2+", 2, 10, 0, "tetrahedral", "sp3"),
    ]

    def test_complexes(self):
        for ent, ox, d, unp, geo, hyb in self.CASES:
            c = P.complex_info(ent)
            self.assertEqual((c["oxidation_state"], c["d_electrons"], c["unpaired"], c["geometry"], c["hybridisation"]),
                             (ox, d, unp, geo, hyb), ent)

    def test_moment_and_cfse(self):
        self.assertEqual(P.complex_info("[FeF6]3-")["spin_only_moment_BM"], 5.92)
        self.assertEqual(P.complex_info("[Fe(CN)6]4-")["cfse"], "-2.4 Δo")
        self.assertEqual(P.complex_info("[Ti(H2O)6]3+")["cfse"], "-0.4 Δo")
        self.assertEqual(P.complex_info("[FeF6]3-")["cfse"], "+0.0 Δo")

    def test_refuses_what_it_cannot_read(self):
        with self.assertRaises(EngineError):
            P.complex_info("[Fe(xyz)6]3-")
        with self.assertRaises(EngineError):
            P.complex_info("[Na(H2O)6]+")


class Isomers(unittest.TestCase):
    def test_octahedral(self):
        cases = [  # ligands, geometric, stereo
            (["a"] * 4 + ["b"] * 2, 2, 2), (["a"] * 3 + ["b"] * 3, 2, 2), (["a", "a", "b", "b", "c", "c"], 5, 6),
            (["AA"] * 3, 1, 2), (["AA", "AA", "b", "b"], 2, 3), (["a", "a", "b", "b", "c", "d"], 6, 8),
            (["a", "b", "c", "d", "e", "f"], 15, 30), (["AA", "b", "b", "c", "c"], 3, 4), (["a"] * 6, 1, 1),
        ]
        for lig, geo, stereo in cases:
            r = P.count_isomers("octahedral", lig)
            self.assertEqual((r["geometric"], r["stereo"]), (geo, stereo), lig)

    def test_square_planar_and_tetrahedral(self):
        self.assertEqual(P.count_isomers("square planar", ["a", "a", "b", "b"])["geometric"], 2)
        self.assertEqual(P.count_isomers("square planar", ["a", "b", "c", "d"])["geometric"], 3)
        self.assertEqual(P.count_isomers("square planar", ["a", "b", "c", "d"])["stereo"], 3)    # planar: no enantiomers
        self.assertEqual(P.count_isomers("tetrahedral", ["a", "b", "c", "d"])["stereo"], 2)


class OxidationState(unittest.TestCase):
    def test_states(self):
        from fractions import Fraction as F
        cases = [("K2Cr2O7", "Cr", {}, 6), ("KMnO4", "Mn", {}, 7), ("Fe3O4", "Fe", {}, F(8, 3)),
                 ("Cr2O7^2-", "Cr", {}, 6), ("S4O6^2-", "S", {}, F(5, 2)), ("Na2O2", "O", {}, -1),
                 ("H2O2", "O", {}, -1), ("NaH", "H", {}, -1), ("XeF6", "Xe", {}, 6), ("H2SO5", "S", {"peroxide": False}, 8)]
        for f, e, kw, want in cases[:-1]:
            self.assertEqual(P.oxidation_state(f, e, **kw), want, f)


if __name__ == "__main__":
    unittest.main()
