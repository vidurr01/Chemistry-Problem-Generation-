"""
Formulas added on 2026-11-15 (core/engine/physical/advanced.py): each test reproduces the real
JEE Advanced answer the formula was added for, through the engine, as a chain where the paper's
solution chains formulas.

Run:  python -m unittest tests.test_engine_advanced

Where a paper fixes a rounder constant than the engine states (R = 8 or 8.3, N_A = 6.0 × 10²³,
h = 6.6 × 10⁻³⁴), the test compares with the same calculation at the engine's constants and
says so; the paper's answer is then within that constant's rounding.
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.engine.base import EngineError, links, plan_chain, plan_tree, roles_consistent, run_chain  # noqa: E402
from core.engine.physical import BRIDGES, STEPS, step  # noqa: E402

R, F, NA, H = 8.314, 96500.0, 6.022e23, 6.626e-34


def run(txs, **given):
    return run_chain(plan_chain([step(t) for t in txs]), {k.replace("__", "."): v for k, v in given.items()})


def chain_ok(*txs):
    st = [step(t) for t in txs]
    return all(a.dst == b.src and links(a, b, BRIDGES) for a, b in zip(st, st[1:])) and roles_consistent(st)


class Close(unittest.TestCase):
    def close(self, got, want, tol=0.01):
        got = got.answer if hasattr(got, "answer") else got
        self.assertTrue(math.isclose(got, want, rel_tol=tol), f"got {got}, expected {want}")


class Solutions(Close):
    def test_2012P2_Q28_dT_to_molality_to_mole_fraction_to_lowering(self):
        """ΔT_b = 2 K, K_b = 0.76 -> m = 2.63 -> x = 0.0452 -> P = 760 − lowering ≈ 726 mm Hg (key: 724)."""
        self.assertTrue(chain_ok(349, 348, 255))
        r = run([349, 348, 255], s0__delta_T=2, s0__constant=0.76, s0__vant_hoff_factor=1,
                s1__solvent_molar_mass=18, s2__pure_vapour_pressure=760)
        m = 2 / 0.76
        x = m * 18 / 1000 / (1 + m * 18 / 1000)
        self.close(r, x * 760)
        self.assertTrue(abs((760 - r.answer) - 724) < 3)

    def test_2017P1_Q36_ethanol_freezing_point(self):
        self.assertTrue(chain_ok(1, 362, 263))
        self.close(run([1, 362, 263], s0__mass=34.5, s0__molar_mass=46, s1__solvent_mass=500, s2__Kf=2,
                       s2__vant_hoff_factor=1), 3.0)

    def test_2019P1_Q14_vapour_pressure_to_freezing_point(self):
        """The masses are stated once: 256 hands them to 370."""
        self.assertTrue(chain_ok(256, 370, 263))
        plan = plan_chain([step(t) for t in (256, 370, 263)])
        self.assertEqual(sorted(g.param.key for g in plan.givens.values()).count("solute_mass"), 1)
        r = run([256, 370, 263], s0__vapour_pressure_lowering=10, s0__pure_vapour_pressure=650, s0__solute_mass=0.5,
                s0__solvent_mass=39, s0__solvent_molar_mass=78, s2__Kf=5.12, s2__vant_hoff_factor=1)
        self.close(r, 1.02)

    def test_2016P1_Q32_molarity_equals_molality_at_ratio_9(self):
        x, d, mv = 0.1, 2.0, 18.0
        molality = run([21], s0__mole_fraction=x, s0__solvent_molar_mass=mv).answer
        molarity = run([358], s0__mole_fraction=x, s0__density=d, s0__solute_molar_mass=9 * mv,
                       s0__solvent_molar_mass=mv).answer
        self.close(molarity, molality, tol=1e-9)

    def test_2019P2_Q10_urea_molarity(self):
        self.assertTrue(chain_ok(373, 374))
        self.close(run([373, 374], s0__mole_fraction=0.05, s0__solvent_mass=900, s0__solvent_molar_mass=18,
                       s1__solute_molar_mass=60, s1__density=1.2), 2.98, tol=0.005)

    def test_2021P2_Q11_ferrous_ion_in_250_mL(self):
        """0.03 M KMnO₄ is 0.15 N; 12.5 mL for a 25 mL aliquot of 250 mL; n-factor of Fe²⁺ = 1."""
        self.assertTrue(chain_ok(35, 379))
        self.close(run([35, 379], s0__normality=0.15, s0__volume=12.5, s1__n_factor=1, s1__total_volume=250,
                       s1__aliquot_volume=25), 1.875e-2)


class Gases(Close):
    def test_2014P2_Q31_meeting_point(self):
        self.assertTrue(chain_ok(95, 355))
        self.close(run([95, 355], s0__molar_mass=10, s0__molar_mass_2=40, s1__tube_length=24), 16)

    def test_2016P1_Q33_diffusion_coefficient_factor(self):
        """D ∝ λū ∝ T^(3/2)/P: T × 4 and P × 2 give 4."""
        self.assertTrue(chain_ok(359, 360))
        d = lambda T, P: run([359, 360], s0__T=T, s0__P=P, s0__molecular_diameter=300, s1__molar_mass=28).answer
        self.close(d(1200, 2) / d(300, 1), 4)

    def test_2023P1_Q9_pressure_from_Z(self):
        """Z = 0.5, V_m = 0.4 L, 800 K: x = ZRT/V_m; ideal V_m = RT/x = V_m/Z; x/y = 100 at R = 0.08 (engine 0.0821)."""
        x = run([386], s0__compressibility_factor=0.5, s0__molar_volume=0.4, s0__T=800).answer
        self.close(x, 0.5 * 0.0821 * 800 / 0.4)
        self.close(x / (0.0821 * 800 / x), 100 * 0.0821 / 0.08)


class Atomic(Close):
    def test_2012P1_Q22_kinetic_energy_in_second_orbit(self):
        """KE = h²/(32π²ma₀²) for n = 2, r = 4a₀: the same as 13.6/4 eV."""
        self.assertTrue(chain_ok(61, 350))
        r = run([61, 350], s0__n=2, s0__Z=1)
        self.close(r, H ** 2 / (32 * math.pi ** 2 * 9.1e-31 * (0.529e-10) ** 2) / 1.6e-19)
        self.close(r, 13.6 / 4, tol=0.02)

    def test_2020P2_Q15_potential_energy_of_two_H_atoms(self):
        self.assertTrue(chain_ok(61, 376))
        self.close(run([61, 376], s0__n=1, s0__Z=1, s1__atoms=2), -5246.5, tol=0.002)

    def test_2021P2_Q18_recoil_of_helium(self):
        """30 cm s⁻¹ with h = 6.6 × 10⁻³⁴ and N_A = 6 × 10²³; engine constants give 30.2."""
        self.close(run([380], s0__wavelength=330, s0__molar_mass=4), 0.30, tol=0.01)
        self.assertTrue(chain_ok(66, 380))


class Thermo(Close):
    def test_2016P1_Q20_surroundings_entropy(self):
        """q = −w = 303.9 J -> ΔS_surr = −1.013 J K⁻¹; the T of the isothermal step is stated once."""
        self.close(run([357, 130], s0__work=-303.9, s1__T=300), -1.013)
        self.assertTrue(chain_ok(117, 357, 130))
        plan = plan_chain([step(t) for t in (117, 357, 130)])
        self.assertEqual([g.param.key for g in plan.givens.values()].count("T"), 1)
        self.assertFalse(chain_ok(119, 357))          # adiabatic: q = 0, not −w

    def test_2015P1_Q28_moles_oxidised(self):
        self.assertTrue(chain_ok(138, 356))
        self.close(run([138, 356], s0__cell_emf=-0.25, s0__electrons=2, s1__driving_delta_g=-193), 4)

    def test_2017P2_Q20_graphite_diamond_pressure(self):
        self.assertTrue(chain_ok(134, 364))
        self.close(run([364], s0__delta_g=2.9, s0__molar_volume_change=-2e-6), 14501)

    def test_2018P2_Q10_minimum_hydrogen_pressure(self):
        """ΔG° = −78 − (−178) = +100 kJ; K = p(H₂)/p(H₂O); ln p(H₂) = −14.6 at R = 8 (−14.23 at 8.314)."""
        self.assertTrue(chain_ok(366, 135, 367))
        steps = [["2Cu + 1/2 O2 -> Cu2O", -78], ["H2 + 1/2 O2 -> H2O", -178]]
        self.close(run([366], s0__target_equation="2Cu + H2O -> Cu2O + H2", s0__step_equations=steps), 100)
        r = run([366, 135, 367], s0__target_equation="2Cu + H2O -> Cu2O + H2", s0__step_equations=steps,
                s1__T=1250, s2__reactant_gas_pressure=0.01)
        self.close(math.log(r.answer), math.log(0.01) - 100000 / (R * 1250), tol=1e-4)
        self.close(math.log(0.01) - 100000 / (8 * 1250), -14.60, tol=0.001)

    def test_2020P1_Q15_fuel_cell_compresses_a_gas(self):
        self.assertTrue(chain_ok(238, 138, 137, 375))
        r = run([238, 138, 137, 375], s0__cathode_potential=1.23, s0__anode_potential=0.0, s1__electrons=2,
                s2__moles=1e-3, s3__efficiency=0.7, s3__n=1, s3__gas_type="monatomic")
        self.close(r, 13.32, tol=0.002)

    def test_2023P2_Q14_entropy_difference_at_300K(self):
        self.close(run([388], s0__delta_s=1, s0__delta_cp=1, s0__T1=600, s0__T2=300), 1 - math.log(2), tol=1e-3)
        self.assertTrue(chain_ok(127, 388))
        self.assertIn("T1", [k for k, (src, _) in plan_chain([step(127), step(388)]).wiring[1].items() if src == "prev"])

    def test_2024P1_Q8_enthalpy_of_an_ideal_gas(self):
        """5 mol, C_v = 12: ΔH = n(C_v + R)ΔT whatever the path; n follows from the state."""
        T, V, n = 300.0, 10.0, 5.0
        P = n * 0.0821 * T / V
        self.close(run([389], s0__P=P, s0__V=V, s0__T=T, s0__Cv=12, s0__new_temperature=500), n * (12 + R) * 200)
        self.assertTrue(chain_ok(87, 389))

    def test_2017P2_Q19_delta_g_of_a_non_standard_cell(self):
        """E = 1.1 − (0.0591/2) log 10; ΔG = 2.303RT − 2.2F at 298 K."""
        self.assertTrue(chain_ok(239, 363))
        r = run([239, 363], s0__standard_emf=1.1, s0__molarity=1.0, s0__cathode_ion_concentration=0.1, s0__electrons=2)
        self.close(r, (2.303 * R * 298 - 2.2 * F) / 1000, tol=0.002)
        self.assertFalse(chain_ok(363, 135))          # a non-standard ΔG gives no K


class Thermochemistry(Close):
    def test_2013P1_Q29_combustion_per_gram(self):
        self.assertTrue(chain_ok(139, 352))
        r = run([139, 352], s0__balanced_equation="C6H12O6 + 6O2 -> 6CO2 + 6H2O",
                s0__formation_enthalpies={"C6H12O6": -1300, "O2": 0, "CO2": -400, "H2O": -300}, s1__molar_mass=180)
        self.close(r, -16.11)

    def test_2022P1_Q1_formation_enthalpy_of_HgO(self):
        """Bomb calorimeter -> ΔU -> ΔH (Δn_g = −3/2) -> ΔfH(HgO) = −90.39 kJ mol⁻¹ (R = 8.3; −90.40 at 8.314)."""
        self.assertTrue(chain_ok(148, 381, 113, 382))
        r = run([148, 381, 113, 382], s0__temperature=298.0, s0__final_temperature=312.8, s0__heat_capacity=20.0,
                s1__moles_reacted=2, s2__balanced_equation="Hg(g) + 1/2 O2(g) -> HgO(s)", s2__T=298,
                s3__formation_enthalpies={"Hg": 61.32, "O2": 0}, s3__unknown_species="HgO")
        self.close(r, -90.39, tol=0.001)


class Equilibrium(Close):
    def test_2017P1_Q27_kc_from_extent(self):
        """2A + B ⇌ C + D, 1 mol A and 1 mol B in 10 L, 0.1 mol D at equilibrium: A 0.8, B 0.9, C 0.1
        -> K_c = 0.174 L mol⁻¹ (the paper's A..D written as real species: 2NH₃ + CO₂ ⇌ urea + H₂O)."""
        self.assertTrue(chain_ok(361, 152))
        r = run([361, 152], s0__balanced_equation="2NH3 + CO2 -> CO(NH2)2 + H2O",
                s0__initial_amounts={"NH3": 1, "CO2": 1}, s0__known_species="H2O", s0__known_equilibrium_amount=0.1,
                s0__species_asked="NH3", s1__volume=10)
        self.close(run([361], s0__balanced_equation="2NH3 + CO2 -> CO(NH2)2 + H2O",
                       s0__initial_amounts={"NH3": 1, "CO2": 1}, s0__known_species="H2O",
                       s0__known_equilibrium_amount=0.1, s0__species_asked="NH3"), 0.8)
        self.close(r, (0.01 * 0.01) / (0.08 ** 2 * 0.09))

    def test_2018P2_Q11_delta_g_from_arrhenius_parameters(self):
        """A_f/A_b = 4, E_a,b − E_a,f = 2RT -> K = 4e² -> |ΔG°| = RT(ln 4 + 2) = 8.5 kJ at RT = 2500 J."""
        self.assertTrue(chain_ok(368, 369))
        plan = plan_chain([step(368), step(369)])
        self.assertEqual([g.param.key for g in plan.givens.values()].count("T"), 1)
        r = run([368, 369], s0__prefactor_ratio=4, s0__activation_energy_difference=2 * R * 300, s0__T=300)
        self.close(r, -R * 300 * (math.log(4) + 2) / 1000, tol=1e-3)
        self.close(2500 * (math.log(4) + 2), 8466, tol=0.001)        # the key's 8500 uses ln 2 = 0.7

    def test_2021P1_Q8_entropy_from_intercept(self):
        self.close(run([378], s0__intercept=17, s0__plot="ln K"), 141.34)
        plan_tree([[step(315)], [step(378)]], step(133), {"delta_h": 0, "delta_s": 1})


class Kinetics(Close):
    def test_2013P1_Q21_order_from_fractional_lives(self):
        self.close(run([351], s0__time_ratio=2), 1, tol=1e-9)
        self.close(run([351], s0__time_ratio=3), 2, tol=1e-9)
        self.assertAlmostEqual(run([351], s0__time_ratio=1.5).answer, 0, places=9)

    def test_2019P1_Q16_new_rate(self):
        r = run([372], s0__reaction_rate=6e-5, s0__orders={"A": 1, "B": 0, "C": 1},
                s0__reference_concentrations={"A": 0.2, "B": 0.1, "C": 0.1},
                s0__new_concentrations={"A": 0.15, "B": 0.25, "C": 0.15})
        self.close(r, 6.75e-5)

    def test_2024P1_Q9_order_from_mechanism(self):
        self.assertEqual(run([390], s0__fast_equilibrium="2NO -> N2O2", s0__slow_step="N2O2 + H2 -> N2O + H2O").answer, 3)


class Ionic(Close):
    def test_2013P1_Q31_acid_catalysis(self):
        """rate ratio 1/100 with 1 M acids: [H⁺] = 0.01 -> K_a ≈ 10⁻⁴ (the key ignores C − [H⁺])."""
        self.assertTrue(chain_ok(353, 354))
        self.close(run([353, 354], s0__rate_ratio=0.01, s0__strong_acid_concentration=1, s1__concentration=1), 1e-4, tol=0.02)

    def test_2018P1_Q11_salt_of_weak_acid_at_pH_3(self):
        self.close(run([365], s0__solubility_product=2e-10, s0__Ka=1e-8, s0__ph=3), 4.47e-3)

    def test_2023P1_Q6_pKa_from_two_solubilities(self):
        """S rises from 10⁻⁴ (pH 7) to 10⁻³ (pH 2) when pK_a = 4."""
        s = lambda ph: run([365], s0__solubility_product=1e-8, s0__Ka=1e-4, s0__ph=ph).answer
        self.close(s(7), 1e-4)
        self.close(s(2), 1e-3)

    def test_2019P1_Q15_ferrous_ion_left(self):
        self.close(run([371], s0__solubility_product=1 / 1.6e17, s0__cation_concentration=0.06, s0__volume_1=100,
                       s0__anion_concentration=0.2, s0__volume_2=100), 8.93e-17)

    def test_2020P2_Q18_minimum_acidity(self):
        self.close(run([377], s0__solubility_product=1.25e-22, s0__h2s_constant=1e-21, s0__h2s_concentration=0.1,
                       s0__cation_concentration=0.05), 0.20)

    def test_2022P1_Q3_carbonate_buffer(self):
        self.assertTrue(chain_ok(384, 185))
        r = run([384, 185], s0__diprotic_acid_moles=0.01, s0__monoanion_moles=0.01, s0__dianion_moles=0.01,
                s0__strong_base_moles=0.01, s0__Ka1=10 ** -6.37, s0__Ka2=10 ** -10.32)
        self.close(r, 10.02, tol=0.001)

    def test_2022P2_Q1_lead_sulfate(self):
        s = run([385], s0__solubility_product=1.6e-8, s0__acid_concentration=1, s0__sulfate_concentration=1.8e-2,
                s0__Ka2=1.2e-2).answer
        self.assertEqual(math.floor(-math.log10(s)) + 1, 6)        # X × 10⁻⁶
        self.close(s, 1.33e-6, tol=0.02)

    def test_2025_Q9_very_weak_acid_with_water(self):
        """K_a = 4 × 10⁻¹¹, C = 10⁻³: [H⁺] = 2.24 × 10⁻⁷ (without water's H⁺: 2.0 × 10⁻⁷)."""
        r = run([175], s0__dissociation_constant=4e-11, s0__concentration=1e-3)
        self.close(10 ** -r.answer, 2.24e-7, tol=0.005)
        # ignoring water gives 2.00 × 10⁻⁷ (pH 6.70 against 6.65): a trap only where pH shifts more than 1 %
        self.assertIn("ignores_water", [t["id"] for t in run([175], s0__dissociation_constant=1e-12,
                                                             s0__concentration=1e-3).traps])
        self.close(run([175], s0__dissociation_constant=1.8e-5, s0__concentration=0.1).answer, 2.875, tol=0.002)


class Electrochemistry(Close):
    def test_2022P1_Q2_permanganate_to_manganese(self):
        self.close(run([383], s0__couples=[[3, 1.68], [2, 1.21], [2, -1.03]], s0__electrons=7), 0.77, tol=0.005)
        with self.assertRaises(EngineError):
            run([383], s0__couples=[[3, 1.68], [2, 1.21]], s0__electrons=7)

    def test_2025_Q8_current_for_one_mole_of_chromium(self):
        self.assertTrue(chain_ok(335, 391))
        self.close(run([335, 391], s0__mass=52, s0__molar_mass=52, s0__electrons=3, s1__time=48.25), 100)


class Surface(Close):
    def test_2024P2_Q8_area_per_molecule(self):
        """0.05 mol added, 0.04 back-titrated: 150 m² over 0.01 N_A molecules = 2500 × 10⁻²³ m² (N_A = 6.0 × 10²³)."""
        self.assertTrue(chain_ok(35, 387))
        r = run([35, 387], s0__normality=1, s0__volume=40, s1__acid_molarity=0.5, s1__acid_volume=100,
                s1__specific_surface_area=150, s1__adsorbent_mass=1)
        self.close(r, 2500e-23 * 6.0e23 / NA)


    def test_2025_Q11_gas_work(self):
        """8 mol H₂O electrolysed -> 8 H₂ + 4 O₂: Δn_g = 12, w = −12RT = −29.93 kJ at 300 K."""
        r = run([392], s0__balanced_equation="2H2O(l) -> 2H2(g) + O2(g)", s0__known_species="H2O",
                s0__moles_known=8, s0__T=300)
        self.close(r, -12 * 8.314 * 300)


class Coverage(unittest.TestCase):
    def test_every_new_step_is_tested_or_chained(self):
        self.assertEqual(sorted(t for t in STEPS if 348 <= t <= 392), list(range(348, 393)))


if __name__ == "__main__":
    unittest.main()
