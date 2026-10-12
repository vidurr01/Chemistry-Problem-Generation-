"""Physical engine — Stoichiometry (concept-book TXs 0-54, 339-341)."""

from __future__ import annotations

from core.engine.base import EngineError, Param, Step, Trap, div
from core.engine.chem import (ATOMIC_MASS, C, balance, check_balanced, const, format_equation,
                              format_formula, parse_equation, parse_formula)

P = Param


def _mass_to_moles(v):
    return {"moles": div(v["mass"], v["molar_mass"])}


_MASS_TO_MOLES_TRAPS = (
    Trap("inverted_ratio", "divides molar mass by mass", lambda v: div(v["molar_mass"], v["mass"])),
    Trap("multiplies_by_molar_mass", "multiplies mass by molar mass", lambda v: v["mass"] * v["molar_mass"]),
)


def _mass_to_moles_step(tx, what):
    return Step(
        tx=tx, src="mass", dst="moles", keeps_role=True,
        needs=(P("mass", "g", f"mass of the {what}", lo=0.1, hi=500),
               P("molar_mass", "g mol⁻¹", f"molar mass of the {what}", lo=1, hi=500)),
        answer="moles", unit="mol", kind="positive", fn=_mass_to_moles,
        traps=_MASS_TO_MOLES_TRAPS, formula="n = m / M",
        asks=f"amount (in mol) of the {what}")


def _species_coef(side_list, species):
    for c, f in side_list:
        if f.replace(" ", "") == species.replace(" ", ""):
            return c
    return None


def _coef(eq_text, species):
    r, p = parse_equation(eq_text)
    c = _species_coef(r, species)
    if c is None:
        c = _species_coef(p, species)
    if c is None:
        raise EngineError(f"{species!r} does not appear in {eq_text!r}")
    return c


def _mole_method(v):
    check_balanced(v["balanced_equation"])
    nk = _coef(v["balanced_equation"], v["known_species"])
    nt = _coef(v["balanced_equation"], v["target_species"])
    return {"moles": v["moles_known"] * nt / nk}


def _poac(v):
    _coef(v["balanced_equation"], v["known_species"])
    _coef(v["balanced_equation"], v["target_species"])
    el = v["element"]
    a_known = parse_formula(v["known_species"])[0].get(el, 0)
    a_target = parse_formula(v["target_species"])[0].get(el, 0)
    if not a_known or not a_target:
        raise EngineError(f"{el} must occur in both {v['known_species']} and {v['target_species']}")
    return {"moles": v["moles_known"] * a_known / a_target}


def _limiting(v):
    eq = v["balanced_equation"]
    check_balanced(eq)
    a, b = _coef(eq, v["reactant_A"]), _coef(eq, v["reactant_B"])
    r, _ = parse_equation(eq)
    if _species_coef(r, v["reactant_A"]) is None or _species_coef(r, v["reactant_B"]) is None:
        raise EngineError("both species must be reactants")
    ra, rb = v["moles"] / a, v["moles_B"] / b
    if abs(ra - rb) <= 1e-9 * max(ra, rb):
        raise EngineError("the reactants are in exact stoichiometric ratio: no limiting reagent")
    lr = v["reactant_A"] if ra < rb else v["reactant_B"]
    return {"limiting_reagent": lr, "n_A": v["moles"], "n_B": v["moles_B"], "coef_A": a,
            "coef_B": b, "reactant_A": v["reactant_A"], "reactant_B": v["reactant_B"]}


def _excess_left(v):
    ra, rb = v["n_A"] / v["coef_A"], v["n_B"] / v["coef_B"]
    if ra < rb:      # A limits, B in excess
        left = v["n_B"] - v["n_A"] * v["coef_B"] / v["coef_A"]
    else:
        left = v["n_A"] - v["n_B"] * v["coef_A"] / v["coef_B"]
    return {"moles": left}


def _excess_left_trap(v):
    ra, rb = v["n_A"] / v["coef_A"], v["n_B"] / v["coef_B"]
    return v["n_B"] - v["n_A"] if ra < rb else v["n_A"] - v["n_B"]


def _sequential(v):
    check_balanced(v["equation_1"])
    check_balanced(v["equation_2"])
    n_mid = v["moles_known"] * _coef(v["equation_1"], v["intermediate_species"]) / _coef(v["equation_1"], v["known_species"])
    n_end = n_mid * _coef(v["equation_2"], v["target_species"]) / _coef(v["equation_2"], v["intermediate_species"])
    return {"moles": n_end}


def _sequential_trap(v):
    n_mid = v["moles_known"] * _coef(v["equation_1"], v["intermediate_species"]) / _coef(v["equation_1"], v["known_species"])
    return n_mid      # treats the second reaction as 1:1


def _empirical(v):
    pc = v["percent_composition"]
    if not isinstance(pc, dict) or len(pc) < 2:
        raise EngineError("give the percentage of at least two elements")
    for el in pc:
        if el not in ATOMIC_MASS:
            raise EngineError(f"unknown element {el}")
    total = sum(pc.values())
    if abs(total - 100) > 1.0:
        raise EngineError(f"percentages add up to {total}, not 100")
    return _formula_from_ratios({el: pc[el] / ATOMIC_MASS[el] for el in pc})


def _formula_from_ratios(moles):
    low = min(moles.values())
    if low <= 0:
        raise EngineError("every element needs a positive percentage")
    ratios = {el: n / low for el, n in moles.items()}
    for k in range(1, 7):
        scaled = {el: r * k for el, r in ratios.items()}
        if all(abs(x - round(x)) <= 0.06 for x in scaled.values()):
            counts = {el: int(round(x)) for el, x in scaled.items()}
            mass = sum(ATOMIC_MASS[el] * n for el, n in counts.items())
            return {"empirical_formula": format_formula(counts), "empirical_mass": mass,
                    "_constants": [f"atomic mass of {el} = {ATOMIC_MASS[el]:g}" for el in counts]}
    raise EngineError("mole ratios do not reach whole numbers with a multiplier up to 6")


def _empirical_trap(v):
    pc = v["percent_composition"]
    return _formula_from_ratios(dict(pc))      # forgets to divide by atomic mass


def _molecular(v):
    counts = parse_formula(v["empirical_formula"])[0]
    m_emp = sum(ATOMIC_MASS[el] * n for el, n in counts.items())
    n = 2 * v["vapour_density"] / m_emp
    if abs(n - round(n)) > 0.03 * n or round(n) < 1:
        raise EngineError(f"molar mass / empirical mass = {n:.3f}, not a whole number")
    k = int(round(n))
    return {"molecular_formula": format_formula({el: c * k for el, c in counts.items()}),
            "molar_mass": 2 * v["vapour_density"],
            "_constants": [f"atomic mass of {el} = {ATOMIC_MASS[el]:g}" for el in counts]}


def _molecular_trap(v):
    counts = parse_formula(v["empirical_formula"])[0]
    m_emp = sum(ATOMIC_MASS[el] * n for el, n in counts.items())
    n = v["vapour_density"] / m_emp           # uses VD as the molar mass
    if abs(n - round(n)) > 0.03 * n or round(n) < 1:
        raise EngineError("not whole")
    return format_formula({el: c * int(round(n)) for el, c in counts.items()})


def _eudiometry(v):
    vh, contraction, co2 = v["gas_volume"], v["contraction_on_cooling"], v["volume_absorbed_by_KOH"]
    x = co2 / vh
    y = 4 * (contraction / vh - 1)
    return {"molecular_formula": _cxhy(x, y)}


def _cxhy(x, y):
    if abs(x - round(x)) > 0.02 or abs(y - round(y)) > 0.02:
        raise EngineError(f"x = {x:.3f}, y = {y:.3f} are not whole numbers")
    x, y = int(round(x)), int(round(y))
    if x < 1 or y < 1 or y % 2 or y > 2 * x + 2:
        raise EngineError(f"C{x}H{y} is not a hydrocarbon")
    return format_formula({"C": x, "H": y})


def _eudiometry_trap(v):
    vh, contraction, co2 = v["gas_volume"], v["contraction_on_cooling"], v["volume_absorbed_by_KOH"]
    # treats water as still gaseous: contraction = V(1 - y/4)
    return _cxhy(co2 / vh, 4 * (1 - contraction / vh))


# ── Oxidation numbers ────────────────────────────────────────────────────────

_PEROXIDE_O = {"H2O2": -1, "Na2O2": -1, "K2O2": -1, "BaO2": -1, "Li2O2": -1, "CaO2": -1,
               "KO2": -0.5, "RbO2": -0.5, "CsO2": -0.5, "NaO2": -0.5, "OF2": 2, "O2F2": 1}
_METAL_HYDRIDES = {"NaH", "LiH", "KH", "CaH2", "MgH2", "BaH2", "LiAlH4", "NaBH4", "AlH3"}
_GROUP1 = {"Li", "Na", "K", "Rb", "Cs"}
_GROUP2 = {"Be", "Mg", "Ca", "Sr", "Ba"}


def _fixed_on(el, formula):
    base = formula.split("^")[0].rstrip("+-")
    if el == "F":
        return -1
    if el == "O":
        return _PEROXIDE_O.get(base, -2)
    if el == "H":
        return -1 if base in _METAL_HYDRIDES else 1
    if el in _GROUP1:
        return 1
    if el in _GROUP2:
        return 2
    if el == "Al":
        return 3
    if el == "Zn":
        return 2
    return None


def _oxidation_number(v):
    formula, target = v["chemical_species"], v["element"]
    counts, charge = parse_formula(formula)
    if target not in counts:
        raise EngineError(f"{target} is not in {formula}")
    known = 0.0
    for el, n in counts.items():
        if el == target:
            continue
        on = _fixed_on(el, formula)
        if on is None:
            raise EngineError(f"{formula}: the oxidation number of {el} is not fixed by the rules, "
                              f"so {target} cannot be found from them alone")
        known += on * n
    return {"oxidation_number": (charge - known) / counts[target]}


def _on_trap_charge(v):
    counts, charge = parse_formula(v["chemical_species"])
    if not charge:
        raise EngineError("neutral")
    known = sum(_fixed_on(el, v["chemical_species"]) * n for el, n in counts.items() if el != v["element"])
    return (0 - known) / counts[v["element"]]          # ignores the ionic charge


def _on_trap_peroxide(v):
    counts, charge = parse_formula(v["chemical_species"])
    base = v["chemical_species"].split("^")[0].rstrip("+-")
    if base not in _PEROXIDE_O or v["element"] == "O":
        raise EngineError("not a peroxide case")
    known = sum((-2 if el == "O" else _fixed_on(el, v["chemical_species"])) * n
                for el, n in counts.items() if el != v["element"])
    return (charge - known) / counts[v["element"]]     # takes O as -2 in a peroxide


def _balance_redox(v):
    reac = [s.strip() for s in v["reactants"].split(",") if s.strip()]
    prod = [s.strip() for s in v["products"].split(",") if s.strip()]
    if not reac or not prod:
        raise EngineError("list the reactants and products, separated by commas")
    coefs = balance(reac, prod)
    nr = len(reac)
    eq = format_equation([(coefs[i], reac[i]) for i in range(nr)],
                         [(coefs[nr + i], prod[i]) for i in range(len(prod))])
    target = v["species_asked"]
    names = reac + prod
    if target not in names:
        raise EngineError(f"{target!r} is not in the skeleton")
    return {"balanced_equation": eq.replace("→", "->"), "coefficient": coefs[names.index(target)],
            "sum_of_coefficients": sum(coefs)}


# ── Redox reagents (n-factor table) ─────────────────────────────────────────

REDOX_N = {
    "KMnO4 in acidic medium (MnO4- -> Mn2+)": 5,
    "KMnO4 in neutral or weakly basic medium (MnO4- -> MnO2)": 3,
    "KMnO4 in strongly basic medium (MnO4- -> MnO4^2-)": 1,
    "K2Cr2O7 in acidic medium (Cr2O7^2- -> 2Cr3+)": 6,
    "oxalate ion with KMnO4 (C2O4^2- -> 2CO2)": 2,
    "H2O2 as oxidant (-> H2O)": 2,
    "H2O2 as reductant (-> O2)": 2,
    "H2O2 decomposition (2H2O2 -> 2H2O + O2)": 1,
    "bleaching powder CaOCl2 with excess KI (Cl -> Cl-)": 2,
    "Mohr's salt FeSO4.(NH4)2SO4.6H2O (Fe2+ -> Fe3+)": 1,
    "ferrous oxalate FeC2O4 with KMnO4 (Fe2+ -> Fe3+ and C2O4^2- -> 2CO2)": 3,
    "IO3- with excess I- in acid (IO3- -> I2)": 5,
    "Cl2 in hot concentrated alkali (3Cl2 -> ClO3- + 5Cl-)": 5 / 3,
    "N2H4 as reductant (N2H4 -> N2)": 4,
    "MnO2 with concentrated HCl (MnO2 -> Mn2+)": 2,
}

_REDOX_CONFUSION = {
    5: (3, "uses the neutral-medium value"), 3: (5, "uses the acidic-medium value"),
    1: (5, "uses the acidic-medium value"), 6: (3, "counts one Cr only"),
    2: (1, "counts one electron"), 5 / 3: (5, "counts only the chlorate-forming Cl"),
    4: (2, "counts two electrons"),
}


def _redox_step(tx, keys, label):
    choices = tuple(keys)

    def fn(v):
        return {"n_factor": REDOX_N[v["redox_reagent"]]}

    def trap(v):
        n = REDOX_N[v["redox_reagent"]]
        if v["redox_reagent"].startswith("ferrous oxalate"):
            return 1
        if v["redox_reagent"].startswith("H2O2 decomposition"):
            return 2
        alt = _REDOX_CONFUSION.get(n)
        if not alt:
            raise EngineError("no confusion")
        return alt[0]

    return Step(tx=tx, src="redox_reagent", dst="n_factor",
                needs=(P("redox_reagent", "", f"the redox reagent and medium ({label})",
                         kind="choice", choices=choices),),
                answer="n_factor", unit="", kind="positive", fn=fn,
                traps=(Trap("wrong_n_factor", "uses the n-factor of a different medium or half-reaction", trap),),
                formula="n-factor = electrons gained or lost per formula unit",
                asks="n-factor of the reagent")


_K = list(REDOX_N)

# ── Steps ────────────────────────────────────────────────────────────────────

STEPS = [
    _mass_to_moles_step(0, "element (as atoms)"),
    _mass_to_moles_step(1, "compound"),
    _mass_to_moles_step(2, "ionic compound (formula units)"),
    Step(tx=3, keeps_role=True, src="moles", dst="number_of_particles",
         needs=(P("moles", "mol", "amount of the substance", lo=0.01, hi=10),
                P("particles_per_unit", "", "number of the counted particles in one formula unit "
                  "(1 to count the molecules themselves)", kind="posint", lo=1, hi=8)),
         answer="number_of_particles", unit="", kind="positive",
         fn=lambda v: {"number_of_particles": v["moles"] * C.NA * v["particles_per_unit"]},
         traps=(Trap("forgets_atomicity", "counts molecules instead of the asked particles",
                     lambda v: v["moles"] * C.NA),),
         constants=(const("NA"),), formula="N = n × N_A × (particles per unit)",
         asks="number of particles"),
    Step(tx=4, src="moles", dst="gas_volume",
         needs=(P("moles", "mol", "amount of the gas", lo=0.01, hi=10, role="gas"),),
         answer="gas_volume", unit="L", kind="positive",
         fn=lambda v: {"gas_volume": v["moles"] * C.MOLAR_VOL_STP},
         traps=(Trap("uses_1_bar_molar_volume", "uses 22.7 L (1 bar) instead of 22.4 L (1 atm)",
                     lambda v: v["moles"] * 22.7),
                Trap("uses_room_temperature_volume", "uses 24.5 L (298 K)", lambda v: v["moles"] * 24.5)),
         constants=(const("MOLAR_VOL_STP"),), formula="V = n × 22.4 L (1 atm, 273 K)",
         asks="volume of the gas at 1 atm and 273 K (L)"),
    Step(tx=5, src="isotopic_abundances", dst="molar_mass",
         needs=(P("isotope_1_mass", "u", "mass of isotope 1", lo=1, hi=240),
                P("isotope_1_percent", "%", "natural abundance of isotope 1", kind="percent", lo=1, hi=99),
                P("isotope_2_mass", "u", "mass of isotope 2", lo=1, hi=240)),
         answer="molar_mass", unit="g mol⁻¹", kind="positive",
         fn=lambda v: {"molar_mass": (v["isotope_1_mass"] * v["isotope_1_percent"]
                                      + v["isotope_2_mass"] * (100 - v["isotope_1_percent"])) / 100},
         traps=(Trap("unweighted_mean", "averages the isotope masses without abundances",
                     lambda v: (v["isotope_1_mass"] + v["isotope_2_mass"]) / 2),
                Trap("swapped_abundances", "attaches each abundance to the other isotope",
                     lambda v: (v["isotope_2_mass"] * v["isotope_1_percent"]
                                + v["isotope_1_mass"] * (100 - v["isotope_1_percent"])) / 100)),
         formula="A_avg = (A1 x1 + A2 x2)/(x1 + x2)", asks="average atomic mass (u)"),
    Step(tx=6, src="moles", dst="molar_mass",
         needs=(P("moles", "mol", "amount of gas 1 in the mixture", lo=0.1, hi=10, role="gas"),
                P("M1", "g mol⁻¹", "molar mass of gas 1", lo=2, hi=200),
                P("moles_2", "mol", "amount of gas 2 in the mixture", lo=0.1, hi=10),
                P("M2", "g mol⁻¹", "molar mass of gas 2", lo=2, hi=200)),
         answer="molar_mass", unit="g mol⁻¹", kind="positive",
         fn=lambda v: {"molar_mass": (v["M1"] * v["moles"] + v["M2"] * v["moles_2"]) / (v["moles"] + v["moles_2"])},
         traps=(Trap("unweighted_mean", "averages the molar masses without mole weighting",
                     lambda v: (v["M1"] + v["M2"]) / 2),),
         formula="M_avg = (M1 n1 + M2 n2)/(n1 + n2)", asks="average molar mass of the mixture"),
    Step(tx=7, src="percent_composition", dst="empirical_formula",
         needs=(P("percent_composition", "% by mass", "mass percentage of each element, e.g. "
                  "{\"C\": 40.0, \"H\": 6.7, \"O\": 53.3}", kind="dict"),),
         answer="empirical_formula", unit="", kind="text", gives=("empirical_mass",),
         fn=_empirical,
         traps=(Trap("skips_atomic_mass", "takes the percentage ratio as the mole ratio", _empirical_trap),),
         formula="mole ratio = %/atomic mass, divide by smallest, scale to whole numbers",
         asks="empirical formula"),
    Step(tx=8, src="empirical_formula", dst="molecular_formula",
         needs=(P("empirical_formula", "", "empirical formula", kind="text"),
                P("vapour_density", "", "vapour density of the compound", lo=5, hi=200)),
         answer="molecular_formula", unit="", kind="text", gives=("molar_mass",),
         fn=_molecular,
         traps=(Trap("vd_as_molar_mass", "uses the vapour density as the molar mass", _molecular_trap),),
         formula="M = 2 × VD; n = M / M_empirical", asks="molecular formula"),
    Step(tx=9, src="vapour_density", dst="molar_mass",
         needs=(P("vapour_density", "", "vapour density (relative to H2)", lo=1, hi=200),),
         answer="molar_mass", unit="g mol⁻¹", kind="positive",
         fn=lambda v: {"molar_mass": 2 * v["vapour_density"]},
         traps=(Trap("vd_as_molar_mass", "takes the vapour density as the molar mass",
                     lambda v: v["vapour_density"]),
                Trap("halves_vd", "divides the vapour density by 2", lambda v: v["vapour_density"] / 2)),
         formula="M = 2 × VD", asks="molar mass (g mol⁻¹)"),
    Step(tx=10, keeps_role=True, src="mass", dst="density",
         needs=(P("mass", "g", "mass of the sample", lo=0.5, hi=500),
                P("volume", "mL", "volume of the sample", lo=0.5, hi=500)),
         answer="density", unit="g mL⁻¹", kind="positive",
         fn=lambda v: {"density": v["mass"] / v["volume"]},
         traps=(Trap("inverted_ratio", "divides volume by mass", lambda v: v["volume"] / v["mass"]),),
         formula="d = m/V; specific gravity = d/d(water, 4 °C)", asks="density (g mL⁻¹)"),
    Step(tx=11, src="balanced_equation", dst="moles",
         needs=(P("balanced_equation", "", "the balanced equation, e.g. '2H2 + O2 -> 2H2O'", kind="text"),
                P("known_species", "", "species whose amount is known", kind="text"),
                P("moles_known", "mol", "amount of the known species", lo=0.05, hi=10),
                P("target_species", "", "species whose amount is asked", kind="text")),
         answer="moles", unit="mol", kind="positive", fn=_mole_method,
         traps=(Trap("ignores_coefficients", "takes the mole ratio as 1:1",
                     lambda v: v["moles_known"]),
                Trap("inverted_coefficients", "inverts the coefficient ratio",
                     lambda v: v["moles_known"] * _coef(v["balanced_equation"], v["known_species"])
                     / _coef(v["balanced_equation"], v["target_species"]))),
         formula="n_target / ν_target = n_known / ν_known", asks="amount of the target species (mol)"),
    Step(tx=12, src="balanced_equation", dst="moles",
         needs=(P("balanced_equation", "", "the reaction (balancing not needed for POAC)", kind="text"),
                P("known_species", "", "species whose amount is known", kind="text"),
                P("moles_known", "mol", "amount of the known species", lo=0.05, hi=10),
                P("target_species", "", "species whose amount is asked", kind="text"),
                P("element", "", "element conserved between the two species", kind="text")),
         answer="moles", unit="mol", kind="positive", fn=_poac,
         traps=(Trap("ignores_atom_count", "ignores how many atoms of the element each species holds",
                     lambda v: v["moles_known"]),),
         formula="POAC: n_known × atoms(known) = n_target × atoms(target)",
         asks="amount of the target species (mol)"),
    Step(tx=13, src="moles", dst="limiting_reagent",
         needs=(P("balanced_equation", "", "the balanced equation", kind="text"),
                P("reactant_A", "", "first reactant (amount = moles)", kind="text"),
                P("moles", "mol", "amount of reactant A", lo=0.05, hi=10, role="reactant"),
                P("reactant_B", "", "second reactant", kind="text"),
                P("moles_B", "mol", "amount of reactant B", lo=0.05, hi=10)),
         answer="limiting_reagent", unit="", kind="text",
         gives=("n_A", "n_B", "coef_A", "coef_B", "reactant_A", "reactant_B"), fn=_limiting,
         traps=(Trap("smaller_amount", "picks the reactant present in smaller amount, ignoring coefficients",
                     lambda v: v["reactant_A"] if v["moles"] < v["moles_B"] else v["reactant_B"]),),
         formula="limiting reagent has the smallest n/ν", asks="the limiting reagent"),
    Step(tx=14, src="limiting_reagent", dst="moles",
         needs=(P("n_A", "mol", "amount of reactant A"), P("n_B", "mol", "amount of reactant B"),
                P("coef_A", "", "coefficient of A in the balanced equation"),
                P("coef_B", "", "coefficient of B in the balanced equation")),
         answer="moles", unit="mol", kind="positive", fn=_excess_left,
         traps=(Trap("subtracts_amounts", "subtracts the amounts directly, ignoring coefficients",
                     _excess_left_trap),),
         formula="left = n_excess − n_LR × ν_excess/ν_LR", asks="amount of the excess reagent left (mol)"),
    Step(tx=15, src="moles", dst="percent_yield",
         needs=(P("moles", "mol", "theoretical amount of product", lo=0.05, hi=10, role="product"),
                P("actual_moles", "mol", "amount of product actually obtained", lo=0.01, hi=10)),
         answer="percent_yield", unit="%", kind="percent",
         fn=lambda v: {"percent_yield": 100 * v["actual_moles"] / v["moles"]},
         traps=(Trap("inverted_ratio", "divides theoretical by actual",
                     lambda v: 100 * v["moles"] / v["actual_moles"]),),
         formula="% yield = actual/theoretical × 100", asks="percentage yield"),
    Step(tx=16, src="balanced_equation", dst="moles",
         needs=(P("equation_1", "", "first balanced equation", kind="text"),
                P("equation_2", "", "second balanced equation (uses a product of the first)", kind="text"),
                P("known_species", "", "starting species in equation 1", kind="text"),
                P("moles_known", "mol", "amount of the starting species", lo=0.05, hi=10),
                P("intermediate_species", "", "product of equation 1 that reacts in equation 2", kind="text"),
                P("target_species", "", "final product in equation 2", kind="text")),
         answer="moles", unit="mol", kind="positive", fn=_sequential,
         traps=(Trap("drops_second_ratio", "treats the second reaction as 1:1", _sequential_trap),),
         formula="carry the product of step 1 into step 2 by mole ratios",
         asks="amount of the final product (mol)"),
    Step(tx=17, keeps_role=True, src="mass_percent", dst="mass",
         needs=(P("mass_percent", "% w/W", "mass percentage of solute in the solution", kind="percent", lo=1, hi=60),
                P("solution_mass", "g", "mass of the solution", lo=10, hi=1000)),
         answer="mass", unit="g", kind="positive",
         fn=lambda v: {"mass": v["mass_percent"] * v["solution_mass"] / 100},
         traps=(Trap("per_100g_solvent", "reads X% as X g per 100 g of solvent",
                     lambda v: v["solution_mass"] * v["mass_percent"] / (100 + v["mass_percent"])),),
         formula="m_solute = (% w/W)/100 × m_solution", asks="mass of solute (g)"),
    Step(tx=18, keeps_role=True, src="mass_percent", dst="mass",
         needs=(P("mass_percent", "% w/V", "grams of solute per 100 mL of solution", kind="percent", lo=0.5, hi=40),
                P("solution_volume", "mL", "volume of the solution", lo=10, hi=2000)),
         answer="mass", unit="g", kind="positive",
         fn=lambda v: {"mass": v["mass_percent"] * v["solution_volume"] / 100},
         traps=(Trap("forgets_per_100", "multiplies without dividing by 100",
                     lambda v: v["mass_percent"] * v["solution_volume"]),),
         formula="m_solute = (% w/V)/100 × V(mL)", asks="mass of solute (g)"),
    Step(tx=19, keeps_role=True, src="mass_percent", dst="molarity",
         needs=(P("mass_percent", "% w/W", "mass percentage of solute", kind="percent", lo=1, hi=98),
                P("density", "g mL⁻¹", "density of the solution", lo=0.8, hi=2.0),
                P("solute_molar_mass", "g mol⁻¹", "molar mass of the solute", lo=10, hi=400)),
         answer="molarity", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"molarity": 10 * v["density"] * v["mass_percent"] / v["solute_molar_mass"]},
         traps=(Trap("forgets_density", "ignores the density (takes 1 g mL⁻¹)",
                     lambda v: 10 * v["mass_percent"] / v["solute_molar_mass"]),),
         formula="M = 10 × d × (% w/W) / M_solute", asks="molarity (mol L⁻¹)"),
    Step(tx=20, keeps_role=True, src="molarity", dst="molality",
         needs=(P("molarity", "mol L⁻¹", "molarity of the solution", lo=0.1, hi=10),
                P("density", "g mL⁻¹", "density of the solution", lo=0.8, hi=2.0),
                P("solute_molar_mass", "g mol⁻¹", "molar mass of the solute", lo=10, hi=400)),
         answer="molality", unit="mol kg⁻¹", kind="positive",
         fn=lambda v: {"molality": 1000 * v["molarity"]
                       / _positive(1000 * v["density"] - v["molarity"] * v["solute_molar_mass"])},
         traps=(Trap("divides_by_density", "divides molarity by density (keeps the solute mass in)",
                     lambda v: v["molarity"] / v["density"]),),
         formula="m = 1000 M / (1000 d − M × M_solute)", asks="molality (mol kg⁻¹)"),
    Step(tx=21, keeps_role=True, src="mole_fraction", dst="molality",
         needs=(P("mole_fraction", "", "mole fraction of the solute", kind="open_fraction", lo=0.01, hi=0.3, role="solute"),
                P("solvent_molar_mass", "g mol⁻¹", "molar mass of the solvent", lo=18, hi=150)),
         answer="molality", unit="mol kg⁻¹", kind="positive",
         fn=lambda v: {"molality": 1000 * v["mole_fraction"] / ((1 - v["mole_fraction"]) * v["solvent_molar_mass"])},
         traps=(Trap("forgets_solvent_fraction", "divides by the solvent molar mass only",
                     lambda v: 1000 * v["mole_fraction"] / v["solvent_molar_mass"]),),
         formula="m = 1000 X_solute / (X_solvent × M_solvent)", asks="molality (mol kg⁻¹)"),
    Step(tx=22, src="gas_volume", dst="mole_fraction",
         needs=(P("gas_volume", "L", "volume of the component gas", lo=0.1, hi=50),
                P("total_volume", "L", "total volume of the gas mixture (same T, P)", lo=0.2, hi=100)),
         answer="mole_fraction", unit="", kind="fraction", roles={"mole_fraction": "gas component"},
         fn=lambda v: {"mole_fraction": v["gas_volume"] / v["total_volume"]},
         traps=(Trap("total_as_other_gas", "takes the total volume as the other component",
                     lambda v: v["gas_volume"] / (v["gas_volume"] + v["total_volume"])),),
         formula="for gases, volume fraction = mole fraction", asks="mole fraction of the component"),
    Step(tx=23, keeps_role=True, src="molarity", dst="molarity",
         needs=(P("molarity", "mol L⁻¹", "initial molarity", lo=0.05, hi=10),
                P("initial_volume", "mL", "initial volume of the solution", lo=5, hi=1000),
                P("water_added", "mL", "volume of water added", lo=5, hi=2000)),
         answer="molarity", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"molarity": v["molarity"] * v["initial_volume"] / (v["initial_volume"] + v["water_added"])},
         traps=(Trap("water_as_final_volume", "takes the water added as the final volume",
                     lambda v: v["molarity"] * v["initial_volume"] / v["water_added"]),),
         formula="M1V1 = M2V2", asks="molarity after dilution (mol L⁻¹)"),
    Step(tx=24, keeps_role=True, src="molarity", dst="molarity",
         needs=(P("molarity", "mol L⁻¹", "molarity of solution 1", lo=0.05, hi=10),
                P("volume_1", "mL", "volume of solution 1", lo=5, hi=1000),
                P("molarity_2", "mol L⁻¹", "molarity of solution 2 (same solute)", lo=0.05, hi=10),
                P("volume_2", "mL", "volume of solution 2", lo=5, hi=1000)),
         answer="molarity", unit="mol L⁻¹", kind="positive",
         fn=lambda v: {"molarity": (v["molarity"] * v["volume_1"] + v["molarity_2"] * v["volume_2"])
                       / (v["volume_1"] + v["volume_2"])},
         traps=(Trap("unweighted_mean", "averages the two molarities",
                     lambda v: (v["molarity"] + v["molarity_2"]) / 2),),
         formula="M = (M1V1 + M2V2)/(V1 + V2)", asks="molarity of the mixture (mol L⁻¹)"),
    Step(tx=25, src="volume_strength", dst="molarity",
         needs=(P("volume_strength", "volume", "volume strength of the H2O2 solution", lo=1, hi=100),),
         answer="molarity", unit="mol L⁻¹", kind="positive", roles={"molarity": "H2O2"},
         fn=lambda v: {"molarity": v["volume_strength"] / 11.2},
         traps=(Trap("uses_22_4", "divides by 22.4 (forgets ½ O2 per H2O2)",
                     lambda v: v["volume_strength"] / 22.4),
                Trap("gives_normality", "divides by 5.6 (normality)", lambda v: v["volume_strength"] / 5.6)),
         constants=(const("MOLAR_VOL_STP"),), formula="M = volume strength / 11.2",
         asks="molarity of the H2O2 solution"),
    Step(tx=26, keeps_role=True, src="ppm", dst="mass",
         needs=(P("ppm", "ppm (by mass)", "concentration of the solute", lo=1, hi=1000),
                P("solution_mass", "g", "mass of the solution", lo=100, hi=1e7)),
         answer="mass", unit="g", kind="positive",
         fn=lambda v: {"mass": v["ppm"] * v["solution_mass"] / 1e6},
         traps=(Trap("uses_1e3", "divides by 10³ instead of 10⁶", lambda v: v["ppm"] * v["solution_mass"] / 1e3),),
         formula="m_solute = ppm × m_solution / 10⁶", asks="mass of solute (g)"),
    Step(tx=27, src="gas_volume", dst="gas_volume",
         needs=(P("balanced_equation", "", "balanced equation of the gaseous reaction", kind="text"),
                P("reactant_species", "", "gas whose volume is known", kind="text"),
                P("gas_volume", "L", "volume of that gas", lo=0.1, hi=50),
                P("product_species", "", "gas whose volume is asked", kind="text")),
         answer="gas_volume", unit="L", kind="positive",
         fn=lambda v: (check_balanced(v["balanced_equation"]),
                       {"gas_volume": v["gas_volume"] * _coef(v["balanced_equation"], v["product_species"])
                        / _coef(v["balanced_equation"], v["reactant_species"])})[1],
         traps=(Trap("ignores_coefficients", "takes the volume ratio as 1:1", lambda v: v["gas_volume"]),),
         formula="Gay-Lussac: volume ratio = mole ratio (same T, P)", asks="volume of the product gas"),
    Step(tx=29, src="gas_volume", dst="molecular_formula",
         needs=(P("gas_volume", "mL", "volume of the gaseous hydrocarbon", lo=5, hi=100),
                P("contraction_on_cooling", "mL", "contraction after explosion with excess O2 and cooling", lo=5, hi=500),
                P("volume_absorbed_by_KOH", "mL", "further contraction on passing through KOH", lo=5, hi=500)),
         answer="molecular_formula", unit="", kind="text", fn=_eudiometry,
         traps=(Trap("water_as_gas", "counts water vapour as a gas after cooling", _eudiometry_trap),),
         formula="CxHy + (x + y/4)O2 → xCO2 + (y/2)H2O(l); contraction = V(1 + y/4); CO2 = xV",
         asks="molecular formula of the hydrocarbon"),
    Step(tx=30, src="chemical_species", dst="oxidation_number",
         needs=(P("chemical_species", "", "formula of the species, with charge if an ion (e.g. 'Cr2O7^2-')", kind="text"),
                P("element", "", "element whose oxidation number is asked", kind="text")),
         answer="oxidation_number", unit="", kind="real", fn=_oxidation_number,
         traps=(Trap("ignores_charge", "ignores the charge on the ion", _on_trap_charge),
                Trap("peroxide_as_oxide", "takes O as −2 in a peroxide/superoxide", _on_trap_peroxide)),
         formula="sum of oxidation numbers = charge; O −2, H +1, F −1 unless an exception applies",
         asks="oxidation number (average if fractional)"),
    Step(tx=31, src="oxidation_number", dst="n_factor",
         needs=(P("oxidation_number", "", "initial oxidation number of the element", kind="real"),
                P("final_oxidation_number", "", "final oxidation number of the element", kind="real"),
                P("atoms_per_formula", "", "atoms of that element per formula unit", kind="posint", lo=1, hi=4)),
         answer="n_factor", unit="", kind="positive",
         fn=lambda v: {"n_factor": abs(v["final_oxidation_number"] - v["oxidation_number"]) * v["atoms_per_formula"]},
         traps=(Trap("forgets_atom_count", "counts the change for one atom only",
                     lambda v: abs(v["final_oxidation_number"] - v["oxidation_number"])),),
         formula="n-factor = |Δ(O.N.)| × atoms per formula unit", asks="n-factor"),
    Step(tx=32, src="redox_skeleton", dst="balanced_equation",
         needs=(P("reactants", "", "reactant species, comma-separated (include H+/OH-/H2O as needed)", kind="text"),
                P("products", "", "product species, comma-separated", kind="text"),
                P("species_asked", "", "species whose coefficient the question asks", kind="text")),
         answer="balanced_equation", unit="", kind="text",
         gives=("coefficient", "sum_of_coefficients"), fn=_balance_redox,
         formula="balance atoms and charge (ion-electron method)",
         final=("coefficient", "", "posint", "coefficient of the asked species in the balanced equation"),
         asks="the balanced equation"),
    Step(tx=33, src="n_factor", dst="equivalent_mass",
         needs=(P("n_factor", "", "n-factor of the species", lo=1, hi=8),
                P("molar_mass", "g mol⁻¹", "molar mass of the species", lo=10, hi=500)),
         answer="equivalent_mass", unit="g eq⁻¹", kind="positive",
         fn=lambda v: {"equivalent_mass": v["molar_mass"] / v["n_factor"]},
         traps=(Trap("multiplies", "multiplies molar mass by n-factor", lambda v: v["molar_mass"] * v["n_factor"]),),
         formula="E = M / n-factor", asks="equivalent mass (g eq⁻¹)"),
    Step(tx=34, src="equivalent_mass", dst="equivalents",
         needs=(P("equivalent_mass", "g eq⁻¹", "equivalent mass", lo=5, hi=300),
                P("mass", "g", "mass of the substance", lo=0.1, hi=100)),
         answer="equivalents", unit="eq", kind="positive",
         fn=lambda v: {"equivalents": v["mass"] / v["equivalent_mass"]},
         traps=(Trap("inverted_ratio", "divides equivalent mass by mass", lambda v: v["equivalent_mass"] / v["mass"]),),
         formula="eq = mass / E", asks="number of equivalents"),
    Step(tx=35, src="normality", dst="equivalents",
         needs=(P("normality", "N", "normality of the solution", lo=0.01, hi=5),
                P("volume", "mL", "volume of the solution", lo=1, hi=1000)),
         answer="equivalents", unit="eq", kind="positive",
         fn=lambda v: {"equivalents": v["normality"] * v["volume"] / 1000},
         traps=(Trap("forgets_mL_to_L", "multiplies N by the volume in mL", lambda v: v["normality"] * v["volume"]),),
         formula="eq = N × V(L); meq = N × V(mL)", asks="number of equivalents"),
    *[Step(tx=tx, src="equivalents", dst="normality",
           needs=(P("equivalents", "eq", "equivalents of titrant used at the end point", lo=1e-4, hi=1),
                  P("volume", "mL", "volume of the solution being titrated", lo=1, hi=1000)),
           answer="normality", unit="N", kind="positive",
           fn=lambda v: {"normality": 1000 * v["equivalents"] / v["volume"]},
           traps=(Trap("forgets_mL_to_L", "divides by the volume in mL without ×1000",
                       lambda v: v["equivalents"] / v["volume"]),),
           formula="law of equivalence: eq(titrant) = eq(analyte); N = eq / V(L)",
           asks="normality of the titrated solution")
      for tx in (36, 40, 42, 43)],
    Step(tx=39, src="equivalents", dst="moles",
         needs=(P("equivalents", "eq", "eq of HCl used to the phenolphthalein end point", lo=1e-4, hi=1),
                P("extra_equivalents", "eq", "further eq of HCl from the phenolphthalein to the methyl orange end point", kind="nonneg", lo=0, hi=1),
                P("component", "", "component whose amount is asked", kind="choice", choices=("NaOH", "Na2CO3"))),
         answer="moles", unit="mol", kind="positive", roles={"moles": "titration mixture component"},
         fn=lambda v: {"moles": v["extra_equivalents"] if v["component"] == "Na2CO3"
                       else _positive(v["equivalents"] - v["extra_equivalents"])},
         traps=(Trap("ph_sees_all_carbonate", "assumes phenolphthalein titrates all the carbonate",
                     lambda v: v["equivalents"] / 2 if v["component"] == "Na2CO3" else v["equivalents"] - 2 * v["extra_equivalents"]),
                Trap("ignores_carbonate_share", "takes all the first-end-point acid as NaOH",
                     lambda v: v["equivalents"] if v["component"] == "NaOH" else v["equivalents"])),
         formula="phenolphthalein: NaOH + ½ Na2CO3; methyl orange step: the other ½ Na2CO3",
         asks="amount of the component in the mixture (mol)"),
    Step(tx=41, src="equivalents", dst="percent_purity",
         needs=(P("equivalents", "eq", "eq of standard reagent added in excess", lo=1e-3, hi=1),
                P("back_titrated_equivalents", "eq", "eq of the second standard used in the back titration", kind="nonneg", lo=0, hi=1),
                P("equivalent_mass", "g eq⁻¹", "equivalent mass of the sample substance", lo=10, hi=300),
                P("sample_mass", "g", "mass of the impure sample", lo=0.1, hi=50)),
         answer="percent_purity", unit="%", kind="percent",
         fn=lambda v: {"percent_purity": 100 * _positive(v["equivalents"] - v["back_titrated_equivalents"])
                       * v["equivalent_mass"] / v["sample_mass"]},
         traps=(Trap("forgets_back_titration", "uses all the reagent added",
                     lambda v: 100 * v["equivalents"] * v["equivalent_mass"] / v["sample_mass"]),),
         formula="eq(sample) = eq(added) − eq(back-titrated); % = eq × E / mass × 100",
         asks="percentage purity of the sample"),
    _redox_step(44, [k for k in _K if k.startswith("KMnO4")], "KMnO4 in different media"),
    _redox_step(45, [k for k in _K if k.startswith("K2Cr2O7")] + [k for k in _K if k.startswith("KMnO4 in acidic")], "dichromate"),
    _redox_step(46, [k for k in _K if "oxalate" in k], "oxalate"),
    _redox_step(47, [k for k in _K if k.startswith("H2O2")], "hydrogen peroxide"),
    _redox_step(48, [k for k in _K if k.startswith("bleaching")] + [k for k in _K if k.startswith("IO3")], "iodometric reagents"),
    Step(tx=49, src="mass", dst="ppm",
         needs=(P("mass", "g", "mass of the hardness-causing salt in the water sample", lo=0.001, hi=10, role="hardness salt"),
                P("salt_molar_mass", "g mol⁻¹", "molar mass of the salt (one Ca²⁺ or Mg²⁺ per formula unit)", lo=50, hi=300),
                P("water_mass", "g", "mass of the water sample", lo=100, hi=1e7)),
         answer="ppm", unit="ppm (as CaCO3)", kind="positive",
         fn=lambda v: {"ppm": v["mass"] * 100 / v["salt_molar_mass"] * 1e6 / v["water_mass"]},
         traps=(Trap("skips_caco3_conversion", "reports the salt mass, not the CaCO3 equivalent",
                     lambda v: v["mass"] * 1e6 / v["water_mass"]),),
         formula="hardness = (mass as CaCO3 / mass of water) × 10⁶", asks="degree of hardness (ppm of CaCO3)"),
    _redox_step(50, [k for k in _K if k.startswith("Mohr") or k.startswith("ferrous")], "iron(II) reagents"),
    _redox_step(51, [k for k in _K if k.startswith("IO3")] + [k for k in _K if k.startswith("bleaching")], "iodate"),
    _redox_step(52, [k for k in _K if k.startswith("Cl2")] + [k for k in _K if k.startswith("MnO2")], "chlorine"),
    _redox_step(53, [k for k in _K if k.startswith("N2H4")] + [k for k in _K if k.startswith("H2O2 as reductant")], "hydrazine"),
    _redox_step(54, [k for k in _K if k.startswith("MnO2")] + [k for k in _K if k.startswith("Cl2")], "MnO2/HCl"),
    Step(tx=339, src="ppm", dst="mass",
         needs=(P("ppm", "ppm (as CaCO3)", "hardness of the water", lo=10, hi=1000),
                P("water_mass", "g", "mass of the water to soften", lo=1e3, hi=1e9),
                P("reagent_molar_mass", "g mol⁻¹", "molar mass of the softening reagent (Na2CO3 = 106)", lo=50, hi=300)),
         answer="mass", unit="g", kind="positive", roles={"mass": "softening reagent"},
         fn=lambda v: {"mass": v["ppm"] * v["water_mass"] / 1e6 * v["reagent_molar_mass"] / 100},
         traps=(Trap("skips_molar_ratio", "uses the CaCO3 mass without converting to the reagent",
                     lambda v: v["ppm"] * v["water_mass"] / 1e6),),
         formula="mass of reagent = (ppm × m_water / 10⁶) × M_reagent / 100",
         asks="mass of softening reagent needed (g)"),
    Step(tx=340, src="mass", dst="gas_volume",
         needs=(P("mass", "g", "mass of sodium azide NaN3 (65 g mol⁻¹)", lo=10, hi=200, role="sodium azide"),
                P("temperature", "K", "temperature of the inflated bag", kind="temperature", lo=273, hi=400),
                P("pressure", "atm", "pressure in the inflated bag", lo=0.8, hi=2.0)),
         answer="gas_volume", unit="L", kind="positive",
         fn=lambda v: {"gas_volume": v["mass"] / 65 * 1.5 * C.R_LATM * v["temperature"] / v["pressure"]},
         traps=(Trap("ignores_3_2_ratio", "takes one N2 per NaN3",
                     lambda v: v["mass"] / 65 * C.R_LATM * v["temperature"] / v["pressure"]),
                Trap("uses_22_4", "uses 22.4 L mol⁻¹ regardless of T and P",
                     lambda v: v["mass"] / 65 * 1.5 * 22.4)),
         constants=(const("R_LATM"), "Na = 23, N = 14"), formula="2NaN3 → 2Na + 3N2; V = nRT/P",
         asks="volume of N2 released (L)"),
    Step(tx=341, src="moles", dst="mass",
         needs=(P("moles", "mol", "amount of Cr2O7²⁻ reduced to Cr³⁺", lo=1e-5, hi=0.1, role="dichromate"),),
         answer="mass", unit="g", kind="positive", roles={"mass": "ethanol"},
         fn=lambda v: {"mass": v["moles"] * 6 / 4 * 46},
         traps=(Trap("one_to_one", "takes one ethanol per dichromate", lambda v: v["moles"] * 46),
                Trap("uses_dichromate_n_as_2", "takes ethanol's n-factor as 2 (to acetaldehyde)",
                     lambda v: v["moles"] * 6 / 2 * 46)),
         constants=("C = 12, H = 1, O = 16",),
         formula="eq(Cr2O7²⁻, n = 6) = eq(C2H5OH → CH3COOH, n = 4)", asks="mass of ethanol oxidised (g)"),
]


def _positive(x):
    if x <= 0:
        raise EngineError(f"value must be positive, got {x}")
    return x
