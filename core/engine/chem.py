"""
Chemistry helpers shared by the engines: atomic data, formula parsing, constants.

Atomic masses are the rounded values JEE questions use (Cl = 35.5, Cu = 63.5); a
question that uses them states them, so the convention is never ambiguous.
"""

from __future__ import annotations

import re
from collections import Counter

from core.engine.base import EngineError

# ── Elements ─────────────────────────────────────────────────────────────────

SYMBOLS = [
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S",
    "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga",
    "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd",
    "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm",
    "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os",
    "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa",
    "U",
]
Z_OF = {s: i + 1 for i, s in enumerate(SYMBOLS)}

ATOMIC_MASS = {
    "H": 1.0, "He": 4.0, "Li": 7.0, "Be": 9.0, "B": 11.0, "C": 12.0, "N": 14.0, "O": 16.0,
    "F": 19.0, "Ne": 20.0, "Na": 23.0, "Mg": 24.0, "Al": 27.0, "Si": 28.0, "P": 31.0,
    "S": 32.0, "Cl": 35.5, "Ar": 40.0, "K": 39.0, "Ca": 40.0, "Sc": 45.0, "Ti": 48.0,
    "V": 51.0, "Cr": 52.0, "Mn": 55.0, "Fe": 56.0, "Co": 59.0, "Ni": 59.0, "Cu": 63.5,
    "Zn": 65.0, "Ga": 70.0, "Ge": 72.5, "As": 75.0, "Se": 79.0, "Br": 80.0, "Kr": 84.0,
    "Rb": 85.5, "Sr": 87.5, "Mo": 96.0, "Pd": 106.0, "Ag": 108.0, "Cd": 112.0, "Sn": 119.0,
    "Sb": 122.0, "I": 127.0, "Xe": 131.0, "Cs": 133.0, "Ba": 137.0, "W": 184.0, "Pt": 195.0,
    "Au": 197.0, "Hg": 200.0, "Pb": 207.0, "Bi": 209.0, "U": 238.0,
}

_TOKEN = re.compile(r"([A-Z][a-z]?|\(|\)|\[|\]|\d+)")


_SUPER_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_SUB_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _split_charge(text: str):
    """Separate an ionic charge from a formula, in the notations exams and models write.

    'Cr2O7^2-', 'Fe^3+'          after '^': the charge
    'Fe²⁺', 'SO₄²⁻'              superscripts: the charge
    'Fe+++'                      repeated signs: one each
    a bare trailing 'digits±' is read by the usual convention:
      one element (a monatomic ion): the digit is the charge      Fe2+, Al3+, O2- (oxide)
      several elements, one digit: a subscript, charge ±1         MnO4-, NH4+, HCO3-
      several digits: the last is the charge                      SO42-, Cr2O72-, PO43-, Hg22+
    """
    raw = text.strip().replace("−", "-")
    m = re.match(r"^(.*?)([⁰¹²³⁴⁵⁶⁷⁸⁹]*)([⁺⁻])$", raw)
    if m and m.group(1):                       # superscript charge
        body = m.group(1).translate(_SUB_DIGITS)
        num = m.group(2).translate(_SUPER_DIGITS)
        return body, int(num or 1) * (1 if m.group(3) == "⁺" else -1)
    s = raw.replace("⁺", "+").replace("⁻", "-").translate(_SUB_DIGITS)
    if "^" in s:
        body, _, ch = s.partition("^")
        ch = ch.strip("()")
        m = re.fullmatch(r"(\d*)([+-])|([+-])(\d*)", ch)
        if not m or not body:
            raise EngineError(f"cannot read charge in {text!r}")
        num = m.group(1) if m.group(2) else m.group(4)
        sign = m.group(2) or m.group(3)
        return body, int(num or 1) * (1 if sign == "+" else -1)
    n = len(s) - len(s.rstrip("+-"))
    if n:
        signs = s[len(s) - n:]
        if len(set(signs)) != 1:
            raise EngineError(f"cannot read charge in {text!r}")
        sign = 1 if signs[0] == "+" else -1
        rest = s[:len(s) - n].rstrip()
        d = re.search(r"(\d+)$", rest)
        if n == 1 and d and not rest.endswith(")"):
            digits, head = d.group(1), rest[:d.start()]
            monatomic = re.fullmatch(r"[A-Z][a-z]?", head) is not None
            if monatomic and len(digits) == 1:
                return head, int(digits) * sign                     # Fe2+ -> Fe, +2
            if len(digits) >= 2:
                return head + digits[:-1], int(digits[-1]) * sign   # SO42- -> SO4, -2
        return rest, n * sign
    return s, 0


def parse_formula(text: str):
    """Element counts and charge of a formula: 'Ca(OH)2' -> ({'Ca':1,'O':2,'H':2}, 0);
    'CuSO4.5H2O' (or with '·') counts the water; 'MnO4^-' has charge -1."""
    body, charge = _split_charge(text)
    total: Counter = Counter()
    for part in re.split(r"[.·*]", body.replace(" ", "")):
        if not part:
            continue
        mult = 1
        m = re.match(r"^(\d+)(.*)$", part)
        if m and m.group(2) and m.group(2)[0].isupper():
            mult, part = int(m.group(1)), m.group(2)
        total.update({k: v * mult for k, v in _parse_group(part).items()})
    if not total:
        raise EngineError(f"cannot read formula {text!r}")
    for el in total:
        if el not in Z_OF:
            raise EngineError(f"unknown element {el!r} in {text!r}")
    return dict(total), charge


def _parse_group(s: str) -> Counter:
    tokens = _TOKEN.findall(s)
    if "".join(tokens) != s:
        raise EngineError(f"cannot read formula {s!r}")
    stack = [Counter()]
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in "([":
            stack.append(Counter())
        elif t in ")]":
            if len(stack) == 1:
                raise EngineError(f"unbalanced brackets in {s!r}")
            group = stack.pop()
            n = 1
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                n = int(tokens[i + 1])
                i += 1
            stack[-1].update({k: v * n for k, v in group.items()})
        elif t.isdigit():
            raise EngineError(f"unexpected number in {s!r}")
        else:
            n = 1
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                n = int(tokens[i + 1])
                i += 1
            stack[-1][t] += n
        i += 1
    if len(stack) != 1:
        raise EngineError(f"unbalanced brackets in {s!r}")
    return stack[0]


def molar_mass(formula: str) -> float:
    counts, _ = parse_formula(formula)
    missing = [el for el in counts if el not in ATOMIC_MASS]
    if missing:
        raise EngineError(f"no atomic mass for {missing}")
    return sum(ATOMIC_MASS[el] * n for el, n in counts.items())


def atomic_masses_used(formulas) -> list:
    """Constant lines 'Atomic masses: C = 12, H = 1, ...' for the elements in formulas."""
    els = []
    for f in formulas:
        for el in parse_formula(f)[0]:
            if el not in els:
                els.append(el)
    return [f"{el} = {ATOMIC_MASS[el]:g}" for el in els]


def format_formula(counts: dict, order=None) -> str:
    """{'C': 2, 'H': 6, 'O': 1} -> 'C2H6O' (Hill order: C, H, then alphabetical)."""
    if order is None:
        keys = sorted(counts)
        if "C" in counts:
            keys = ["C"] + (["H"] if "H" in counts else []) + [k for k in keys if k not in ("C", "H")]
    else:
        keys = [k for k in order if k in counts]
    return "".join(f"{k}{'' if counts[k] == 1 else counts[k]}" for k in keys if counts[k])


# ── Equations ────────────────────────────────────────────────────────────────

_STATE = re.compile(r"\((s|l|g|aq)\)$")


def _species(term: str):
    """'2H2O(l)' -> (2, 'H2O'); '3/2 O2' -> (1.5, 'O2'). Electrons may be written 'e-'."""
    t = term.strip()
    m = re.match(r"^(\d+(?:\.\d+)?(?:/\d+)?)\s*(.+)$", t)
    coef = 1.0
    if m and not m.group(2)[0].isdigit():
        num = m.group(1)
        if "/" in num:
            a, b = num.split("/")
            coef = float(a) / float(b)
        else:
            coef = float(num)
        t = m.group(2).strip()
    t = _STATE.sub("", t).strip()
    return coef, t


def parse_equation(text: str):
    """'2H2 + O2 -> 2H2O' -> ([(2,'H2'), (1,'O2')], [(2,'H2O')]). Accepts ->, →, =, ⇌."""
    s = text.replace("→", "->").replace("⇌", "->").replace("<=>", "->").replace("⟶", "->")
    if "->" not in s:
        if s.count("=") == 1:
            s = s.replace("=", "->")
        else:
            raise EngineError(f"cannot read equation {text!r}")
    left, right = s.split("->", 1)
    side = lambda part: [_species(t) for t in re.split(r"\s\+\s|\s\+(?=\s*\d*[A-Za-z(])", part) if t.strip()]
    return side(left), side(right)


def _counts(formula: str):
    if formula in ("e", "e-", "e^-"):
        return {}, -1
    return parse_formula(formula)


def equation_balance(reactants, products):
    """Net element counts and net charge (products minus reactants); all zero if balanced."""
    net: Counter = Counter()
    charge = 0.0
    for sign, side in ((-1, reactants), (1, products)):
        for coef, f in side:
            counts, ch = _counts(f)
            for el, n in counts.items():
                net[el] += sign * coef * n
            charge += sign * coef * ch
    return {k: v for k, v in net.items() if abs(v) > 1e-9}, charge


def check_balanced(text: str):
    r, p = parse_equation(text)
    net, charge = equation_balance(r, p)
    if net or abs(charge) > 1e-9:
        raise EngineError(f"equation is not balanced: {text!r} (excess {net}, charge {charge:+g})")
    return r, p


def balance(reactant_formulas, product_formulas):
    """Smallest whole-number coefficients balancing atoms and charge, via the nullspace
    of the element/charge matrix. Raises if the skeleton has no unique balance."""
    import sympy
    species = list(reactant_formulas) + list(product_formulas)
    parsed = [_counts(f) for f in species]
    elements = sorted({el for c, _ in parsed for el in c})
    rows = []
    for el in elements:
        rows.append([(-1 if i < len(reactant_formulas) else 1) * parsed[i][0].get(el, 0)
                     for i in range(len(species))])
    rows.append([(-1 if i < len(reactant_formulas) else 1) * parsed[i][1] for i in range(len(species))])
    ns = sympy.Matrix(rows).nullspace()
    if len(ns) != 1:
        raise EngineError(f"skeleton has {len(ns)} independent balances, need exactly one")
    v = ns[0]
    lcm = sympy.ilcm(*[sympy.fraction(x)[1] for x in v])
    v = [x * lcm for x in v]
    if all(x <= 0 for x in v):
        v = [-x for x in v]
    if any(x <= 0 for x in v):
        raise EngineError("no all-positive balance for this skeleton")
    g = sympy.igcd(*[int(x) for x in v])
    return [int(x) // g for x in v]


def format_equation(reactants, products) -> str:
    fmt = lambda side: " + ".join(f"{'' if c == 1 else (int(c) if float(c).is_integer() else c)}{f}" for c, f in side)
    return f"{fmt(reactants)} → {fmt(products)}"


# ── Physical constants (value, the line the question states) ────────────────

class C:
    R_J = 8.314               # J K^-1 mol^-1
    R_LATM = 0.0821           # L atm K^-1 mol^-1
    R_CAL = 2.0               # cal K^-1 mol^-1 (approximate)
    F = 96500.0               # C mol^-1
    NA = 6.022e23             # mol^-1
    H = 6.626e-34             # J s
    C_LIGHT = 3.0e8           # m s^-1
    K_B = 1.38e-23            # J K^-1
    M_E = 9.1e-31             # kg
    E_CHARGE = 1.6e-19        # C
    K_COULOMB = 9.0e9         # N m^2 C^-2
    AMU_MEV = 931.5           # MeV per u
    EV_NM = 1240.0            # eV nm (hc)
    RYDBERG_CM = 109677.0     # cm^-1
    BOHR_R_A = 0.529          # angstrom
    E1_EV = 13.6              # eV
    V1_MS = 2.18e6            # m s^-1
    KW_25 = 1.0e-14
    NERNST_25 = 0.0591        # V (2.303RT/F at 298 K)
    MOLAR_VOL_STP = 22.4      # L mol^-1 at 1 atm, 273 K
    G = 9.8                   # m s^-2


CONST_TEXT = {
    "R_J": "R = 8.314 J K⁻¹ mol⁻¹",
    "R_LATM": "R = 0.0821 L atm K⁻¹ mol⁻¹",
    "F": "F = 96500 C mol⁻¹",
    "NA": "N_A = 6.022 × 10²³ mol⁻¹",
    "H": "h = 6.626 × 10⁻³⁴ J s",
    "C_LIGHT": "c = 3.0 × 10⁸ m s⁻¹",
    "K_B": "k_B = 1.38 × 10⁻²³ J K⁻¹",
    "M_E": "mass of electron = 9.1 × 10⁻³¹ kg",
    "E_CHARGE": "e = 1.6 × 10⁻¹⁹ C",
    "K_COULOMB": "1/(4πε₀) = 9.0 × 10⁹ N m² C⁻²",
    "AMU_MEV": "1 u = 931.5 MeV",
    "EV_NM": "hc = 1240 eV nm",
    "RYDBERG_CM": "R_H = 109677 cm⁻¹",
    "BOHR_R_A": "radius of the first Bohr orbit of H = 0.529 Å",
    "E1_EV": "energy of the electron in the first Bohr orbit of H = −13.6 eV",
    "V1_MS": "velocity of the electron in the first Bohr orbit of H = 2.18 × 10⁶ m s⁻¹",
    "KW_25": "K_w = 1.0 × 10⁻¹⁴ at 25 °C",
    "NERNST_25": "2.303RT/F = 0.0591 V at 298 K",
    "MOLAR_VOL_STP": "molar volume of an ideal gas at 1 atm and 273 K = 22.4 L",
    "G": "g = 9.8 m s⁻²",
}


def const(name: str) -> str:
    return CONST_TEXT[name]
