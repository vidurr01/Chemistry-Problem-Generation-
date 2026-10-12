"""
Physical-chemistry engine.

Every computable entry of knowledge/concept_book_physical.json is a Step here, keyed by
its concept-book index (tx). The physical knowledge graph is built from these steps
(tools/graph_rules_physical.py reads STEPS), so a graph edge exists only when the engine
can compute it: a chain the walk picks is always computable.
"""

from __future__ import annotations

import dataclasses
import json
import os

from core.engine.base import EngineError, Step, assign_steps, links, plan_chain, run_chain  # noqa: F401
from core.engine.physical import (atomic, electro_solutions, equilibrium, gases, kinetics, stoichiometry,
                                  thermo)

_MODULES = [stoichiometry, atomic, gases, thermo, equilibrium, kinetics, electro_solutions]

# ── Topics ──────────────────────────────────────────────────────────────────
# A step's topic is its concept-book chapter, except that nuclear entries are split off
# from chemical kinetics (they share a chapter but not a story). Chains cross topics only
# along BRIDGES: pairs where the quantity passed on means the same thing on both sides.

_CB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..",
                   "knowledge", "concept_book_physical.json")
with open(_CB, encoding="utf-8") as _f:
    _CHAPTER = {i: t.get("chapter", "") for i, t in enumerate(
        json.load(_f)["structural_operators"]["add_reaction_step"]["valid_transformations"])}

NUCLEAR = "Nuclear Chemistry"
_NUCLEAR_TX = {219, 220, 221, 222, 224, 225, 226, 227, 228, 229, 230, 232, 332, 333}
_ANY_TOPIC = {218}     # half-life <-> decay constant serves both kinetics and nuclear chains


def _domain(tx):
    if tx in _ANY_TOPIC:
        return None
    if tx in _NUCLEAR_TX:
        return NUCLEAR
    return _CHAPTER.get(tx) or None


BRIDGES = {frozenset(p) for p in [
    ("Stoichiometry", "Gaseous State"), ("Stoichiometry", "Dilute Solutions"),
    ("Stoichiometry", "Ionic Equilibrium"), ("Stoichiometry", "Electrochemistry"),
    ("Stoichiometry", "Chemical Equilibrium"), ("Stoichiometry", "Solid State"),
    ("Gaseous State", "Thermodynamics"), ("Gaseous State", "Chemical Equilibrium"),
    ("Gaseous State", "Surface Chemistry"), ("Gaseous State", "Dilute Solutions"),
    ("Thermodynamics", "Thermochemistry"), ("Thermodynamics", "Chemical Equilibrium"),
    ("Thermodynamics", "Electrochemistry"), ("Thermochemistry", "Chemical Equilibrium"),
    ("Thermochemistry", "Chemical Kinetics & Nuclear Chemistry"),
    ("Chemical Equilibrium", "Ionic Equilibrium"),
    ("Chemical Equilibrium", "Chemical Kinetics & Nuclear Chemistry"),
    ("Ionic Equilibrium", "Electrochemistry"), ("Ionic Equilibrium", "Dilute Solutions"),
    ("Electrochemistry", "Dilute Solutions"),
]}

STEPS: dict = {}
for _m in _MODULES:
    for _s in _m.STEPS:
        if _s.tx in STEPS:
            raise RuntimeError(f"tx {_s.tx} defined twice")
        STEPS[_s.tx] = dataclasses.replace(_s, domain=_domain(_s.tx))

# Graph nodes introduced by the engine (not in the original quantity list).
NEW_NODE_NAMES = {
    "isotopic_abundances": "isotopic masses and abundances",
    "density":             "density / specific gravity",
    "chemical_species":    "chemical species (formula and charge)",
    "redox_skeleton":      "skeleton redox equation",
    "redox_reagent":       "redox reagent and medium",
    "nuclide":             "nuclide (Z, A, charge)",
    "particle_count":      "number of protons / neutrons / electrons",
    "mass_number":         "mass number",
    "nuclear_radius":      "nuclear radius",
    "alpha_kinetic_energy": "kinetic energy of an α-particle",
    "closest_approach":    "distance of closest approach",
    "spectral_line":       "spectral series and line",
    "excited_sample":      "excited atoms (levels involved)",
    "spectral_line_count": "number of spectral lines",
    "quantum_numbers":     "set of quantum numbers",
    "orbital_label":       "orbital (n, l)",
    "node_count":          "number of nodes",
    "orbital_angular_momentum": "orbital angular momentum",
    "radial_peaks":        "peaks in the radial distribution curve",
    "shell":               "electron shell",
    "electron_capacity":   "electron / orbital capacity",
    "nuclide_pair":        "pair of nuclides",
    "nuclide_relation":    "isotope / isobar / isotone relation",
    "work_function":       "work function",
    "liquid_column":       "liquid column (barometer / manometer)",
    "pressure":            "pressure",
    "relative_humidity":   "relative humidity",
    "virial_coefficient":  "second virial coefficient",
    "reduced_state":       "reduced variables",
    "inversion_temperature": "Joule-Thomson inversion temperature",
    "gas_mixture":         "mixture of ideal gases",
    "formation_gibbs_data": "standard Gibbs energies of formation",
    "vant_hoff_plot":      "ln K (or log K) vs 1/T plot",
    "water_ionization":    "ionisation of water",
    "indicator_ratio":     "indicator [In⁻]/[HIn] ratio",
    "half_life_plot":      "log t½ vs log a₀ plot",
    "distillate_mass_ratio": "mass ratio in steam distillate",
    "close_packing":       "close-packed arrangement",
    "void_count":          "number of voids",
    "void_type":           "void geometry",
    "ionic_formula":       "formula from void occupancy",
    "xray_diffraction":    "X-ray diffraction data",
    "interplanar_spacing": "interplanar spacing",
    "electrolyte_addition": "electrolyte added to a sol",
    "coagulation_value":   "coagulation value",
    "protective_colloid":  "protective colloid",
    "gold_number":         "gold number",
    "secular_ratio":       "daughter : parent ratio at secular equilibrium",
    "rate_factor":         "factor by which the rate increases",
    "gamma":               "ratio of heat capacities γ",
    "entropy_change":      "entropy change of a system (J K⁻¹)",
    "vapour_pressure_lowering": "lowering of vapour pressure",
    "delta_T":             "elevation of boiling point / depression of freezing point",
    "osmotic_pressure":    "osmotic pressure",
    "relative_lowering":   "relative lowering of vapour pressure",
    "ostwald_walker":      "Ostwald-Walker measurement",
    "equilibrium_reaction": "equilibrium reaction (states, ΔH)",
}


def step(tx: int) -> Step:
    try:
        return STEPS[tx]
    except KeyError:
        raise EngineError(f"no physical engine step for concept-book entry {tx}") from None


def edge_nodes(tx: int):
    """(src, dst) graph nodes of an entry, or None if the engine does not compute it."""
    s = STEPS.get(tx)
    return (s.src, s.dst) if s else None


def edge_steps(edge: dict) -> list:
    """The engine steps behind one graph edge (one per concept-book entry)."""
    return [STEPS[t] for t in edge.get("tx_ids", []) if t in STEPS]


def can_follow(edge_a: dict, edge_b: dict) -> bool:
    """True if some step of edge_b can use the output of some step of edge_a."""
    return any(links(a, b, BRIDGES) for a in edge_steps(edge_a) for b in edge_steps(edge_b))


def chain_steps(edges: list, rng=None):
    """One engine step per edge such that the chain links up, or None."""
    return assign_steps([edge_steps(e) for e in edges], rng, BRIDGES)
