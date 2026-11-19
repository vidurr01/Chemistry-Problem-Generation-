"""Physical engine — formulas added on 2026-11-15 so that every formula the real JEE Advanced
physical questions of 2012-2025 use exists in the engine (docs/advanced_formula_map.py lists
which question needs which step). Concept-book TXs 348-392; each step names the question it
was added for, and tests/test_engine_advanced.py reproduces that question's answer. Tx 392
(w = −Δn_gRT, 2025 Q11) was added after the first 44.

Grouped by chapter; a step's topic (and so which chains it may join) is the chapter of its
concept-book entry, as for every other physical step.
"""

from __future__ import annotations

import math
import re

from core.engine.base import Derive, EngineError, Param, Step, Trap, ln, log10, sqrt
from core.engine.chem import C, check_balanced, const, parse_equation, species_key
from core.engine.physical.thermo import _CV, _cv_constants, _hess, _hess_trap

P = Param


def _pos(x, what="value"):
    if not x > 0:
        raise EngineError(f"{what} must be positive, got {x:g}")
    return x


def _marked_gases(eq_text):
    """Species written with (g) in the equation, without coefficients or the state mark."""
    gases = set()
    for term in re.split(r"->|=|\+", eq_text):
        t = term.strip()
        if t.endswith("(g)"):
            gases.add(re.sub(r"^[\d./\s]+", "", t[:-3]).strip())
    if not gases:
        raise EngineError("mark the gaseous species with (g)")
    return gases


def _gas_work(v, all_species=False):
    """w = −Δn_g RT (J) for the reaction run on moles_known of known_species."""
    eq = v["balanced_equation"]
    check_balanced(eq)
    r, p = parse_equation(eq)
    gases = {f for _, f in r + p} if all_species else _marked_gases(eq)
    nu = {f: c for c, f in r + p}
    if species_key(v["known_species"]) not in {species_key(f) for f in nu}:
        raise EngineError(f"{v['known_species']} is not in the equation")
    dn = sum(c for c, f in p if f in gases) - sum(c for c, f in r if f in gases)
    if dn == 0:
        raise EngineError("no change in the moles of gas")
    return -dn * v["moles_known"] / nu[v["known_species"]] * C.R_J * v["T"]


def _nz(x):
    if x == 0:
        raise EngineError("division by zero")
    return x


def _aliquot_factor(v):
    if v["aliquot_volume"] > v["total_volume"]:
        raise EngineError("the aliquot cannot be larger than the whole solution")
    return v["total_volume"] / v["aliquot_volume"]


# ── Dilute Solutions ─────────────────────────────────────────────────────────

def _x_from_m(v, dilute=False):
    nm = v["molality"] * v["solvent_molar_mass"] / 1000          # mol solute per mol solvent
    return nm if dilute else nm / (1 + nm)


def _molality_from_dt(v, use_i=True):
    return v["delta_T"] / (v["constant"] * (v["vant_hoff_factor"] if use_i else 1))


# ── Ionic Equilibrium ────────────────────────────────────────────────────────

def _ka_from_ph(v, approx=False):
    h, c = 10 ** -v["ph"], v["concentration"]
    if h >= c:
        raise EngineError("[H⁺] must be below the acid's concentration")
    return h * h / (c if approx else c - h)


def _salt_solubility_at_ph(v, protonation=True):
    h = 10 ** -v["ph"]
    return sqrt(v["solubility_product"] * ((1 + h / v["Ka"]) if protonation else 1))


def _residual(v, dilute=True):
    vt = v["volume_1"] + v["volume_2"]
    c1 = v["cation_concentration"] * (v["volume_1"] / vt if dilute else 1)
    c2 = v["anion_concentration"] * (v["volume_2"] / vt if dilute else 1)
    if math.isclose(c1, c2, rel_tol=1e-6):
        raise EngineError("equal amounts: neither ion is in excess")
    return v["solubility_product"] / abs(c1 - c2)


def _min_h_for_sulfide(v, root=True):
    x = v["h2s_constant"] * v["h2s_concentration"] * v["cation_concentration"] / v["solubility_product"]
    return sqrt(x) if root else x


def _buffer_after_base(v, react=True):
    """H₂A, HA⁻, A²⁻ and a strong base mixed: the base turns H₂A into HA⁻, then HA⁻ into A²⁻.
    The pair left decides the buffer: (HA⁻/H₂A, K₁) or (A²⁻/HA⁻, K₂)."""
    a0, a1, a2, b = (v["diprotic_acid_moles"], v["monoanion_moles"], v["dianion_moles"],
                     v["strong_base_moles"] if react else 0.0)
    step = min(a0, b)
    a0, a1, b = a0 - step, a1 + step, b - step
    step = min(a1, b)
    a1, a2, b = a1 - step, a2 + step, b - step
    if b > 1e-12:
        raise EngineError("the strong base exceeds the acid: not a buffer")
    if a0 > 1e-12 and a1 > 1e-12:
        return {"buffer_ratio": a1 / a0, "dissociation_constant": v["Ka1"]}
    if a1 > 1e-12 and a2 > 1e-12:
        return {"buffer_ratio": a2 / a1, "dissociation_constant": v["Ka2"]}
    raise EngineError("only one form of the acid is left: not a buffer")


def _sulfate_solubility(v, mode="exact"):
    """PbSO₄-type salt in H₂SO₄ (c_a) + Na₂SO₄ (c_s): HSO₄⁻ ⇌ H⁺ + SO₄²⁻ (K_a2) sets the free
    sulfate, then S = K_sp/[SO₄²⁻] (the salt adds a negligible amount)."""
    ca, cs, k2 = v["acid_concentration"], v["sulfate_concentration"], v["Ka2"]
    if mode == "ignore_bisulfate":
        so4 = cs
    elif mode == "full_dissociation":
        so4 = cs + ca
    else:
        b, c = ca + cs + k2, ca * cs - k2 * ca             # a² + b a + c = 0, a = SO₄²⁻ formed
        a = (-b + sqrt(b * b - 4 * c)) / 2
        so4 = cs + a
        if so4 <= 0 or ca - a <= 0:
            raise EngineError("no physical sulfate equilibrium for these values")
    return v["solubility_product"] / so4


# ── Chemical Equilibrium ─────────────────────────────────────────────────────

def _ice_extent(v, use_coef=True):
    """Equilibrium amounts from the initial amounts and one species' equilibrium amount."""
    r, p = parse_equation(v["balanced_equation"])
    nu = {}
    for sign, side in ((-1, r), (1, p)):
        for c, f in side:
            nu[species_key(f)] = nu.get(species_key(f), 0) + sign * (c if use_coef else 1)
    init = {species_key(k): float(x) for k, x in v["initial_amounts"].items()}
    known = species_key(v["known_species"])
    if known not in nu:
        raise EngineError(f"{known} is not in the equation")
    xi = (v["known_equilibrium_amount"] - init.get(known, 0.0)) / nu[known]
    amounts = {s: init.get(s, 0.0) + n * xi for s, n in nu.items()}
    if any(a <= 0 for a in amounts.values()):
        raise EngineError("an equilibrium amount comes out zero or negative")
    asked = species_key(v["species_asked"])
    if asked not in amounts:
        raise EngineError(f"{asked} is not in the equation")
    return {"equilibrium_moles": amounts[asked], "eq_amounts": amounts,
            "balanced_equation": v["balanced_equation"]}


# ── Kinetics ─────────────────────────────────────────────────────────────────

def _order_from_ratio(r):
    """t₇₅/t₅₀ = 2^(n−1) + 1 for any order n (zero order 1.5, first order 2, second order 3)."""
    if not r > 1:
        raise EngineError("t₇₅ must be longer than t₅₀")
    return 1 + math.log2(r - 1)


def _rate_from_orders(v, use_orders=True):
    orders = v["orders"]
    ref, new = v["reference_concentrations"], v["new_concentrations"]
    if set(orders) != set(ref) or set(orders) != set(new):
        raise EngineError("give an order and both concentrations for every reactant")
    rate = v["reaction_rate"]
    for s, n in orders.items():
        rate *= (_pos(float(new[s]), "concentration") / _pos(float(ref[s]), "concentration")) ** \
            (float(n) if use_orders else 1.0)
    return rate


def _mechanism_order(v, substitute=True):
    """Overall order of a slow step whose intermediate comes from a fast pre-equilibrium."""
    fr, fp = parse_equation(v["fast_equilibrium"])
    sr, _ = parse_equation(v["slow_step"])
    if len(fp) != 1:
        raise EngineError("the fast equilibrium must form one intermediate")
    nu_i, inter = fp[0]
    order = 0.0
    for c, f in sr:
        if f == inter and substitute:
            order += sum(cc for cc, _ in fr) * c / nu_i
        else:
            order += c
    if substitute and not any(f == inter for _, f in sr):
        raise EngineError("the slow step must use the intermediate")
    return order


# ── Electrochemistry ─────────────────────────────────────────────────────────

def _combined_potential(v, weighted=True):
    couples = v["couples"]
    if not isinstance(couples, (list, tuple)) or len(couples) < 2:
        raise EngineError("give at least two couples [electrons, E°]")
    pairs = [(float(n), float(e)) for n, e in couples]
    n_total = sum(n for n, _ in pairs)
    if not math.isclose(n_total, v["electrons"]):
        raise EngineError(f"the couples transfer {n_total:g} electrons, not {v['electrons']}")
    if not weighted:
        return sum(e for _, e in pairs) / len(pairs)
    return sum(n * e for n, e in pairs) / v["electrons"]


# ── Thermochemistry ──────────────────────────────────────────────────────────

def _formation_by_hess(v, use_coef=True):
    """ΔrH = Σν ΔfH(products) − Σν ΔfH(reactants), solved for the one species not given."""
    r, p = parse_equation(v["balanced_equation"])
    known = {species_key(k): float(x) for k, x in v["formation_enthalpies"].items()}
    unknown = species_key(v["unknown_species"])
    total, coef_u = v["delta_h"], None
    for sign, side in ((1, p), (-1, r)):
        for c, f in side:
            key, c = species_key(f), (c if use_coef else 1)
            if key == unknown:
                coef_u = sign * c
            elif key in known:
                total -= sign * c * known[key]
            else:
                raise EngineError(f"no ΔfH given for {f}")
    if coef_u is None:
        raise EngineError(f"{unknown} is not in the equation")
    return total / coef_u


STEPS = [
    # ── Dilute Solutions ──
    Step(tx=348, src="molality", dst="mole_fraction", keeps_role=True, not_after=(21,),
         carries=("solvent_mass", "density", "solute_molar_mass"),         # the same solution
         needs=(P("molality", "mol kg⁻¹", "molality of the solution", lo=0.01, hi=5),
                P("solvent_molar_mass", "g mol⁻¹", "molar mass of the solvent", lo=18, hi=150)),
         answer="mole_fraction", unit="", kind="open_fraction", roles={"mole_fraction": "solute"},
         gives=("solvent_molar_mass",),
         fn=lambda v: {"mole_fraction": _x_from_m(v), "solvent_molar_mass": v["solvent_molar_mass"]},
         traps=(Trap("dilute_ratio", "takes n₂/n₁ as the mole fraction", lambda v: _x_from_m(v, dilute=True)),),
         formula="X₂ = mM₁/(1000 + mM₁)", asks="mole fraction of the solute"),
    # 2012 P2 Q28: ΔT_b given -> molality -> mole fraction -> lowering of vapour pressure
    Step(tx=349, src="delta_T", dst="molality", not_after=(262, 263),
         needs=(P("delta_T", "K", "observed elevation of boiling point or depression of freezing point", lo=0.05, hi=20),
                P("constant", "K kg mol⁻¹", "K_b or K_f of the solvent", lo=0.5, hi=40),
                P("vant_hoff_factor", "", "van 't Hoff factor i (1 for a non-electrolyte)", lo=0.5, hi=4)),
         answer="molality", unit="mol kg⁻¹", kind="positive", gives=("vant_hoff_factor",),
         fn=lambda v: {"molality": _molality_from_dt(v), "vant_hoff_factor": v["vant_hoff_factor"]},
         traps=(Trap("forgets_i", "ignores the van 't Hoff factor", lambda v: _molality_from_dt(v, use_i=False)),),
         formula="m = ΔT/(iK)", asks="molality of the solution (mol kg⁻¹)"),
    # 2017 P1 Q36: moles of ethanol -> molality -> ΔT_f
    Step(tx=362, src="moles", dst="molality", keeps_role=True,
         carries=("solvent_molar_mass", "density", "solute_molar_mass"),
         needs=(P("moles", "mol", "amount of solute", lo=0.01, hi=5, role="solute"),
                P("solvent_mass", "g", "mass of the solvent", lo=10, hi=2000)),
         answer="molality", unit="mol kg⁻¹", kind="positive", gives=("solvent_mass",),
         fn=lambda v: {"molality": 1000 * v["moles"] / v["solvent_mass"], "solvent_mass": v["solvent_mass"]},
         traps=(Trap("grams_as_kg", "divides by the solvent mass in grams", lambda v: v["moles"] / v["solvent_mass"]),),
         formula="m = n_solute / (w_solvent in kg)", asks="molality (mol kg⁻¹)"),
    # 2019 P1 Q14: molar mass from the vapour-pressure lowering -> molality -> ΔT_f
    Step(tx=370, src="molar_mass", dst="molality", not_after=(264,), carries=("solvent_molar_mass",),
         needs=(P("molar_mass", "g mol⁻¹", "molar mass of the solute", lo=10, hi=1000, role="solute"),
                P("solute_mass", "g", "mass of solute", lo=0.1, hi=100),
                P("solvent_mass", "g", "mass of solvent", lo=10, hi=2000)),
         answer="molality", unit="mol kg⁻¹", kind="positive", gives=("solvent_mass",),
         fn=lambda v: {"molality": 1000 * v["solute_mass"] / (v["molar_mass"] * v["solvent_mass"]),
                       "solvent_mass": v["solvent_mass"]},
         traps=(Trap("grams_as_kg", "divides by the solvent mass in grams",
                     lambda v: v["solute_mass"] / (v["molar_mass"] * v["solvent_mass"])),),
         formula="m = (w₂/M₂)/(w₁/1000)", asks="molality (mol kg⁻¹)"),

    # ── Stoichiometry ──
    # 2016 P1 Q32: molarity of a solution from its mole fraction and density
    Step(tx=358, src="mole_fraction", dst="molarity", keeps_role=True,
         needs=(P("mole_fraction", "", "mole fraction of the solute", kind="open_fraction", lo=0.01, hi=0.5, role="solute"),
                P("density", "g mL⁻¹", "density of the solution", lo=0.7, hi=2.5),
                P("solute_molar_mass", "g mol⁻¹", "molar mass of the solute", lo=10, hi=400),
                P("solvent_molar_mass", "g mol⁻¹", "molar mass of the solvent", lo=18, hi=150)),
         answer="molarity", unit="mol L⁻¹", kind="positive", gives=("solute_molar_mass", "density", "solvent_molar_mass"),
         fn=lambda v: {"molarity": 1000 * v["density"] * v["mole_fraction"]
                       / (v["mole_fraction"] * v["solute_molar_mass"] + (1 - v["mole_fraction"]) * v["solvent_molar_mass"]),
                       "solute_molar_mass": v["solute_molar_mass"], "density": v["density"],
                       "solvent_molar_mass": v["solvent_molar_mass"]},
         traps=(Trap("forgets_density", "takes the density as 1 g mL⁻¹",
                     lambda v: 1000 * v["mole_fraction"] / (v["mole_fraction"] * v["solute_molar_mass"]
                                                            + (1 - v["mole_fraction"]) * v["solvent_molar_mass"])),),
         formula="M = 1000 d X₂ / (X₂M₂ + X₁M₁)", asks="molarity (mol L⁻¹)"),
    # 2019 P2 Q10: moles of urea from its mole fraction in 900 g water -> molarity
    Step(tx=373, src="mole_fraction", dst="moles", carries=("density", "solute_molar_mass"),
         needs=(P("mole_fraction", "", "mole fraction of the solute", kind="open_fraction", lo=0.01, hi=0.5, role="solute"),
                P("solvent_mass", "g", "mass of the solvent", lo=10, hi=5000),
                P("solvent_molar_mass", "g mol⁻¹", "molar mass of the solvent", lo=18, hi=150)),
         answer="moles", unit="mol", kind="positive", roles={"moles": "solute"},
         gives=("solvent_mass", "solvent_molar_mass"),
         fn=lambda v: {"moles": v["mole_fraction"] / (1 - v["mole_fraction"]) * v["solvent_mass"] / v["solvent_molar_mass"],
                       "solvent_mass": v["solvent_mass"], "solvent_molar_mass": v["solvent_molar_mass"]},
         traps=(Trap("fraction_of_solvent", "multiplies the mole fraction by the moles of solvent",
                     lambda v: v["mole_fraction"] * v["solvent_mass"] / v["solvent_molar_mass"]),),
         formula="n₂ = X₂/(1 − X₂) × w₁/M₁", asks="amount of solute (mol)"),
    Step(tx=374, src="moles", dst="molarity", keeps_role=True, carries=("solvent_molar_mass",),
         needs=(P("moles", "mol", "amount of solute", lo=0.01, hi=10, role="solute"),
                P("solute_molar_mass", "g mol⁻¹", "molar mass of the solute", lo=10, hi=400),
                P("solvent_mass", "g", "mass of the solvent", lo=10, hi=5000),
                P("density", "g mL⁻¹", "density of the solution", lo=0.7, hi=2.5)),
         answer="molarity", unit="mol L⁻¹", kind="positive", gives=("density", "solute_molar_mass"),
         fn=lambda v: {"molarity": 1000 * v["moles"] * v["density"]
                       / (v["moles"] * v["solute_molar_mass"] + v["solvent_mass"]),
                       "density": v["density"], "solute_molar_mass": v["solute_molar_mass"]},
         traps=(Trap("solvent_volume", "takes the volume from the solvent mass alone",
                     lambda v: 1000 * v["moles"] * v["density"] / v["solvent_mass"]),),
         formula="V = (n₂M₂ + w₁)/d; M = n₂/V(L)", asks="molarity (mol L⁻¹)"),
    # 2021 P2 Q11: equivalents of KMnO₄ for an aliquot -> moles of Fe²⁺ in the whole solution
    Step(tx=379, src="equivalents", dst="moles",
         needs=(P("equivalents", "eq", "equivalents of titrant used for the aliquot", lo=1e-5, hi=0.5),
                P("n_factor", "", "n-factor of the species titrated", lo=1, hi=8),
                P("total_volume", "mL", "volume of the whole solution", lo=50, hi=1000),
                P("aliquot_volume", "mL", "volume of the aliquot titrated", lo=5, hi=50)),
         answer="moles", unit="mol", kind="positive", roles={"moles": "titrated species"},
         fn=lambda v: {"moles": v["equivalents"] / v["n_factor"] * _aliquot_factor(v)},
         traps=(Trap("forgets_aliquot", "counts only the aliquot", lambda v: v["equivalents"] / v["n_factor"]),
                Trap("forgets_n_factor", "takes equivalents as moles",
                     lambda v: v["equivalents"] * v["total_volume"] / v["aliquot_volume"])),
         formula="n = eq/n-factor × V(total)/V(aliquot)", asks="amount of the species in the whole solution (mol)"),

    # ── Gaseous State ──
    # 2014 P2 Q31: where the two vapours meet in a tube
    Step(tx=355, src="effusion_rate", dst="meeting_distance",
         needs=(P("effusion_rate", "", "ratio of the rates of gas 1 to gas 2", lo=0.25, hi=4),
                P("tube_length", "cm", "length of the tube", lo=10, hi=200)),
         answer="meeting_distance", unit="cm", kind="positive",
         fn=lambda v: {"meeting_distance": v["tube_length"] * v["effusion_rate"] / (1 + v["effusion_rate"])},
         traps=(Trap("inverted_ratio", "measures from the wrong end (uses r₂/r₁)",
                     lambda v: v["tube_length"] / (1 + v["effusion_rate"])),),
         formula="d/(L − d) = r₁/r₂", asks="distance from gas 1's end where the gases meet (cm)"),
    # 2016 P1 Q33: mean free path and diffusion coefficient
    Step(tx=359, src="gas_state", dst="mean_free_path",
         needs=(P("T", "K", "temperature", kind="temperature", lo=100, hi=1500),
                P("P", "atm", "pressure", lo=0.01, hi=10),
                P("molecular_diameter", "pm", "collision diameter of a molecule", lo=100, hi=600)),
         answer="mean_free_path", unit="nm", kind="positive", gives=("T",),
         fn=lambda v: {"mean_free_path": C.K_B * v["T"] / (math.sqrt(2) * math.pi * (v["molecular_diameter"] * 1e-12) ** 2
                                                         * v["P"] * 101325) * 1e9, "T": v["T"]},
         traps=(Trap("forgets_root2", "drops the √2", lambda v: C.K_B * v["T"] / (math.pi * (v["molecular_diameter"] * 1e-12) ** 2
                                                                                 * v["P"] * 101325) * 1e9),),
         constants=(const("K_B"), "1 atm = 101325 Pa"), formula="λ = kT/(√2 π d² P)",
         asks="mean free path (nm)"),
    Step(tx=360, src="mean_free_path", dst="diffusion_coefficient",
         needs=(P("mean_free_path", "nm", "mean free path", lo=1, hi=1e4),
                P("T", "K", "temperature", kind="temperature", lo=100, hi=1500),
                P("molar_mass", "g mol⁻¹", "molar mass of the gas", lo=2, hi=200)),
         answer="diffusion_coefficient", unit="m² s⁻¹", kind="positive",
         fn=lambda v: {"diffusion_coefficient": v["mean_free_path"] * 1e-9
                       * sqrt(8 * C.R_J * v["T"] / (math.pi * v["molar_mass"] / 1000)) / 3},
         traps=(Trap("rms_speed", "uses the rms speed", lambda v: v["mean_free_path"] * 1e-9
                     * sqrt(3 * C.R_J * v["T"] / (v["molar_mass"] / 1000)) / 3),),
         constants=(const("R_J"),), formula="D = ⅓ λ ū, ū = √(8RT/πM)", asks="diffusion coefficient (m² s⁻¹)"),
    # 2023 P1 Q9: pressure from the compressibility factor
    Step(tx=386, src="compressibility_factor", dst="gas_state", not_after=(104,),
         needs=(P("compressibility_factor", "", "compressibility factor Z", lo=0.2, hi=2),
                P("molar_volume", "L mol⁻¹", "molar volume of the gas", lo=0.05, hi=50),
                P("T", "K", "temperature", kind="temperature", lo=150, hi=1500)),
         answer="P", unit="atm", kind="positive", gives=("T",),
         fn=lambda v: {"P": v["compressibility_factor"] * C.R_LATM * v["T"] / v["molar_volume"], "T": v["T"]},
         traps=(Trap("ideal_gas", "ignores Z (takes the gas as ideal)", lambda v: C.R_LATM * v["T"] / v["molar_volume"]),),
         constants=(const("R_LATM"),), formula="Z = PV_m/RT", asks="pressure of the gas (atm)"),

    # ── Atomic Structure ──
    # 2012 P1 Q22: kinetic energy from the quantised angular momentum and the orbit radius
    Step(tx=350, src="orbit_radius", dst="electron_kinetic_energy",
         needs=(P("orbit_radius", "Å", "radius of the orbit", lo=0.1, hi=30),
                P("n", "", "principal quantum number of the orbit", kind="posint", lo=1, hi=7)),
         answer="orbit_kinetic_energy", unit="eV", kind="positive",
         fn=lambda v: {"orbit_kinetic_energy": (v["n"] * C.H) ** 2 / (8 * math.pi ** 2 * C.M_E
                                                                     * (v["orbit_radius"] * 1e-10) ** 2) / C.E_CHARGE},
         traps=(Trap("forgets_n", "uses mvr = h/2π for every orbit",
                     lambda v: C.H ** 2 / (8 * math.pi ** 2 * C.M_E * (v["orbit_radius"] * 1e-10) ** 2) / C.E_CHARGE),),
         constants=(const("H"), const("M_E"), const("E_CHARGE")),
         formula="mvr = nh/2π → KE = ½mv² = n²h²/(8π²mr²)", asks="kinetic energy of the electron (eV)"),
    # 2020 P2 Q15: electrostatic potential energy of the H atoms, per mole
    Step(tx=376, src="orbit_radius", dst="potential_energy",
         needs=(P("orbit_radius", "Å", "distance between the electron and the nucleus", lo=0.1, hi=30),
                P("Z", "", "atomic number of the one-electron species", kind="posint", lo=1, hi=4),
                P("atoms", "", "number of such atoms counted (per molecule)", kind="posint", lo=1, hi=4)),
         answer="potential_energy", unit="kJ mol⁻¹", kind="negative",
         fn=lambda v: {"potential_energy": -C.K_COULOMB * v["Z"] * C.E_CHARGE ** 2 / (v["orbit_radius"] * 1e-10)
                       * v["atoms"] * C.NA / 1000},
         traps=(Trap("one_atom", "counts one atom only",
                     lambda v: -C.K_COULOMB * v["Z"] * C.E_CHARGE ** 2 / (v["orbit_radius"] * 1e-10) * C.NA / 1000),),
         constants=(const("K_COULOMB"), const("E_CHARGE"), const("NA")),
         formula="PE = −k Ze²/r per atom; × atoms × N_A", asks="potential energy (kJ mol⁻¹)"),
    # 2021 P2 Q18: recoil of an atom that absorbs (or emits) a photon
    Step(tx=380, src="wavelength", dst="recoil_velocity",
         needs=(P("wavelength", "nm", "wavelength of the photon", lo=50, hi=2000),
                P("molar_mass", "g mol⁻¹", "molar mass of the atom", lo=1, hi=300)),
         answer="recoil_velocity", unit="m s⁻¹", kind="positive",
         fn=lambda v: {"recoil_velocity": C.H / (v["wavelength"] * 1e-9) / (v["molar_mass"] / 1000 / C.NA)},
         traps=(Trap("grams_as_kg", "uses the atom's mass in grams",
                     lambda v: C.H / (v["wavelength"] * 1e-9) / (v["molar_mass"] / C.NA)),),
         constants=(const("H"), const("NA")), formula="p = h/λ; Δv = p/m, m = M/N_A",
         asks="change in the velocity of the atom (m s⁻¹)"),

    # ── Thermodynamics ──
    # 2016 P1 Q20: isothermal ideal gas, ΔU = 0
    Step(tx=357, src="work", dst="heat", not_after=(119, 392), carries=("T",),
         needs=(P("work", "J", "work done on the gas in the isothermal process", kind="real", lo=-50000, hi=50000),),
         answer="heat", unit="J", kind="real", roles={"heat": "isothermal gas"},
         fn=lambda v: {"heat": -v["work"]},
         traps=(Trap("sign", "takes q = w", lambda v: v["work"]),),
         formula="isothermal ideal gas: ΔU = 0, so q = −w", asks="heat absorbed by the gas (J)"),
    # 2025 Q11: gas formed at constant pressure does expansion work
    Step(tx=392, src="balanced_equation", dst="work", not_after=(32,),
         needs=(P("balanced_equation", "", "the reaction with states, e.g. '2H2O(l) -> 2H2(g) + O2(g)'", kind="text"),
                P("known_species", "", "species whose amount is known", kind="text"),
                P("moles_known", "mol", "amount of that species that reacts", lo=0.1, hi=20),
                P("T", "K", "temperature", kind="temperature", lo=250, hi=1000)),
         answer="work", unit="J", kind="real", fn=lambda v: {"work": _gas_work(v)},
         traps=(Trap("counts_liquids", "counts every species, not just the gases, in Δn",
                     lambda v: _gas_work(v, all_species=True)),
                Trap("sign", "takes w = +Δn_gRT", lambda v: -_gas_work(v))),
         constants=(const("R_J"),), formula="w = −P_extΔV = −Δn_gRT",
         asks="work done on the system by the surroundings (J)"),
    # 2015 P1 Q28: the energy of one reaction drives another
    # follows the ΔG of a driven half-reaction (tx 138), not a whole reaction's ΔG
    Step(tx=356, src="delta_g", dst="moles", not_after=(132, 134, 363, 366, 369),
         needs=(P("delta_g", "kJ mol⁻¹", "Gibbs energy needed per mole of the driven process", kind="positive",
                  lo=1, hi=1000, role="standard"),
                P("driving_delta_g", "kJ mol⁻¹", "Gibbs energy change of the driving reaction (per mole)",
                  kind="negative", lo=-2000, hi=-1)),
         answer="moles", unit="mol", kind="positive", roles={"moles": "reactant"},
         fn=lambda v: {"moles": -v["driving_delta_g"] / v["delta_g"]},
         traps=(Trap("inverted", "divides the other way round", lambda v: v["delta_g"] / -v["driving_delta_g"]),),
         formula="moles driven = |ΔG(driving)| / ΔG(driven per mole)",
         asks="moles of the driven process per mole of the driving reaction"),
    # 2017 P2 Q20: pressure at which graphite and diamond are in equilibrium
    Step(tx=364, src="delta_g", dst="pressure",
         needs=(P("delta_g", "kJ mol⁻¹", "standard Gibbs energy of the phase change (at 1 bar)", kind="real",
                  lo=-50, hi=50, role="standard"),
                P("molar_volume_change", "m³ mol⁻¹", "change in molar volume on the phase change (V₂ − V₁)",
                  kind="real", lo=-1e-4, hi=1e-4)),
         answer="equilibrium_pressure", unit="bar", kind="positive",
         fn=lambda v: {"equilibrium_pressure": 1 + 1000 * v["delta_g"] / -_nz(v["molar_volume_change"]) / 1e5},
         traps=(Trap("forgets_1_bar", "forgets that the change starts from 1 bar",
                     lambda v: 1000 * v["delta_g"] / -_nz(v["molar_volume_change"]) / 1e5),),
         formula="ΔG(P) = ΔG° + ΔV(P − 1 bar) = 0", asks="pressure at which the two phases are in equilibrium (bar)"),
    # 2018 P2 Q10: ΔG° of a reaction from other reactions (Hess's law on ΔG)
    Step(tx=366, src="formation_gibbs_data", dst="delta_g",
         needs=(P("target_equation", "", "equation whose ΔG° is asked", kind="text"),
                P("step_equations", "", "list of [equation, ΔG° in kJ mol⁻¹] pairs", kind="list")),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "standard"},
         fn=lambda v: {"delta_g": _hess(v)["delta_h"]},
         traps=(Trap("adds_as_given", "adds the ΔG° values without reversing/scaling the equations", _hess_trap),),
         formula="Hess: combine the equations; ΔG° combines the same way", asks="standard Gibbs energy of the target reaction (kJ mol⁻¹)"),
    # 2020 P1 Q15: fuel-cell work compresses a gas adiabatically
    Step(tx=375, src="work", dst="temperature", not_after=(392,),
         needs=(P("useful_work", "kJ", "useful work available", lo=0.001, hi=100),
                P("efficiency", "", "fraction of the work used", kind="open_fraction", lo=0.1, hi=0.99),
                P("n", "mol", "amount of ideal gas compressed adiabatically", lo=0.1, hi=10),
                P("gas_type", "", "type of gas", kind="choice", choices=tuple(_CV))),
         answer="temperature_change", unit="K", kind="positive",
         fn=lambda v: {"temperature_change": v["efficiency"] * v["useful_work"] * 1000 / (v["n"] * _CV[v["gas_type"]] * C.R_J),
                       "_constants": _cv_constants(v["gas_type"])},
         traps=(Trap("uses_cp", "uses C_p instead of C_v",
                     lambda v: v["efficiency"] * v["useful_work"] * 1000 / (v["n"] * (_CV[v["gas_type"]] + 1) * C.R_J)),
                Trap("forgets_efficiency", "uses all the work",
                     lambda v: v["useful_work"] * 1000 / (v["n"] * _CV[v["gas_type"]] * C.R_J))),
         constants=(const("R_J"),), formula="adiabatic: w = ΔU = nC_vΔT", asks="rise in the temperature of the gas (K)"),
    # 2023 P2 Q14: entropy difference at another temperature
    Step(tx=388, src="delta_s", dst="delta_s", not_after=(114,),
         needs=(P("delta_s", "J K⁻¹ mol⁻¹", "entropy change at T₁", kind="real", lo=-300, hi=300),
                P("delta_cp", "J K⁻¹ mol⁻¹", "ΔC_p (taken as constant)", kind="real", lo=-100, hi=100),
                P("T1", "K", "temperature T₁", kind="temperature", lo=200, hi=1500),
                P("T2", "K", "temperature T₂", kind="temperature", lo=200, hi=1500)),
         answer="delta_s", unit="J K⁻¹ mol⁻¹", kind="real",
         fn=lambda v: {"delta_s": v["delta_s"] + v["delta_cp"] * ln(v["T2"] / v["T1"])},
         traps=(Trap("linear_in_T", "uses ΔC_p(T₂ − T₁)", lambda v: v["delta_s"] + v["delta_cp"] * (v["T2"] - v["T1"])),),
         formula="ΔS(T₂) = ΔS(T₁) + ∫ΔC_p/T dT = ΔS(T₁) + ΔC_p ln(T₂/T₁)", asks="entropy change at T₂ (J K⁻¹ mol⁻¹)"),
    # 2024 P1 Q8: ΔH of an ideal gas between two states (any path); the state fixes n
    Step(tx=389, src="gas_state", dst="delta_h",
         derive=(Derive("n", (P("P", "atm", "initial pressure", lo=0.1, hi=20),),
                        lambda v: v["P"] * v["V"] / (C.R_LATM * v["T"])),),
         needs=(P("Cv", "J K⁻¹ mol⁻¹", "molar C_v of the gas", lo=12, hi=30),
                P("T", "K", "initial temperature", kind="temperature", lo=150, hi=1500),
                P("V", "L", "initial volume", lo=0.1, hi=100),
                P("new_temperature", "K", "final temperature", kind="temperature", lo=150, hi=1500)),
         answer="gas_enthalpy_change", unit="J", kind="real",
         fn=lambda v: {"gas_enthalpy_change": v["n"] * (v["Cv"] + C.R_J) * (v["new_temperature"] - v["T"])},
         traps=(Trap("uses_cv", "uses C_v (that is ΔU)", lambda v: v["n"] * v["Cv"] * (v["new_temperature"] - v["T"])),),
         constants=(const("R_LATM"), const("R_J")), formula="n = PV/RT; ΔH = nC_pΔT, C_p = C_v + R (any path)",
         asks="enthalpy change of the gas (J)"),

    # ── Chemical Equilibrium ──
    # 2017 P1 Q27: equilibrium amounts from the extent of reaction
    Step(tx=361, src="balanced_equation", dst="equilibrium_moles", not_after=(32,),
         needs=(P("balanced_equation", "", "the balanced equation, e.g. '2A + B -> C + D'", kind="text"),
                P("initial_amounts", "mol", "initial amount of each species (0 if absent)", kind="dict"),
                P("known_species", "", "species whose equilibrium amount is known", kind="text"),
                P("known_equilibrium_amount", "mol", "equilibrium amount of that species", lo=0.001, hi=10),
                P("species_asked", "", "species whose equilibrium amount is asked", kind="text")),
         answer="equilibrium_moles", unit="mol", kind="positive", gives=("eq_amounts", "balanced_equation"),
         fn=_ice_extent,
         traps=(Trap("ignores_coefficients", "changes every amount by the same extent",
                     lambda v: _ice_extent(v, use_coef=False)["equilibrium_moles"]),),
         formula="n = n₀ + νξ for every species", asks="equilibrium amount of the species (mol)"),
    # 2018 P2 Q10: a gas-solid equilibrium with one gas on each side
    Step(tx=367, src="equilibrium_constant", dst="partial_pressure",
         needs=(P("equilibrium_constant", "", "K_p of solid + X(g) ⇌ solid + Y(g)", lo=1e-12, hi=1e12, role=("K°", "Kp")),
                P("reactant_gas_pressure", "atm", "partial pressure of the reactant gas X", lo=1e-4, hi=10)),
         answer="partial_pressure", unit="atm", kind="positive", roles={"partial_pressure": "equilibrium gas"},
         fn=lambda v: {"partial_pressure": v["equilibrium_constant"] * v["reactant_gas_pressure"]},
         traps=(Trap("inverted", "divides by K", lambda v: v["reactant_gas_pressure"] / v["equilibrium_constant"]),),
         formula="K_p = p(Y)/p(X) (solids omitted)", asks="equilibrium partial pressure of the product gas Y (atm)"),
    # 2018 P2 Q11 (second half): ΔG° from K
    Step(tx=369, src="equilibrium_constant", dst="delta_g", not_after=(135,),
         needs=(P("equilibrium_constant", "", "equilibrium constant K", lo=1e-30, hi=1e30, role=("K°", "Kp", "Kc")),
                P("T", "K", "temperature", kind="temperature", lo=200, hi=1500)),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "standard"},
         fn=lambda v: {"delta_g": -C.R_J * v["T"] * ln(v["equilibrium_constant"]) / 1000},
         traps=(Trap("log10_as_ln", "uses log₁₀ K", lambda v: -C.R_J * v["T"] * log10(v["equilibrium_constant"]) / 1000),),
         constants=(const("R_J"),), formula="ΔG° = −RT ln K", asks="standard Gibbs energy change (kJ mol⁻¹)"),
    # 2021 P1 Q8: ΔS° from the intercept of ln K against 1/T
    Step(tx=378, src="vant_hoff_plot", dst="delta_s",
         needs=(P("intercept", "", "intercept of the plot (at 1/T = 0)", kind="real", lo=-50, hi=50),
                P("plot", "", "what is plotted against 1/T", kind="choice", choices=("ln K", "log K"))),
         answer="delta_s", unit="J K⁻¹ mol⁻¹", kind="real",
         fn=lambda v: {"delta_s": v["intercept"] * C.R_J * (1 if v["plot"] == "ln K" else 2.303)},
         traps=(Trap("forgets_2303", "omits 2.303 for a log K plot (or adds it for ln K)",
                     lambda v: v["intercept"] * C.R_J * (2.303 if v["plot"] == "ln K" else 1)),),
         constants=(const("R_J"),), formula="ln K = −ΔH°/RT + ΔS°/R: intercept = ΔS°/R",
         asks="standard entropy change (J K⁻¹ mol⁻¹)"),

    # ── Chemical Kinetics ──
    # 2013 P1 Q21: order from t₇₅/t₅₀
    Step(tx=351, src="fractional_life_ratio", dst="rate_law",
         needs=(P("time_ratio", "", "time for 75 % reaction / time for 50 % reaction", lo=1.5, hi=9),),
         answer="rate_law", unit="", kind="real",
         fn=lambda v: {"rate_law": _order_from_ratio(v["time_ratio"])},
         traps=(Trap("ratio_minus_one", "takes the order as t₇₅/t₅₀ − 1", lambda v: v["time_ratio"] - 1),),
         formula="t₇₅/t₅₀ = 2^(n−1) + 1 (first order: 2)", asks="order of the reaction"),
    # 2018 P2 Q11 (first half): K from the pre-exponential factors and the activation energies
    Step(tx=368, src="activation_energy", dst="equilibrium_constant",
         needs=(P("prefactor_ratio", "", "A(forward)/A(backward)", lo=0.01, hi=100),
                P("activation_energy_difference", "J mol⁻¹", "E_a(backward) − E_a(forward)", kind="real", lo=-50000, hi=50000),
                P("T", "K", "temperature", kind="temperature", lo=250, hi=1500)),
         answer="equilibrium_constant", unit="", kind="positive", roles={"equilibrium_constant": "Kc"}, gives=("T",),
         fn=lambda v: {"equilibrium_constant": v["prefactor_ratio"]
                       * math.exp(v["activation_energy_difference"] / (C.R_J * v["T"])), "T": v["T"]},
         traps=(Trap("sign", "uses the opposite sign in the exponent",
                     lambda v: v["prefactor_ratio"] * math.exp(-v["activation_energy_difference"] / (C.R_J * v["T"]))),),
         constants=(const("R_J"),), formula="K = k_f/k_b = (A_f/A_b) e^((E_a,b − E_a,f)/RT)",
         asks="equilibrium constant"),
    # 2019 P1 Q16: a new rate from the orders and one measured rate
    Step(tx=372, src="rate_law", dst="reaction_rate",
         needs=(P("reaction_rate", "mol L⁻¹ s⁻¹", "rate measured in the reference run", lo=1e-8, hi=1,
                  role="rate of reaction"),
                P("orders", "", "order with respect to each reactant", kind="dict"),
                P("reference_concentrations", "mol L⁻¹", "concentrations in the reference run", kind="dict"),
                P("new_concentrations", "mol L⁻¹", "concentrations in the new run", kind="dict")),
         answer="reaction_rate", unit="mol L⁻¹ s⁻¹", kind="positive", roles={"reaction_rate": "rate of reaction"},
         fn=lambda v: {"reaction_rate": _rate_from_orders(v)},
         traps=(Trap("first_order_in_all", "takes every order as 1", lambda v: _rate_from_orders(v, use_orders=False)),),
         formula="rate = k[A]^x[B]^y[C]^z: rate₂ = rate₁ Π(c₂/c₁)^order", asks="rate in the new run (mol L⁻¹ s⁻¹)"),
    # 2024 P1 Q9: order from a mechanism with a fast pre-equilibrium
    Step(tx=390, src="reaction_mechanism", dst="rate_law",
         needs=(P("fast_equilibrium", "", "the fast pre-equilibrium, e.g. '2NO -> N2O2'", kind="text"),
                P("slow_step", "", "the slow step, e.g. 'N2O2 + H2 -> N2O + H2O'", kind="text")),
         answer="rate_law", unit="", kind="real",
         fn=lambda v: {"rate_law": _mechanism_order(v)},
         traps=(Trap("slow_step_only", "reads the order off the slow step alone", lambda v: _mechanism_order(v, substitute=False)),),
         formula="rate = k[I][B]; [I] = K Π[reactants of the fast step]", asks="overall order of the reaction"),

    # ── Ionic Equilibrium ──
    # 2013 P1 Q31: acid catalysis, rate ∝ [H⁺]
    Step(tx=353, src="reaction_rate", dst="ph",
         needs=(P("rate_ratio", "", "rate with the weak acid / rate with the strong acid (same concentration)", lo=1e-4, hi=0.5),
                P("strong_acid_concentration", "mol L⁻¹", "concentration of the monobasic strong acid", lo=1e-3, hi=2)),
         answer="ph", unit="", kind="ph", roles={"ph": "weak acid solution"},
         fn=lambda v: {"ph": -log10(v["rate_ratio"] * v["strong_acid_concentration"])},
         traps=(Trap("square_law", "takes the rate as proportional to [H⁺]²",
                     lambda v: -log10(sqrt(v["rate_ratio"]) * v["strong_acid_concentration"])),),
         formula="rate ∝ [H⁺]: [H⁺](weak) = (rate ratio) × [H⁺](strong)", asks="pH of the weak acid solution"),
    Step(tx=354, src="ph", dst="dissociation_constant",
         needs=(P("ph", "", "pH of the weak acid solution", kind="ph", lo=1, hi=7, role="weak acid solution"),
                P("concentration", "mol L⁻¹", "concentration of the weak acid", lo=1e-3, hi=2)),
         answer="dissociation_constant", unit="", kind="positive", gives=("concentration",),
         fn=lambda v: {"dissociation_constant": _ka_from_ph(v), "concentration": v["concentration"]},
         traps=(Trap("ignores_dissociated", "uses K_a = [H⁺]²/C", lambda v: _ka_from_ph(v, approx=True)),),
         formula="K_a = [H⁺]²/(C − [H⁺])", asks="K_a of the acid"),
    # 2018 P1 Q11, 2023 P1 Q6: a salt of a weak acid dissolved at a fixed pH
    Step(tx=365, src="solubility_product", dst="solubility",
         needs=(P("solubility_product", "", "K_sp of the 1:1 salt MX", lo=1e-20, hi=1e-4),
                P("Ka", "", "K_a of the weak acid HX", lo=1e-12, hi=1e-2),
                P("ph", "", "pH of the solution", kind="ph", lo=0, hi=12)),
         answer="solubility", unit="mol L⁻¹", kind="positive", roles={"solubility": "fixed pH"},
         fn=lambda v: {"solubility": _salt_solubility_at_ph(v)},
         traps=(Trap("ignores_protonation", "uses S = √K_sp", lambda v: _salt_solubility_at_ph(v, protonation=False)),),
         formula="S² = K_sp(1 + [H⁺]/K_a)", asks="molar solubility at that pH (mol L⁻¹)"),
    # 2019 P1 Q15: the ion left after a near-complete precipitation
    Step(tx=371, src="solubility_product", dst="residual_concentration",
         needs=(P("solubility_product", "", "K_sp of the 1:1 precipitate (1/K of its formation)", lo=1e-40, hi=1e-6),
                P("cation_concentration", "mol L⁻¹", "concentration of the cation solution before mixing", lo=1e-4, hi=1),
                P("volume_1", "mL", "volume of the cation solution", lo=1, hi=1000),
                P("anion_concentration", "mol L⁻¹", "concentration of the anion solution before mixing", lo=1e-4, hi=1),
                P("volume_2", "mL", "volume of the anion solution", lo=1, hi=1000)),
         answer="residual_concentration", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"residual_concentration": _residual(v)},
         traps=(Trap("forgets_dilution", "uses the concentrations before mixing", lambda v: _residual(v, dilute=False)),),
         formula="precipitation is complete; [minor ion] = K_sp/[ion in excess]",
         asks="equilibrium concentration of the ion that is not in excess (mol L⁻¹)"),
    # 2020 P2 Q18: least [H⁺] that keeps a sulfide from precipitating
    Step(tx=377, src="solubility_product", dst="ph",
         needs=(P("solubility_product", "", "K_sp of the sulfide MS", lo=1e-30, hi=1e-10),
                P("h2s_constant", "", "overall dissociation constant K₁K₂ of H₂S", lo=1e-24, hi=1e-18),
                P("h2s_concentration", "mol L⁻¹", "concentration of H₂S (saturated)", lo=0.01, hi=0.2),
                P("cation_concentration", "mol L⁻¹", "concentration of M²⁺", lo=1e-4, hi=1)),
         answer="hydrogen_ion_concentration", unit="mol L⁻¹", kind="positive", gives=("ph",),
         roles={"ph": "solution"},
         fn=lambda v: (lambda h: {"hydrogen_ion_concentration": h, "ph": -log10(h)})(_min_h_for_sulfide(v)),
         traps=(Trap("forgets_square", "takes [S²⁻] = K₁K₂[H₂S]/[H⁺]", lambda v: _min_h_for_sulfide(v, root=False)),),
         formula="[S²⁻] = K₁K₂[H₂S]/[H⁺]²; [M²⁺][S²⁻] = K_sp at the limit",
         asks="minimum [H⁺] that prevents precipitation (mol L⁻¹)"),
    # 2022 P1 Q3: a diprotic acid, its salts and a strong base mixed -> the buffer left
    Step(tx=384, src="moles", dst="buffer_ratio",
         needs=(P("diprotic_acid_moles", "mol", "amount of H₂A", kind="nonneg", lo=0, hi=0.5),
                P("monoanion_moles", "mol", "amount of NaHA", kind="nonneg", lo=0, hi=0.5),
                P("dianion_moles", "mol", "amount of Na₂A", kind="nonneg", lo=0, hi=0.5),
                P("strong_base_moles", "mol", "amount of NaOH", kind="nonneg", lo=0, hi=0.5),
                P("Ka1", "", "K₁ of H₂A", lo=1e-9, hi=1e-2),
                P("Ka2", "", "K₂ of H₂A", lo=1e-13, hi=1e-5)),
         answer="buffer_ratio", unit="", kind="positive", gives=("dissociation_constant",),
         fn=_buffer_after_base,
         traps=(Trap("ignores_base", "forgets that NaOH converts the acid", lambda v: _buffer_after_base(v, react=False)),),
         formula="NaOH: H₂A → HA⁻, then HA⁻ → A²⁻; the pair left is the buffer",
         asks="[base form]/[acid form] ratio of the buffer"),
    # 2022 P2 Q1: PbSO₄ in H₂SO₄ + Na₂SO₄ (K_a2 of H₂SO₄)
    Step(tx=385, src="solubility_product", dst="solubility",
         needs=(P("solubility_product", "", "K_sp of the sulfate MSO₄", lo=1e-12, hi=1e-5),
                P("acid_concentration", "mol L⁻¹", "concentration of H₂SO₄", lo=0.01, hi=2),
                P("sulfate_concentration", "mol L⁻¹", "concentration of Na₂SO₄", lo=1e-4, hi=1),
                P("Ka2", "", "K_a2 of H₂SO₄ (K_a1 very large)", lo=1e-3, hi=0.1)),
         answer="solubility", unit="mol L⁻¹", kind="positive", roles={"solubility": "common ion"},
         fn=lambda v: {"solubility": _sulfate_solubility(v)},
         traps=(Trap("ignores_bisulfate", "takes [SO₄²⁻] as the Na₂SO₄ alone",
                     lambda v: _sulfate_solubility(v, "ignore_bisulfate")),
                Trap("full_dissociation", "takes H₂SO₄ as fully dissociated to SO₄²⁻",
                     lambda v: _sulfate_solubility(v, "full_dissociation"))),
         formula="HSO₄⁻ ⇌ H⁺ + SO₄²⁻ (K_a2) sets [SO₄²⁻]; S = K_sp/[SO₄²⁻]",
         asks="molar solubility of the sulfate (mol L⁻¹)"),

    # ── Electrochemistry ──
    # 2017 P2 Q19: ΔG of a cell from its non-standard EMF
    Step(tx=363, src="cell_emf", dst="delta_g",
         needs=(P("cell_emf", "V", "EMF of the cell under the stated conditions", kind="real", lo=-3, hi=4,
                  role="non-standard", strict=True),
                P("electrons", "", "electrons transferred", kind="posint", lo=1, hi=6)),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "non-standard"},
         fn=lambda v: {"delta_g": -v["electrons"] * C.F * v["cell_emf"] / 1000},
         traps=(Trap("forgets_n", "uses −FE", lambda v: -C.F * v["cell_emf"] / 1000),),
         constants=(const("F"),), formula="ΔG = −nFE", asks="Gibbs energy change of the cell reaction (kJ mol⁻¹)"),
    # 2022 P1 Q2: E° of a couple from other couples
    Step(tx=383, src="electrode_potential", dst="electrode_potential",
         needs=(P("couples", "", "list of [electrons, E° in V] for the couples that add up to the asked one", kind="list"),
                P("electrons", "", "electrons in the asked couple", kind="posint", lo=2, hi=12)),
         answer="reduction_potential", unit="V", kind="real",
         fn=lambda v: {"reduction_potential": _combined_potential(v)},
         traps=(Trap("averages", "averages the potentials (E° is not additive)", lambda v: _combined_potential(v, weighted=False)),),
         formula="ΔG° adds: −nFE° = Σ(−nᵢFEᵢ°) → E° = ΣnᵢEᵢ°/n", asks="standard reduction potential of the couple (V)"),
    # 2025 Q8: the current that passes a charge in a time
    Step(tx=391, src="charge", dst="current",
         needs=(P("charge", "C", "charge passed", lo=100, hi=1e7),
                P("time", "min", "time of electrolysis", lo=0.5, hi=600)),
         answer="current", unit="A", kind="positive",
         fn=lambda v: {"current": v["charge"] / (60 * v["time"])},
         traps=(Trap("minutes_as_seconds", "uses the time in minutes", lambda v: v["charge"] / v["time"]),),
         formula="I = Q/t", asks="current (A)"),

    # ── Thermochemistry ──
    # 2013 P1 Q29: per gram instead of per mole
    Step(tx=352, src="delta_h", dst="specific_enthalpy",
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy of reaction per mole of the substance", kind="real", lo=-10000, hi=10000,
                  role="reaction", strict=True),
                P("molar_mass", "g mol⁻¹", "molar mass of the substance", lo=2, hi=400)),
         answer="specific_enthalpy", unit="kJ g⁻¹", kind="real",
         fn=lambda v: {"specific_enthalpy": v["delta_h"] / v["molar_mass"]},
         traps=(Trap("multiplies", "multiplies by the molar mass", lambda v: v["delta_h"] * v["molar_mass"]),),
         formula="per gram = per mole / M", asks="enthalpy change per gram (kJ g⁻¹)"),
    # 2022 P1 Q1: bomb calorimeter -> ΔU per mole (then ΔH by tx 113, ΔfH by tx 382)
    Step(tx=381, src="heat", dst="delta_u",
         needs=(P("heat", "J", "heat absorbed by the calorimeter", lo=10, hi=1e7, role="calorimeter", strict=True),
                P("moles_reacted", "mol", "amount of the substance that reacted", lo=0.001, hi=10)),
         answer="reaction_delta_u", unit="kJ mol⁻¹", kind="real",
         fn=lambda v: {"reaction_delta_u": -v["heat"] / 1000 / v["moles_reacted"]},
         traps=(Trap("sign", "gives a positive ΔU for a reaction that heats the calorimeter",
                     lambda v: v["heat"] / 1000 / v["moles_reacted"]),),
         formula="q_v = ΔU = −C_cal ΔT per mole reacted", asks="internal energy change of the reaction (kJ mol⁻¹)"),
    Step(tx=382, src="delta_h", dst="enthalpy_data", not_after_any=(139,),
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy change of the reaction", kind="real", lo=-5000, hi=5000,
                  role="reaction", strict=True),
                P("balanced_equation", "", "the balanced equation", kind="text"),
                P("formation_enthalpies", "kJ mol⁻¹", "ΔfH of every other species (0 for elements)", kind="dict"),
                P("unknown_species", "", "species whose ΔfH is asked", kind="text")),
         answer="formation_enthalpy", unit="kJ mol⁻¹", kind="real",
         fn=lambda v: {"formation_enthalpy": _formation_by_hess(v)},
         traps=(Trap("ignores_coefficients", "ignores the coefficients", lambda v: _formation_by_hess(v, use_coef=False)),),
         formula="ΔrH = ΣνΔfH(products) − ΣνΔfH(reactants), solved for the one unknown",
         asks="standard enthalpy of formation of the species (kJ mol⁻¹)"),

    # ── Surface Chemistry ──
    # 2024 P2 Q8: area each adsorbed molecule occupies (back titration of what was not adsorbed)
    Step(tx=387, src="equivalents", dst="molecular_area",
         needs=(P("equivalents", "eq", "equivalents of base used for the acid left unadsorbed", lo=1e-4, hi=1),
                P("acid_molarity", "mol L⁻¹", "molarity of the monobasic acid added", lo=0.01, hi=2),
                P("acid_volume", "mL", "volume of acid added", lo=10, hi=500),
                P("specific_surface_area", "m² g⁻¹", "surface area of the adsorbent", lo=10, hi=3000),
                P("adsorbent_mass", "g", "mass of the adsorbent", lo=0.1, hi=20)),
         answer="molecular_area", unit="m²", kind="positive",
         fn=lambda v: {"molecular_area": v["specific_surface_area"] * v["adsorbent_mass"]
                       / (_pos(v["acid_molarity"] * v["acid_volume"] / 1000 - v["equivalents"], "acid adsorbed") * C.NA)},
         traps=(Trap("all_acid_adsorbed", "takes all the acid added as adsorbed",
                     lambda v: v["specific_surface_area"] * v["adsorbent_mass"]
                     / (v["acid_molarity"] * v["acid_volume"] / 1000 * C.NA)),),
         constants=(const("NA"),), formula="adsorbed = added − back-titrated; area per molecule = total area / N",
         asks="surface area occupied by one molecule (m²)"),
]
