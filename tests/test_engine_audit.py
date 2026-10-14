"""
Engine audit (offline): the chain-level errors found on 2026-10-14 cannot come back.

Run:  python -m unittest tests.test_engine_audit

Each test names the error it pins: a value passed in the wrong unit or meaning, a value
stated twice, data that over-determine the answer, a wrong formula. The last tests run the
whole audit (tools/audit_engine.py): every chain of up to three steps the walk can build is
checked and executed on sampled inputs.
"""

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from core import units                                            # noqa: E402
from core.engine.base import plan_chain, roles_consistent, run_chain  # noqa: E402
from core.engine.chem import balance, parse_formula               # noqa: E402
from core.engine.physical import BRIDGES, STEPS, links, step      # noqa: E402


def run(txs, **given):
    return run_chain(plan_chain([step(t) for t in txs]), {k.replace("__", "."): v for k, v in given.items()})


def link(a, b):
    return links(step(a), step(b), BRIDGES) and roles_consistent([step(a), step(b)])


def chain_ok(*txs):
    steps = [step(t) for t in txs]
    return all(links(a, b, BRIDGES) for a, b in zip(steps, steps[1:])) and roles_consistent(steps)


def wired(txs, i, key):
    return plan_chain([step(t) for t in txs]).wiring[i].get(key, (None,))[0] == "prev"


class Close(unittest.TestCase):
    def close(self, got, want, tol=0.01):
        got = got.answer if hasattr(got, "answer") else got
        self.assertTrue(math.isclose(got, want, rel_tol=tol), f"got {got}, expected {want}")


class Equilibrium(Close):
    def test_dissociation_kp_for_any_stoichiometry(self):
        """K_p = α²P/(1 − α²) is A ⇌ B + C only; N2O4 ⇌ 2NO2 is 4α²P/(1 − α²)."""
        self.close(run([160], s0__balanced_equation="PCl5 -> PCl3 + Cl2", s0__gas_dissociation_degree=0.4,
                       s0__total_pressure=2), 0.16 * 2 / 0.84)
        self.close(run([160], s0__balanced_equation="N2O4 -> 2NO2", s0__gas_dissociation_degree=0.4,
                       s0__total_pressure=2), 4 * 0.16 * 2 / 0.84)
        r = run([160], s0__balanced_equation="2NH3 -> N2 + 3H2", s0__gas_dissociation_degree=0.5, s0__total_pressure=1)
        # per 2 NH3: 2(1−α) NH3, α N2, 3α H2 -> per mole of NH3: 0.5, 0.25, 0.75 ; total 1.5
        self.close(r, (0.25 / 1.5) * (0.75 / 1.5) ** 3 / (0.5 / 1.5) ** 2)
        self.assertEqual(r.unit, "atm²")

    def test_vapour_density_reads_D_and_n_from_the_equation(self):
        """D and n were separate givens that could contradict the reactant's formula."""
        r = run([159], s0__balanced_equation="PCl5 -> PCl3 + Cl2", s0__vapour_density=80)
        D = (30.97 + 5 * 35.45) / 2
        self.close(r, (D - 80) / 80)
        self.close(run([159], s0__balanced_equation="N2O4 -> 2NO2", s0__vapour_density=35), (46 - 35) / 35, tol=0.02)
        self.assertTrue(wired([159, 160], 1, "balanced_equation"))

    def test_kc_comparison_needs_kc(self):
        """Q from concentrations was compared with K_p and K_x."""
        for producer in (153, 154, 160, 155):
            self.assertFalse(link(producer, 157), producer)
        self.assertTrue(link(152, 157))
        self.assertTrue(link(210, 157))
        self.assertFalse(link(135, 157))           # untagged K from ΔG°

    def test_van_t_hoff_takes_kp_or_kc_and_gives_delta_s(self):
        """Run 12 chain 1: K_x was fed into van 't Hoff; chain 3: ΔS° was stated as well
        as K₁ and K₂ and contradicted them."""
        self.assertFalse(link(155, 136))
        self.assertTrue(link(160, 136))
        r = run([136, 133], s0__equilibrium_constant=1e-3, s0__T1=300, s0__K2=1e-2, s0__T2=350)
        plan = plan_chain([step(136), step(133)])
        self.assertNotIn("s1.delta_s", plan.givens)
        dh = 8.314 * math.log(10) / (1 / 300 - 1 / 350)
        ds = dh / 300 + 8.314 * math.log(1e-3)
        self.close(r, dh / ds)
        # at that temperature K = 1, as it must be when ΔG° = 0
        T = r.answer
        self.assertAlmostEqual(math.log(1e-3) - dh / 8.314 * (1 / T - 1 / 300), 0, places=2)

    def test_temperatures_carried(self):
        self.assertTrue(wired([135, 136], 1, "T1"))
        self.assertTrue(wired([154, 136], 1, "T1"))
        self.assertTrue(wired([135, 163], 1, "T1"))
        self.assertTrue(wired([163, 154], 1, "T"))
        self.assertTrue(wired([132, 135], 1, "T"))
        self.assertTrue(wired([113, 114], 1, "T1"))
        self.assertTrue(wired([114, 132], 1, "T"))
        self.assertTrue(wired([265, 330], 1, "T"))

    def test_delta_h_never_stated_twice(self):
        self.assertTrue(wired([132, 135, 163], 2, "delta_h"))
        self.assertFalse(chain_ok(132, 135, 136))   # ΔH given with ΔS, then recomputed from two K
        self.assertFalse(chain_ok(163, 154, 136))   # ΔH given for K₁ -> K₂, then recomputed
        self.assertFalse(link(163, 136))

    def test_total_pressure_is_the_sum(self):
        r = run([153, 155], s0__balanced_equation="N2O4 -> 2NO2", s0__partial_pressures={"N2O4": 0.4, "NO2": 0.6})
        self.close(r, (0.6 ** 2 / 0.4) * 1.0 ** -1)
        self.assertTrue(wired([160, 155], 1, "total_pressure"))

    def test_k_units(self):
        self.assertEqual(run([152], s0__balanced_equation="N2O4 -> 2NO2", s0__eq_amounts={"N2O4": 0.5, "NO2": 1.0},
                             s0__volume=1).unit, "mol L⁻¹")
        self.assertEqual(run([152], s0__balanced_equation="N2 + 3H2 -> 2NH3",
                             s0__eq_amounts={"N2": 0.5, "H2": 1.5, "NH3": 0.2}, s0__volume=1).unit, "L² mol⁻²")
        self.assertEqual(run([154], s0__equilibrium_constant=2, s0__balanced_equation="N2 + 3H2 -> 2NH3",
                             s0__T=500).unit, "atm⁻²")
        self.assertEqual(run([153], s0__balanced_equation="H2 + I2 -> 2HI",
                             s0__partial_pressures={"H2": 0.2, "I2": 0.2, "HI": 1.4}).unit, "")
        for u in ("mol L⁻¹", "L² mol⁻²", "atm⁻²", "atm²", "mol² L⁻²", "L mol⁻¹", "atm⁻¹"):
            self.assertIsNotNone(units.parse(u), u)

    def test_solubility_product_from_pure_water_solubility_only(self):
        for producer in (195, 196, 197):
            self.assertFalse(link(producer, 193), producer)
        self.assertTrue(link(252, 193))

    def test_salt_of_weak_acid_and_weak_base(self):
        self.assertFalse(link(178, 183))            # K_b of the conjugate base is not the weak base's
        self.assertTrue(link(191, 183))


class Thermo(Close):
    def test_enthalpy_kinds(self):
        for producer in (144, 145, 149, 150):         # neutralisation, hydration, dilution, atomization
            self.assertFalse(link(producer, 132), producer)
            self.assertFalse(link(producer, 133), producer)
        self.assertTrue(link(139, 132))
        self.assertTrue(link(146, 133))
        self.assertFalse(link(114, 127))            # a reaction's ΔH is not a phase change's
        self.assertFalse(link(315, 127))
        self.assertFalse(link(240, 127))
        self.assertFalse(link(144, 216))            # no activation energy for neutralisation

    def test_constant_delta_h_not_corrected_by_kirchhoff(self):
        self.assertFalse(link(136, 114))
        self.assertFalse(link(315, 114))
        self.assertFalse(link(114, 133))

    def test_entropy_of_the_universe_needs_the_system(self):
        self.assertFalse(link(130, 129))            # ΔS_surr was wired in as ΔS_sys
        self.assertTrue(link(125, 129))
        self.assertTrue(link(126, 129))
        self.assertFalse(link(148, 130))

    def test_cell_emf_kinds(self):
        self.assertFalse(link(239, 138))            # a non-standard E gives no ΔG°
        self.assertFalse(link(239, 243))            # nor K_sp
        self.assertFalse(link(241, 243))
        self.assertTrue(link(238, 138))
        self.assertTrue(link(238, 243))
        self.assertTrue(wired([239, 240], 1, "electrons"))

    def test_emf_temperature_coefficient_gives_delta_s(self):
        r = run([240, 132], s0__cell_emf=1.1, s0__electrons=2, s0__T=298, s0__temperature_coefficient=-4e-4)
        self.assertNotIn("s1.delta_s", plan_chain([step(240), step(132)]).givens)
        self.close(r, -2 * 96485 * 1.1 / 1000, tol=0.002)   # ΔG = ΔH − TΔS = −nFE


class Gases(Close):
    def test_temperature_and_constant_quantity_carried(self):
        self.assertTrue(wired([85, 86], 1, "t1_celsius"))
        self.assertTrue(wired([87, 85], 1, "t1_celsius"))
        plan = plan_chain([step(84), step(85), step(86)])
        self.assertEqual(plan.wiring[2]["P"][0], "prev")   # Charles at constant P hands on Boyle's P
        r = run([84, 85, 86], s0__P=2, s0__V=10, s0__new_volume=5, s1__t1_celsius=27, s1__t2_celsius=127,
                s2__t2_celsius=227)
        self.close(r, 4 * 500 / 400)

    def test_amagat_total_is_a_total(self):
        r = run([93, 22], s0__gas_volume=2, s0__partial_volume_2=6)
        self.close(r, 0.25)
        # what goes on is gas 1's own partial volume, never the total
        self.assertEqual(plan_chain([step(93), step(27)]).wiring[1]["gas_volume"], ("prev", "gas_volume"))
        self.assertNotIn("total_volume", plan_chain([step(93), step(27)]).wiring[1])
        self.assertFalse(link(4, 29))               # L into the eudiometry step's mL

    def test_graham_needs_a_gas(self):
        self.assertFalse(link(5, 95))               # an element's average atomic mass (Cl 35.5, not Cl2)
        self.assertFalse(link(256, 95))             # a non-volatile solute
        self.assertTrue(link(9, 95))
        self.assertTrue(link(6, 95))

    def test_separation_factor_whichever_gas_is_first(self):
        """0.25⁶ was reported instead of 4⁶ when the heavier gas was called gas 1."""
        a = run([95, 96], s0__molar_mass=32, s0__molar_mass_2=2, s1__stages=3)
        b = run([95, 96], s0__molar_mass=2, s0__molar_mass_2=32, s1__stages=3)
        self.close(a, 64)
        self.close(b, 64)

    def test_critical_constant_unit(self):
        for which, u in (("T_c", "K"), ("P_c", "atm"), ("V_c", "L mol⁻¹")):
            self.assertEqual(run([107], s0__a=3.59, s0__b=0.0427, s0__which=which).unit, u)

    def test_solid_decomposition_pressure_is_not_a_gas_law_state(self):
        for b in (84, 86, 87, 89, 92, 97, 103):
            self.assertFalse(link(170, b), b)
        self.assertTrue(link(170, 88))

    def test_real_gas_from_ideal_gas_law_results(self):
        for a in (84, 85, 86, 87, 91):
            self.assertFalse(link(a, 103), a)


class Stoichiometry(Close):
    def test_atoms_are_not_gas_molecules(self):
        self.assertFalse(link(0, 4))
        self.assertFalse(link(0, 6))
        self.assertFalse(link(2, 4))                # an ionic compound is not a gas
        self.assertTrue(link(1, 4))
        self.assertTrue(link(0, 3))
        self.assertTrue(link(0, 13))                # Mg atoms react

    def test_fixed_substances(self):
        self.assertFalse(link(341, 335))            # ethanol is not a metal to deposit
        self.assertFalse(link(341, 0))
        self.assertTrue(link(341, 1))
        self.assertTrue(link(341, 10))
        self.assertFalse(link(17, 10))              # a solute's mass over "the sample's" volume
        self.assertFalse(link(17, 49))
        self.assertFalse(link(26, 49))
        self.assertFalse(link(49, 26))              # ppm as CaCO3 is not ppm by mass
        self.assertFalse(link(17, 235))
        self.assertTrue(link(234, 235))
        self.assertTrue(link(338, 235))
        self.assertTrue(link(14, 341))              # run 11: the excess reagent can be the dichromate
        self.assertFalse(link(14, 15))              # the reagent left over is not the product

    def test_values_that_follow_from_the_formula(self):
        r = run([30, 31], s0__chemical_species="Cr2O7^2-", s0__element="Cr", s1__final_oxidation_number=3)
        self.assertTrue(wired([30, 31], 1, "atoms_per_formula"))
        self.close(r, 6)
        r = run([44, 33], s0__redox_reagent="KMnO4 in acidic medium (MnO4- -> Mn2+)")
        self.assertTrue(wired([44, 33], 1, "molar_mass"))
        self.close(r, 158.03 / 5, tol=0.002)
        for key in [k for k in __import__("core.engine.physical.stoichiometry", fromlist=["REDOX_N"]).REDOX_N]:
            from core.engine.physical.stoichiometry import _reagent_molar_mass
            self.assertGreater(_reagent_molar_mass(key)[0], 30, key)

    def test_same_solution_density_and_molar_mass(self):
        self.assertTrue(wired([19, 20], 1, "density"))
        self.assertTrue(wired([19, 20], 1, "solute_molar_mass"))
        self.assertTrue(wired([19, 23, 20], 2, "solute_molar_mass"))
        self.assertTrue(wired([49, 339], 1, "water_mass"))

    def test_ion_notation(self):
        """'Fe2+' was read as Fe₂ with charge +1 and 'Fe²⁺' crashed: redox balancing failed."""
        for f, want in (("Fe2+", ({"Fe": 1}, 2)), ("Fe²⁺", ({"Fe": 1}, 2)), ("Al3+", ({"Al": 1}, 3)),
                        ("MnO4-", ({"Mn": 1, "O": 4}, -1)), ("NH4+", ({"N": 1, "H": 4}, 1)),
                        ("SO42-", ({"S": 1, "O": 4}, -2)), ("SO₄²⁻", ({"S": 1, "O": 4}, -2)),
                        ("Cr2O72-", ({"Cr": 2, "O": 7}, -2)), ("PO43-", ({"P": 1, "O": 4}, -3)),
                        ("Hg22+", ({"Hg": 2}, 2)), ("HCO3-", ({"H": 1, "C": 1, "O": 3}, -1)),
                        ("Fe(CN)6^4-", ({"Fe": 1, "C": 6, "N": 6}, -4)), ("Cl-", ({"Cl": 1}, -1)),
                        ("O2^-", ({"O": 2}, -1)), ("Cu2+", ({"Cu": 1}, 2))):
            self.assertEqual(parse_formula(f), want, f)
        self.assertEqual(balance(["MnO4-", "Fe2+", "H+"], ["Mn2+", "Fe3+", "H2O"]), [1, 5, 8, 1, 5, 4])
        self.assertEqual(balance(["MnO₄⁻", "Fe²⁺", "H⁺"], ["Mn²⁺", "Fe³⁺", "H₂O"]), [1, 5, 8, 1, 5, 4])


class KineticsSolutions(Close):
    def test_first_order_only(self):
        self.assertFalse(link(207, 218))            # an nth-order half-life is not 0.693/k

    def test_colligative(self):
        self.assertFalse(link(262, 264))            # M from ΔT assumes i = 1
        self.assertFalse(link(263, 264))
        self.assertTrue(wired([263, 328], 1, "Kf"))
        self.assertFalse(link(330, 265))            # circular
        self.assertFalse(link(254, 258))            # a pure liquid's VP is not a solution's total
        self.assertFalse(link(257, 94))
        self.assertTrue(link(257, 258))
        self.assertTrue(link(254, 94))

    def test_adsorption_unit(self):
        self.assertEqual(run([286], s0__partial_pressure=0.64, s0__k=2.45, s0__n=2).unit, "g g⁻¹")
        self.assertIsNotNone(units.parse("g g⁻¹"))

    def test_radial_peaks_not_circular(self):
        self.assertFalse(link(82, 326))


class PromptSide(unittest.TestCase):
    def test_chain_text_says_what_each_step_takes(self):
        """The generator picks the substances: it is told what each result is used as."""
        from core.pipeline.adapters import PhysicalAdapter
        text = PhysicalAdapter.chain_text(plan_chain([step(13), step(14), step(341)]))
        self.assertIn("takes from step 2: 'amount of Cr2O7²⁻ reduced to Cr³⁺'", text)
        text = PhysicalAdapter.chain_text(plan_chain([step(1), step(4)]))
        self.assertIn("takes from step 1: 'amount of the gas'", text)

    def test_gate_refuses_a_computed_log(self):
        """Run 12: the stem added 'ln(13.25) = 2.584', i.e. ln(K₂/K₁)."""
        from core.pipeline import gate
        self.assertEqual(gate.computed_values("(Given: R = 8.314 J K⁻¹ mol⁻¹; ln(13.25) = 2.584)"),
                         ["ln(13.25) = 2.584"])
        self.assertEqual(gate.computed_values("(Given: log 2 = 0.301, log 3 = 0.477; ln 10 = 2.303)"), [])
        self.assertEqual(gate.computed_values("K = 12.0 at 600 K and ln K rises with T"), [])

    def test_stem_prompt_forbids_computed_values(self):
        from unittest import mock
        from core import models
        from core.pipeline import stages
        got = {}
        with mock.patch.object(models, "ask_json", lambda r, m, s, u, **k: got.setdefault("u", u) and {"stem": "x"}):
            stages.write_stem("physical chemistry", "s", "c", [], {}, [], "a", "", [])
        self.assertIn("never a value you computed", got["u"])


class WholeAudit(unittest.TestCase):
    """tools/audit_engine.py on every chain of 1-3 steps."""

    @classmethod
    def setUpClass(cls):
        import audit_engine
        cls.A = audit_engine
        cls.chains = audit_engine.chains()

    def test_enough_chains(self):
        self.assertGreater(sum(1 for c, _ in self.chains if len(c) == 3), 400)

    def test_no_unit_or_repeated_value_flags(self):
        flags = [(k, [s.tx for s in c], m) for c, p in self.chains for k, m in self.A.check_chain(c, p)]
        self.assertEqual(flags, [])

    def test_every_chain_runs_on_sampled_inputs(self):
        never, problems = [], []
        for chain, plan in self.chains:
            ok, refused, probs = self.A.run_chain_samples(chain, plan, n=20)
            if not ok:
                never.append([s.tx for s in chain])
            problems += [([s.tx for s in chain], p) for p in probs]
        self.assertEqual(problems, [])
        self.assertEqual(never, [])

    def test_every_unit_reads(self):
        for tx, s in STEPS.items():
            for u in [p.unit for p in s.needs] + ([s.unit] if isinstance(s.unit, str) else []):
                if u:
                    self.assertIsNotNone(units.parse(u), (tx, u))


if __name__ == "__main__":
    unittest.main()
