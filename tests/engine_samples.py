"""
Sample inputs for running every engine chain offline (tools/audit_engine.py --run,
tests/test_engine_audit.py).

Numbers are drawn inside each input's realistic range (Param.lo .. Param.hi). Text, JSON and
list inputs come from FIXTURES: per step, sets of values that belong together (an equation
and the species named from it). A value already wired from the previous step is not drawn.
"""

from __future__ import annotations

import math
import random

from core.engine.base import EngineError

FIXTURES = {
    7: [{"percent_composition": {"C": 40.0, "H": 6.7, "O": 53.3}},
        {"percent_composition": {"C": 85.7, "H": 14.3}}],
    8: [{"empirical_formula": "CH2O", "vapour_density": 30}, {"empirical_formula": "CH2", "vapour_density": 28}],
    11: [{"balanced_equation": "N2 + 3H2 -> 2NH3", "known_species": "N2", "target_species": "NH3"},
         {"balanced_equation": "2KClO3 -> 2KCl + 3O2", "known_species": "KClO3", "target_species": "O2"},
         {"balanced_equation": "MnO4- + 5Fe2+ + 8H+ -> Mn2+ + 5Fe3+ + 4H2O", "known_species": "MnO4-",
          "target_species": "Fe3+"}],
    12: [{"balanced_equation": "Fe3O4 -> Fe2(SO4)3", "known_species": "Fe3O4", "target_species": "Fe2(SO4)3",
          "element": "Fe"},
         {"balanced_equation": "MnO4- + 5Fe2+ + 8H+ -> Mn2+ + 5Fe3+ + 4H2O", "known_species": "Fe2+",
          "target_species": "Fe3+", "element": "Fe"}],
    13: [{"balanced_equation": "2H2 + O2 -> 2H2O", "reactant_A": "H2", "reactant_B": "O2"},
         {"balanced_equation": "N2 + 3H2 -> 2NH3", "reactant_A": "N2", "reactant_B": "H2"}],
    16: [{"equation_1": "CaCO3 -> CaO + CO2", "equation_2": "CO2 + 2NaOH -> Na2CO3 + H2O",
          "known_species": "CaCO3", "intermediate_species": "CO2", "target_species": "Na2CO3"}],
    27: [{"balanced_equation": "N2 + 3H2 -> 2NH3", "reactant_species": "H2", "product_species": "NH3"}],
    29: [{"hydrocarbon_volume": 10, "contraction_on_cooling": 25, "volume_absorbed_by_KOH": 20},
         {"hydrocarbon_volume": 20, "contraction_on_cooling": 60, "volume_absorbed_by_KOH": 40}],
    41: [{"equivalents": 0.05, "back_titrated_equivalents": 0.01, "equivalent_mass": 50, "sample_mass": 2.5}],
    224: [{"initial_Z": 92, "initial_A": 238, "count": "alpha"}],
    30: [{"chemical_species": "Cr2O7^2-", "element": "Cr"}, {"chemical_species": "KMnO4", "element": "Mn"}],
    32: [{"reactants": "MnO4-, Fe2+, H+", "products": "Mn2+, Fe3+, H2O", "species_asked": "Fe2+"}],
    77: [{"orbital_label": "3d"}, {"orbital_label": "4p"}],
    78: [{"orbital_label": "3d"}],
    82: [{"orbital_label": "4s"}, {"orbital_label": "3p"}],
    113: [{"balanced_equation": "C2H6(g) + 7/2 O2(g) -> 2CO2(g) + 3H2O(l)"}],
    131: [{"balanced_equation": "N2 + 3H2 -> 2NH3", "standard_entropies": {"N2": 191.6, "H2": 130.7, "NH3": 192.5}}],
    134: [{"balanced_equation": "N2 + 3H2 -> 2NH3", "formation_gibbs": {"N2": 0, "H2": 0, "NH3": -16.5}}],
    139: [{"balanced_equation": "CH4 + 2O2 -> CO2 + 2H2O",
           "formation_enthalpies": {"CH4": -74.8, "O2": 0, "CO2": -393.5, "H2O": -285.8}}],
    140: [{"balanced_equation": "C2H4 + H2 -> C2H6", "combustion_enthalpies": {"C2H4": -1411, "H2": -285.8, "C2H6": -1560}}],
    141: [{"target_equation": "C + 2H2 -> CH4",
           "step_equations": [["C + O2 -> CO2", -393.5], ["H2 + 1/2 O2 -> H2O", -285.8], ["CH4 + 2O2 -> CO2 + 2H2O", -890.3]]}],
    142: [{"bonds_broken": {"H-H": 1, "Cl-Cl": 1}, "bonds_formed": {"H-Cl": 2},
            "bond_enthalpies": {"H-H": 436, "Cl-Cl": 242, "H-Cl": 431}}],
    151: [{"balanced_equation": "PCl5 -> PCl3 + Cl2", "species_asked": "Cl2"},
          {"balanced_equation": "N2O4 -> 2NO2", "species_asked": "NO2"}],
    152: [{"balanced_equation": "N2O4 -> 2NO2", "eq_amounts": {"N2O4": 0.5, "NO2": 1.0}},
          {"balanced_equation": "N2 + 3H2 -> 2NH3", "eq_amounts": {"N2": 0.5, "H2": 1.5, "NH3": 0.2}}],
    153: [{"balanced_equation": "N2O4 -> 2NO2", "partial_pressures": {"N2O4": 0.4, "NO2": 0.6}},
          {"balanced_equation": "H2 + I2 -> 2HI", "partial_pressures": {"H2": 0.2, "I2": 0.2, "HI": 1.4}}],
    154: [{"balanced_equation": "N2O4 -> 2NO2"}, {"balanced_equation": "N2 + 3H2 -> 2NH3"}],
    155: [{"balanced_equation": "N2O4 -> 2NO2"}, {"balanced_equation": "PCl5 -> PCl3 + Cl2"}],
    157: [{"balanced_equation": "N2 + 3H2 -> 2NH3", "current_concentrations": {"N2": 1, "H2": 1, "NH3": 0.5}},
          {"balanced_equation": "PCl5 -> PCl3 + Cl2", "current_concentrations": {"PCl5": 0.5, "PCl3": 0.2, "Cl2": 0.2}},
          {"balanced_equation": "N2O4 -> 2NO2", "current_concentrations": {"N2O4": 0.5, "NO2": 0.3}}],
    159: [{"balanced_equation": "PCl5 -> PCl3 + Cl2", "vapour_density": 80},
          {"balanced_equation": "N2O4 -> 2NO2", "vapour_density": 35}],
    160: [{"balanced_equation": "PCl5 -> PCl3 + Cl2"}, {"balanced_equation": "N2O4 -> 2NO2"}],
    161: [{"balanced_equation": "N2(g) + 3H2(g) -> 2NH3(g)"}],
    162: [{"balanced_equation": "N2(g) + 3H2(g) -> 2NH3(g)"}, {"balanced_equation": "CaCO3(s) -> CaO(s) + CO2(g)"}],
    164: [{"balanced_equation": "PCl5(g) -> PCl3(g) + Cl2(g)"}],
    166: [{"balanced_equation": "CO2(g) -> CO2(aq)"}],
    167: [{"balanced_equation": "KNO3(s) -> KNO3(aq)"}],
}

_INTEGER = {"posint", "count", "integer"}


def _number(p, rng):
    lo = p.lo if p.lo is not None else (1 if p.kind != "real" else -10)
    hi = p.hi if p.hi is not None else (lo * 10 if lo > 0 else 10)
    if p.kind in _INTEGER:
        return rng.randint(int(math.ceil(lo)), int(math.floor(hi))) if hi >= lo else int(lo)
    if lo > 0 and hi / lo > 100:
        return float(f"{math.exp(rng.uniform(math.log(lo), math.log(hi))):.3g}")
    return float(f"{rng.uniform(lo, hi):.3g}")


def sample_values(plan, rng: random.Random) -> dict:
    """Values for every given of a chain plan; raises EngineError if a step has no fixture
    for a text input."""
    values, chosen = {}, {}
    for qk, g in plan.givens.items():
        p, i = g.param, g.steps[0]
        st = plan.steps[i]
        if p.kind in ("text", "dict", "list") or (st.tx in FIXTURES and p.key in FIXTURES[st.tx][0]):
            if st.tx not in FIXTURES:
                raise EngineError(f"no fixture for tx {st.tx} ({p.key})")
            fx = chosen.setdefault(i, rng.choice(FIXTURES[st.tx]))
            if p.key not in fx:
                if p.kind in ("text", "dict", "list"):
                    raise EngineError(f"fixture for tx {st.tx} lacks {p.key}")
                values[qk] = _number(p, rng)
                continue
            values[qk] = fx[p.key]
        elif p.kind == "choice":
            values[qk] = rng.choice(list(p.choices))
        else:
            values[qk] = _number(p, rng)
    return values
