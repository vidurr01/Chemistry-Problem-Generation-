"""Physical engine — Gaseous State (concept-book TXs 84-109)."""

from __future__ import annotations

import math

from core.engine.base import EngineError, Param, Step, Trap, div, sqrt
from core.engine.chem import C, const

P = Param
_L_ATM_J = 101.325        # J per L atm


def _celsius_k(t):
    k = t + 273
    if k <= 0:
        raise EngineError("temperature below absolute zero")
    return k


_SPEEDS = {
    98: ("rms", 3.0, "u_rms = √(3RT/M)"),
    99: ("average", 8 / math.pi, "u_av = √(8RT/πM)"),
    100: ("most probable", 2.0, "u_mp = √(2RT/M)"),
}


def _speed_step(tx):
    name, factor, formula = _SPEEDS[tx]
    others = [(n, f) for t, (n, f, _) in _SPEEDS.items() if t != tx]

    def wrong_type(v, f=others[0][1]):
        return sqrt(f * C.R_J * v["temperature"] / (v["molar_mass"] / 1000))

    return Step(
        tx=tx, src="temperature", dst="molecular_speed",
        needs=(P("temperature", "K", "temperature of the gas", kind="temperature", lo=100, hi=1500, role="gas"),
               P("molar_mass", "g mol⁻¹", "molar mass of the gas", lo=2, hi=200)),
        answer="molecular_speed", unit="m s⁻¹", kind="positive",
        fn=lambda v: {"molecular_speed": sqrt(factor * C.R_J * v["temperature"] / (v["molar_mass"] / 1000))},
        traps=(Trap("molar_mass_in_grams", "uses M in g mol⁻¹ with R in J",
                    lambda v: sqrt(factor * C.R_J * v["temperature"] / v["molar_mass"])),
               Trap("wrong_speed_type", f"uses the {others[0][0]} speed formula", wrong_type)),
        constants=(const("R_J"),), formula=formula, asks=f"{name} speed of the molecules (m s⁻¹)")


def _vdw_a(v):
    n, V, T, Pr, b = v["n"], v["V"], v["T"], v["P"], v["b"]
    if V <= n * b:
        raise EngineError("volume must exceed the excluded volume nb")
    a = (n * C.R_LATM * T / (V - n * b) - Pr) * V ** 2 / n ** 2
    if a <= 0:
        raise EngineError("these data give a non-positive a")
    return {"a": a, "b": b}


def _vdw_a_trap(v):
    n, V, T, Pr = v["n"], v["V"], v["T"], v["P"]
    return {"a": (n * C.R_LATM * T / V - Pr) * V ** 2 / n ** 2}       # ignores nb


STEPS = [
    Step(tx=84, keeps_role=True, src="gas_state", dst="gas_state",
         needs=(P("P", "atm", "initial pressure", lo=0.1, hi=20), P("V", "L", "initial volume", lo=0.1, hi=100),
                P("new_volume", "L", "final volume (same T and amount)", lo=0.1, hi=100)),
         answer="P", unit="atm", kind="positive", gives=("V",),
         fn=lambda v: {"P": v["P"] * v["V"] / v["new_volume"], "V": v["new_volume"]},
         traps=(Trap("inverted_ratio", "multiplies by V2/V1", lambda v: v["P"] * v["new_volume"] / v["V"]),),
         formula="Boyle: P₁V₁ = P₂V₂", asks="final pressure (atm)"),
    Step(tx=85, keeps_role=True, src="gas_state", dst="gas_state",
         needs=(P("V", "L", "initial volume", lo=0.1, hi=100),
                P("t1_celsius", "°C", "initial temperature", kind="real", lo=-50, hi=300),
                P("t2_celsius", "°C", "final temperature (same P and amount)", kind="real", lo=-50, hi=500)),
         answer="V", unit="L", kind="positive", gives=("T",),
         fn=lambda v: {"V": v["V"] * _celsius_k(v["t2_celsius"]) / _celsius_k(v["t1_celsius"]),
                       "T": _celsius_k(v["t2_celsius"])},
         traps=(Trap("celsius_ratio", "uses the Celsius temperatures in the ratio",
                     lambda v: v["V"] * div(v["t2_celsius"], v["t1_celsius"])),),
         formula="Charles: V₁/T₁ = V₂/T₂ (T in K)", asks="final volume (L)"),
    Step(tx=86, keeps_role=True, src="gas_state", dst="gas_state",
         needs=(P("P", "atm", "initial pressure", lo=0.1, hi=20),
                P("t1_celsius", "°C", "initial temperature", kind="real", lo=-50, hi=300),
                P("t2_celsius", "°C", "final temperature (same V and amount)", kind="real", lo=-50, hi=500)),
         answer="P", unit="atm", kind="positive", gives=("T",),
         fn=lambda v: {"P": v["P"] * _celsius_k(v["t2_celsius"]) / _celsius_k(v["t1_celsius"]),
                       "T": _celsius_k(v["t2_celsius"])},
         traps=(Trap("celsius_ratio", "uses the Celsius temperatures in the ratio",
                     lambda v: v["P"] * div(v["t2_celsius"], v["t1_celsius"])),),
         formula="Gay-Lussac: P₁/T₁ = P₂/T₂ (T in K)", asks="final pressure (atm)"),
    Step(tx=87, keeps_role=True, src="gas_state", dst="gas_state",
         needs=(P("P", "atm", "initial pressure", lo=0.1, hi=20), P("V", "L", "initial volume", lo=0.1, hi=100),
                P("T", "K", "initial temperature", kind="temperature", lo=150, hi=800),
                P("new_pressure", "atm", "final pressure", lo=0.1, hi=20),
                P("new_temperature", "K", "final temperature", kind="temperature", lo=150, hi=800)),
         answer="V", unit="L", kind="positive", gives=("P", "T"),
         fn=lambda v: {"V": v["P"] * v["V"] * v["new_temperature"] / (v["T"] * v["new_pressure"]),
                       "P": v["new_pressure"], "T": v["new_temperature"]},
         traps=(Trap("temperature_inverted", "inverts the temperature ratio",
                     lambda v: v["P"] * v["V"] * v["T"] / (v["new_temperature"] * v["new_pressure"])),),
         formula="P₁V₁/T₁ = P₂V₂/T₂", asks="final volume (L)"),
    Step(tx=88, src="gas_state", dst="moles",
         needs=(P("P", "atm", "pressure", lo=0.1, hi=20), P("V", "L", "volume", lo=0.1, hi=100),
                P("T", "K", "temperature", kind="temperature", lo=150, hi=1000)),
         answer="moles", unit="mol", kind="positive", roles={"moles": "gas"},
         fn=lambda v: {"moles": v["P"] * v["V"] / (C.R_LATM * v["T"])},
         traps=(Trap("wrong_R", "uses R = 8.314 with atm and L", lambda v: v["P"] * v["V"] / (C.R_J * v["T"])),),
         constants=(const("R_LATM"),), formula="n = PV/RT", asks="amount of gas (mol)"),
    Step(tx=89, keeps_role=True, src="gas_state", dst="gas_density",
         needs=(P("P", "atm", "pressure", lo=0.1, hi=20), P("T", "K", "temperature", kind="temperature", lo=150, hi=1000),
                P("molar_mass", "g mol⁻¹", "molar mass of the gas", lo=2, hi=200)),
         answer="gas_density", unit="g L⁻¹", kind="positive",
         fn=lambda v: {"gas_density": v["P"] * v["molar_mass"] / (C.R_LATM * v["T"])},
         traps=(Trap("wrong_R", "uses R = 8.314 with atm and L",
                     lambda v: v["P"] * v["molar_mass"] / (C.R_J * v["T"])),),
         constants=(const("R_LATM"),), formula="d = PM/RT", asks="density of the gas (g L⁻¹)"),
    Step(tx=90, src="liquid_column", dst="pressure",
         needs=(P("column_height", "m", "height of the liquid column", lo=0.01, hi=20),
                P("liquid_density", "kg m⁻³", "density of the liquid", lo=500, hi=14000)),
         answer="pressure", unit="Pa", kind="positive",
         fn=lambda v: {"pressure": v["column_height"] * v["liquid_density"] * C.G},
         traps=(Trap("forgets_g", "uses P = hd", lambda v: v["column_height"] * v["liquid_density"]),),
         constants=(const("G"),), formula="P = h d g", asks="pressure exerted by the column (Pa)"),
    Step(tx=91, src="partial_pressure", dst="gas_state",
         needs=(P("partial_pressure", "atm", "partial pressure of gas 1", lo=0.01, hi=10),
                P("partial_pressure_2", "atm", "partial pressure of gas 2", lo=0.01, hi=10),
                P("partial_pressure_3", "atm", "partial pressure of gas 3 (0 if absent)", kind="nonneg", lo=0, hi=10)),
         answer="P", unit="atm", kind="positive",
         fn=lambda v: {"P": v["partial_pressure"] + v["partial_pressure_2"] + v["partial_pressure_3"]},
         traps=(Trap("averages", "averages the partial pressures",
                     lambda v: (v["partial_pressure"] + v["partial_pressure_2"] + v["partial_pressure_3"])
                     / (3 if v["partial_pressure_3"] else 2)),),
         formula="Dalton: P_total = ΣPᵢ", asks="total pressure (atm)"),
    Step(tx=92, src="gas_state", dst="partial_pressure",
         needs=(P("P", "atm", "total pressure of the gas collected over water", lo=0.5, hi=2),
                P("aqueous_tension", "atm", "vapour pressure of water at that temperature", lo=0.005, hi=0.2)),
         answer="partial_pressure", unit="atm", kind="positive", roles={"partial_pressure": "dry gas"},
         fn=lambda v: {"partial_pressure": v["P"] - v["aqueous_tension"]},
         traps=(Trap("adds_tension", "adds the aqueous tension", lambda v: v["P"] + v["aqueous_tension"]),),
         formula="P_dry = P_wet − aqueous tension", asks="pressure of the dry gas (atm)"),
    Step(tx=93, keeps_role=True, src="gas_volume", dst="gas_volume",
         needs=(P("gas_volume", "L", "partial volume of gas 1 (at the mixture's T and P)", lo=0.1, hi=50),
                P("partial_volume_2", "L", "partial volume of gas 2", lo=0.1, hi=50)),
         answer="gas_volume", unit="L", kind="positive",
         fn=lambda v: {"gas_volume": v["gas_volume"] + v["partial_volume_2"]},
         traps=(Trap("averages", "averages the partial volumes", lambda v: (v["gas_volume"] + v["partial_volume_2"]) / 2),),
         formula="Amagat: V_total = ΣVᵢ (same T, P)", asks="total volume (L)"),
    Step(tx=94, src="vapour_pressure", dst="relative_humidity",
         needs=(P("water_vapour_pressure", "mm Hg", "partial pressure of water vapour in the air", lo=1, hi=40),
                P("vapour_pressure", "mm Hg", "saturation vapour pressure of water at that temperature", lo=5, hi=150)),
         answer="relative_humidity", unit="%", kind="percent",
         fn=lambda v: {"relative_humidity": 100 * v["water_vapour_pressure"] / v["vapour_pressure"]},
         traps=(Trap("inverted", "divides saturation by actual", lambda v: 100 * v["vapour_pressure"] / v["water_vapour_pressure"]),),
         formula="%RH = p(H₂O)/VP(H₂O) × 100", asks="relative humidity (%)"),
    Step(tx=95, src="molar_mass", dst="effusion_rate",
         needs=(P("molar_mass", "g mol⁻¹", "molar mass of gas 1", lo=2, hi=400),
                P("molar_mass_2", "g mol⁻¹", "molar mass of gas 2", lo=2, hi=400)),
         answer="effusion_rate", unit="", kind="positive",
         fn=lambda v: {"effusion_rate": sqrt(v["molar_mass_2"] / v["molar_mass"])},
         traps=(Trap("no_square_root", "uses M₂/M₁ without the square root", lambda v: v["molar_mass_2"] / v["molar_mass"]),
                Trap("inverted", "uses √(M₁/M₂)", lambda v: sqrt(v["molar_mass"] / v["molar_mass_2"]))),
         formula="Graham: r₁/r₂ = √(M₂/M₁)", asks="ratio of the effusion rates r₁/r₂"),
    Step(tx=96, src="effusion_rate", dst="separation_factor",
         needs=(P("effusion_rate", "", "single-stage separation ratio √(M₂/M₁)", lo=1.001, hi=4),
                P("stages", "", "number of effusion stages", kind="posint", lo=1, hi=2000)),
         answer="separation_factor", unit="", kind="positive",
         fn=lambda v: {"separation_factor": v["effusion_rate"] ** v["stages"]},
         traps=(Trap("multiplies_by_stages", "multiplies the ratio by the number of stages",
                     lambda v: v["effusion_rate"] * v["stages"]),),
         formula="f = (M₂/M₁)^(x/2)", asks="overall separation factor"),
    Step(tx=97, src="gas_state", dst="molecular_speed",
         needs=(P("P", "atm", "pressure", lo=0.1, hi=20), P("V", "L", "volume", lo=0.1, hi=100),
                P("gas_mass", "g", "total mass of the gas", lo=0.1, hi=500)),
         answer="molecular_speed", unit="m s⁻¹", kind="positive",
         fn=lambda v: {"molecular_speed": sqrt(3 * v["P"] * 101325 * v["V"] * 1e-3 / (v["gas_mass"] * 1e-3))},
         traps=(Trap("forgets_3", "uses PV = mu²", lambda v: sqrt(v["P"] * 101325 * v["V"] * 1e-3 / (v["gas_mass"] * 1e-3))),),
         constants=("1 atm = 101325 Pa",), formula="PV = ⅓ m N u² → u_rms = √(3PV/m_total)",
         asks="root-mean-square speed (m s⁻¹)"),
    _speed_step(98), _speed_step(99), _speed_step(100),
    Step(tx=101, src="temperature", dst="gas_kinetic_energy",
         needs=(P("temperature", "K", "temperature", kind="temperature", lo=100, hi=1500, role="gas"),
                P("amount", "", "per mole or per molecule", kind="choice", choices=("per mole", "per molecule"))),
         answer="gas_kinetic_energy", unit="J", kind="positive",
         fn=lambda v: {"gas_kinetic_energy": 1.5 * (C.R_J if v["amount"] == "per mole" else C.K_B) * v["temperature"]},
         traps=(Trap("forgets_3_2", "uses RT (or kT)",
                     lambda v: (C.R_J if v["amount"] == "per mole" else C.K_B) * v["temperature"]),),
         constants=(const("R_J"), const("K_B")), formula="KE = (3/2)RT per mole = (3/2)kT per molecule",
         asks="average translational kinetic energy (J)"),
    Step(tx=103, src="gas_state", dst="vdw_constants",
         needs=(P("P", "atm", "measured pressure", lo=1, hi=200), P("V", "L", "volume", lo=0.05, hi=50),
                P("T", "K", "temperature", kind="temperature", lo=150, hi=800),
                P("n", "mol", "amount of gas", lo=0.1, hi=10), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2)),
         answer="a", unit="atm L² mol⁻²", kind="positive", gives=("b",), fn=_vdw_a,
         traps=(Trap("ignores_nb", "drops the excluded volume", _vdw_a_trap),),
         constants=(const("R_LATM"),), formula="(P + an²/V²)(V − nb) = nRT", asks="van der Waals constant a"),
    Step(tx=104, src="vdw_constants", dst="compressibility_factor",
         needs=(P("a", "atm L² mol⁻²", "van der Waals a", lo=0.03, hi=20), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2),
                P("T", "K", "temperature", kind="temperature", lo=150, hi=800),
                P("P", "atm", "pressure", lo=0.1, hi=500),
                P("regime", "", "pressure regime", kind="choice", choices=("low pressure", "high pressure"))),
         answer="compressibility_factor", unit="", kind="positive",
         fn=lambda v: {"compressibility_factor": _z(v, v["regime"])},
         traps=(Trap("other_regime", "uses the formula for the other pressure regime",
                     lambda v: _z(v, "high pressure" if v["regime"] == "low pressure" else "low pressure")),),
         constants=(const("R_LATM"),), formula="low P: Z = 1 − a/(V_m RT) ≈ 1 − aP/(RT)²; high P: Z = 1 + Pb/RT",
         asks="compressibility factor Z"),
    Step(tx=105, src="vdw_constants", dst="virial_coefficient",
         needs=(P("a", "atm L² mol⁻²", "van der Waals a", lo=0.03, hi=20), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2),
                P("T", "K", "temperature", kind="temperature", lo=150, hi=1500)),
         answer="virial_coefficient", unit="L mol⁻¹", kind="real",
         fn=lambda v: {"virial_coefficient": v["b"] - v["a"] / (C.R_LATM * v["T"])},
         traps=(Trap("sign_error", "uses b + a/RT", lambda v: v["b"] + v["a"] / (C.R_LATM * v["T"])),),
         constants=(const("R_LATM"),), formula="B = b − a/RT", asks="second virial coefficient B (L mol⁻¹)"),
    Step(tx=106, src="vdw_constants", dst="boyle_temperature",
         needs=(P("a", "atm L² mol⁻²", "van der Waals a", lo=0.03, hi=20), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2)),
         answer="boyle_temperature", unit="K", kind="positive",
         fn=lambda v: {"boyle_temperature": v["a"] / (v["b"] * C.R_LATM)},
         traps=(Trap("critical_instead", "uses T_c = 8a/27Rb", lambda v: 8 * v["a"] / (27 * C.R_LATM * v["b"])),),
         constants=(const("R_LATM"),), formula="T_B = a/(bR)", asks="Boyle temperature (K)"),
    Step(tx=107, src="vdw_constants", dst="critical_constants",
         needs=(P("a", "atm L² mol⁻²", "van der Waals a", lo=0.03, hi=20), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2),
                P("which", "", "critical constant asked", kind="choice", choices=("T_c", "P_c", "V_c"))),
         answer="critical_constants", unit="", kind="positive", gives=("Tc", "Pc", "Vc"),
         fn=lambda v: _critical(v),
         traps=(Trap("boyle_for_tc", "uses a/bR for T_c or a/27b for P_c",
                     lambda v: {"T_c": v["a"] / (v["b"] * C.R_LATM), "P_c": v["a"] / (27 * v["b"]),
                                "V_c": v["b"]}[v["which"]]),),
         constants=(const("R_LATM"),), formula="T_c = 8a/27Rb; P_c = a/27b²; V_c = 3b",
         asks="the critical constant (K, atm or L mol⁻¹)"),
    Step(tx=108, src="critical_constants", dst="reduced_state",
         needs=(P("Tc", "K", "critical temperature", lo=5, hi=700), P("Pc", "atm", "critical pressure", lo=2, hi=250),
                P("T", "K", "temperature of the gas", kind="temperature", lo=5, hi=1500),
                P("P", "atm", "pressure of the gas", lo=0.1, hi=500),
                P("which", "", "reduced variable asked", kind="choice", choices=("reduced temperature", "reduced pressure"))),
         answer="reduced_state", unit="", kind="positive",
         fn=lambda v: {"reduced_state": v["T"] / v["Tc"] if v["which"] == "reduced temperature" else v["P"] / v["Pc"]},
         traps=(Trap("inverted", "divides the critical value by the actual value",
                     lambda v: v["Tc"] / v["T"] if v["which"] == "reduced temperature" else v["Pc"] / v["P"]),),
         formula="T_r = T/T_c; P_r = P/P_c", asks="the reduced variable"),
    Step(tx=109, src="vdw_constants", dst="inversion_temperature",
         needs=(P("a", "atm L² mol⁻²", "van der Waals a", lo=0.03, hi=20), P("b", "L mol⁻¹", "van der Waals b", lo=0.01, hi=0.2)),
         answer="inversion_temperature", unit="K", kind="positive",
         fn=lambda v: {"inversion_temperature": 2 * v["a"] / (v["b"] * C.R_LATM)},
         traps=(Trap("boyle_instead", "uses a/bR (the Boyle temperature)", lambda v: v["a"] / (v["b"] * C.R_LATM)),),
         constants=(const("R_LATM"),), formula="T_i = 2a/(bR); cooling on expansion below T_i",
         asks="Joule-Thomson inversion temperature (K)"),
]


def _z(v, regime):
    if regime == "high pressure":
        return 1 + v["P"] * v["b"] / (C.R_LATM * v["T"])
    return 1 - v["a"] * v["P"] / (C.R_LATM * v["T"]) ** 2


def _critical(v):
    a, b = v["a"], v["b"]
    tc, pc, vc = 8 * a / (27 * C.R_LATM * b), a / (27 * b ** 2), 3 * b
    return {"critical_constants": {"T_c": tc, "P_c": pc, "V_c": vc}[v["which"]], "Tc": tc, "Pc": pc, "Vc": vc}
