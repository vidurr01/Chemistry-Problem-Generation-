"""Physical engine — Atomic Structure (concept-book TXs 55-83, 326, 327)."""

from __future__ import annotations

import math

from core.engine.base import Derive, EngineError, Param, Step, Trap, sqrt
from core.engine.chem import C, SYMBOLS, const

P = Param
L_LETTER = "spdfghi"


def _orbit(v):
    n, Z = v["n"], v["Z"]
    return {"n": n, "Z": Z}


_ORBIT_PARAMS = (P("n", "", "principal quantum number of the orbit", kind="posint", lo=1, hi=7),
                 P("Z", "", "atomic number of the one-electron species (H 1, He⁺ 2, Li²⁺ 3)",
                   kind="posint", lo=1, hi=4))


def _energy(v):
    return {"electron_energy": -C.E1_EV * v["Z"] ** 2 / v["n"] ** 2, "n": v["n"], "Z": v["Z"]}


_LEVEL_ENERGY = Derive(
    "electron_energy",
    (P("Z", "", "atomic number of the one-electron species (H 1, He⁺ 2, Li²⁺ 3)", kind="posint", lo=1, hi=4),),
    lambda v: -C.E1_EV * v["Z"] ** 2 / v["n"] ** 2)


def _z2(v):
    """Z² implied by the energy of level n (hydrogen-like: E_n = −13.6 Z²/n²)."""
    return -v["electron_energy"] * v["n"] ** 2 / C.E1_EV


def _delta_e(v):
    n1, n2 = v["lower_level"], v["n"]
    if not n1 < n2:
        raise EngineError("the lower level must be below the upper level")
    return C.E1_EV * _z2(v) * (1 / n1 ** 2 - 1 / n2 ** 2)


def _rydberg_nm(n1, n2, z2, squares=True):
    if not n1 < n2:
        raise EngineError("the lower level must be below the upper level")
    term = (1 / n1 ** 2 - 1 / n2 ** 2) if squares else (1 / n1 - 1 / n2)
    wavenumber = C.RYDBERG_CM * z2 * term              # cm^-1
    return 1e7 / wavenumber                              # nm


SERIES = {"Lyman": 1, "Balmer": 2, "Paschen": 3, "Brackett": 4, "Pfund": 5}
LINES = {"first (alpha)": 1, "second (beta)": 2, "third (gamma)": 3, "fourth (delta)": 4}


def _spectral_line(v):
    n1 = SERIES[v["series"]]
    n2 = n1 + LINES[v["line"]]
    return {"electron_energy": -C.E1_EV * v["Z"] ** 2 / n2 ** 2, "n": n2, "Z": v["Z"], "lower_level": n1}


def _spectral_line_trap(v):
    n1 = SERIES[v["series"]]
    n2 = n1 + LINES[v["line"]] - 1 if LINES[v["line"]] > 1 else n1 + 2
    return {"electron_energy": -C.E1_EV * v["Z"] ** 2 / n2 ** 2, "n": n2, "lower_level": n1}


# ── Electronic configuration ─────────────────────────────────────────────────

def _filling_order():
    subs = [(n, l) for n in range(1, 8) for l in range(0, min(n, 4))]
    return sorted(subs, key=lambda s: (s[0] + s[1], s[0]))


_ORDER = _filling_order()

# Neutral-atom exceptions to the Aufbau order: {Z: {(n, l): electrons}} applied on top.
_EXCEPTIONS = {
    24: {(3, 2): 5, (4, 0): 1}, 29: {(3, 2): 10, (4, 0): 1},
    41: {(4, 2): 4, (5, 0): 1}, 42: {(4, 2): 5, (5, 0): 1}, 44: {(4, 2): 7, (5, 0): 1},
    45: {(4, 2): 8, (5, 0): 1}, 46: {(4, 2): 10, (5, 0): 0}, 47: {(4, 2): 10, (5, 0): 1},
    78: {(5, 2): 9, (6, 0): 1}, 79: {(5, 2): 10, (6, 0): 1},
}


def configuration(Z: int, charge: int = 0, exceptions: bool = True, remove_ns_first: bool = True) -> dict:
    """{(n, l): electrons} for element Z with the given positive charge."""
    if not 1 <= Z <= 86:
        raise EngineError(f"Z = {Z} is outside the supported range 1-86")
    occ, left = {}, Z
    for n, l in _ORDER:
        if left <= 0:
            break
        k = min(left, 2 * (2 * l + 1))
        occ[(n, l)] = k
        left -= k
    if exceptions and Z in _EXCEPTIONS:
        occ.update(_EXCEPTIONS[Z])
    if charge < 0 or charge > 4:
        raise EngineError("only cations with charge 0 to +4 are supported")
    for _ in range(charge):
        filled = [s for s, e in occ.items() if e > 0]
        if remove_ns_first:
            s = max(filled, key=lambda s: (s[0], s[1]))       # highest n first, then highest l
        else:
            s = max(filled, key=lambda s: (s[0] + s[1], s[0]))  # reverse filling order (wrong for ions)
        occ[s] -= 1
    return {s: e for s, e in occ.items() if e > 0}


def config_text(occ: dict) -> str:
    return " ".join(f"{n}{L_LETTER[l]}{e}" for (n, l), e in sorted(occ.items()))


def unpaired(occ: dict) -> int:
    total = 0
    for (n, l), e in occ.items():
        orbitals = 2 * l + 1
        total += e if e <= orbitals else 2 * orbitals - e
    return total


def _config(v):
    occ = configuration(v["atomic_number"], v["charge"])
    return {"electronic_configuration": config_text(occ), "unpaired_electrons": unpaired(occ),
            "_constants": [f"{SYMBOLS[v['atomic_number'] - 1]} has atomic number {v['atomic_number']}"]}


def _config_trap_order(v):
    if not v["charge"]:
        raise EngineError("neutral atom")
    occ = configuration(v["atomic_number"], v["charge"], remove_ns_first=False)
    return {"electronic_configuration": config_text(occ), "unpaired_electrons": unpaired(occ)}


def _config_trap_exception(v):
    if v["atomic_number"] not in _EXCEPTIONS:
        raise EngineError("no exception")
    occ = configuration(v["atomic_number"], v["charge"], exceptions=False)
    return {"electronic_configuration": config_text(occ), "unpaired_electrons": unpaired(occ)}


# ── Orbitals ─────────────────────────────────────────────────────────────────

def _parse_orbital(label: str):
    s = label.strip().lower()
    if len(s) < 2 or not s[:-1].isdigit() or s[-1] not in L_LETTER:
        raise EngineError(f"cannot read orbital {label!r} (expected e.g. '3d')")
    n, l = int(s[:-1]), L_LETTER.index(s[-1])
    if l >= n:
        raise EngineError(f"{label} does not exist (l must be < n)")
    return n, l


def _qn_label(v):
    n, l, m = v["n"], v["l"], v["m"]
    if not (0 <= l < n and -l <= m <= l):
        return {"orbital_label": "not allowed"}
    return {"orbital_label": f"{n}{L_LETTER[l]}"}


def _node_count(v):
    n, l = _parse_orbital(v["orbital_label"])
    return {"node_count": {"radial": n - l - 1, "angular": l, "total": n - 1}[v["node_type"]]}


def _nuclide_relation(v):
    z1, a1, z2, a2 = v["Z1"], v["A1"], v["Z2"], v["A2"]
    if (z1, a1) == (z2, a2):
        raise EngineError("the two nuclides are identical")
    if z1 == z2:
        rel = "isotopes"
    elif a1 == a2:
        rel = "isobars"
    elif a1 - z1 == a2 - z2:
        rel = "isotones"
    elif a1 - 2 * z1 == a2 - 2 * z2:
        rel = "isodiaphers"
    else:
        rel = "none of these"
    return {"nuclide_relation": rel}


def _nuclide_relation_trap(v):
    rel = _nuclide_relation(v)["nuclide_relation"]
    swap = {"isobars": "isotones", "isotones": "isobars"}
    if rel not in swap:
        raise EngineError("no confusion")
    return swap[rel]


def _check_nuclide(v):
    if not 1 <= v["Z"] <= 100 or v["A"] < v["Z"]:
        raise EngineError("mass number must be at least the atomic number")


STEPS = [
    Step(tx=55, src="nuclide", dst="particle_count",
         needs=(P("Z", "", "atomic number", kind="posint", lo=1, hi=92),
                P("A", "", "mass number", kind="posint", lo=1, hi=240),
                P("charge", "", "charge on the species (0 for the neutral atom)", kind="integer", lo=-3, hi=3),
                P("particle", "", "particle to count", kind="choice", choices=("protons", "neutrons", "electrons"))),
         answer="particle_count", unit="", kind="count",
         fn=lambda v: (_check_nuclide(v), {"particle_count": {"protons": v["Z"], "neutrons": v["A"] - v["Z"],
                                                              "electrons": v["Z"] - v["charge"]}[v["particle"]]})[1],
         traps=(Trap("charge_sign_reversed", "adds a positive charge to the electron count",
                     lambda v: v["Z"] + v["charge"] if v["particle"] == "electrons" else v["A"]),),
         formula="p = Z; n = A − Z; e = Z − charge", asks="number of the asked particles"),
    Step(tx=56, src="mass_number", dst="nuclear_radius",
         needs=(P("mass_number", "", "mass number A", kind="posint", lo=1, hi=240),),
         answer="nuclear_radius", unit="cm", kind="positive",
         fn=lambda v: {"nuclear_radius": 1.33e-13 * v["mass_number"] ** (1 / 3)},
         traps=(Trap("square_root", "uses A^(1/2)", lambda v: 1.33e-13 * v["mass_number"] ** 0.5),
                Trap("linear", "uses A", lambda v: 1.33e-13 * v["mass_number"])),
         constants=("R₀ = 1.33 × 10⁻¹³ cm",), formula="R = R₀ A^(1/3)", asks="nuclear radius (cm)"),
    Step(tx=57, src="alpha_kinetic_energy", dst="closest_approach",
         needs=(P("alpha_kinetic_energy", "MeV", "kinetic energy of the α-particle", lo=1, hi=10),
                P("target_Z", "", "atomic number of the target nucleus", kind="posint", lo=10, hi=92)),
         answer="closest_approach", unit="m", kind="positive",
         fn=lambda v: {"closest_approach": C.K_COULOMB * 2 * v["target_Z"] * C.E_CHARGE ** 2
                       / (v["alpha_kinetic_energy"] * 1e6 * C.E_CHARGE)},
         traps=(Trap("alpha_charge_e", "takes the α-particle charge as e instead of 2e",
                     lambda v: C.K_COULOMB * v["target_Z"] * C.E_CHARGE ** 2
                     / (v["alpha_kinetic_energy"] * 1e6 * C.E_CHARGE)),),
         constants=(const("K_COULOMB"), const("E_CHARGE")),
         formula="KE = k (2e)(Ze)/r at closest approach", asks="distance of closest approach (m)"),
    Step(tx=58, src="wavelength", dst="photon_energy",
         needs=(P("wavelength", "nm", "wavelength of the radiation", lo=50, hi=2000),),
         answer="photon_energy", unit="eV", kind="positive",
         fn=lambda v: {"photon_energy": C.EV_NM / v["wavelength"]},
         traps=(Trap("inverted", "computes λ/hc", lambda v: v["wavelength"] / C.EV_NM),),
         constants=(const("EV_NM"),), formula="E = hc/λ = 1240/λ(nm) eV", asks="energy of one photon (eV)"),
    Step(tx=59, src="photon_energy", dst="number_of_photons",
         needs=(P("photon_energy", "eV", "energy of one photon", lo=0.5, hi=20),
                P("power", "W", "power of the source", lo=1e-3, hi=1000),
                P("time", "s", "duration of emission", lo=1e-3, hi=1e4)),
         answer="number_of_photons", unit="", kind="positive",
         fn=lambda v: {"number_of_photons": v["power"] * v["time"] / (v["photon_energy"] * C.E_CHARGE)},
         traps=(Trap("forgets_eV_to_J", "divides joules by the photon energy in eV",
                     lambda v: v["power"] * v["time"] / v["photon_energy"]),),
         constants=(const("E_CHARGE"),), formula="N = P t / E_photon", asks="number of photons emitted"),
    Step(tx=60, src="bohr_orbit", dst="electron_energy", needs=_ORBIT_PARAMS,
         answer="electron_energy", unit="eV", kind="negative", gives=("n", "Z"), fn=_energy,
         traps=(Trap("linear_in_Z", "uses Z instead of Z²", lambda v: -C.E1_EV * v["Z"] / v["n"] ** 2),
                Trap("linear_in_n", "uses n instead of n²", lambda v: -C.E1_EV * v["Z"] ** 2 / v["n"])),
         constants=(const("E1_EV"),), formula="E_n = −13.6 Z²/n² eV", asks="energy of the electron (eV)"),
    Step(tx=61, src="bohr_orbit", dst="orbit_radius", needs=_ORBIT_PARAMS,
         answer="orbit_radius", unit="Å", kind="positive", gives=("n", "Z"),
         fn=lambda v: {"orbit_radius": C.BOHR_R_A * v["n"] ** 2 / v["Z"], "n": v["n"], "Z": v["Z"]},
         traps=(Trap("multiplies_by_Z", "multiplies by Z instead of dividing", lambda v: C.BOHR_R_A * v["n"] ** 2 * v["Z"]),
                Trap("linear_in_n", "uses n instead of n²", lambda v: C.BOHR_R_A * v["n"] / v["Z"])),
         constants=(const("BOHR_R_A"),), formula="r_n = 0.529 n²/Z Å", asks="radius of the orbit (Å)"),
    Step(tx=62, src="bohr_orbit", dst="electron_velocity", needs=_ORBIT_PARAMS,
         answer="electron_velocity", unit="m s⁻¹", kind="positive", gives=("n", "Z", "orbit_radius_m"),
         fn=lambda v: {"electron_velocity": C.V1_MS * v["Z"] / v["n"], "n": v["n"], "Z": v["Z"],
                       "orbit_radius_m": C.BOHR_R_A * 1e-10 * v["n"] ** 2 / v["Z"]},
         traps=(Trap("uses_n_squared", "divides by n² instead of n", lambda v: C.V1_MS * v["Z"] / v["n"] ** 2),),
         constants=(const("V1_MS"), const("BOHR_R_A")), formula="v_n = 2.18 × 10⁶ Z/n m s⁻¹",
         asks="velocity of the electron (m s⁻¹)"),
    Step(tx=63, src="electron_velocity", dst="revolutions_per_second",
         needs=(P("electron_velocity", "m s⁻¹", "velocity of the electron", lo=1e5, hi=1e7),
                P("orbit_radius_m", "m", "radius of the orbit", lo=1e-11, hi=1e-8)),
         answer="revolutions_per_second", unit="s⁻¹", kind="positive",
         fn=lambda v: {"revolutions_per_second": v["electron_velocity"] / (2 * math.pi * v["orbit_radius_m"])},
         traps=(Trap("forgets_2pi", "divides by r instead of 2πr", lambda v: v["electron_velocity"] / v["orbit_radius_m"]),),
         formula="f = v / 2πr", asks="number of revolutions per second"),
    Step(tx=64, src="bohr_orbit", dst="angular_momentum", needs=_ORBIT_PARAMS,
         answer="angular_momentum", unit="J s", kind="positive",
         fn=lambda v: {"angular_momentum": v["n"] * C.H / (2 * math.pi)},
         traps=(Trap("forgets_2pi", "uses nh", lambda v: v["n"] * C.H),),
         constants=(const("H"),), formula="mvr = nh/2π", asks="angular momentum of the electron (J s)"),
    Step(tx=65, src="electron_energy", dst="photon_energy",
         needs=(P("n", "", "upper level of the transition", kind="posint", lo=2, hi=7),
                P("lower_level", "", "lower level of the transition", kind="posint", lo=1, hi=6)),
         derive=(_LEVEL_ENERGY,),
         answer="photon_energy", unit="eV", kind="positive",
         fn=lambda v: {"photon_energy": _delta_e(v)},
         traps=(Trap("forgets_Z_squared", "drops Z²", lambda v: _delta_e(v) / _z2(v)),),
         constants=(const("E1_EV"),), formula="ΔE = 13.6 Z² (1/n₁² − 1/n₂²) eV",
         asks="energy of the emitted photon (eV)"),
    Step(tx=66, src="electron_energy", dst="wavelength",
         needs=(P("n", "", "upper level of the transition", kind="posint", lo=2, hi=7),
                P("lower_level", "", "lower level of the transition", kind="posint", lo=1, hi=6)),
         derive=(_LEVEL_ENERGY,),
         answer="wavelength", unit="nm", kind="positive",
         fn=lambda v: {"wavelength": _rydberg_nm(v["lower_level"], v["n"], _z2(v))},
         traps=(Trap("forgets_Z_squared", "drops Z²", lambda v: _rydberg_nm(v["lower_level"], v["n"], 1.0)),
                Trap("no_squares", "uses 1/n instead of 1/n²",
                     lambda v: _rydberg_nm(v["lower_level"], v["n"], _z2(v), squares=False))),
         constants=(const("RYDBERG_CM"),), formula="1/λ = R_H Z² (1/n₁² − 1/n₂²)",
         asks="wavelength of the spectral line (nm)"),
    Step(tx=67, src="spectral_line", dst="electron_energy",
         needs=(P("series", "", "spectral series", kind="choice", choices=tuple(SERIES)),
                P("line", "", "line of the series", kind="choice", choices=tuple(LINES)),
                P("Z", "", "atomic number of the one-electron species", kind="posint", lo=1, hi=4)),
         answer="electron_energy", unit="eV", kind="negative", gives=("n", "Z", "lower_level"),
         fn=_spectral_line,
         traps=(Trap("line_index_off_by_one", "counts the line from the wrong level", _spectral_line_trap),),
         constants=(const("E1_EV"),), formula="Lyman n₁=1, Balmer 2, Paschen 3...; first line n₂ = n₁ + 1",
         final=("n", "", "posint", "principal quantum number of the upper level"),
         asks="upper level of the line"),
    Step(tx=68, src="excited_sample", dst="spectral_line_count",
         needs=(P("upper_level", "", "level the electrons are excited to", kind="posint", lo=2, hi=8),
                P("final_level", "", "level they return to", kind="posint", lo=1, hi=5),
                P("sample", "", "many atoms or one isolated atom", kind="choice",
                  choices=("a sample of many atoms", "a single isolated atom"))),
         answer="spectral_line_count", unit="", kind="count",
         fn=lambda v: {"spectral_line_count": _lines(v, v["sample"] == "a sample of many atoms")},
         traps=(Trap("wrong_formula", "uses the other formula (sample vs single atom)",
                     lambda v: _lines(v, v["sample"] != "a sample of many atoms")),),
         formula="sample: Δn(Δn + 1)/2; single atom: Δn", asks="maximum number of spectral lines"),
    Step(tx=69, src="ionization_energy", dst="electron_energy",
         needs=(P("ionization_energy", "eV", "ionisation energy from the ground state", lo=5, hi=150),
                P("n", "", "level whose energy is asked", kind="posint", lo=1, hi=6)),
         answer="electron_energy", unit="eV", kind="negative", gives=("n",),
         fn=lambda v: {"electron_energy": -v["ionization_energy"] / v["n"] ** 2, "n": v["n"]},
         traps=(Trap("linear_in_n", "divides by n instead of n²", lambda v: -v["ionization_energy"] / v["n"]),),
         formula="E_GS = −IE; E_n = E_GS / n²", asks="energy of the electron in level n (eV)"),
    Step(tx=70, src="electron_energy", dst="electron_kinetic_energy",
         needs=(P("electron_energy", "eV", "total energy of the electron", kind="negative", lo=-122, hi=-0.3),
                P("which", "", "energy asked", kind="choice", choices=("kinetic", "potential"))),
         answer="electron_kinetic_energy", unit="eV", kind="real",
         fn=lambda v: {"electron_kinetic_energy": -v["electron_energy"] if v["which"] == "kinetic" else 2 * v["electron_energy"]},
         traps=(Trap("sign_error", "takes KE = E or PE = E/2",
                     lambda v: v["electron_energy"] if v["which"] == "kinetic" else v["electron_energy"] / 2),),
         formula="KE = −E; PE = 2E", asks="the asked energy (eV)"),
    Step(tx=71, src="frequency", dst="photoelectron_ke",
         needs=(P("frequency", "Hz", "frequency of the incident radiation", lo=1e14, hi=5e15),
                P("work_function", "eV", "work function of the metal", lo=1.5, hi=6)),
         answer="photoelectron_ke", unit="eV", kind="positive",
         fn=lambda v: {"photoelectron_ke": C.H * v["frequency"] / C.E_CHARGE - v["work_function"]},
         traps=(Trap("forgets_work_function", "uses hν alone", lambda v: C.H * v["frequency"] / C.E_CHARGE),),
         constants=(const("H"), const("E_CHARGE")), formula="KE_max = hν − W",
         asks="maximum kinetic energy of the photoelectrons (eV)"),
    Step(tx=72, src="stopping_potential", dst="photoelectron_ke",
         needs=(P("stopping_potential", "V", "stopping potential", lo=0.2, hi=10),),
         answer="photoelectron_ke", unit="eV", kind="positive", gives=("max_speed",),
         fn=lambda v: {"photoelectron_ke": v["stopping_potential"],
                       "max_speed": sqrt(2 * C.E_CHARGE * v["stopping_potential"] / C.M_E)},
         traps=(Trap("forgets_factor_2", "uses v = √(eV₀/m)",
                     lambda v: {"max_speed": sqrt(C.E_CHARGE * v["stopping_potential"] / C.M_E)}),),
         constants=(const("E_CHARGE"), const("M_E")), formula="eV₀ = KE_max = ½mv²",
         final=("max_speed", "m s⁻¹", "positive", "maximum speed of the photoelectrons"),
         asks="maximum kinetic energy of the photoelectrons (eV)"),
    Step(tx=73, src="momentum", dst="de_broglie_wavelength",
         needs=(P("momentum", "kg m s⁻¹", "momentum of the particle", lo=1e-30, hi=10),),
         answer="de_broglie_wavelength", unit="m", kind="positive",
         fn=lambda v: {"de_broglie_wavelength": C.H / v["momentum"]},
         traps=(Trap("uses_hbar", "uses h/2π", lambda v: C.H / (2 * math.pi * v["momentum"])),),
         constants=(const("H"),), formula="λ = h/p", asks="de Broglie wavelength (m)"),
    Step(tx=74, src="bohr_orbit", dst="de_broglie_wavelength", needs=_ORBIT_PARAMS,
         answer="de_broglie_wavelength", unit="m", kind="positive",
         fn=lambda v: {"de_broglie_wavelength": 2 * math.pi * C.BOHR_R_A * 1e-10 * v["n"] / v["Z"]},
         traps=(Trap("forgets_n_waves", "takes the whole circumference as one wavelength",
                     lambda v: 2 * math.pi * C.BOHR_R_A * 1e-10 * v["n"] ** 2 / v["Z"]),),
         constants=(const("BOHR_R_A"),), formula="2πr_n = nλ", asks="de Broglie wavelength of the electron (m)"),
    Step(tx=75, src="position_uncertainty", dst="momentum_uncertainty",
         needs=(P("position_uncertainty", "m", "uncertainty in position", lo=1e-15, hi=1e-3),),
         answer="momentum_uncertainty", unit="kg m s⁻¹", kind="positive",
         fn=lambda v: {"momentum_uncertainty": C.H / (4 * math.pi * v["position_uncertainty"])},
         traps=(Trap("uses_2pi", "uses h/2π", lambda v: C.H / (2 * math.pi * v["position_uncertainty"])),
                Trap("uses_h", "uses h", lambda v: C.H / v["position_uncertainty"])),
         constants=(const("H"),), formula="Δx·Δp ≥ h/4π", asks="minimum uncertainty in momentum (kg m s⁻¹)"),
    Step(tx=76, src="quantum_numbers", dst="orbital_label",
         needs=(P("n", "", "principal quantum number", kind="posint", lo=1, hi=6),
                P("l", "", "azimuthal quantum number", kind="count", lo=0, hi=4),
                P("m", "", "magnetic quantum number", kind="integer", lo=-4, hi=4)),
         answer="orbital_label", unit="", kind="text", fn=_qn_label,
         traps=(Trap("letter_off_by_one", "maps l to the next letter",
                     lambda v: f"{v['n']}{L_LETTER[v['l'] + 1]}" if 0 <= v["l"] < v["n"] and abs(v["m"]) <= v["l"] else "allowed"),),
         formula="l = 0..n−1, m = −l..+l; l = 0 s, 1 p, 2 d, 3 f",
         asks="the orbital described (or 'not allowed')"),
    Step(tx=77, src="orbital_label", dst="node_count",
         needs=(P("orbital_label", "", "orbital, e.g. '3d'", kind="text"),
                P("node_type", "", "nodes to count", kind="choice", choices=("radial", "angular", "total"))),
         answer="node_count", unit="", kind="count", fn=_node_count,
         traps=(Trap("radial_as_peaks", "counts radial nodes as n − l",
                     lambda v: (lambda n, l: n - l if v["node_type"] == "radial" else n)(*_parse_orbital(v["orbital_label"]))),),
         formula="radial = n − l − 1; angular = l; total = n − 1", asks="number of nodes"),
    Step(tx=78, src="orbital_label", dst="orbital_angular_momentum",
         needs=(P("orbital_label", "", "orbital, e.g. '3d'", kind="text"),),
         answer="orbital_angular_momentum", unit="h/2π", kind="nonneg",
         fn=lambda v: {"orbital_angular_momentum": sqrt((lambda n, l: l * (l + 1))(*_parse_orbital(v["orbital_label"])))},
         traps=(Trap("bohr_like", "uses l h/2π", lambda v: _parse_orbital(v["orbital_label"])[1]),),
         formula="L = √(l(l + 1)) h/2π", asks="orbital angular momentum (in units of h/2π)"),
    Step(tx=79, src="electronic_configuration", dst="magnetic_moment",
         needs=(P("unpaired_electrons", "", "number of unpaired electrons", kind="count", lo=0, hi=7),),
         answer="magnetic_moment", unit="BM", kind="nonneg",
         fn=lambda v: {"magnetic_moment": sqrt(v["unpaired_electrons"] * (v["unpaired_electrons"] + 2))},
         traps=(Trap("n_plus_1", "uses √(n(n + 1))", lambda v: sqrt(v["unpaired_electrons"] * (v["unpaired_electrons"] + 1))),),
         formula="μ = √(n(n + 2)) BM", asks="spin-only magnetic moment (BM)"),
    Step(tx=80, src="shell", dst="electron_capacity",
         needs=(P("n", "", "principal quantum number of the shell", kind="posint", lo=1, hi=6),
                P("count", "", "what to count", kind="choice",
                  choices=("electrons in the shell", "orbitals in the shell"))),
         answer="electron_capacity", unit="", kind="count",
         fn=lambda v: {"electron_capacity": 2 * v["n"] ** 2 if v["count"].startswith("electrons") else v["n"] ** 2},
         traps=(Trap("swaps_electrons_orbitals", "gives n² for electrons or 2n² for orbitals",
                     lambda v: v["n"] ** 2 if v["count"].startswith("electrons") else 2 * v["n"] ** 2),),
         formula="electrons = 2n²; orbitals = n²", asks="the asked count"),
    Step(tx=81, src="atomic_number", dst="electronic_configuration",
         needs=(P("atomic_number", "", "atomic number of the element", kind="posint", lo=1, hi=54),
                P("charge", "", "positive charge of the ion (0 for the atom)", kind="count", lo=0, hi=3)),
         answer="electronic_configuration", unit="", kind="text", gives=("unpaired_electrons",),
         fn=_config,
         traps=(Trap("removes_3d_first", "removes electrons in reverse filling order (3d before 4s)", _config_trap_order),
                Trap("ignores_exception", "ignores the half-filled/full d exception", _config_trap_exception)),
         formula="Aufbau (n + l rule), Pauli, Hund; cations lose ns before (n−1)d",
         final=("unpaired_electrons", "", "count", "number of unpaired electrons"),
         asks="electronic configuration"),
    Step(tx=82, src="orbital_label", dst="radial_peaks",
         needs=(P("orbital_label", "", "orbital, e.g. '3s'", kind="text"),),
         answer="radial_peaks", unit="", kind="posint",
         fn=lambda v: {"radial_peaks": (lambda n, l: n - l)(*_parse_orbital(v["orbital_label"]))},
         traps=(Trap("peaks_as_nodes", "counts n − l − 1", lambda v: (lambda n, l: n - l - 1)(*_parse_orbital(v["orbital_label"]))),),
         formula="peaks in 4πr²R² = n − l", asks="number of peaks in the radial distribution curve"),
    Step(tx=83, src="nuclide_pair", dst="nuclide_relation",
         needs=(P("Z1", "", "atomic number of nuclide 1", kind="posint", lo=1, hi=92),
                P("A1", "", "mass number of nuclide 1", kind="posint", lo=1, hi=240),
                P("Z2", "", "atomic number of nuclide 2", kind="posint", lo=1, hi=92),
                P("A2", "", "mass number of nuclide 2", kind="posint", lo=1, hi=240)),
         answer="nuclide_relation", unit="", kind="text", fn=_nuclide_relation,
         traps=(Trap("isobar_isotone_swap", "swaps the isobar and isotone definitions", _nuclide_relation_trap),),
         formula="isotopes same Z; isobars same A; isotones same A − Z; isodiaphers same A − 2Z",
         asks="relation between the two nuclides"),
    Step(tx=326, src="radial_peaks", dst="orbital_label", not_after=(82,),
         needs=(P("radial_peaks", "", "number of peaks in the radial probability curve", kind="posint", lo=1, hi=5),
                P("n", "", "principal quantum number", kind="posint", lo=1, hi=6)),
         answer="orbital_label", unit="", kind="text",
         fn=lambda v: {"orbital_label": _orbital_from_peaks(v["n"], v["n"] - v["radial_peaks"])},
         traps=(Trap("peaks_as_nodes", "takes peaks = n − l − 1",
                     lambda v: _orbital_from_peaks(v["n"], v["n"] - v["radial_peaks"] - 1)),),
         formula="peaks = n − l", asks="the orbital"),
    Step(tx=327, src="frequency", dst="work_function",
         needs=(P("frequency", "Hz", "threshold frequency (x-intercept of the KE vs ν plot)", lo=1e14, hi=2e15),),
         answer="work_function", unit="eV", kind="positive",
         fn=lambda v: {"work_function": C.H * v["frequency"] / C.E_CHARGE},
         traps=(Trap("leaves_in_joules", "reports hν₀ in joules as eV", lambda v: C.H * v["frequency"]),),
         constants=(const("H"), const("E_CHARGE")), formula="W = hν₀ (slope h, x-intercept ν₀)",
         asks="work function of the metal (eV)"),
]


def _lines(v, sample: bool) -> int:
    d = v["upper_level"] - v["final_level"]
    if d < 1:
        raise EngineError("the upper level must be above the final level")
    return d * (d + 1) // 2 if sample else d


def _orbital_from_peaks(n, l):
    if not 0 <= l < n or l >= len(L_LETTER):
        raise EngineError("no orbital matches")
    return f"{n}{L_LETTER[l]}"
