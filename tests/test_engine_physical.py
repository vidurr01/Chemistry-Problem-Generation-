"""Physical engine: every computed answer checked against a textbook result.

Run:  python -m unittest tests.test_engine_physical
"""

import unittest

from core.engine.base import EngineError, answers_match, links, plan_chain, run_chain
from core.engine.physical import STEPS, step


def run(txs, **given):
    """Run a chain; keyword s0__mass=4.4 means given 's0.mass' (ctx__x -> 'ctx.x')."""
    values = {k.replace("__", "."): v for k, v in given.items()}
    return run_chain(plan_chain([step(t) for t in txs]), values)


class Close(unittest.TestCase):
    def close(self, result, expected, tol=0.01):
        got = result.answer if hasattr(result, "answer") else result
        self.assertTrue(answers_match(got, expected, tol), f"got {got!r}, expected {expected!r}")


class Stoichiometry(Close):
    def test_mass_moles_volume(self):
        self.close(run([1], s0__mass=4.4, s0__molar_mass=44), 0.1)
        self.close(run([1, 4], s0__mass=4.4, s0__molar_mass=44), 2.24)

    def test_particles(self):
        self.close(run([3], s0__moles=0.5, s0__particles_per_unit=3), 9.033e23)

    def test_isotopic_average(self):
        self.close(run([5], s0__isotope_1_mass=35, s0__isotope_1_percent=75, s0__isotope_2_mass=37), 35.5)

    def test_mixture_molar_mass(self):
        self.close(run([6], s0__moles=1, s0__M1=2, s0__moles_2=1, s0__M2=32), 17)

    def test_empirical_and_molecular(self):
        r = run([7, 8], s0__percent_composition={"C": 40.0, "H": 6.67, "O": 53.33}, s1__vapour_density=90)
        self.assertEqual(r.answer, "C6H12O6")
        self.assertIn("atomic mass of C = 12", r.constants)

    def test_vapour_density(self):
        self.close(run([9], s0__vapour_density=22), 44)

    def test_mole_method_and_poac(self):
        self.close(run([11], s0__balanced_equation="2H2 + O2 -> 2H2O", s0__known_species="O2",
                       s0__moles_known=1.5, s0__target_species="H2O"), 3.0)
        self.close(run([12], s0__balanced_equation="KClO3 -> KCl + O2", s0__known_species="KClO3",
                       s0__moles_known=2, s0__target_species="O2", s0__element="O"), 3.0)
        with self.assertRaises(EngineError):
            run([11], s0__balanced_equation="H2 + O2 -> H2O", s0__known_species="O2",
                s0__moles_known=1, s0__target_species="H2O")

    def test_limiting_and_excess(self):
        r = run([13, 14], s0__balanced_equation="N2 + 3H2 -> 2NH3", s0__reactant_A="N2", s0__moles=2,
                s0__reactant_B="H2", s0__moles_B=3)
        self.close(r, 1.0)
        self.assertEqual(run([13], s0__balanced_equation="N2 + 3H2 -> 2NH3", s0__reactant_A="N2", s0__moles=2,
                             s0__reactant_B="H2", s0__moles_B=3).answer, "H2")

    def test_yield_and_sequential(self):
        self.close(run([15], s0__moles=2, s0__actual_moles=1.5), 75)
        self.close(run([16], s0__equation_1="C + O2 -> CO2", s0__equation_2="CO2 + 2NaOH -> Na2CO3 + H2O",
                       s0__known_species="C", s0__moles_known=2, s0__intermediate_species="CO2",
                       s0__target_species="Na2CO3"), 2)

    def test_concentration_terms(self):
        self.close(run([17], s0__mass_percent=20, s0__solution_mass=50), 10)
        self.close(run([19], s0__mass_percent=98, s0__density=1.84, s0__solute_molar_mass=98), 18.4)
        self.close(run([21], s0__mole_fraction=0.1, s0__solvent_molar_mass=18), 6.173)
        self.close(run([23], s0__molarity=1, s0__initial_volume=100, s0__water_added=400), 0.2)
        self.close(run([24], s0__molarity=1, s0__volume_1=100, s0__molarity_2=2, s0__volume_2=300), 1.75)
        self.close(run([25], s0__volume_strength=20), 1.786)

    def test_eudiometry(self):
        r = run([29], s0__gas_volume=10, s0__contraction_on_cooling=25, s0__volume_absorbed_by_KOH=20)
        self.assertEqual(r.answer, "C2H6")

    def test_oxidation_numbers(self):
        on = lambda sp, el: run([30], s0__chemical_species=sp, s0__element=el).answer
        self.close(on("Cr2O7^2-", "Cr"), 6)
        self.close(on("Fe3O4", "Fe"), 8 / 3)
        self.close(on("H2O2", "O"), -1)
        self.close(on("MnO4^-", "Mn"), 7)
        self.close(on("S4O6^2-", "S"), 2.5)
        self.close(on("KO2", "K"), 1)
        self.close(on("NaH", "Na"), 1)

    def test_n_factor_chain(self):
        r = run([30, 31, 33], s0__chemical_species="Cr2O7^2-", s0__element="Cr", s1__final_oxidation_number=3,
                s1__atoms_per_formula=2, s2__molar_mass=294)
        self.close(r, 49)
        self.assertTrue(any(t["id"] == "forgets_atom_count" for t in r.traps))

    def test_balancing(self):
        self.assertEqual(run([32], s0__reactants="MnO4^-, Fe^2+, H+", s0__products="Mn^2+, Fe^3+, H2O",
                             s0__species_asked="H+").answer, 8)
        self.assertEqual(run([32], s0__reactants="Cr2O7^2-, I^-, H+", s0__products="Cr^3+, I2, H2O",
                             s0__species_asked="I^-").answer, 6)

    def test_equivalents(self):
        self.close(run([33], s0__n_factor=5, s0__molar_mass=158), 31.6)
        self.close(run([35], s0__normality=0.1, s0__volume=25), 0.0025)
        self.close(run([36], s0__equivalents=0.0025, s0__volume=20), 0.125)
        self.close(run([39], s0__equivalents=0.003, s0__extra_equivalents=0.001, s0__component="NaOH"), 0.002)
        self.close(run([39], s0__equivalents=0.003, s0__extra_equivalents=0.001, s0__component="Na2CO3"), 0.001)
        self.close(run([41], s0__equivalents=0.01, s0__back_titrated_equivalents=0.002, s0__equivalent_mass=50,
                       s0__sample_mass=0.5), 80)

    def test_redox_reagents(self):
        self.close(run([44], s0__redox_reagent="KMnO4 in acidic medium (MnO4- -> Mn2+)"), 5)
        self.close(run([52], s0__redox_reagent="Cl2 in hot concentrated alkali (3Cl2 -> ClO3- + 5Cl-)"), 5 / 3)
        self.close(run([50], s0__redox_reagent="ferrous oxalate FeC2O4 with KMnO4 (Fe2+ -> Fe3+ and C2O4^2- -> 2CO2)"), 3)

    def test_hardness(self):
        self.close(run([49], s0__mass=0.0136, s0__salt_molar_mass=136, s0__water_mass=1000), 10)


class Atomic(Close):
    def test_bohr(self):
        self.close(run([60], s0__n=1, s0__Z=1), -13.6)
        self.close(run([61], s0__n=2, s0__Z=1), 2.116)
        self.close(run([62], s0__n=1, s0__Z=1), 2.18e6)
        self.close(run([64], s0__n=1, s0__Z=1), 1.0546e-34)
        self.close(run([62, 63], s0__n=1, s0__Z=1), 6.56e15)

    def test_spectra(self):
        self.close(run([67, 66], s0__series="Balmer", s0__line="first (alpha)", s0__Z=1), 656.5)
        self.close(run([60, 65], s0__n=2, s0__Z=2, s1__lower_level=1), 40.8)
        self.close(run([69, 65], s0__ionization_energy=54.4, s0__n=2, s1__lower_level=1), 40.8)
        self.close(run([68], s0__upper_level=5, s0__final_level=1, s0__sample="a sample of many atoms"), 10)
        self.close(run([58], s0__wavelength=620), 2.0)

    def test_configuration(self):
        unp = lambda Z, ch: run([81], s0__atomic_number=Z, s0__charge=ch).answer
        self.assertEqual(unp(26, 3), 5)
        self.assertEqual(unp(24, 0), 6)
        self.assertEqual(unp(29, 1), 0)
        self.assertEqual(unp(25, 2), 5)
        self.assertEqual(unp(8, 0), 2)
        self.close(run([81, 79], s0__atomic_number=26, s0__charge=3), 5.916)

    def test_orbitals(self):
        self.assertEqual(run([76], s0__n=3, s0__l=3, s0__m=0).answer, "not allowed")
        self.assertEqual(run([76, 77], s0__n=3, s0__l=1, s0__m=0, s1__node_type="radial").answer, 1)
        self.assertEqual(run([82], s0__orbital_label="3s").answer, 3)
        self.close(run([78], s0__orbital_label="3d"), 6 ** 0.5)
        self.assertEqual(run([326], s0__radial_peaks=2, s0__n=3).answer, "3p")

    def test_uncertainty_and_nuclides(self):
        self.close(run([75], s0__position_uncertainty=1e-10), 5.27e-25)
        self.assertEqual(run([55], s0__Z=11, s0__A=23, s0__charge=1, s0__particle="electrons").answer, 10)
        self.assertEqual(run([83], s0__Z1=6, s0__A1=14, s0__Z2=7, s0__A2=14).answer, "isobars")
        self.close(run([57], s0__alpha_kinetic_energy=5, s0__target_Z=79), 4.55e-14)


class Gases(Close):
    def test_gas_laws(self):
        self.close(run([84], s0__P=1, s0__V=10, s0__new_volume=5), 2)
        self.close(run([85], s0__V=1, s0__t1_celsius=27, s0__t2_celsius=127), 1.3333)
        self.close(run([88], s0__P=1, s0__V=22.4, s0__T=273), 0.9994)
        self.close(run([89], s0__P=1, s0__T=273, s0__molar_mass=32), 1.428)

    def test_graham_and_speeds(self):
        self.close(run([95], s0__molar_mass=2, s0__molar_mass_2=32), 4)
        self.close(run([98], s0__temperature=300, s0__molar_mass=32), 483.6)

    def test_real_gases(self):
        self.close(run([106], s0__a=3.59, s0__b=0.0427), 1024)
        self.close(run([107], s0__a=3.59, s0__b=0.0427, s0__which="T_c"), 303.4)


class Thermo(Close):
    def test_work_and_entropy(self):
        self.close(run([117], s0__n=1, s0__T=300, s0__V1=1, s0__V2=10), -5743)
        self.close(run([127], s0__delta_h=40.7, s0__T=373), 109.1)
        self.close(run([124], s0__temperature=500, s0__cold_temperature=300), 0.4)

    def test_gibbs(self):
        self.close(run([132], s0__delta_h=-100, s0__delta_s=-200, s0__T=300), -40)
        self.close(run([135], s0__delta_g=-5.7, s0__T=298), 9.97)
        self.close(run([138], s0__cell_emf=1.1, s0__electrons=2), -212.3)

    def test_enthalpy_routes(self):
        self.close(run([139], s0__balanced_equation="CH4 + 2O2 -> CO2 + 2H2O",
                       s0__formation_enthalpies={"CH4": -74.8, "O2": 0, "CO2": -393.5, "H2O": -285.8}), -890.3)
        self.close(run([141], s0__target_equation="C + 2H2 -> CH4",
                       s0__step_equations=[["C + O2 -> CO2", -393.5], ["H2 + 1/2 O2 -> H2O", -285.8],
                                           ["CH4 + 2O2 -> CO2 + 2H2O", -890.3]]), -74.8)
        self.close(run([142], s0__bonds_broken={"H-H": 1, "Cl-Cl": 1}, s0__bonds_formed={"H-Cl": 2},
                       s0__bond_enthalpies={"H-H": 436, "Cl-Cl": 242, "H-Cl": 431}), -184)


class Equilibrium(Close):
    def test_constants(self):
        self.close(run([152], s0__balanced_equation="N2O4 -> 2NO2", s0__eq_amounts={"N2O4": 0.5, "NO2": 1.0},
                       s0__volume=1), 2.0)
        self.close(run([154], s0__equilibrium_constant=2, s0__balanced_equation="N2O4 -> 2NO2", s0__T=300), 49.26)
        self.close(run([160], s0__gas_dissociation_degree=0.5, s0__total_pressure=1), 1 / 3)

    def test_ph(self):
        self.close(run([174], s0__molarity=1e-8, s0__basicity=1), 6.979)
        self.close(run([175], s0__dissociation_constant=1.8e-5, s0__concentration=0.1), 2.875)
        self.close(run([181], s0__molarity=0.1, s0__Kb=1.8e-5), 5.127)
        self.close(run([185], s0__buffer_ratio=1, s0__dissociation_constant=1.8e-5), 4.745)
        self.close(run([199], s0__moles=0.01, s0__acid_volume=100, s0__base_moles=0.005, s0__base_volume=100), 1.602)

    def test_solubility(self):
        self.close(run([193], s0__solubility=1e-4, s0__cation_count=2, s0__anion_count=1), 4e-12)
        self.close(run([195], s0__solubility_product=1.8e-10, s0__cation_count=1, s0__anion_count=1,
                       s0__common_ion="anion", s0__common_ion_concentration=0.1), 1.8e-9)
        # Ag2CrO4 (K_sp 1.1e-12) in 0.1 M chromate: (2S)²(0.1) = K_sp -> S = 1.66e-6
        self.close(run([195], s0__solubility_product=1.1e-12, s0__cation_count=2, s0__anion_count=1,
                       s0__common_ion="anion", s0__common_ion_concentration=0.1), 1.658e-6)


class LeChatelier(unittest.TestCase):
    def shift(self, tx, eq, dh, change):
        return run([tx], s0__balanced_equation=eq, s0__delta_h=dh, s0__change=change).answer

    def test_rules(self):
        self.assertEqual(self.shift(162, "N2(g) + 3H2(g) -> 2NH3(g)", -92.4, "increase the pressure by compression"), "forward")
        self.assertEqual(self.shift(162, "CaCO3(s) -> CaO(s) + CO2(g)", 178, "increase the pressure by compression"), "backward")
        self.assertEqual(self.shift(162, "H2(g) + I2(g) -> 2HI(g)", -10, "increase the pressure by compression"), "no shift")
        self.assertEqual(self.shift(164, "PCl5(g) -> PCl3(g) + Cl2(g)", 92, "add an inert gas at constant pressure"), "forward")
        self.assertEqual(self.shift(164, "PCl5(g) -> PCl3(g) + Cl2(g)", 92, "add an inert gas at constant volume"), "no shift")
        self.assertEqual(self.shift(167, "KNO3(s) -> KNO3(aq)", 35, "increase the temperature"), "forward")


class Facts(unittest.TestCase):
    def test_every_source_builds_every_mode_with_a_consistent_key(self):
        import random
        from core.engine.facts import LETTERS, MODES, build
        from core.engine.physical.facts_data import FACTS
        rng = random.Random(0)
        for src in FACTS:
            for mode in MODES:
                q = build(src, mode, rng)
                self.assertEqual(len(q.options), 4)
                want = [LETTERS[i] for i, t in enumerate(q.truth) if (not t if mode == "mcq_incorrect" else t)]
                self.assertEqual(q.answer, "".join(want), (src.id, mode))
                if mode != "msq":
                    self.assertEqual(len(q.answer), 1)

    def test_letters(self):
        from core.engine.facts import letters_of
        self.assertEqual(letters_of("A and C"), "AC")
        self.assertEqual(letters_of("(b), (d)"), "BD")
        self.assertEqual(letters_of("None"), "")


class Kinetics(Close):
    def test_rate_constants(self):
        self.close(run([205], s0__initial_concentration=1, s0__concentration=0.25, s0__time=100), 0.01386)
        self.close(run([218], s0__half_life=693), 0.001)
        self.close(run([209], s0__fraction_remaining=0.125, s0__half_life=10), 30)
        self.close(run([213], s0__rate_constant=1, s0__T1=300, s0__k2=2, s0__T2=310), 53.6)

    def test_nuclear(self):
        self.assertEqual(run([219], s0__Z=92, s0__A=238).answer, "Th-234")
        r = run([224], s0__Z=82, s0__A=206, s0__initial_Z=92, s0__initial_A=238, s0__count="beta")
        self.assertEqual(r.answer, 6)
        self.assertEqual(run([224], s0__Z=82, s0__A=206, s0__initial_Z=92, s0__initial_A=238, s0__count="alpha").answer, 8)
        self.close(run([227], s0__uranium_mass=1, s0__lead_mass=0.1, s0__half_life=4.5e9), 7.10e8)
        self.close(run([229, 230], s0__Z=2, s0__A=4, s0__atomic_mass=4.002603, s1__which="per nucleon"), 7.074)


class Electro(Close):
    def test_faraday_and_cells(self):
        self.close(run([234], s0__charge=96500, s0__molar_mass=63.5, s0__electrons=2), 31.75)
        self.close(run([238], s0__cathode_potential=0.34, s0__anode_potential=-0.76), 1.10)
        self.close(run([239], s0__standard_emf=1.1, s0__molarity=0.1, s0__cathode_ion_concentration=1, s0__electrons=2), 1.1296)
        self.close(run([241], s0__molarity=0.01, s0__concentration_2=0.1, s0__electrons=1), 0.0591)
        self.close(run([248], s0__conductivity=0.0129, s0__molarity=0.1), 129)


class Solutions(Close):
    def test_colligative(self):
        self.close(run([262], s0__molality=0.5, s0__Kb=0.52, s0__vant_hoff_factor=1), 0.26)
        self.close(run([263], s0__molality=0.1, s0__Kf=1.86, s0__vant_hoff_factor=2), 0.372)
        self.close(run([264], s0__delta_T=0.93, s0__constant=1.86, s0__solute_mass=9, s0__solvent_mass=100), 180)
        self.close(run([265], s0__molarity=0.1, s0__T=300, s0__vant_hoff_factor=1), 2.463)
        self.close(run([257, 258], s0__mole_fraction=0.5, s0__PA_pure=100, s0__PB_pure=50), 2 / 3)
        self.close(run([267], s0__degree_of_dissociation=1, s0__particles=2, s0__process="association"), 0.5)


class Solids(Close):
    def test_cells(self):
        self.close(run([272], s0__corner_atoms=8, s0__face_atoms=6, s0__edge_atoms=0, s0__body_atoms=0), 4)
        self.close(run([273], s0__edge_length=564, s0__atoms_per_cell=4, s0__molar_mass=58.5), 2.165)
        self.close(run([274], s0__lattice="face-centred cubic", s0__atomic_radius=128), 362.0)
        self.close(run([275], s0__lattice="body-centred cubic"), 0.680)
        self.assertEqual(run([278], s0__cation_radius=95, s0__anion_radius=181).answer, 6)
        self.assertEqual(run([279], s0__void_type="octahedral", s0__fraction_occupied="2/3").answer, "A2B3")
        self.close(run([280], s0__wavelength=154, s0__angle=30, s0__order=1), 154)


class Chains(unittest.TestCase):
    def test_every_step_declares_nodes_and_constants_text(self):
        for tx, st in STEPS.items():
            self.assertTrue(st.src and st.dst, tx)
            for c in st.constants:
                self.assertIsInstance(c, str)

    def test_unlinked_chain_is_refused(self):
        with self.assertRaises(EngineError):
            plan_chain([step(9), step(60)])       # molar mass has nothing to do with a Bohr orbit

    def test_links_follow_fields(self):
        self.assertTrue(links(step(1), step(4)))
        self.assertTrue(links(step(13), step(14)))
        self.assertFalse(links(step(9), step(60)))

    def test_roles_block_incoherent_links(self):
        from core.engine.physical import BRIDGES
        self.assertFalse(links(step(339), step(340), BRIDGES))      # softener mass is not sodium azide
        self.assertFalse(links(step(39), step(151), BRIDGES))       # NaOH moles are not a dissociating gas
        self.assertFalse(links(step(263), step(330), BRIDGES))      # ΔT_f is not an osmotic pressure
        self.assertFalse(links(step(214), step(333), BRIDGES))      # rate factor is not a decay constant
        self.assertFalse(links(step(205), step(226), BRIDGES))      # chemical k is not a radioactive λ
        self.assertTrue(links(step(88), step(4), BRIDGES))          # moles of gas -> volume
        self.assertTrue(links(step(263), step(328), BRIDGES))       # ΔT_f -> antifreeze mass
        self.assertTrue(links(step(218), step(226), BRIDGES))       # half-life -> λ -> secular ratio

    def test_sampled_chains_link_and_run(self):
        """Every chain the walk offers has a linked step assignment."""
        from core.coverage import Coverage
        from core.engine import physical as ph
        from core.graph_traversal import load_graph, sample_chains
        g = load_graph("knowledge/reaction_graph_physical.json")
        chains = sample_chains(g, Coverage(), None, None, n_options=200, depth=3, can_follow=ph.can_follow,
                               validate=lambda es: ph.chain_steps(es) is not None)
        self.assertGreater(len(chains), 50)
        for c in chains:
            steps = ph.chain_steps([g.edge_map[e] for e in c["edges"]])
            self.assertIsNotNone(steps, c["edges"])
            plan_chain(steps)


if __name__ == "__main__":
    unittest.main()
