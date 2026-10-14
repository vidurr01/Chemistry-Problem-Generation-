"""
Question forms reproduce REAL JEE Advanced answers from the audited engine steps (offline).

Each test is one Advanced question (docs/advanced_formula_map.md) rebuilt with core.engine.forms
and the engine's own steps: if the engine and the form are right, the official answer comes out.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.engine import forms                                    # noqa: E402
from core.engine.base import EngineError, plan_chain             # noqa: E402
from core.engine.physical import step                            # noqa: E402

R = 8.314


def plan(*txs):
    return plan_chain([step(t) for t in txs])


class RealAdvanced(unittest.TestCase):
    def test_2016_P2_Q21_inverse_nernst(self):
        """E_cell = 0.092 V, E° = 0.151 V, n = 2; [M²⁺]/[M⁴⁺] = 10ˣ: x = 2."""
        q = forms.Inverse(plan(239), "s0.molarity").build(
            {"s0.standard_emf": 0.151, "s0.molarity": 100.0, "s0.cathode_ion_concentration": 1.0, "s0.electrons": 2})
        self.assertAlmostEqual(q.detail["observed_value"], 0.0919, places=4)    # the stated EMF (JEE: 0.092)
        self.assertAlmostEqual(math.log10(q.answer), 2, places=2)
        self.assertNotIn("s0.molarity", q.stated)
        self.assertTrue(any(t["id"] == "inverted_Q" and math.isclose(t["wrong_answer"], 0.01, rel_tol=0.02)
                            for t in q.traps), q.traps)                         # inverting Q gives x = −2

    def test_2012_P1_Q36_two_state_ratio(self):
        """First order: t(1/8)/t(1/10) × 10 = 9 (log 2 = 0.3)."""
        q = forms.TwoState(plan(209), {"s0.fraction_remaining": 1 / 10}).build(
            {"s0.fraction_remaining": 1 / 8, "s0.half_life": 30.0})
        self.assertAlmostEqual(10 / q.answer, 9.03, places=2)

    def test_2024_P2_Q9_two_state_ratio(self):
        """M(X) = 0.8 M(Y), i(X) = 1.2 i(Y), same masses: ΔT_b(X) is 150 % of ΔT_b(Y)."""
        q = forms.TwoState(plan(262), {"s0.molality": 0.5 / 0.8, "s0.vant_hoff_factor": 1.2}).build(
            {"s0.molality": 0.5, "s0.Kb": 0.52, "s0.vant_hoff_factor": 1.0})
        self.assertAlmostEqual(q.answer, 1.5, places=6)
        self.assertTrue(any(t["id"] == "forgets_i" for t in q.traps))

    def test_2014_P1_Q38_two_state_ratio(self):
        """MX₂, α = 0.5: observed ΔT_f / ΔT_f without dissociation = i = 2."""
        i = forms.value_of(plan(267), {"s0.degree_of_dissociation": 0.5, "s0.particles": 3,
                                       "s0.process": "dissociation"})
        q = forms.TwoState(plan(263), {"s0.vant_hoff_factor": i}).build(
            {"s0.molality": 0.1, "s0.Kf": 1.86, "s0.vant_hoff_factor": 1.0})
        self.assertAlmostEqual(q.answer, 2.0, places=6)

    def test_2015_P2_Q27_ratio_to_pka_difference(self):
        """Λm(HX, 0.01 M) is 1/10 of Λm(HY, 0.10 M), α ≪ 1: pK_a(HX) − pK_a(HY) = 3."""
        ka_y = 1e-5
        a_y = forms.value_of(plan(173), {"s0.dissociation_constant": ka_y, "s0.concentration": 0.10})
        # find K_a(HX) whose α at 0.01 M is a tenth of HY's: the inverse form on step 173
        target = a_y / 10
        rs = forms.roots(lambda k: forms.value_of(plan(173), {"s0.dissociation_constant": k,
                                                              "s0.concentration": 0.01}) - target, 1e-12, 1e-3)
        self.assertEqual(len(rs), 1)
        self.assertAlmostEqual(-math.log10(rs[0]) + math.log10(ka_y), 3.0, places=2)

    def test_2020_P2_Q14_simultaneous(self):
        """Ideal solution: 0.3 bar at x_A = 0.25, 0.4 bar at x_A = 0.50: p°_B = 0.2 bar."""
        q = forms.Simultaneous(plan(257), ["s0.PA_pure", "s0.PB_pure"], {"s0.mole_fraction": 0.50},
                               ask="s0.PB_pure").build({"s0.mole_fraction": 0.25, "s0.PA_pure": 0.6, "s0.PB_pure": 0.2})
        self.assertEqual(q.stated["results"], (0.3, 0.4))
        self.assertAlmostEqual(q.answer, 0.2, places=6)

    def test_2020_P2_Q17_tree(self):
        """SnO₂ + C -> Sn + CO₂: ΔH from ΔfH and ΔS from S° (two branches) -> T = ΔH/ΔS = 935 K."""
        eq = "SnO2 + C -> Sn + CO2"
        t = forms.Tree(step(133), {"delta_h": plan(139), "delta_s": plan(131)})
        q = t.build({"delta_h": {"s0.balanced_equation": eq,
                                 "s0.formation_enthalpies": {"SnO2": -581.0, "C": 0, "Sn": 0, "CO2": -394.0}},
                     "delta_s": {"s0.balanced_equation": eq,
                                 "s0.standard_entropies": {"SnO2": 56.0, "C": 6.0, "Sn": 52.0, "CO2": 210.0}}}, {})
        self.assertAlmostEqual(q.answer, 935, places=0)
        self.assertEqual(q.detail["branch_results"], {"s0.delta_h": 187, "s0.delta_s": 200})
        self.assertTrue(q.traps)                     # e.g. reactants − products in a branch

    def test_2021_P2_Q17_condition(self):
        """Adiabatic 900 K -> 180 K (C_v = 5/2 R), then isothermal at 180 K with the same work:
        ln(V₃/V₂) = 10."""
        v2 = 5 ** 2.5                                 # TV^(γ−1) constant: V₂/V₁ = (900/180)^(1/0.4)
        c = forms.Condition(plan(119), plan(117), (None, "s0.V2"), 1.0, 1e6, "", "V₃/V₂")
        q = c.build({"s0.n": 1, "s0.Cv": 2.5 * R, "s0.T": 900, "s0.V1": 1.0, "s0.V2": v2},
                    {"s0.n": 1, "s0.T": 180, "s0.V1": 1.0})
        self.assertAlmostEqual(math.log(q.answer), 10.0, places=3)

    def test_2023_P2_Q11_inverse_bohr(self):
        """He⁺ orbit of radius 105.8 pm is n = 2 (and 26.45 pm is n = 1)."""
        q = forms.Inverse(plan(61), "s0.n").build({"s0.n": 2, "s0.Z": 2})
        self.assertAlmostEqual(q.detail["observed_value"], 1.058, places=3)     # Å
        self.assertAlmostEqual(q.answer, 2, places=6)


class Checks(unittest.TestCase):
    def test_inverse_needs_a_numeric_input(self):
        with self.assertRaises(EngineError):        # a text input cannot be the unknown
            forms.Inverse(plan(30), "s0.chemical_species").build({"s0.chemical_species": "Cr2O7^2-", "s0.element": "Cr"})

    def test_inverse_refuses_two_roots(self):
        """y = (x − 5)² + 1 gives y = 5 at x = 3 and x = 7: hiding x must be refused."""
        from core.engine.base import Param, Step
        st = Step(tx=9999, src="a", dst="b", needs=(Param("x", "", "x", kind="real", lo=0, hi=10),),
                  answer="y", unit="", fn=lambda v: {"y": (v["x"] - 5) ** 2 + 1})
        with self.assertRaises(EngineError):
            forms.Inverse(plan_chain([st]), "s0.x").build({"s0.x": 3.0})
        st2 = Step(tx=9998, src="a", dst="b", needs=(Param("x", "", "x", kind="real", lo=0, hi=4),),
                   answer="y", unit="", fn=lambda v: {"y": (v["x"] - 5) ** 2 + 1})
        self.assertAlmostEqual(forms.Inverse(plan_chain([st2]), "s0.x").build({"s0.x": 3.0}).answer, 3.0)

    def test_inverse_unique_when_monotone(self):
        """t_max = ln(k₁/k₂)/(k₁ − k₂) with k₁ fixed is monotone in k₂: one root, accepted."""
        q = forms.Inverse(plan(212), "s0.k2").build({"s0.rate_constant": 0.02, "s0.k2": 0.05})
        self.assertTrue(math.isclose(q.answer, 0.05, rel_tol=1e-3), q.answer)

    def test_inverse_tolerance_from_rounding(self):
        """A stated result rounded to 4 s.f. moves a steep inverse more: the tolerance widens."""
        q = forms.Inverse(plan(239), "s0.molarity").build(
            {"s0.standard_emf": 0.151, "s0.molarity": 100.0, "s0.cathode_ion_concentration": 1.0, "s0.electrons": 2})
        self.assertGreaterEqual(q.tolerance, 0.01)
        self.assertLessEqual(q.tolerance, 0.10)

    def test_simultaneous_needs_a_unique_solution(self):
        with self.assertRaises(EngineError):        # both states identical: two equations are one
            forms.Simultaneous(plan(257), ["s0.PA_pure", "s0.PB_pure"], {"s0.mole_fraction": 0.25},
                               ask="s0.PB_pure").build({"s0.mole_fraction": 0.25, "s0.PA_pure": 0.6, "s0.PB_pure": 0.2})


if __name__ == "__main__":
    unittest.main()
