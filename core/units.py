"""
Unit conversion for graded answers, on the pint library.

A solver reports the number it calculated and the unit of that number
([CALC_VALUE: -45200] [CALC_UNIT: J]); code converts it to the unit the question asked
(kJ) here. Unit strings come in exam notation ("kJ mol⁻¹", "J K⁻¹ mol⁻¹", "g mL⁻¹", "dm³",
"°C", "mmHg", "M") or plain text ("kJ/mol", "mol L^-1", "s-1"); to_pint() rewrites both
into pint's syntax. Conversions between different kinds of quantity (eV per particle and
kJ per mole, J and K) are refused: convert() returns None.
"""

from __future__ import annotations

import functools
import re

import pint

UREG = pint.UnitRegistry()
UREG.define("BM = bohr_magneton")                     # spin-only magnetic moments
UREG.define("amu = unified_atomic_mass_unit")
UREG.define("eq = [equivalent]")                     # gram-equivalents (normality, equivalent mass)

_NONE = {"", "none", "null", "-", "—", "dimensionless", "unitless", "no unit", "n/a",
         "volume"}                                    # "20 volume" H2O2 strength is a pure number
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_SUPERSCRIPT_RUN = "[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+"


def to_pint(unit) -> str:
    """'kJ mol⁻¹' -> 'kJ*mol**-1'; 'J/(K mol)' -> 'J/(K*mol)'; '' / 'none' -> ''."""
    s = str(unit or "").strip()
    if s.lower() in _NONE:
        return ""
    # qualifiers that name what a ratio is of, not a unit: "ppm (as CaCO3)", "% by mass", "% w/V"
    s = re.sub(r"\((?:by|as|of|w/|v/|m/)[^)]*\)", "", s, flags=re.I)
    s = re.sub(r"%\s*(?:by\s+mass|by\s+volume|by\s+weight|w/w|w/v|v/v|m/m|m/v)", "%", s, flags=re.I)
    s = re.sub(r"\bmm\s+Hg\b", "mmHg", s)
    if s.strip().lower() in _NONE:
        return ""
    for a, b in (("°C", "degC"), ("℃", "degC"), ("°F", "degF"), ("Å", "angstrom"), ("µ", "u"),
                 ("μ", "u"), ("%", "percent"), ("·", " "), ("×", " "), ("−", "-"), ("⋅", " ")):
        s = s.replace(a, b)
    s = re.sub(r"([A-Za-z)])(" + _SUPERSCRIPT_RUN + ")",
               lambda m: f"{m.group(1)}**{m.group(2).translate(_SUP)}", s)        # mol⁻¹ -> mol**-1
    s = s.replace("^", "**")                                                      # mol^-1 -> mol**-1
    s = re.sub(r"(?<=[A-Za-z])(?<!\*)(-?\d+)\b", lambda m: f"**{m.group(1)}", s)   # s-1, m3 -> s**-1, m**3
    s = re.sub(r"\s*\*\*\s*", "**", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s+", "*", s.strip())                                            # spaces multiply
    return s


@functools.lru_cache(maxsize=1024)
def parse(unit) -> "pint.Unit | None":
    """The pint unit of a unit string, or None if it cannot be read."""
    p = to_pint(unit)
    if p == "":
        return UREG.dimensionless
    try:
        q = UREG.parse_expression(p)
    except Exception:                                    # noqa: BLE001 - any parse failure
        return None
    return q.units if hasattr(q, "units") else None


def convert(value: float, from_unit, to_unit) -> float | None:
    """value in from_unit expressed in to_unit, or None (unreadable unit or different kind)."""
    a, b = parse(from_unit), parse(to_unit)
    if a is None or b is None:
        return None
    try:
        return float(UREG.Quantity(value, a).to(b).magnitude)
    except Exception:                                    # noqa: BLE001 - DimensionalityError etc.
        return None
