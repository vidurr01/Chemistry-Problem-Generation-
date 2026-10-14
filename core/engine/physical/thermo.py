"""Physical engine — Thermodynamics and Thermochemistry (concept-book TXs 112-150)."""

from __future__ import annotations

import math

from core.engine.base import EngineError, Param, Step, Trap, ln
from core.engine.chem import C, check_balanced, const, parse_equation

P = Param
L_ATM_J = 101.3          # J per L atm (the value JEE uses)
_LATM = "1 L atm = 101.3 J"

_CV = {"monatomic": 1.5, "diatomic": 2.5, "linear triatomic": 3.5, "non-linear polyatomic": 3.0}


def _signed_sum(eq_text, values, products_minus_reactants=True, use_coefficients=True):
    """Σν·X(products) − Σν·X(reactants) for a dict of per-species values."""
    r, p = parse_equation(eq_text)
    total = 0.0
    for sign, side in ((1, p), (-1, r)):
        for c, f in side:
            key = f.replace(" ", "")
            if key not in values:
                raise EngineError(f"no value given for {f}")
            total += sign * (c if use_coefficients else 1) * values[key]
    return total if products_minus_reactants else -total


def _norm_values(d):
    if not isinstance(d, dict) or not d:
        raise EngineError("give the values as a mapping species -> value")
    return {k.replace(" ", ""): float(v) for k, v in d.items()}


def _reaction_sum(v, key, reverse=False, coefs=True):
    check_balanced(v["balanced_equation"])
    return _signed_sum(v["balanced_equation"], _norm_values(v[key]), not reverse, coefs)


def _vant_hoff(v):
    """ΔH° from K at two temperatures, and the ΔS° the same data fix:
    ΔG°(T₁) = −RT₁ ln K₁ = ΔH° − T₁ΔS°."""
    dh = -C.R_J * ln(v["K2"] / v["equilibrium_constant"]) / _nz(1 / v["T2"] - 1 / v["T1"])
    ds = dh / v["T1"] + C.R_J * ln(v["equilibrium_constant"])
    return {"delta_h": dh / 1000, "delta_s": ds}


def _hess(v):
    import sympy
    target_r, target_p = parse_equation(v["target_equation"])
    steps = v["step_equations"]
    if not isinstance(steps, list) or len(steps) < 2:
        raise EngineError("give at least two thermochemical equations [equation, ΔH]")
    species, vecs = [], []

    def vec(eq):
        r, p = parse_equation(eq)
        d = {}
        for sign, side in ((-1, r), (1, p)):
            for c, f in side:
                d[f] = d.get(f, 0) + sign * c
        return d

    tv = vec(v["target_equation"])
    svs = [vec(e) for e, _ in steps]
    for d in [tv] + svs:
        for k in d:
            if k not in species:
                species.append(k)
    M = sympy.Matrix([[sympy.nsimplify(sv.get(s, 0)) for sv in svs] for s in species])
    b = sympy.Matrix([sympy.nsimplify(tv.get(s, 0)) for s in species])
    sol = sympy.linsolve((M, b))
    if not sol:
        raise EngineError("the target equation is not a combination of the given equations")
    coeffs = list(next(iter(sol)))
    if any(c.free_symbols for c in coeffs):
        raise EngineError("the combination is not unique")
    mult = [float(c) for c in coeffs]
    dh = sum(m * float(h) for m, (_, h) in zip(mult, steps))
    return {"delta_h": dh, "_multipliers": mult}


def _hess_trap(v):
    return sum(float(h) for _, h in v["step_equations"])     # adds the ΔH values as given


def _adiabatic_rev(v):
    gamma = (v["Cv"] + C.R_J) / v["Cv"]
    T2 = v["T"] * (v["V1"] / v["V2"]) ** (gamma - 1)
    w = v["n"] * v["Cv"] * (T2 - v["T"])
    return {"work": w, "temperature": T2}


def _adiabatic_rev_trap(v):
    gamma = v["Cv"] / (v["Cv"] + C.R_J)          # inverts gamma
    T2 = v["T"] * (v["V1"] / v["V2"]) ** (gamma - 1)
    return {"work": v["n"] * v["Cv"] * (T2 - v["T"]), "temperature": T2}


def _adiabatic_irrev(v):
    cv, T1, P1, P2 = v["Cv"], v["T"], v["P1"], v["P2"]
    return {"temperature": T1 * (cv + C.R_J * P2 / P1) / (cv + C.R_J)}


def _adiabatic_irrev_trap(v):
    cv, T1, P1, P2 = v["Cv"], v["T"], v["P1"], v["P2"]
    return T1 * (P2 / P1) ** (C.R_J / (cv + C.R_J))      # reversible formula


STEPS = [
    Step(tx=112, src="thermodynamic_process", dst="delta_u",
         needs=(P("heat", "J", "heat absorbed by the system (negative if released)", kind="real", lo=-5000, hi=5000),
                P("work", "J", "work done ON the system (negative if done by it)", kind="real", lo=-5000, hi=5000)),
         answer="delta_u", unit="J", kind="real",
         fn=lambda v: {"delta_u": v["heat"] + v["work"]},
         traps=(Trap("physics_sign", "uses ΔU = q − w with w on the system", lambda v: v["heat"] - v["work"]),),
         formula="ΔU = q + w (IUPAC)", asks="change in internal energy (J)"),
    Step(tx=113, src="delta_u", dst="delta_h",
         needs=(P("reaction_delta_u", "kJ mol⁻¹", "ΔU of the reaction (e.g. from a bomb calorimeter)", kind="real", lo=-3000, hi=500),
                P("balanced_equation", "", "balanced equation with states, e.g. 'C2H6(g) + 7/2 O2(g) -> 2CO2(g) + 3H2O(l)'", kind="text"),
                P("T", "K", "temperature", kind="temperature", lo=273, hi=1000)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"},
         gives=("T1",),                   # ΔH is at this temperature: a Kirchhoff step's T₁
         fn=lambda v: {"delta_h": v["reaction_delta_u"] + _dng(v["balanced_equation"]) * C.R_J * v["T"] / 1000,
                       "T1": v["T"]},
         traps=(Trap("counts_all_species", "counts liquids and solids in Δn",
                     lambda v: v["reaction_delta_u"] + _dn_all(v["balanced_equation"]) * C.R_J * v["T"] / 1000),
                Trap("units_mixed", "adds Δn_gRT in J to ΔU in kJ",
                     lambda v: v["reaction_delta_u"] + _dng(v["balanced_equation"]) * C.R_J * v["T"])),
         constants=(const("R_J"),), formula="ΔH = ΔU + Δn_g RT (q_p = ΔH)", asks="enthalpy change (kJ mol⁻¹)"),
    Step(tx=115, src="thermodynamic_process", dst="delta_u",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("gas_type", "", "type of gas", kind="choice", choices=tuple(_CV)),
                P("delta_T", "K", "temperature change at constant volume", kind="real", lo=-300, hi=500)),
         answer="delta_u", unit="J", kind="real",
         fn=lambda v: {"delta_u": v["n"] * _CV[v["gas_type"]] * C.R_J * v["delta_T"]},
         traps=(Trap("uses_cp", "uses Cp instead of Cv", lambda v: v["n"] * (_CV[v["gas_type"]] + 1) * C.R_J * v["delta_T"]),),
         constants=(const("R_J"),), formula="isochoric: w = 0, ΔU = q_v = nC_vΔT",
         asks="change in internal energy (J)"),
    Step(tx=116, src="thermodynamic_process", dst="delta_u",
         needs=(P("heat", "J", "heat absorbed at constant external pressure", kind="real", lo=-5000, hi=5000),
                P("external_pressure", "atm", "constant external pressure", lo=0.1, hi=10),
                P("V1", "L", "initial volume", lo=0.1, hi=50), P("V2", "L", "final volume", lo=0.1, hi=50)),
         answer="delta_u", unit="J", kind="real",
         fn=lambda v: {"delta_u": v["heat"] - v["external_pressure"] * (v["V2"] - v["V1"]) * L_ATM_J},
         traps=(Trap("no_unit_conversion", "subtracts PΔV in L atm from q in J",
                     lambda v: v["heat"] - v["external_pressure"] * (v["V2"] - v["V1"])),
                Trap("work_sign", "adds PΔV", lambda v: v["heat"] + v["external_pressure"] * (v["V2"] - v["V1"]) * L_ATM_J)),
         constants=(_LATM,), formula="w = −P_ext(V₂ − V₁); ΔU = q + w", asks="change in internal energy (J)"),
    Step(tx=117, src="thermodynamic_process", dst="work",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("T", "K", "temperature", kind="temperature", lo=200, hi=1000),
                P("V1", "L", "initial volume", lo=0.1, hi=50), P("V2", "L", "final volume", lo=0.1, hi=100)),
         answer="work", unit="J", kind="real",
         fn=lambda v: {"work": -v["n"] * C.R_J * v["T"] * ln(v["V2"] / v["V1"])},
         traps=(Trap("log10_without_2303", "uses log₁₀ without 2.303",
                     lambda v: -v["n"] * C.R_J * v["T"] * math.log10(v["V2"] / v["V1"])),
                Trap("sign", "gives +nRT ln(V₂/V₁)", lambda v: v["n"] * C.R_J * v["T"] * ln(v["V2"] / v["V1"]))),
         constants=(const("R_J"),), formula="w = −nRT ln(V₂/V₁) (isothermal reversible)",
         asks="work done on the gas (J)"),
    Step(tx=118, src="thermodynamic_process", dst="work",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("T", "K", "temperature", kind="temperature", lo=200, hi=1000),
                P("P1", "atm", "initial pressure", lo=0.5, hi=20),
                P("P2", "atm", "final pressure = constant external pressure", lo=0.1, hi=20)),
         answer="work", unit="J", kind="real",
         fn=lambda v: {"work": -v["P2"] * (v["n"] * C.R_LATM * v["T"] / v["P2"]
                                           - v["n"] * C.R_LATM * v["T"] / v["P1"]) * L_ATM_J},
         traps=(Trap("reversible_formula", "uses −nRT ln(P₁/P₂)", lambda v: -v["n"] * C.R_J * v["T"] * ln(v["P1"] / v["P2"])),),
         constants=(const("R_LATM"), _LATM), formula="w = −P_ext(V₂ − V₁), V = nRT/P",
         asks="work done on the gas (J)"),
    Step(tx=119, src="thermodynamic_process", dst="work",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("Cv", "J K⁻¹ mol⁻¹", "molar C_v of the gas", lo=12, hi=30),
                P("T", "K", "initial temperature", kind="temperature", lo=200, hi=1000),
                P("V1", "L", "initial volume", lo=0.1, hi=50), P("V2", "L", "final volume", lo=0.1, hi=100)),
         answer="work", unit="J", kind="real", gives=("temperature",), fn=_adiabatic_rev,
         traps=(Trap("inverted_gamma", "uses γ = Cv/Cp", _adiabatic_rev_trap),),
         constants=(const("R_J"),), formula="TV^(γ−1) = const; w = ΔU = nC_v(T₂ − T₁)",
         asks="work done on the gas (J)"),
    Step(tx=120, src="thermodynamic_process", dst="temperature",
         needs=(P("Cv", "J K⁻¹ mol⁻¹", "molar C_v of the gas", lo=12, hi=30),
                P("T", "K", "initial temperature", kind="temperature", lo=200, hi=1000),
                P("P1", "atm", "initial pressure", lo=0.5, hi=20),
                P("P2", "atm", "final pressure = constant external pressure", lo=0.1, hi=20)),
         answer="temperature", unit="K", kind="temperature", roles={"temperature": "gas"}, fn=_adiabatic_irrev,
         traps=(Trap("reversible_formula", "uses the reversible adiabatic relation", _adiabatic_irrev_trap),),
         constants=(const("R_J"),), formula="nC_v(T₂ − T₁) = −P_ext(V₂ − V₁), V = nRT/P",
         asks="final temperature (K)"),
    Step(tx=121, src="thermodynamic_process", dst="work",
         needs=(P("P_low", "atm", "lower pressure of the rectangular cycle", lo=0.5, hi=10),
                P("P_high", "atm", "higher pressure of the cycle", lo=1, hi=20),
                P("V_small", "L", "smaller volume", lo=0.5, hi=20), P("V_large", "L", "larger volume", lo=1, hi=50),
                P("direction", "", "direction on the P-V diagram", kind="choice", choices=("clockwise", "anticlockwise"))),
         answer="work", unit="J", kind="real",
         fn=lambda v: {"work": (-1 if v["direction"] == "clockwise" else 1)
                       * _pos(v["P_high"] - v["P_low"]) * _pos(v["V_large"] - v["V_small"]) * L_ATM_J},
         traps=(Trap("sign", "takes clockwise work as positive",
                     lambda v: (1 if v["direction"] == "clockwise" else -1)
                     * (v["P_high"] - v["P_low"]) * (v["V_large"] - v["V_small"]) * L_ATM_J),),
         constants=(_LATM,), formula="|w_net| = enclosed area; clockwise: work done by the system (w < 0)",
         asks="net work done on the gas per cycle (J)"),
    Step(tx=122, src="thermodynamic_process", dst="heat_capacity",
         needs=(P("Cv", "J K⁻¹ mol⁻¹", "molar C_v of the gas", lo=12, hi=30),
                P("polytropic_index", "", "x in PV^x = constant (x ≠ 1)", kind="real", lo=-2, hi=3)),
         answer="heat_capacity", unit="J K⁻¹ mol⁻¹", kind="real",
         fn=lambda v: {"heat_capacity": v["Cv"] + C.R_J / _nz(1 - v["polytropic_index"])},
         traps=(Trap("sign", "uses R/(x − 1)", lambda v: v["Cv"] + C.R_J / _nz(v["polytropic_index"] - 1)),),
         constants=(const("R_J"),), formula="C = C_v + R/(1 − x)", asks="molar heat capacity of the process"),
    Step(tx=123, src="gas_mixture", dst="gamma",
         needs=(P("n1", "mol", "amount of gas 1", lo=0.5, hi=5),
                P("gas1_type", "", "type of gas 1", kind="choice", choices=tuple(_CV)),
                P("n2", "mol", "amount of gas 2", lo=0.5, hi=5),
                P("gas2_type", "", "type of gas 2", kind="choice", choices=tuple(_CV))),
         answer="gamma", unit="", kind="positive",
         fn=lambda v: {"gamma": (v["n1"] * (_CV[v["gas1_type"]] + 1) + v["n2"] * (_CV[v["gas2_type"]] + 1))
                       / (v["n1"] * _CV[v["gas1_type"]] + v["n2"] * _CV[v["gas2_type"]])},
         traps=(Trap("averages_gamma", "takes the mole-weighted average of γ",
                     lambda v: (v["n1"] * (_CV[v["gas1_type"]] + 1) / _CV[v["gas1_type"]]
                                + v["n2"] * (_CV[v["gas2_type"]] + 1) / _CV[v["gas2_type"]]) / (v["n1"] + v["n2"])),),
         formula="γ_mix = Σnᵢ C_p,ᵢ / Σnᵢ C_v,ᵢ", asks="γ (Cp/Cv) of the mixture"),
    Step(tx=124, src="temperature", dst="efficiency",
         needs=(P("temperature", "K", "temperature of the hot reservoir", kind="temperature", lo=300, hi=1500, role="reservoir"),
                P("cold_temperature", "K", "temperature of the cold reservoir", kind="temperature", lo=200, hi=500)),
         answer="efficiency", unit="", kind="open_fraction",
         fn=lambda v: {"efficiency": 1 - v["cold_temperature"] / v["temperature"]},
         traps=(Trap("divides_by_cold", "divides by the cold temperature",
                     lambda v: (v["temperature"] - v["cold_temperature"]) / v["cold_temperature"]),),
         formula="η = (T_h − T_c)/T_h", asks="maximum efficiency of the engine (as a fraction)"),
    Step(tx=125, src="gas_state", dst="entropy_change",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("gas_type", "", "type of gas", kind="choice", choices=tuple(_CV)),
                P("T", "K", "initial temperature", kind="temperature", lo=200, hi=1000),
                P("new_temperature", "K", "final temperature", kind="temperature", lo=200, hi=1500),
                P("V", "L", "initial volume", lo=0.1, hi=50), P("new_volume", "L", "final volume", lo=0.1, hi=100)),
         answer="entropy_change", unit="J K⁻¹", kind="real", roles={"entropy_change": "system"},
         fn=lambda v: {"entropy_change": v["n"] * C.R_J * (_CV[v["gas_type"]] * ln(v["new_temperature"] / v["T"])
                                                    + ln(v["new_volume"] / v["V"]))},
         traps=(Trap("uses_cp_with_volume", "uses C_p with the volume term",
                     lambda v: v["n"] * C.R_J * ((_CV[v["gas_type"]] + 1) * ln(v["new_temperature"] / v["T"])
                                                 + ln(v["new_volume"] / v["V"]))),),
         constants=(const("R_J"),), formula="ΔS = nC_v ln(T₂/T₁) + nR ln(V₂/V₁)", asks="entropy change of the gas (J K⁻¹)"),
    Step(tx=126, src="thermodynamic_process", dst="entropy_change",
         needs=(P("n", "mol", "amount of ideal gas", lo=0.1, hi=10),
                P("V1", "L", "initial volume", lo=0.1, hi=50), P("V2", "L", "final volume", lo=0.1, hi=100)),
         answer="entropy_change", unit="J K⁻¹", kind="real", roles={"entropy_change": "system"},
         fn=lambda v: {"entropy_change": v["n"] * C.R_J * ln(v["V2"] / v["V1"])},
         traps=(Trap("log10_without_2303", "uses log₁₀ without 2.303", lambda v: v["n"] * C.R_J * math.log10(v["V2"] / v["V1"])),),
         constants=(const("R_J"),), formula="ΔS = nR ln(V₂/V₁) (isothermal, ideal gas)", asks="entropy change (J K⁻¹)"),
    Step(tx=127, src="delta_h", dst="delta_s",
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy of the phase transition", kind="real", lo=1, hi=60, role="phase transition", strict=True),
                P("T", "K", "transition temperature", kind="temperature", lo=50, hi=1500)),
         answer="delta_s", unit="J K⁻¹ mol⁻¹", kind="real",
         fn=lambda v: {"delta_s": 1000 * v["delta_h"] / v["T"]},
         traps=(Trap("kJ_not_converted", "keeps ΔH in kJ", lambda v: v["delta_h"] / v["T"]),),
         formula="ΔS = ΔH/T at the transition temperature", asks="entropy of transition (J K⁻¹ mol⁻¹)"),
    Step(tx=129, src="entropy_change", dst="entropy_change",
         needs=(P("entropy_change", "J K⁻¹", "entropy change of the system", kind="real", lo=-200, hi=200,
                  role="system", strict=True),
                P("heat", "J", "heat absorbed by the system", kind="real", lo=-50000, hi=50000),
                P("T", "K", "temperature of the surroundings", kind="temperature", lo=200, hi=1000)),
         answer="entropy_change", unit="J K⁻¹", kind="real",
         fn=lambda v: {"entropy_change": v["entropy_change"] - v["heat"] / v["T"]},
         traps=(Trap("surroundings_sign", "adds +q/T for the surroundings", lambda v: v["entropy_change"] + v["heat"] / v["T"]),),
         formula="ΔS_univ = ΔS_sys + ΔS_surr; ΔS_surr = −q_sys/T", asks="entropy change of the universe (J K⁻¹)"),
    # the calorimeter's heat is not the system's heat at the surroundings' temperature
    Step(tx=130, src="heat", dst="entropy_change", not_after=(148,),
         needs=(P("heat", "J", "heat absorbed by the system", kind="real", lo=-50000, hi=50000),
                P("T", "K", "temperature of the surroundings", kind="temperature", lo=200, hi=1000)),
         answer="entropy_change", unit="J K⁻¹", kind="real", roles={"entropy_change": "surroundings"},
         fn=lambda v: {"entropy_change": -v["heat"] / v["T"]},
         traps=(Trap("sign", "uses +q/T", lambda v: v["heat"] / v["T"]),),
         formula="ΔS_surr = −q_sys/T", asks="entropy change of the surroundings (J K⁻¹)"),
    Step(tx=131, src="standard_entropy", dst="delta_s",
         needs=(P("balanced_equation", "", "balanced equation", kind="text"),
                P("standard_entropies", "J K⁻¹ mol⁻¹", "S° of each species, e.g. {\"N2\": 191.6, ...}", kind="dict")),
         answer="delta_s", unit="J K⁻¹ mol⁻¹", kind="real",
         fn=lambda v: {"delta_s": _reaction_sum(v, "standard_entropies")},
         traps=(Trap("reactants_minus_products", "subtracts products from reactants", lambda v: _reaction_sum(v, "standard_entropies", reverse=True)),
                Trap("ignores_coefficients", "ignores the coefficients", lambda v: _reaction_sum(v, "standard_entropies", coefs=False))),
         formula="ΔS° = ΣνS°(products) − ΣνS°(reactants)", asks="standard entropy change (J K⁻¹ mol⁻¹)"),
    Step(tx=132, src="delta_h", dst="delta_g",
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy change", kind="real", lo=-500, hi=500,
                  role=("reaction", "allotrope transition", "phase transition"), strict=True),
                P("delta_s", "J K⁻¹ mol⁻¹", "entropy change", kind="real", lo=-400, hi=400),
                P("T", "K", "temperature", kind="temperature", lo=200, hi=1500)),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "standard"},
         gives=("T", "delta_h", "delta_s"),   # ΔG° -> K uses the same T; ΔH, ΔS stay this reaction's
         fn=lambda v: {"delta_g": v["delta_h"] - v["T"] * v["delta_s"] / 1000, "T": v["T"],
                       "delta_h": v["delta_h"], "delta_s": v["delta_s"]},
         traps=(Trap("units_mixed", "subtracts TΔS in J from ΔH in kJ", lambda v: v["delta_h"] - v["T"] * v["delta_s"]),),
         formula="ΔG = ΔH − TΔS", asks="Gibbs energy change (kJ mol⁻¹)"),
    Step(tx=133, src="delta_h", dst="temperature", not_after=(114,),
         needs=(P("delta_h", "kJ mol⁻¹", "enthalpy change", kind="real", lo=-500, hi=500,
                  role=("reaction", "allotrope transition", "phase transition"), strict=True),
                P("delta_s", "J K⁻¹ mol⁻¹", "entropy change (same sign as ΔH)", kind="real", lo=-400, hi=400)),
         answer="temperature", unit="K", kind="temperature", roles={"temperature": "transition"},
         fn=lambda v: {"temperature": 1000 * v["delta_h"] / _nz(v["delta_s"])},
         traps=(Trap("units_mixed", "divides kJ by J", lambda v: v["delta_h"] / _nz(v["delta_s"])),),
         formula="T = ΔH/ΔS at ΔG = 0", asks="temperature at which ΔG = 0 (K)"),
    Step(tx=134, src="formation_gibbs_data", dst="delta_g",
         needs=(P("balanced_equation", "", "balanced equation", kind="text"),
                P("formation_gibbs", "kJ mol⁻¹", "ΔfG° of each species (0 for elements)", kind="dict")),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "standard"},
         gives=("balanced_equation",),
         fn=lambda v: {"delta_g": _reaction_sum(v, "formation_gibbs"), "balanced_equation": v["balanced_equation"]},
         traps=(Trap("ignores_coefficients", "ignores the coefficients", lambda v: _reaction_sum(v, "formation_gibbs", coefs=False)),),
         formula="ΔrG° = ΣνΔfG°(products) − ΣνΔfG°(reactants)", asks="standard Gibbs energy of reaction (kJ mol⁻¹)"),
    Step(tx=135, src="delta_g", dst="equilibrium_constant",
         needs=(P("delta_g", "kJ mol⁻¹", "standard Gibbs energy change", kind="real", lo=-60, hi=60,
                  role="standard"),
                P("T", "K", "temperature", kind="temperature", lo=250, hi=1200)),
         answer="equilibrium_constant", unit="", kind="positive", gives=("T1", "T"),
         carries=("delta_h", "delta_s", "balanced_equation"),
         fn=lambda v: {"equilibrium_constant": math.exp(-1000 * v["delta_g"] / (C.R_J * v["T"])),
                       "T1": v["T"], "T": v["T"]},
         traps=(Trap("log10_as_ln", "uses 10^(−ΔG/RT)", lambda v: 10 ** (-1000 * v["delta_g"] / (C.R_J * v["T"]))),
                Trap("kJ_not_converted", "keeps ΔG in kJ", lambda v: math.exp(-v["delta_g"] / (C.R_J * v["T"])))),
         constants=(const("R_J"),), formula="ΔG° = −RT ln K", asks="equilibrium constant K"),
    Step(tx=136, src="equilibrium_constant", dst="delta_h", not_after=(163,), not_after_any=(132, 163),
         needs=(P("equilibrium_constant", "", "K at T₁ (K_p in atm or K_c in mol L⁻¹ units)", lo=1e-10, hi=1e10,
                  role=("Kp", "Kc")),
                P("T1", "K", "temperature T₁", kind="temperature", lo=250, hi=1200),
                P("K2", "", "K at T₂ (the same kind of constant as at T₁)", lo=1e-10, hi=1e10),
                P("T2", "K", "temperature T₂", kind="temperature", lo=250, hi=1200)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"},
         gives=("delta_s",),
         fn=_vant_hoff,
         traps=(Trap("sign_of_bracket", "uses (1/T₁ − 1/T₂) with a minus sign",
                     lambda v: C.R_J * ln(v["K2"] / v["equilibrium_constant"]) / _nz(1 / v["T2"] - 1 / v["T1"]) / 1000),),
         constants=(const("R_J"),), formula="ln(K₂/K₁) = −(ΔH°/R)(1/T₂ − 1/T₁)", asks="standard enthalpy change (kJ mol⁻¹)"),
    Step(tx=137, src="delta_g", dst="work",
         needs=(P("delta_g", "kJ mol⁻¹", "Gibbs energy change of the reaction", kind="real", lo=-1000, hi=-1),
                P("moles", "mol", "amount reacting", lo=0.1, hi=10)),
         answer="useful_work", unit="kJ", kind="positive",
         fn=lambda v: {"useful_work": -v["delta_g"] * v["moles"]},
         traps=(Trap("per_mole_only", "ignores the amount reacting", lambda v: -v["delta_g"]),),
         formula="w_non-PV,max = −ΔG", asks="maximum useful (non-PV) work obtainable (kJ)"),
    Step(tx=138, src="cell_emf", dst="delta_g",
         needs=(P("cell_emf", "V", "standard cell EMF", kind="real", lo=-3, hi=4, role="standard", strict=True),
                P("electrons", "", "electrons transferred in the cell reaction", kind="posint", lo=1, hi=6)),
         answer="delta_g", unit="kJ mol⁻¹", kind="real", roles={"delta_g": "standard"},
         fn=lambda v: {"delta_g": -v["electrons"] * C.F * v["cell_emf"] / 1000},
         traps=(Trap("forgets_n", "uses −FE", lambda v: -C.F * v["cell_emf"] / 1000),),
         constants=(const("F"),), formula="ΔG = −nFE", asks="Gibbs energy change (kJ mol⁻¹)"),
    # ── Thermochemistry ──
    # van 't Hoff (136, 315) assumes ΔH constant over T₁…T₂: a ΔC_p correction contradicts it
    Step(tx=114, keeps_role=True, src="delta_h", dst="delta_h", not_after=(136, 315),
         needs=(P("delta_h", "kJ mol⁻¹", "reaction enthalpy at T₁", kind="real", lo=-500, hi=500,
                  role="reaction", strict=True),
                P("delta_cp", "J K⁻¹ mol⁻¹", "ΔrC_p = ΣC_p(products) − ΣC_p(reactants)", kind="real", lo=-100, hi=100),
                P("T1", "K", "temperature T₁", kind="temperature", lo=250, hi=1200),
                P("T2", "K", "temperature T₂", kind="temperature", lo=250, hi=1500)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", gives=("T",),
         fn=lambda v: {"delta_h": v["delta_h"] + v["delta_cp"] * (v["T2"] - v["T1"]) / 1000, "T": v["T2"]},
         traps=(Trap("units_mixed", "adds ΔCpΔT in J to ΔH in kJ", lambda v: v["delta_h"] + v["delta_cp"] * (v["T2"] - v["T1"])),),
         formula="Kirchhoff: ΔH(T₂) = ΔH(T₁) + ΔC_p(T₂ − T₁)", asks="reaction enthalpy at T₂ (kJ mol⁻¹)"),
    Step(tx=139, src="enthalpy_data", dst="delta_h",
         needs=(P("balanced_equation", "", "balanced equation", kind="text"),
                P("formation_enthalpies", "kJ mol⁻¹", "ΔfH° of each species (0 for elements)", kind="dict")),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"},
         fn=lambda v: {"delta_h": _reaction_sum(v, "formation_enthalpies")},
         traps=(Trap("reactants_minus_products", "subtracts products from reactants",
                     lambda v: _reaction_sum(v, "formation_enthalpies", reverse=True)),
                Trap("ignores_coefficients", "ignores the coefficients",
                     lambda v: _reaction_sum(v, "formation_enthalpies", coefs=False))),
         formula="ΔrH° = ΣνΔfH°(products) − ΣνΔfH°(reactants)", asks="enthalpy of reaction (kJ mol⁻¹)"),
    Step(tx=140, src="enthalpy_data", dst="delta_h",
         needs=(P("balanced_equation", "", "balanced equation", kind="text"),
                P("combustion_enthalpies", "kJ mol⁻¹", "ΔcH° of each species (0 for CO2, H2O, O2)", kind="dict")),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"},
         fn=lambda v: {"delta_h": _reaction_sum(v, "combustion_enthalpies", reverse=True)},
         traps=(Trap("formation_order", "uses products − reactants as for formation enthalpies",
                     lambda v: _reaction_sum(v, "combustion_enthalpies")),),
         formula="ΔrH = ΣνΔcH(reactants) − ΣνΔcH(products)", asks="enthalpy of reaction (kJ mol⁻¹)"),
    Step(tx=141, src="enthalpy_data", dst="delta_h",
         needs=(P("target_equation", "", "equation whose ΔH is asked", kind="text"),
                P("step_equations", "", "list of [equation, ΔH in kJ] pairs", kind="list")),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"}, fn=_hess,
         traps=(Trap("adds_as_given", "adds the ΔH values without reversing/scaling the equations", _hess_trap),),
         formula="Hess: combine the equations; ΔH combines the same way", asks="enthalpy of the target reaction (kJ mol⁻¹)"),
    Step(tx=142, src="enthalpy_data", dst="delta_h",
         needs=(P("bonds_broken", "", "bonds broken with counts, e.g. {\"C-H\": 4, \"O=O\": 2}", kind="dict"),
                P("bonds_formed", "", "bonds formed with counts", kind="dict"),
                P("bond_enthalpies", "kJ mol⁻¹", "average bond enthalpy of each bond type", kind="dict")),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "reaction"},
         fn=lambda v: {"delta_h": _bonds(v)},
         traps=(Trap("formed_minus_broken", "uses Σ(formed) − Σ(broken)", lambda v: -_bonds(v)),),
         formula="ΔH = ΣBE(broken) − ΣBE(formed) (gases)", asks="enthalpy of reaction (kJ mol⁻¹)"),
    Step(tx=143, src="delta_h", dst="resonance_energy",
         needs=(P("delta_h", "kJ mol⁻¹", "experimental enthalpy of formation", kind="real", lo=-500, hi=500, role="formation", strict=True),
                P("calculated_delta_h", "kJ mol⁻¹", "enthalpy of formation calculated for the non-resonating structure",
                  kind="real", lo=-500, hi=500)),
         answer="resonance_energy", unit="kJ mol⁻¹", kind="real",
         fn=lambda v: {"resonance_energy": v["delta_h"] - v["calculated_delta_h"]},
         traps=(Trap("reversed", "uses calculated − experimental", lambda v: v["calculated_delta_h"] - v["delta_h"]),),
         formula="ΔH_res = ΔfH(exp) − ΔfH(calc)", asks="resonance energy (kJ mol⁻¹)"),
    Step(tx=144, src="heat", dst="delta_h",
         needs=(P("heat", "J", "heat evolved on neutralisation (positive number)", lo=10, hi=1e5),
                P("water_moles", "mol", "amount of water formed (= equivalents neutralised)", lo=0.001, hi=2)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "neutralisation"},
         fn=lambda v: {"delta_h": -v["heat"] / 1000 / v["water_moles"]},
         traps=(Trap("sign", "reports a positive enthalpy for an exothermic process", lambda v: v["heat"] / 1000 / v["water_moles"]),
                Trap("joules_as_kJ", "forgets to convert J to kJ", lambda v: -v["heat"] / v["water_moles"])),
         formula="ΔH_neut = −q/n(H₂O); strong acid + strong base ≈ −57.3 kJ per equivalent",
         asks="enthalpy of neutralisation (kJ per mol of water)"),
    Step(tx=145, src="enthalpy_data", dst="delta_h",
         needs=(P("solution_enthalpy_anhydrous", "kJ mol⁻¹", "enthalpy of solution of the anhydrous salt", kind="real", lo=-100, hi=100),
                P("solution_enthalpy_hydrated", "kJ mol⁻¹", "enthalpy of solution of the hydrated salt", kind="real", lo=-100, hi=100)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "hydration"},
         fn=lambda v: {"delta_h": v["solution_enthalpy_anhydrous"] - v["solution_enthalpy_hydrated"]},
         traps=(Trap("reversed", "subtracts the other way round",
                     lambda v: v["solution_enthalpy_hydrated"] - v["solution_enthalpy_anhydrous"]),),
         formula="ΔH_hyd = ΔH_sol(anhydrous) − ΔH_sol(hydrated)", asks="enthalpy of hydration (kJ mol⁻¹)"),
    Step(tx=146, src="enthalpy_data", dst="delta_h",
         needs=(P("combustion_enthalpy_1", "kJ mol⁻¹", "ΔcH of the stable allotrope (e.g. graphite)", kind="negative", lo=-1000, hi=-10),
                P("combustion_enthalpy_2", "kJ mol⁻¹", "ΔcH of the other allotrope (e.g. diamond)", kind="negative", lo=-1000, hi=-10)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "allotrope transition"},
         fn=lambda v: {"delta_h": v["combustion_enthalpy_1"] - v["combustion_enthalpy_2"]},
         traps=(Trap("reversed", "subtracts the other way round", lambda v: v["combustion_enthalpy_2"] - v["combustion_enthalpy_1"]),),
         formula="ΔH(1 → 2) = ΔcH(1) − ΔcH(2)", asks="enthalpy of transition between the allotropes (kJ mol⁻¹)"),
    Step(tx=148, src="temperature", dst="heat",
         needs=(P("temperature", "K", "initial temperature of the calorimeter", kind="temperature", lo=270, hi=320, role="calorimeter"),
                P("final_temperature", "K", "final temperature", kind="temperature", lo=270, hi=400),
                P("heat_capacity", "kJ K⁻¹", "heat capacity of the calorimeter", lo=0.1, hi=20)),
         answer="heat", unit="J", kind="real", roles={"heat": "calorimeter"},
         fn=lambda v: {"heat": 1000 * v["heat_capacity"] * (v["final_temperature"] - v["temperature"])},
         traps=(Trap("uses_final_temperature", "multiplies by the final temperature instead of ΔT",
                     lambda v: 1000 * v["heat_capacity"] * v["final_temperature"]),),
         formula="q = C_cal ΔT (bomb calorimeter: q_v = ΔU)", asks="heat absorbed by the calorimeter (J)"),
    Step(tx=149, src="enthalpy_data", dst="delta_h",
         needs=(P("solution_enthalpy_initial", "kJ mol⁻¹", "integral enthalpy of solution at the initial concentration", kind="real", lo=-100, hi=100),
                P("solution_enthalpy_final", "kJ mol⁻¹", "integral enthalpy of solution after dilution", kind="real", lo=-100, hi=100)),
         answer="delta_h", unit="kJ mol⁻¹", kind="real", roles={"delta_h": "dilution"},
         fn=lambda v: {"delta_h": v["solution_enthalpy_final"] - v["solution_enthalpy_initial"]},
         traps=(Trap("reversed", "subtracts the other way round",
                     lambda v: v["solution_enthalpy_initial"] - v["solution_enthalpy_final"]),),
         formula="ΔH_dil = ΔH_sol(final) − ΔH_sol(initial)", asks="enthalpy of dilution (kJ mol⁻¹)"),
    Step(tx=150, src="enthalpy_data", dst="delta_h",
         needs=(P("bond_dissociation_enthalpy", "kJ mol⁻¹", "bond dissociation enthalpy of the diatomic X₂", lo=100, hi=1000),),
         answer="delta_h", unit="kJ mol⁻¹", kind="positive", roles={"delta_h": "atomization"},
         fn=lambda v: {"delta_h": v["bond_dissociation_enthalpy"] / 2},
         traps=(Trap("forgets_half", "uses the whole bond enthalpy per mole of atoms", lambda v: v["bond_dissociation_enthalpy"]),),
         formula="ΔH_a per mole of X atoms = ½ BDE(X₂)", asks="enthalpy of atomization per mole of atoms (kJ mol⁻¹)"),
]


def _states(eq_text):
    """[(sign, coefficient, state)] for every species; the state comes from '(g)', '(l)', '(s)', '(aq)'."""
    import re
    s = eq_text.replace("→", "->")
    if "->" not in s:
        raise EngineError("write the equation with '->'")
    out = []
    for sign, part in ((-1, s.split("->")[0]), (1, s.split("->")[1])):
        for term in re.split(r"\s\+\s", part):
            m = re.match(r"^\s*(\d+(?:\.\d+)?(?:/\d+)?)?\s*(.+?)\((g|l|s|aq)\)\s*$", term)
            if not m:
                raise EngineError(f"give the state of every species, e.g. 'H2O(l)': {term!r}")
            num = m.group(1) or "1"
            c = float(num.split("/")[0]) / float(num.split("/")[1]) if "/" in num else float(num)
            out.append((sign, c, m.group(3)))
    return out


def _dng(eq_text):
    return sum(sign * c for sign, c, st in _states(eq_text) if st == "g")


def _dn_all(eq_text):
    return sum(sign * c for sign, c, st in _states(eq_text))


def _bonds(v):
    be = {k.replace(" ", ""): float(x) for k, x in v["bond_enthalpies"].items()}
    total = 0.0
    for sign, key in ((1, "bonds_broken"), (-1, "bonds_formed")):
        for bond, count in v[key].items():
            b = bond.replace(" ", "")
            if b not in be:
                raise EngineError(f"no bond enthalpy given for {bond}")
            total += sign * float(count) * be[b]
    return total


def _nz(x):
    if x == 0:
        raise EngineError("division by zero")
    return x


def _pos(x):
    if x <= 0:
        raise EngineError("value must be positive")
    return x
