"""Physical engine — Chemical and Ionic Equilibrium (concept-book TXs 151-199, 315, 316)."""

from __future__ import annotations

import math

from core.engine.base import EngineError, Param, Step, Trap, log10, solve_bisect, sqrt
from core.engine.chem import C, check_balanced, const, parse_equation

P = Param
KW = C.KW_25


def _gas_delta_n(eq_text, gases=None):
    r, p = parse_equation(eq_text)
    gases = gases or {f for _, f in r + p}
    return sum(c for c, f in p if f in gases) - sum(c for c, f in r if f in gases)


def _mass_action(eq_text, values, use_powers=True):
    check_balanced(eq_text)
    r, p = parse_equation(eq_text)
    vals = {k.replace(" ", ""): float(x) for k, x in values.items()}
    k = 1.0
    for sign, side in ((1, p), (-1, r)):
        for c, f in side:
            key = f.replace(" ", "")
            if key not in vals:
                raise EngineError(f"no value for {f}")
            if vals[key] <= 0:
                raise EngineError(f"{f} must be positive")
            k *= vals[key] ** (sign * (c if use_powers else 1))
    return k


def _ice_alpha(v, use_coef=True):
    eq = v["balanced_equation"]
    check_balanced(eq)
    r, p = parse_equation(eq)
    if len(r) != 1:
        raise EngineError("degree-of-dissociation tables need a single reactant")
    nu_r, reac = r[0]
    n0, a = v["moles"], v["gas_dissociation_degree"]
    amounts = {reac: n0 * (1 - a)}
    for c, f in p:
        amounts[f] = n0 * a * (c / nu_r if use_coef else 1)
    target = v["species_asked"]
    if target not in amounts:
        raise EngineError(f"{target} is not in the equation")
    return {"equilibrium_moles": amounts[target], "eq_amounts": amounts, "balanced_equation": eq,
            "total_moles": sum(amounts.values())}


def _strong_acid_h(c, basicity):
    ca = c * basicity
    return (ca + sqrt(ca * ca + 4 * KW)) / 2


def _weak_h(K, Cc):
    return (-K + sqrt(K * K + 4 * K * Cc)) / 2


def _quad_common_ion(ksp, c):
    return (-c + sqrt(c * c + 4 * ksp)) / 2


def _pH(h):
    return -log10(h)


def _shift(v, reverse=False):
    q = _mass_action(v["balanced_equation"], v["current_concentrations"])
    K = v["equilibrium_constant"]
    if math.isclose(q, K, rel_tol=1e-3):
        return "at equilibrium"
    forward = q < K
    if reverse:
        forward = not forward
    return "forward" if forward else "backward"


_MANIP = ("reverse the reaction", "multiply the reaction by 2", "halve the reaction")


def _manipulate(v, wrong=False):
    K, how = v["equilibrium_constant"], v["manipulation"]
    if how == _MANIP[0]:
        return -K if wrong else 1 / K
    if how == _MANIP[1]:
        return 2 * K if wrong else K ** 2
    return K / 2 if wrong else sqrt(K)


def _mixing_q(v, dilute=True):
    vt = v["volume_1"] + v["volume_2"]
    c1 = v["cation_concentration"] * (v["volume_1"] / vt if dilute else 1)
    c2 = v["anion_concentration"] * (v["volume_2"] / vt if dilute else 1)
    return c1 ** v["cation_count"] * c2 ** v["anion_count"]


def _precipitates(v, dilute=True):
    return "precipitate forms" if _mixing_q(v, dilute) > v["solubility_product"] else "no precipitate"


_CHANGES = {
    "increase the pressure by compression": "pressure+",
    "decrease the pressure by expansion": "pressure-",
    "increase the temperature": "temperature+",
    "decrease the temperature": "temperature-",
    "add more of a reactant": "reactant+",
    "remove some product": "product-",
    "add more of a product": "product+",
    "add an inert gas at constant volume": "inert_V",
    "add an inert gas at constant pressure": "inert_P",
    "add a catalyst": "catalyst",
}


def _le_chatelier(v, wrong=None):
    """Direction an equilibrium shifts: 'forward', 'backward' or 'no shift'."""
    from core.engine.physical.thermo import _dn_all, _dng
    eq, dh, change = v["balanced_equation"], v["delta_h"], _CHANGES[v["change"]]
    dn = _dn_all(eq) if wrong == "counts_condensed" else _dng(eq)
    sign = lambda x: "forward" if x > 0 else ("backward" if x < 0 else "no shift")
    if change == "pressure+":
        return sign(-dn)
    if change == "pressure-":
        return sign(dn)
    if change == "temperature+":
        return sign(dh)
    if change == "temperature-":
        return sign(-dh)
    if change in ("reactant+", "product-"):
        return "forward"
    if change == "product+":
        return "backward"
    if change == "inert_V":
        return sign(dn) if wrong == "inert_like_pressure" else "no shift"
    if change == "inert_P":
        return "no shift" if wrong == "inert_like_pressure" else sign(dn)
    return "no shift"


def _le_chatelier_step(tx, changes, what):
    return Step(
        tx=tx, src="equilibrium_reaction", dst="direction_of_shift",
        needs=(P("balanced_equation", "", "the equilibrium with the state of every species, e.g. "
                 "'N2(g) + 3H2(g) -> 2NH3(g)'", kind="text"),
               P("delta_h", "kJ mol⁻¹", "ΔH of the forward reaction", kind="real", lo=-300, hi=300),
               P("change", "", f"the change made ({what})", kind="choice", choices=tuple(changes))),
        answer="direction_of_shift", unit="", kind="text",
        fn=lambda v: {"direction_of_shift": _le_chatelier(v)},
        traps=(Trap("counts_condensed", "counts solids and liquids in Δn", lambda v: _le_chatelier(v, "counts_condensed")),
               Trap("inert_like_pressure", "treats inert gas at constant volume like a pressure rise (or at "
                    "constant pressure as having no effect)", lambda v: _le_chatelier(v, "inert_like_pressure")),
               Trap("reversed", "shifts towards the side that adds to the disturbance",
                    lambda v: {"forward": "backward", "backward": "forward"}.get(_le_chatelier(v), "forward"))),
        formula="Le Chatelier: the shift opposes the change; pressure acts through Δn_g, temperature through the sign of ΔH",
        asks="direction in which the equilibrium shifts (forward, backward or no shift)")


_C = list(_CHANGES)

STEPS = [
    _le_chatelier_step(161, _C[4:7] + _C[9:], "a concentration change or a catalyst"),
    _le_chatelier_step(162, _C[0:2] + _C[9:], "a pressure change"),
    _le_chatelier_step(164, _C[7:9] + _C[0:1], "adding an inert gas"),
    _le_chatelier_step(166, _C[0:4], "pressure or temperature on a gas dissolving, e.g. 'CO2(g) -> CO2(aq)'"),
    _le_chatelier_step(167, _C[2:4], "temperature on a solid dissolving, e.g. 'KNO3(s) -> KNO3(aq)'"),
    # ── Chemical Equilibrium ──
    Step(tx=151, src="moles", dst="equilibrium_moles",
         needs=(P("balanced_equation", "", "dissociation equilibrium with one reactant, e.g. 'PCl5 -> PCl3 + Cl2'", kind="text"),
                P("moles", "mol", "initial amount of the reactant", lo=0.1, hi=10, role="dissociating reactant"),
                P("gas_dissociation_degree", "", "degree of dissociation α", kind="open_fraction", lo=0.05, hi=0.9),
                P("species_asked", "", "species whose equilibrium amount is asked", kind="text")),
         answer="equilibrium_moles", unit="mol", kind="positive",
         gives=("eq_amounts", "balanced_equation", "total_moles"), fn=_ice_alpha,
         traps=(Trap("ignores_coefficients", "takes every product amount as n₀α",
                     lambda v: _ice_alpha(v, use_coef=False)),),
         formula="reactant n₀(1 − α); product n₀α ν/ν_reactant", asks="equilibrium amount of the species (mol)"),
    Step(tx=152, src="equilibrium_moles", dst="equilibrium_constant",
         needs=(P("balanced_equation", "", "balanced equation", kind="text"),
                P("eq_amounts", "mol", "equilibrium amount of each species (gases/solutes only)", kind="dict"),
                P("volume", "L", "volume of the vessel", lo=0.1, hi=20)),
         answer="equilibrium_constant", unit="", kind="positive", roles={"equilibrium_constant": "Kc"},
         fn=lambda v: {"equilibrium_constant": _mass_action(v["balanced_equation"],
                                                            {k: x / v["volume"] for k, x in v["eq_amounts"].items()})},
         traps=(Trap("uses_moles", "puts amounts instead of concentrations into K_c",
                     lambda v: _mass_action(v["balanced_equation"], v["eq_amounts"])),
                Trap("ignores_powers", "ignores the stoichiometric powers",
                     lambda v: _mass_action(v["balanced_equation"], {k: x / v["volume"] for k, x in v["eq_amounts"].items()}, False))),
         formula="K_c = Π[products]^ν / Π[reactants]^ν", asks="K_c"),
    Step(tx=153, src="partial_pressure", dst="equilibrium_constant",
         needs=(P("balanced_equation", "", "balanced equation (gaseous species)", kind="text"),
                P("partial_pressures", "atm", "equilibrium partial pressure of each gas", kind="dict")),
         answer="equilibrium_constant", unit="", kind="positive", roles={"equilibrium_constant": "Kp"},
         fn=lambda v: {"equilibrium_constant": _mass_action(v["balanced_equation"], v["partial_pressures"])},
         traps=(Trap("ignores_powers", "ignores the stoichiometric powers",
                     lambda v: _mass_action(v["balanced_equation"], v["partial_pressures"], False)),),
         formula="K_p = Πp(products)^ν / Πp(reactants)^ν", asks="K_p"),
    Step(tx=154, src="equilibrium_constant", dst="equilibrium_constant",
         needs=(P("equilibrium_constant", "", "K_c", lo=1e-6, hi=1e6, role="Kc"),
                P("balanced_equation", "", "balanced equation (all species gaseous)", kind="text"),
                P("T", "K", "temperature", kind="temperature", lo=250, hi=1500)),
         answer="equilibrium_constant", unit="", kind="positive", roles={"equilibrium_constant": "Kp"},
         fn=lambda v: {"equilibrium_constant": v["equilibrium_constant"] * (C.R_LATM * v["T"]) ** _gas_delta_n(v["balanced_equation"])},
         traps=(Trap("delta_n_sign", "uses (RT)^(−Δn)",
                     lambda v: v["equilibrium_constant"] * (C.R_LATM * v["T"]) ** -_gas_delta_n(v["balanced_equation"])),
                Trap("wrong_R", "uses R = 8.314",
                     lambda v: v["equilibrium_constant"] * (C.R_J * v["T"]) ** _gas_delta_n(v["balanced_equation"]))),
         constants=(const("R_LATM"),), formula="K_p = K_c (RT)^Δn_g", asks="K_p"),
    Step(tx=155, src="equilibrium_constant", dst="equilibrium_constant",
         needs=(P("equilibrium_constant", "", "K_p (atm units)", lo=1e-6, hi=1e6, role="Kp"),
                P("balanced_equation", "", "balanced equation (all species gaseous)", kind="text"),
                P("total_pressure", "atm", "total equilibrium pressure", lo=0.1, hi=50)),
         answer="equilibrium_constant", unit="", kind="positive", roles={"equilibrium_constant": "Kx"},
         fn=lambda v: {"equilibrium_constant": v["equilibrium_constant"] * v["total_pressure"] ** -_gas_delta_n(v["balanced_equation"])},
         traps=(Trap("power_sign", "uses P^Δn", lambda v: v["equilibrium_constant"] * v["total_pressure"] ** _gas_delta_n(v["balanced_equation"])),),
         formula="K_p = K_x P^Δn", asks="K_x"),
    Step(tx=156, src="equilibrium_constant", dst="equilibrium_constant",
         needs=(P("equilibrium_constant", "", "K of the original reaction", lo=1e-6, hi=1e6),
                P("manipulation", "", "how the reaction is changed", kind="choice", choices=_MANIP)),
         answer="equilibrium_constant", unit="", kind="positive",
         fn=lambda v: {"equilibrium_constant": _manipulate(v)},
         traps=(Trap("arithmetic_instead_of_power", "negates, doubles or halves K instead",
                     lambda v: _manipulate(v, wrong=True)),),
         formula="reverse: 1/K; ×2: K²; ×½: √K", asks="K of the new reaction"),
    Step(tx=157, src="equilibrium_constant", dst="direction_of_shift",
         needs=(P("equilibrium_constant", "", "K at the temperature", lo=1e-6, hi=1e6),
                P("balanced_equation", "", "balanced equation", kind="text"),
                P("current_concentrations", "mol L⁻¹", "concentration of each species at the moment considered", kind="dict")),
         answer="direction_of_shift", unit="", kind="text",
         fn=lambda v: {"direction_of_shift": _shift(v)},
         traps=(Trap("reversed_criterion", "shifts forward when Q > K", lambda v: _shift(v, reverse=True)),),
         formula="Q < K forward; Q > K backward; Q = K at equilibrium", asks="direction the reaction proceeds"),
    Step(tx=159, src="vapour_density", dst="degree_of_dissociation",
         needs=(P("vapour_density", "", "observed vapour density of the equilibrium mixture", lo=5, hi=200),
                P("theoretical_vapour_density", "", "vapour density if undissociated", lo=5, hi=300),
                P("particles_per_molecule", "", "n in A → nB", kind="posint", lo=2, hi=4)),
         answer="gas_dissociation_degree", unit="", kind="open_fraction",
         fn=lambda v: {"gas_dissociation_degree": (v["theoretical_vapour_density"] - v["vapour_density"])
                       / (v["vapour_density"] * (v["particles_per_molecule"] - 1))},
         traps=(Trap("forgets_n_minus_1", "divides by d only",
                     lambda v: (v["theoretical_vapour_density"] - v["vapour_density"]) / v["vapour_density"]),),
         formula="α = (D − d)/(d(n − 1))", asks="degree of dissociation"),
    Step(tx=160, src="degree_of_dissociation", dst="equilibrium_constant",
         needs=(P("gas_dissociation_degree", "", "degree of dissociation of a PCl5-type (1 → 2) gas", kind="open_fraction", lo=0.05, hi=0.9),
                P("total_pressure", "atm", "total equilibrium pressure", lo=0.1, hi=20)),
         answer="equilibrium_constant", unit="atm", kind="positive", roles={"equilibrium_constant": "Kp"},
         fn=lambda v: {"equilibrium_constant": v["gas_dissociation_degree"] ** 2 * v["total_pressure"]
                       / (1 - v["gas_dissociation_degree"] ** 2)},
         traps=(Trap("forgets_total_moles", "uses α²P/(1 − α)",
                     lambda v: v["gas_dissociation_degree"] ** 2 * v["total_pressure"] / (1 - v["gas_dissociation_degree"])),),
         formula="K_p = α²P/(1 − α²)", asks="K_p (atm)"),
    Step(tx=163, src="equilibrium_constant", dst="equilibrium_constant",
         needs=(P("equilibrium_constant", "", "K at T₁", lo=1e-6, hi=1e6),
                P("delta_h", "kJ mol⁻¹", "standard enthalpy change", kind="real", lo=-200, hi=200),
                P("T1", "K", "temperature T₁", kind="temperature", lo=250, hi=1200),
                P("T2", "K", "temperature T₂", kind="temperature", lo=250, hi=1200)),
         answer="equilibrium_constant", unit="", kind="positive",
         fn=lambda v: {"equilibrium_constant": v["equilibrium_constant"]
                       * math.exp(1000 * v["delta_h"] / C.R_J * (v["T2"] - v["T1"]) / (v["T1"] * v["T2"]))},
         traps=(Trap("sign", "uses the opposite sign in the exponent",
                     lambda v: v["equilibrium_constant"]
                     * math.exp(-1000 * v["delta_h"] / C.R_J * (v["T2"] - v["T1"]) / (v["T1"] * v["T2"]))),),
         constants=(const("R_J"),), formula="ln(K₂/K₁) = (ΔH/R)(T₂ − T₁)/(T₁T₂)", asks="K at T₂"),
    Step(tx=170, src="equilibrium_constant", dst="gas_state",
         needs=(P("Kp_solid_decomposition", "atm²", "K_p of A(s) ⇌ X(g) + Y(g)", lo=1e-4, hi=100),
                P("K2", "atm²", "K_p of B(s) ⇌ X(g) + Z(g) in the same vessel", lo=1e-4, hi=100)),
         answer="P", unit="atm", kind="positive",
         fn=lambda v: {"P": 2 * sqrt(v["Kp_solid_decomposition"] + v["K2"])},
         traps=(Trap("independent_equilibria", "treats the two equilibria separately",
                     lambda v: 2 * (sqrt(v["Kp_solid_decomposition"]) + sqrt(v["K2"]))),),
         formula="p_X = p_Y + p_Z; K₁ + K₂ = p_X² → P_total = 2√(K₁ + K₂)", asks="total pressure at equilibrium (atm)"),
    Step(tx=315, src="vant_hoff_plot", dst="delta_h",
         needs=(P("slope", "K", "slope of the plot against 1/T", kind="negative", lo=-20000, hi=-100),
                P("plot", "", "what is plotted against 1/T", kind="choice", choices=("ln K", "log K"))),
         answer="delta_h", unit="kJ mol⁻¹", kind="real",
         fn=lambda v: {"delta_h": -v["slope"] * C.R_J * (1 if v["plot"] == "ln K" else 2.303) / 1000},
         traps=(Trap("forgets_2303", "omits 2.303 for a log K plot (or adds it for ln K)",
                     lambda v: -v["slope"] * C.R_J * (2.303 if v["plot"] == "ln K" else 1) / 1000),
                Trap("sign", "takes ΔH = slope × R", lambda v: v["slope"] * C.R_J * (1 if v["plot"] == "ln K" else 2.303) / 1000)),
         constants=(const("R_J"),), formula="ln K = −ΔH°/RT + ΔS°/R: slope = −ΔH°/R",
         asks="standard enthalpy change (kJ mol⁻¹)"),
    # ── Ionic Equilibrium ──
    Step(tx=173, src="dissociation_constant", dst="degree_of_dissociation",
         needs=(P("dissociation_constant", "", "K_a (or K_b) of the weak electrolyte", lo=1e-10, hi=1e-1),
                P("concentration", "mol L⁻¹", "concentration", lo=1e-4, hi=2)),
         answer="degree_of_dissociation", unit="", kind="open_fraction",
         fn=lambda v: {"degree_of_dissociation": _weak_h(v["dissociation_constant"], v["concentration"]) / v["concentration"]},
         traps=(Trap("sqrt_KC", "uses √(KC)", lambda v: sqrt(v["dissociation_constant"] * v["concentration"])),
                Trap("approximation_when_large", "uses √(K/C) although α is not small",
                     lambda v: sqrt(v["dissociation_constant"] / v["concentration"]))),
         formula="K = Cα²/(1 − α) (≈ √(K/C) when α ≪ 1)", asks="degree of dissociation"),
    Step(tx=174, src="molarity", dst="ph",
         needs=(P("molarity", "mol L⁻¹", "concentration of the strong acid", lo=1e-9, hi=1, role="strong acid"),
                P("basicity", "", "H⁺ released per formula unit", kind="posint", lo=1, hi=3)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _pH(_strong_acid_h(v["molarity"], v["basicity"]))},
         traps=(Trap("ignores_water", "ignores H⁺ from water (pH > 7 for a very dilute acid)",
                     lambda v: _pH(v["molarity"] * v["basicity"])),
                Trap("forgets_basicity", "counts one H⁺ per formula unit", lambda v: _pH(_strong_acid_h(v["molarity"], 1)))),
         constants=(const("KW_25"),), formula="pH = −log[H⁺]; [H⁺] = C·basicity (+ water for very dilute acid)",
         asks="pH"),
    Step(tx=175, src="dissociation_constant", dst="ph",
         needs=(P("dissociation_constant", "", "K_a of the weak acid", lo=1e-10, hi=1e-2),
                P("concentration", "mol L⁻¹", "concentration of the acid", lo=1e-3, hi=2)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _pH(_weak_h(v["dissociation_constant"], v["concentration"]))},
         traps=(Trap("forgets_sqrt", "uses [H⁺] = K_aC", lambda v: _pH(v["dissociation_constant"] * v["concentration"])),
                Trap("treats_as_strong", "takes [H⁺] = C", lambda v: _pH(v["concentration"]))),
         formula="[H⁺] = √(K_aC); pH = ½(pK_a − log C)", asks="pH"),
    Step(tx=176, src="dissociation_constant", dst="ph",
         needs=(P("Kb", "", "K_b of the weak base", lo=1e-10, hi=1e-2),
                P("concentration", "mol L⁻¹", "concentration of the base", lo=1e-3, hi=2)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": 14 + log10(_weak_h(v["Kb"], v["concentration"]))},
         traps=(Trap("reports_pOH", "reports pOH as pH", lambda v: -log10(_weak_h(v["Kb"], v["concentration"]))),),
         constants=(const("KW_25"),), formula="[OH⁻] = √(K_bC); pH = 14 − pOH", asks="pH"),
    Step(tx=177, src="water_ionization", dst="ph",
         needs=(P("ionization_enthalpy", "kJ mol⁻¹", "enthalpy of ionisation of water", lo=50, hi=60),
                P("T", "K", "temperature", kind="temperature", lo=273, hi=373)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": -0.5 * log10(KW * math.exp(1000 * v["ionization_enthalpy"] / C.R_J * (v["T"] - 298) / (298 * v["T"])))},
         traps=(Trap("neutral_is_7", "assumes neutral pH is 7 at every temperature", lambda v: 7.0),),
         constants=(const("KW_25"), const("R_J")), formula="ln(K_w₂/K_w₁) = (ΔH/R)(T₂ − T₁)/(T₁T₂); neutral pH = −½ log K_w",
         asks="pH of pure water at that temperature"),
    Step(tx=178, src="dissociation_constant", dst="dissociation_constant",
         needs=(P("dissociation_constant", "", "K_a of the acid", lo=1e-12, hi=1e-2),),
         answer="Kb", unit="", kind="positive",
         fn=lambda v: {"Kb": KW / v["dissociation_constant"]},
         traps=(Trap("multiplies_by_kw", "multiplies K_w by K_a instead of dividing",
                     lambda v: KW * v["dissociation_constant"]),),
         constants=(const("KW_25"),), formula="K_a K_b = K_w (conjugate pair)", asks="K_b of the conjugate base"),
    Step(tx=179, src="dissociation_constant", dst="ph",
         needs=(P("dissociation_constant", "", "K_a of acid 1", lo=1e-10, hi=1e-3),
                P("concentration", "mol L⁻¹", "concentration of acid 1", lo=1e-3, hi=1),
                P("Ka2", "", "K_a of acid 2", lo=1e-10, hi=1e-3),
                P("concentration_2", "mol L⁻¹", "concentration of acid 2", lo=1e-3, hi=1)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _pH(sqrt(v["dissociation_constant"] * v["concentration"] + v["Ka2"] * v["concentration_2"]))},
         traps=(Trap("adds_separately", "adds the two [H⁺] values computed separately",
                     lambda v: _pH(sqrt(v["dissociation_constant"] * v["concentration"]) + sqrt(v["Ka2"] * v["concentration_2"]))),),
         formula="[H⁺] = √(K₁C₁ + K₂C₂)", asks="pH of the mixture"),
    Step(tx=181, src="molarity", dst="ph",
         needs=(P("molarity", "mol L⁻¹", "concentration of the salt of a strong acid and weak base", lo=1e-3, hi=1, role="salt of strong acid and weak base"),
                P("Kb", "", "K_b of the weak base", lo=1e-10, hi=1e-3)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": 7 - 0.5 * (-log10(v["Kb"]) + log10(v["molarity"]))},
         traps=(Trap("wrong_sign", "uses 7 + ½(pK_b + log C)", lambda v: 7 + 0.5 * (-log10(v["Kb"]) + log10(v["molarity"]))),),
         constants=(const("KW_25"),), formula="pH = 7 − ½(pK_b + log C)", asks="pH of the salt solution"),
    Step(tx=182, src="molarity", dst="ph",
         needs=(P("molarity", "mol L⁻¹", "concentration of the salt of a weak acid and strong base", lo=1e-3, hi=1, role="salt of weak acid and strong base"),
                P("Ka", "", "K_a of the weak acid", lo=1e-10, hi=1e-3)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": 7 + 0.5 * (-log10(v["Ka"]) + log10(v["molarity"]))},
         traps=(Trap("wrong_sign", "uses 7 − ½(pK_a + log C)", lambda v: 7 - 0.5 * (-log10(v["Ka"]) + log10(v["molarity"]))),),
         constants=(const("KW_25"),), formula="pH = 7 + ½(pK_a + log C)", asks="pH of the salt solution"),
    Step(tx=183, src="dissociation_constant", dst="ph",
         needs=(P("dissociation_constant", "", "K_a of the weak acid", lo=1e-10, hi=1e-3),
                P("Kb", "", "K_b of the weak base", lo=1e-10, hi=1e-3)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": 7 + 0.5 * (-log10(v["dissociation_constant"]) + log10(v["Kb"]))},
         traps=(Trap("swapped", "uses 7 + ½(pK_b − pK_a)", lambda v: 7 + 0.5 * (-log10(v["Kb"]) + log10(v["dissociation_constant"]))),),
         constants=(const("KW_25"),), formula="pH = 7 + ½(pK_a − pK_b) (independent of C)", asks="pH of the salt solution"),
    Step(tx=184, src="dissociation_constant", dst="ph",
         needs=(P("dissociation_constant", "", "K₁ of the parent acid", lo=1e-10, hi=1e-2),
                P("K2", "", "K₂ of the parent acid", lo=1e-14, hi=1e-4)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": 0.5 * (-log10(v["dissociation_constant"]) - log10(v["K2"]))},
         traps=(Trap("averages_K", "averages K₁ and K₂ before taking the log",
                     lambda v: -log10((v["dissociation_constant"] + v["K2"]) / 2)),),
         formula="pH = ½(pK₁ + pK₂)", asks="pH of the amphiprotic salt solution"),
    Step(tx=185, src="buffer_ratio", dst="ph",
         needs=(P("buffer_ratio", "", "[salt]/[acid] ratio of the acidic buffer", lo=0.05, hi=20),
                P("dissociation_constant", "", "K_a of the weak acid", lo=1e-10, hi=1e-2)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _henderson(v)},
         traps=(Trap("inverted_ratio", "uses log([acid]/[salt])", lambda v: _henderson(v, invert=True)),),
         formula="pH = pK_a + log([salt]/[acid])",
         asks="pH of the buffer"),
    Step(tx=186, src="buffer_ratio", dst="ph",
         needs=(P("acid_moles", "mol", "amount of weak acid in the buffer", lo=1e-3, hi=1),
                P("salt_moles", "mol", "amount of its salt in the buffer", lo=1e-3, hi=1),
                P("added_base_moles", "mol", "strong base added (use a negative value for strong acid)", kind="real", lo=-0.5, hi=0.5),
                P("Ka", "", "K_a of the weak acid", lo=1e-10, hi=1e-2)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": -log10(v["Ka"]) + log10(_pos(v["salt_moles"] + v["added_base_moles"])
                                                      / _pos(v["acid_moles"] - v["added_base_moles"]))},
         traps=(Trap("ignores_addition", "uses the buffer ratio before the addition",
                     lambda v: -log10(v["Ka"]) + log10(v["salt_moles"] / v["acid_moles"])),),
         formula="added base converts acid → salt; then Henderson", asks="pH after the addition"),
    Step(tx=187, src="moles", dst="buffer_ratio",
         needs=(P("moles", "mol", "amount of weak acid", lo=1e-3, hi=1, role="weak acid"),
                P("strong_base_moles", "mol", "amount of strong base added (less than the acid)", lo=1e-4, hi=1)),
         answer="buffer_ratio", unit="", kind="positive", gives=("acid_moles", "salt_moles"),
         fn=lambda v: {"buffer_ratio": v["strong_base_moles"] / _pos(v["moles"] - v["strong_base_moles"]),
                       "acid_moles": v["moles"] - v["strong_base_moles"], "salt_moles": v["strong_base_moles"]},
         traps=(Trap("forgets_consumed_acid", "divides by the initial acid amount",
                     lambda v: {"buffer_ratio": v["strong_base_moles"] / v["moles"], "acid_moles": v["moles"]}),),
         formula="WA + insufficient SB: salt = n_SB, acid = n_WA − n_SB", asks="[salt]/[acid] ratio"),
    Step(tx=189, src="dissociation_constant", dst="indicator_ratio",
         needs=(P("indicator_constant", "", "K_In of the indicator", lo=1e-11, hi=1e-3),
                P("ph", "", "pH of the solution", kind="ph", lo=1, hi=13)),
         answer="indicator_ratio", unit="", kind="positive",
         fn=lambda v: {"indicator_ratio": 10 ** (v["ph"] + log10(v["indicator_constant"]))},
         traps=(Trap("inverted", "gives [HIn]/[In⁻]", lambda v: 10 ** -(v["ph"] + log10(v["indicator_constant"]))),),
         formula="pH = pK_In + log([In⁻]/[HIn])", asks="[In⁻]/[HIn]"),
    *[Step(tx=tx, src="ph", dst="dissociation_constant",
           needs=(P("ph", "", "pH at the half-equivalence point", kind="ph", lo=2, hi=12, role="half-equivalence point"),),
           answer="dissociation_constant", unit="", kind="positive",
           fn=lambda v: {"dissociation_constant": 10 ** -v["ph"]},
           traps=(Trap("weak_acid_formula", "applies [H⁺] = √(K_aC) with C = 1", lambda v: 10 ** (-2 * v["ph"])),),
           formula="at half-equivalence [salt] = [acid] so pH = pK_a", asks="K_a of the acid")
      for tx in (191, 316)],
    Step(tx=192, src="dissociation_constant", dst="ph",
         needs=(P("dissociation_constant", "", "first dissociation constant K₁", lo=1e-8, hi=1e-2),
                P("concentration", "mol L⁻¹", "concentration of the polyprotic acid", lo=1e-3, hi=1)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _pH(_weak_h(v["dissociation_constant"], v["concentration"]))},
         traps=(Trap("full_dissociation", "assumes both protons are released", lambda v: _pH(2 * v["concentration"])),),
         formula="K₁ ≫ K₂: only the first step sets [H⁺]", asks="pH"),
    Step(tx=193, src="solubility", dst="solubility_product",
         needs=(P("solubility", "mol L⁻¹", "molar solubility S", lo=1e-10, hi=1e-1),
                P("cation_count", "", "x in AxBy", kind="posint", lo=1, hi=3),
                P("anion_count", "", "y in AxBy", kind="posint", lo=1, hi=3)),
         answer="solubility_product", unit="", kind="positive", gives=("cation_count", "anion_count"),
         fn=lambda v: {"solubility_product": _ksp(v), "cation_count": v["cation_count"], "anion_count": v["anion_count"]},
         traps=(Trap("forgets_coefficients", "uses S^(x+y) only",
                     lambda v: v["solubility"] ** (v["cation_count"] + v["anion_count"])),),
         formula="K_sp = x^x y^y S^(x+y)", asks="solubility product"),
    Step(tx=194, src="solubility_product", dst="precipitation",
         needs=(P("solubility_product", "", "K_sp of the salt", lo=1e-40, hi=1e-2),
                P("cation_concentration", "mol L⁻¹", "concentration of the cation solution before mixing", lo=1e-8, hi=1),
                P("volume_1", "mL", "volume of the cation solution", lo=1, hi=1000),
                P("anion_concentration", "mol L⁻¹", "concentration of the anion solution before mixing", lo=1e-8, hi=1),
                P("volume_2", "mL", "volume of the anion solution", lo=1, hi=1000),
                P("cation_count", "", "x in AxBy", kind="posint", lo=1, hi=3),
                P("anion_count", "", "y in AxBy", kind="posint", lo=1, hi=3)),
         answer="precipitation", unit="", kind="text",
         fn=lambda v: {"precipitation": _precipitates(v)},
         traps=(Trap("forgets_dilution", "uses concentrations before mixing", lambda v: _precipitates(v, dilute=False)),),
         formula="ionic product Q (after mixing) vs K_sp", asks="whether a precipitate forms"),
    Step(tx=195, src="solubility_product", dst="solubility",
         needs=(P("solubility_product", "", "K_sp of the AxBy salt", lo=1e-30, hi=1e-4),
                P("cation_count", "", "x in AxBy", kind="posint", lo=1, hi=3),
                P("anion_count", "", "y in AxBy", kind="posint", lo=1, hi=3),
                P("common_ion", "", "which ion is already present", kind="choice", choices=("anion", "cation")),
                P("common_ion_concentration", "mol L⁻¹", "concentration of the common ion already present", lo=1e-4, hi=1)),
         answer="solubility", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"solubility": _common_ion_s(v)},
         traps=(Trap("ignores_common_ion", "ignores the common ion",
                     lambda v: _common_ion_s(dict(v, common_ion_concentration=0.0))),),
         formula="K_sp = (xS)^x (yS + c)^y (common anion) or (xS + c)^x (yS)^y",
         asks="solubility in the presence of the common ion (mol L⁻¹)"),
    Step(tx=196, src="solubility_product", dst="solubility",
         needs=(P("Ksp_AB", "", "K_sp of AB-type salt 1 (e.g. AgCl)", lo=1e-20, hi=1e-4),
                P("Ksp2", "", "K_sp of AB-type salt 2 sharing the cation (e.g. AgBr)", lo=1e-20, hi=1e-4)),
         answer="solubility", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"solubility": v["Ksp_AB"] / sqrt(v["Ksp_AB"] + v["Ksp2"])},
         traps=(Trap("ignores_other_salt", "uses √K_sp of salt 1 alone", lambda v: sqrt(v["Ksp_AB"])),),
         formula="x(x + y) = K₁, y(x + y) = K₂ → x = K₁/√(K₁ + K₂)", asks="solubility of salt 1 (mol L⁻¹)"),
    Step(tx=197, src="solubility_product", dst="solubility",
         needs=(P("Ksp_AB", "", "K_sp of the AB-type salt (e.g. AgBr)", lo=1e-20, hi=1e-8),
                P("Kf", "", "formation constant of the complex [M(L)₂]⁺", lo=1e5, hi=1e9),
                P("ligand_concentration", "mol L⁻¹", "initial concentration of the ligand (e.g. NH3)", lo=0.01, hi=6)),
         answer="solubility", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"solubility": (lambda r: v["ligand_concentration"] * r / (1 + 2 * r))(sqrt(v["Ksp_AB"] * v["Kf"]))},
         traps=(Trap("ignores_ligand_use", "ignores the ligand used up in the complex",
                     lambda v: v["ligand_concentration"] * sqrt(v["Ksp_AB"] * v["Kf"])),),
         formula="K = K_sp K_f = x²/(z − 2x)²", asks="solubility in the ligand solution (mol L⁻¹)"),
    Step(tx=198, src="solubility_product", dst="precipitation",
         needs=(P("Ksp_AB", "", "K_sp of salt with ion 1 (AB type)", lo=1e-20, hi=1e-4),
                P("Ksp2", "", "K_sp of salt with ion 2 (AB type, same precipitant)", lo=1e-20, hi=1e-4),
                P("concentration_1", "mol L⁻¹", "concentration of ion 1", lo=1e-5, hi=1),
                P("concentration_2", "mol L⁻¹", "concentration of ion 2", lo=1e-5, hi=1)),
         answer="precipitation", unit="", kind="text",
         fn=lambda v: {"precipitation": _first(v)},
         traps=(Trap("compares_raw_ksp", "picks the salt with the smaller K_sp",
                     lambda v: "ion 1 precipitates first" if v["Ksp_AB"] < v["Ksp2"] else "ion 2 precipitates first"),),
         formula="ion needing the lower [precipitant] = K_sp/c precipitates first", asks="which ion precipitates first"),
    Step(tx=199, src="moles", dst="ph",
         needs=(P("moles", "mol", "H⁺ from the strong acid", lo=1e-4, hi=1, role="H+ from a strong acid"),
                P("acid_volume", "mL", "volume of the acid", lo=1, hi=1000),
                P("base_moles", "mol", "OH⁻ from the strong base", lo=1e-4, hi=1),
                P("base_volume", "mL", "volume of the base", lo=1, hi=1000)),
         answer="ph", unit="", kind="ph", roles={"ph": "solution"},
         fn=lambda v: {"ph": _mix_ph(v, v["acid_volume"] + v["base_volume"])},
         traps=(Trap("ignores_total_volume", "divides by the acid's volume only", lambda v: _mix_ph(v, v["acid_volume"])),),
         constants=(const("KW_25"),), formula="excess H⁺ or OH⁻ over the total volume decides the pH",
         asks="pH of the mixture"),
]


def _henderson(v, invert=False):
    r = v["buffer_ratio"]
    if invert:
        r = 1 / r
    return -log10(v["dissociation_constant"]) + log10(r)


def _common_ion_s(v):
    x, y, ksp, c = v["cation_count"], v["anion_count"], v["solubility_product"], v["common_ion_concentration"]
    if v["common_ion"] == "anion":
        f = lambda s: (x * s) ** x * (y * s + c) ** y - ksp
    else:
        f = lambda s: (x * s + c) ** x * (y * s) ** y - ksp
    hi = 1.0
    while f(hi) < 0:
        hi *= 10
    return solve_bisect(f, 0.0, hi)


def _ksp(v):
    x, y, s = v["cation_count"], v["anion_count"], v["solubility"]
    return (x ** x) * (y ** y) * s ** (x + y)


def _first(v):
    t1 = v["Ksp_AB"] / v["concentration_1"]
    t2 = v["Ksp2"] / v["concentration_2"]
    if math.isclose(t1, t2, rel_tol=1e-3):
        raise EngineError("both ions start precipitating together")
    return "ion 1 precipitates first" if t1 < t2 else "ion 2 precipitates first"


def _mix_ph(v, volume_ml):
    excess = v["moles"] - v["base_moles"]
    if abs(excess) < 1e-12:
        return 7.0
    conc = abs(excess) / (volume_ml / 1000)
    return -log10(conc) if excess > 0 else 14 + log10(conc)


def _pos(x):
    if x <= 0:
        raise EngineError("amount must stay positive")
    return x
