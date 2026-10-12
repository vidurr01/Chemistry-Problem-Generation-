"""Physical engine — Chemical Kinetics and Nuclear Chemistry (concept-book TXs 200-232, 318, 332, 333)."""

from __future__ import annotations

import math

from core.engine.base import EngineError, Param, Step, Trap, ln, log10
from core.engine.chem import C, SYMBOLS, const

P = Param
M_H = 1.007825      # u, hydrogen atom (atomic masses absorb the electrons)
M_N = 1.008665      # u, neutron


def _nuclide_name(Z, A):
    if not 1 <= Z <= len(SYMBOLS) or A < Z:
        raise EngineError(f"no nuclide with Z = {Z}, A = {A}")
    return f"{SYMBOLS[Z - 1]}-{A}"


def _decay(v, dz, da):
    Z, A = v["Z"] + dz, v["A"] + da
    return {"daughter_nuclide": _nuclide_name(Z, A), "Z": Z, "A": A}


_PARENT = (P("Z", "", "atomic number of the parent nuclide", kind="posint", lo=5, hi=92),
           P("A", "", "mass number of the parent nuclide", kind="posint", lo=10, hi=240))

_PROJECTILES = {"neutron": (0, 1), "proton": (1, 1), "deuteron": (1, 2), "alpha": (2, 4), "gamma": (0, 0)}


def _bombard(v, swap=False):
    pin, pout = v["projectile"], v["emitted"]
    if swap:
        pin, pout = pout, pin
    zi, ai = _PROJECTILES[pin]
    zo, ao = _PROJECTILES[pout]
    return _decay(v, zi - zo, ai - ao)


def _decay_counts(v, sign=1):
    da = v["initial_A"] - v["A"]
    if da < 0 or da % 4:
        raise EngineError("mass number change must be a non-negative multiple of 4")
    n_alpha = da // 4
    n_beta = 2 * n_alpha - sign * (v["initial_Z"] - v["Z"])
    if n_beta < 0:
        raise EngineError("negative number of β decays")
    return {"decay_counts": n_alpha if v["count"] == "alpha" else n_beta}


def _order_from_rates(v, use_log=True):
    rr = v["reaction_rate_2"] / v["reaction_rate"]
    cr = v["concentration_2"] / v["concentration"]
    if math.isclose(cr, 1.0):
        raise EngineError("the concentrations must differ")
    return log10(rr) / log10(cr) if use_log else rr / cr


def _k_from_data(order, r0, r, t):
    if r >= r0:
        raise EngineError("concentration must fall")
    if order == 0:
        return (r0 - r) / t
    if order == 1:
        return ln(r0 / r) / t
    return (1 / r - 1 / r0) / t


_KIN_NEEDS = (P("initial_concentration", "mol L⁻¹", "initial concentration [R]₀", lo=0.01, hi=2),
              P("concentration", "mol L⁻¹", "concentration [R] at time t", lo=0.001, hi=2),
              P("time", "s", "time elapsed", lo=1, hi=1e5))


_K_FIELD = {0: "rate_constant_zero_order", 1: "rate_constant", 2: "rate_constant_second_order"}


def _order_step(tx, order, name, formula):
    others = [o for o in (0, 1, 2) if o != order]
    return Step(
        tx=tx, src="rate_law", dst="rate_constant", needs=_KIN_NEEDS,
        answer=_K_FIELD[order], unit={0: "mol L⁻¹ s⁻¹", 1: "s⁻¹", 2: "L mol⁻¹ s⁻¹"}[order], kind="positive",
        roles={_K_FIELD[order]: "reaction"},
        fn=lambda v: {_K_FIELD[order]: _k_from_data(order, v["initial_concentration"], v["concentration"], v["time"])},
        traps=tuple(Trap(f"uses_order_{o}", f"uses the order-{o} integrated rate law",
                         lambda v, o=o: _k_from_data(o, v["initial_concentration"], v["concentration"], v["time"]))
                    for o in others) + ((Trap("log10_without_2303", "uses log₁₀ without 2.303",
                                              lambda v: log10(v["initial_concentration"] / v["concentration"]) / v["time"]),)
                                        if order == 1 else ()),
        formula=formula, asks=f"rate constant of the {name} reaction")


def _gas_k(v, use_total=False):
    n, p0, pt = v["moles_of_gaseous_products"], v["initial_pressure"], v["total_pressure"]
    if n <= 1:
        raise EngineError("need more than one mole of gaseous product per mole of reactant")
    pa = pt if use_total else (n * p0 - pt) / (n - 1)
    if not 0 < pa < p0:
        raise EngineError("these pressures are not reachable")
    return ln(p0 / pa) / v["time"]


STEPS = [
    Step(tx=200, src="molarity", dst="reaction_rate",
         needs=(P("molarity", "mol L⁻¹", "initial concentration of reactant A", lo=0.05, hi=2, role="reactant"),
                P("final_concentration", "mol L⁻¹", "concentration of A after the interval", lo=0.001, hi=2),
                P("time", "s", "length of the interval", lo=1, hi=1e4),
                P("coefficient", "", "stoichiometric coefficient of A", kind="posint", lo=1, hi=4)),
         answer="reaction_rate", unit="mol L⁻¹ s⁻¹", kind="positive",
         fn=lambda v: {"reaction_rate": (v["molarity"] - v["final_concentration"]) / (v["coefficient"] * v["time"])},
         traps=(Trap("forgets_coefficient", "reports −Δ[A]/Δt without dividing by the coefficient",
                     lambda v: (v["molarity"] - v["final_concentration"]) / v["time"]),),
         formula="rate = −(1/a) Δ[A]/Δt", asks="average rate of the reaction (mol L⁻¹ s⁻¹)"),
    Step(tx=201, src="reaction_rate", dst="reaction_rate",
         needs=(P("reaction_rate", "mol L⁻¹ s⁻¹", "rate of disappearance of A, −d[A]/dt", lo=1e-6, hi=1),
                P("coefficient_A", "", "coefficient of A", kind="posint", lo=1, hi=4),
                P("coefficient_C", "", "coefficient of product C", kind="posint", lo=1, hi=4)),
         answer="reaction_rate", unit="mol L⁻¹ s⁻¹", kind="positive",
         fn=lambda v: {"reaction_rate": v["reaction_rate"] * v["coefficient_C"] / v["coefficient_A"]},
         traps=(Trap("inverted_ratio", "multiplies by a/c", lambda v: v["reaction_rate"] * v["coefficient_A"] / v["coefficient_C"]),),
         formula="−(1/a) d[A]/dt = (1/c) d[C]/dt", asks="rate of formation of C (mol L⁻¹ s⁻¹)"),
    Step(tx=202, src="reaction_rate", dst="rate_law",
         needs=(P("reaction_rate", "mol L⁻¹ s⁻¹", "initial rate in run 1", lo=1e-8, hi=1),
                P("concentration", "mol L⁻¹", "[A] in run 1", lo=0.001, hi=2),
                P("reaction_rate_2", "mol L⁻¹ s⁻¹", "initial rate in run 2 (other concentrations unchanged)", lo=1e-8, hi=10),
                P("concentration_2", "mol L⁻¹", "[A] in run 2", lo=0.001, hi=4)),
         answer="rate_law", unit="", kind="real",
         fn=lambda v: {"rate_law": _order_from_rates(v)},
         traps=(Trap("ratio_without_log", "divides the rate ratio by the concentration ratio",
                     lambda v: _order_from_rates(v, use_log=False)),),
         formula="rate₂/rate₁ = ([A]₂/[A]₁)^m", asks="order with respect to A"),
    _order_step(204, 0, "zero-order", "kt = [R]₀ − [R]"),
    _order_step(205, 1, "first-order", "kt = ln([R]₀/[R])"),
    _order_step(206, 2, "second-order", "kt = 1/[R] − 1/[R]₀"),
    Step(tx=207, src="rate_law", dst="half_life",
         needs=(P("order", "", "order n of the reaction (n ≠ 1)", kind="real", lo=0, hi=3),
                P("rate_constant", "", "rate constant (units for order n)", lo=1e-6, hi=10),
                P("initial_concentration", "mol L⁻¹", "initial concentration a", lo=0.01, hi=2)),
         answer="half_life", unit="s", kind="positive",
         fn=lambda v: {"half_life": _t_half(v)},
         traps=(Trap("first_order_formula", "uses t½ = 0.693/k", lambda v: 0.693 / v["rate_constant"]),),
         formula="t½ = (2^(n−1) − 1)/(k(n − 1)a^(n−1))", asks="half-life (s)"),
    Step(tx=208, src="partial_pressure", dst="rate_constant",
         needs=(P("initial_pressure", "atm", "initial pressure of the gaseous reactant (alone)", lo=0.1, hi=10),
                P("total_pressure", "atm", "total pressure at time t", lo=0.1, hi=30),
                P("moles_of_gaseous_products", "", "n in A(g) → n mol of gaseous products", kind="real", lo=1.5, hi=4),
                P("time", "s", "time elapsed", lo=1, hi=1e5)),
         answer="rate_constant", unit="s⁻¹", kind="positive", roles={"rate_constant": "reaction"},
         fn=lambda v: {"rate_constant": _gas_k(v)},
         traps=(Trap("total_as_reactant", "uses the total pressure as the reactant's pressure",
                     lambda v: _gas_k(v, use_total=True)),),
         formula="k = (1/t) ln(P₀/P_A), P_A = (nP₀ − P_t)/(n − 1)", asks="first-order rate constant (s⁻¹)"),
    Step(tx=209, src="fraction_remaining", dst="time_elapsed",
         needs=(P("fraction_remaining", "", "fraction of the sample remaining", kind="open_fraction", lo=0.01, hi=0.95),
                P("half_life", "s", "half-life", lo=1, hi=1e9)),
         answer="time_elapsed", unit="s", kind="positive",
         fn=lambda v: {"time_elapsed": v["half_life"] * math.log2(1 / v["fraction_remaining"])},
         traps=(Trap("linear_decay", "treats the decay as linear (half gone per half-life, all gone in two)",
                     lambda v: v["half_life"] * 2 * (1 - v["fraction_remaining"])),),
         formula="N/N₀ = (½)^(t/t½)", asks="time elapsed (in the unit of the half-life)"),
    Step(tx=210, src="rate_constant", dst="equilibrium_constant",
         needs=(P("rate_constant", "s⁻¹", "forward rate constant k_f", lo=1e-6, hi=10, role="reaction"),
                P("kb", "s⁻¹", "backward rate constant k_b", lo=1e-6, hi=10)),
         answer="equilibrium_constant", unit="", kind="positive",
         fn=lambda v: {"equilibrium_constant": v["rate_constant"] / v["kb"]},
         traps=(Trap("inverted", "uses k_b/k_f", lambda v: v["kb"] / v["rate_constant"]),),
         formula="K = k_f/k_b", asks="equilibrium constant"),
    Step(tx=211, src="rate_constant", dst="branch_ratio",
         needs=(P("rate_constant", "s⁻¹", "rate constant k₁ of the branch giving B", lo=1e-6, hi=10, role="reaction"),
                P("k2", "s⁻¹", "rate constant k₂ of the branch giving C", lo=1e-6, hi=10)),
         answer="branch_ratio", unit="%", kind="percent",
         fn=lambda v: {"branch_ratio": 100 * v["rate_constant"] / (v["rate_constant"] + v["k2"])},
         traps=(Trap("ratio_not_fraction", "reports k₁/k₂ × 100", lambda v: 100 * v["rate_constant"] / v["k2"]),),
         formula="%B = k₁/(k₁ + k₂) × 100", asks="percentage of B in the products"),
    Step(tx=212, src="rate_constant", dst="time_elapsed",
         needs=(P("rate_constant", "s⁻¹", "k₁ of A → B", lo=1e-6, hi=10, role="reaction"),
                P("k2", "s⁻¹", "k₂ of B → C", lo=1e-6, hi=10)),
         answer="time_elapsed", unit="s", kind="positive",
         fn=lambda v: {"time_elapsed": ln(v["rate_constant"] / v["k2"]) / _nz(v["rate_constant"] - v["k2"])},
         traps=(Trap("log10", "uses log₁₀ without 2.303", lambda v: log10(v["rate_constant"] / v["k2"]) / _nz(v["rate_constant"] - v["k2"])),),
         formula="t_max = ln(k₁/k₂)/(k₁ − k₂)", asks="time at which [B] is maximum (s)"),
    Step(tx=213, src="rate_constant", dst="activation_energy",
         needs=(P("rate_constant", "", "rate constant k₁ at T₁", lo=1e-8, hi=10),
                P("T1", "K", "temperature T₁", kind="temperature", lo=250, hi=1000),
                P("k2", "", "rate constant k₂ at T₂ (same units)", lo=1e-8, hi=100),
                P("T2", "K", "temperature T₂", kind="temperature", lo=250, hi=1100)),
         answer="activation_energy", unit="kJ mol⁻¹", kind="positive",
         fn=lambda v: {"activation_energy": C.R_J * ln(v["k2"] / v["rate_constant"])
                       * v["T1"] * v["T2"] / _nz(v["T2"] - v["T1"]) / 1000},
         traps=(Trap("forgets_2303", "uses log₁₀ without 2.303",
                     lambda v: C.R_J * log10(v["k2"] / v["rate_constant"]) * v["T1"] * v["T2"] / _nz(v["T2"] - v["T1"]) / 1000),),
         constants=(const("R_J"),), formula="log(k₂/k₁) = (E_a/2.303R)(1/T₁ − 1/T₂)", asks="activation energy (kJ mol⁻¹)"),
    Step(tx=214, src="temperature", dst="rate_factor",
         needs=(P("temperature", "K", "initial temperature", kind="temperature", lo=273, hi=400, role="reaction"),
                P("final_temperature", "K", "final temperature", kind="temperature", lo=273, hi=450),
                P("temperature_coefficient", "", "factor by which the rate rises per 10 K", lo=1.5, hi=3.5)),
         answer="rate_factor", unit="", kind="positive",
         fn=lambda v: {"rate_factor": v["temperature_coefficient"] ** ((v["final_temperature"] - v["temperature"]) / 10)},
         traps=(Trap("linear", "multiplies the coefficient by the number of 10 K steps",
                     lambda v: v["temperature_coefficient"] * (v["final_temperature"] - v["temperature"]) / 10),),
         formula="k₂/k₁ = μ^(ΔT/10)", asks="factor by which the rate constant increases"),
    Step(tx=215, src="activation_energy", dst="fraction_above_ea",
         needs=(P("activation_energy", "kJ mol⁻¹", "activation energy", lo=10, hi=200),
                P("T", "K", "temperature", kind="temperature", lo=250, hi=1000)),
         answer="fraction_above_ea", unit="", kind="open_fraction",
         fn=lambda v: {"fraction_above_ea": math.exp(-1000 * v["activation_energy"] / (C.R_J * v["T"]))},
         traps=(Trap("uses_power_of_10", "uses 10^(−Ea/RT)", lambda v: 10 ** (-1000 * v["activation_energy"] / (C.R_J * v["T"]))),),
         constants=(const("R_J"),), formula="fraction = e^(−E_a/RT)", asks="fraction of molecules with energy ≥ E_a"),
    Step(tx=216, src="delta_h", dst="activation_energy",
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy change of the reaction", kind="real", lo=-300, hi=300),
                P("forward_activation_energy", "kJ mol⁻¹", "activation energy of the forward reaction", lo=1, hi=400)),
         answer="activation_energy", unit="kJ mol⁻¹", kind="positive",
         fn=lambda v: {"activation_energy": v["forward_activation_energy"] - v["delta_h"]},
         traps=(Trap("adds_delta_h", "uses E_a,b = E_a,f + ΔH", lambda v: v["forward_activation_energy"] + v["delta_h"]),),
         formula="ΔH = E_a,f − E_a,b", asks="activation energy of the backward reaction (kJ mol⁻¹)"),
    Step(tx=218, src="half_life", dst="rate_constant",
         needs=(P("half_life", "s", "half-life of the first-order process", lo=1, hi=1e10),),
         answer="rate_constant", unit="s⁻¹", kind="positive", gives=("average_life",),
         fn=lambda v: {"rate_constant": 0.693 / v["half_life"], "average_life": v["half_life"] / 0.693},
         traps=(Trap("inverted", "uses λ = t½/0.693", lambda v: v["half_life"] / 0.693),),
         formula="λ = 0.693/t½; average life = 1/λ = 1.44 t½", asks="decay constant (s⁻¹)"),
    Step(tx=219, src="parent_nuclide", dst="daughter_nuclide", needs=_PARENT,
         answer="daughter_nuclide", unit="", kind="text", gives=("Z", "A"),
         fn=lambda v: _decay(v, -2, -4),
         traps=(Trap("swaps_changes", "lowers Z by 4 and A by 2", lambda v: _decay(v, -4, -2)),),
         formula="α decay: Z − 2, A − 4", asks="daughter nuclide after α emission"),
    Step(tx=220, src="parent_nuclide", dst="daughter_nuclide", needs=_PARENT,
         answer="daughter_nuclide", unit="", kind="text", gives=("Z", "A"),
         fn=lambda v: _decay(v, 1, 0),
         traps=(Trap("wrong_sign", "lowers Z by 1", lambda v: _decay(v, -1, 0)),),
         formula="β⁻ decay: Z + 1, A unchanged", asks="daughter nuclide after β⁻ emission"),
    Step(tx=221, src="parent_nuclide", dst="daughter_nuclide", needs=_PARENT,
         answer="daughter_nuclide", unit="", kind="text", gives=("Z", "A"),
         fn=lambda v: _decay(v, -1, 0),
         traps=(Trap("wrong_sign", "raises Z by 1", lambda v: _decay(v, 1, 0)),),
         formula="β⁺ decay: Z − 1, A unchanged", asks="daughter nuclide after positron emission"),
    Step(tx=222, src="parent_nuclide", dst="daughter_nuclide", needs=_PARENT,
         answer="daughter_nuclide", unit="", kind="text", gives=("Z", "A"),
         fn=lambda v: _decay(v, -1, 0),
         traps=(Trap("mass_change", "also lowers A by 1", lambda v: _decay(v, -1, -1)),),
         formula="electron capture: Z − 1, A unchanged", asks="daughter nuclide after K-electron capture"),
    Step(tx=224, src="daughter_nuclide", dst="decay_counts",
         needs=(P("Z", "", "atomic number of the final nuclide", kind="posint", lo=5, hi=92),
                P("A", "", "mass number of the final nuclide", kind="posint", lo=10, hi=240),
                P("initial_Z", "", "atomic number of the starting nuclide", kind="posint", lo=5, hi=92),
                P("initial_A", "", "mass number of the starting nuclide", kind="posint", lo=10, hi=240),
                P("count", "", "decays to count", kind="choice", choices=("alpha", "beta"))),
         answer="decay_counts", unit="", kind="count", fn=_decay_counts,
         traps=(Trap("beta_sign", "uses #β = (Z_i − Z_f) − 2#α", lambda v: _decay_counts(v, sign=-1)),),
         formula="#α = (A_i − A_f)/4; #β = 2#α − (Z_i − Z_f)", asks="number of α (or β) particles emitted"),
    Step(tx=225, src="parent_nuclide", dst="daughter_nuclide",
         needs=_PARENT + (P("projectile", "", "particle that bombards the target", kind="choice", choices=tuple(_PROJECTILES)),
                          P("emitted", "", "particle emitted", kind="choice", choices=tuple(_PROJECTILES))),
         answer="daughter_nuclide", unit="", kind="text", gives=("Z", "A"),
         fn=_bombard,
         traps=(Trap("swaps_particles", "adds the emitted particle and removes the projectile", lambda v: _bombard(v, swap=True)),),
         formula="conserve Z and A: target + projectile = product + emitted", asks="product nuclide"),
    Step(tx=226, src="rate_constant", dst="secular_ratio",
         needs=(P("rate_constant", "s⁻¹", "decay constant λ_A of the long-lived parent", lo=1e-18, hi=1e-3, role="radioactive decay"),
                P("daughter_decay_constant", "s⁻¹", "decay constant λ_B of the daughter", lo=1e-12, hi=1)),
         answer="secular_ratio", unit="", kind="positive",
         fn=lambda v: {"secular_ratio": v["rate_constant"] / v["daughter_decay_constant"]},
         traps=(Trap("inverted", "uses λ_B/λ_A", lambda v: v["daughter_decay_constant"] / v["rate_constant"]),),
         formula="secular equilibrium: λ_A N_A = λ_B N_B", asks="N_B/N_A at secular equilibrium"),
    Step(tx=227, src="parent_daughter_ratio", dst="time_elapsed",
         needs=(P("uranium_mass", "g", "mass of U-238 now", lo=0.1, hi=100),
                P("lead_mass", "g", "mass of Pb-206 now", lo=0.01, hi=100),
                P("half_life", "years", "half-life of U-238", lo=1e8, hi=1e10)),
         answer="time_elapsed", unit="years", kind="positive",
         fn=lambda v: {"time_elapsed": v["half_life"] / 0.693 * ln((v["uranium_mass"] + 238 / 206 * v["lead_mass"]) / v["uranium_mass"])},
         traps=(Trap("ignores_mass_ratio", "adds the lead mass directly as uranium",
                     lambda v: v["half_life"] / 0.693 * ln((v["uranium_mass"] + v["lead_mass"]) / v["uranium_mass"])),),
         formula="w₀ = w + (238/206) y; t = (1/λ) ln(w₀/w)", asks="age of the rock (years)"),
    *[Step(tx=tx, src="activity", dst="time_elapsed",
           needs=(P("activity", "counts min⁻¹ g⁻¹", "present activity of the sample", lo=0.1, hi=20),
                  P("initial_activity", "counts min⁻¹ g⁻¹", "activity of fresh (living) material", lo=1, hi=30),
                  P("half_life", "years", "half-life of C-14 used", lo=5500, hi=5800)),
           answer="time_elapsed", unit="years", kind="positive",
           fn=lambda v: {"time_elapsed": v["half_life"] / 0.693 * ln(v["initial_activity"] / v["activity"])},
           traps=(Trap("log10_without_2303", "uses log₁₀ without 2.303",
                       lambda v: v["half_life"] / 0.693 * log10(v["initial_activity"] / v["activity"])),),
           formula="t = (t½/0.693) ln(A₀/A)", asks="age of the sample (years)")
      for tx in (228, 332)],
    Step(tx=229, src="nuclide_masses", dst="mass_defect",
         needs=(P("Z", "", "atomic number", kind="posint", lo=1, hi=92),
                P("A", "", "mass number", kind="posint", lo=2, hi=240),
                P("atomic_mass", "u", "measured atomic mass of the nuclide", lo=2, hi=240)),
         answer="mass_defect", unit="u", kind="positive", gives=("A",),
         fn=lambda v: {"mass_defect": v["Z"] * M_H + (v["A"] - v["Z"]) * M_N - v["atomic_mass"], "A": v["A"]},
         traps=(Trap("forgets_neutrons", "counts only the protons", lambda v: v["Z"] * M_H - v["atomic_mass"] + v["A"] - v["Z"]),),
         constants=(f"mass of ¹H atom = {M_H} u", f"mass of neutron = {M_N} u"),
         formula="Δm = Z m_H + (A − Z) m_n − M", asks="mass defect (u)"),
    Step(tx=230, src="mass_defect", dst="binding_energy",
         needs=(P("mass_defect", "u", "mass defect", lo=0.001, hi=3),
                P("A", "", "mass number", kind="posint", lo=2, hi=240),
                P("which", "", "total or per nucleon", kind="choice", choices=("total", "per nucleon"))),
         answer="binding_energy", unit="MeV", kind="positive",
         fn=lambda v: {"binding_energy": v["mass_defect"] * C.AMU_MEV / (1 if v["which"] == "total" else v["A"])},
         traps=(Trap("per_nucleon_confusion", "reports the total for per-nucleon (or vice versa)",
                     lambda v: v["mass_defect"] * C.AMU_MEV / (v["A"] if v["which"] == "total" else 1)),),
         constants=(const("AMU_MEV"),), formula="BE = Δm × 931.5 MeV; per nucleon = BE/A", asks="binding energy (MeV)"),
    Step(tx=232, src="mass_defect", dst="nuclear_energy",
         needs=(P("mass_defect", "u", "mass lost in the nuclear reaction", lo=0.001, hi=1),),
         answer="nuclear_energy", unit="MeV", kind="positive",
         fn=lambda v: {"nuclear_energy": v["mass_defect"] * C.AMU_MEV},
         constants=(const("AMU_MEV"),), formula="E = Δm × 931.5 MeV", asks="energy released per reaction (MeV)"),
    Step(tx=318, src="half_life_plot", dst="rate_law",
         needs=(P("slope", "", "slope of log t½ vs log a₀", kind="real", lo=-3, hi=1),),
         answer="rate_law", unit="", kind="real",
         fn=lambda v: {"rate_law": 1 - v["slope"]},
         traps=(Trap("sign", "takes n = slope + 1", lambda v: v["slope"] + 1),),
         formula="slope of log t½ vs log a₀ = 1 − n", asks="order of the reaction"),
    Step(tx=333, src="rate_constant", dst="activity",
         needs=(P("rate_constant", "s⁻¹", "decay constant of the isotope", lo=1e-8, hi=1e-3, role="radioactive decay"),
                P("initial_activity", "mCi", "activity at production", lo=1, hi=1000),
                P("time", "h", "time until administration", lo=0.1, hi=100)),
         answer="dose_activity", unit="mCi", kind="positive",
         fn=lambda v: {"dose_activity": v["initial_activity"] * math.exp(-v["rate_constant"] * v["time"] * 3600)},
         traps=(Trap("hours_not_converted", "uses t in hours with λ in s⁻¹",
                     lambda v: v["initial_activity"] * math.exp(-v["rate_constant"] * v["time"])),),
         formula="A = A₀ e^(−λt)", asks="activity at administration (mCi)"),
]


def _t_half(v):
    n, k, a = v["order"], v["rate_constant"], v["initial_concentration"]
    if math.isclose(n, 1.0):
        raise EngineError("use the first-order relation for n = 1")
    return (2 ** (n - 1) - 1) / (k * (n - 1) * a ** (n - 1))


def _nz(x):
    if x == 0:
        raise EngineError("division by zero")
    return x
