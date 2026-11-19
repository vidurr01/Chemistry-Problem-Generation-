"""
Inorganic fact tables for MCQ/MSQ questions (core/engine/facts.py builds the four statements and the key).

Every value here is COMPUTED by core/engine/inorganic/properties.py from the species' formula; nothing is
typed in by hand. A statement is true when it pairs a species with its own computed value and false when it
pairs it with another (core.engine.facts.Category). Species are the standard JEE ones; a species a property
function refuses is simply left out of that table.
"""

from __future__ import annotations

from core.engine.base import EngineError
from core.engine.facts import Category
from core.engine.inorganic import properties as P

# JEE coordination entities (the property functions decide spin, geometry and so on). Left out on purpose:
# [Cu(NH3)4]2+, which JEE treats as square planar (dsp2) although it is d9 (the geometry rule makes only d8
# square planar), so its key would be wrong.
COMPLEXES = (
    "[Fe(CN)6]4-", "[Fe(CN)6]3-", "[FeF6]3-", "[Fe(H2O)6]2+", "[Fe(H2O)6]3+", "[CoF6]3-", "[Co(NH3)6]3+",
    "[Co(en)3]3+", "[Co(H2O)6]3+", "[Cr(NH3)6]3+", "[Cr(H2O)6]3+", "[Mn(CN)6]4-", "[Mn(H2O)6]2+", "[MnCl4]2-",
    "[Ni(CO)4]", "[NiCl4]2-", "[Ni(CN)4]2-", "[Ni(NH3)6]2+", "[PtCl4]2-", "[Pt(NH3)2Cl2]", "[CuCl4]2-",
    "[Zn(NH3)4]2+", "[Ti(H2O)6]3+", "[V(H2O)6]3+", "[Fe(C2O4)3]3-", "[CoCl4]2-", "[Fe(CO)5]",
)
# main-group molecules and discrete ions
MOLECULES = (
    "BeCl2", "BF3", "CH4", "NH3", "H2O", "PCl5", "SF6", "SF4", "ClF3", "XeF2", "XeF4", "XeF6", "IF7", "BrF5",
    "I3-", "ICl4-", "NH4+", "H3O+", "CO2", "SO2", "SO3", "SO4^2-", "NO3-", "NO2+", "NO2-", "O3", "ClO4-",
    "XeO3", "XeOF4", "SnCl2", "PCl3", "BCl3", "SiF6^2-", "PF6-", "ClO3-", "IF5",
)
DIATOMICS = ("H2", "He2", "Li2", "Be2", "B2", "C2", "N2", "O2", "F2", "Ne2", "O2+", "O2-", "O2^2-", "N2+",
             "NO", "NO+", "CO", "CN-", "H2+")
# complexes with stereoisomers worth asking about: entity -> (geometry, ligand pattern for count_isomers)
ISOMER_SETS = {
    "[Co(NH3)4Cl2]+": ("octahedral", ["a"] * 4 + ["b"] * 2),
    "[Co(NH3)3Cl3]": ("octahedral", ["a"] * 3 + ["b"] * 3),
    "[Co(en)3]3+": ("octahedral", ["AA"] * 3),
    "[Co(en)2Cl2]+": ("octahedral", ["AA", "AA", "b", "b"]),
    "[Pt(NH3)2Cl2]": ("square planar", ["a", "a", "b", "b"]),
    "[Pt(NH3)(py)ClBr]": ("square planar", ["a", "b", "c", "d"]),
    "[Co(NH3)2(H2O)2Cl2]+": ("octahedral", ["a", "a", "b", "b", "c", "c"]),
    "[Co(en)(NH3)2Cl2]+": ("octahedral", ["AA", "b", "b", "c", "c"]),
    "[Cr(C2O4)3]3-": ("octahedral", ["AA"] * 3),
    "[Co(NH3)5Cl]2+": ("octahedral", ["a"] * 5 + ["b"]),
}


def _rows(items, fn):
    rows = []
    for it in items:
        try:
            v = fn(it)
        except EngineError:
            continue
        if v is not None:
            rows.append((it, v))
    return tuple(rows)


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _tables():
    cx = lambda e: P.complex_info(e)                                  # noqa: E731
    return [
        Category("inorg_cx_magnetism", (), "coordination_compounds", "the magnetic behaviour of complexes",
                 "{item} is {value}.", _rows(COMPLEXES, lambda e: cx(e)["magnetism"])),
        Category("inorg_cx_unpaired", (), "coordination_compounds", "unpaired electrons in complexes",
                 "The number of unpaired electrons in {item} is {value}.",
                 _rows(COMPLEXES, lambda e: str(cx(e)["unpaired"])), distractors=tuple(str(i) for i in range(6))),
        Category("inorg_cx_hybrid", (), "coordination_compounds", "the hybridisation of the metal in complexes",
                 "The hybridisation of the central metal in {item} is {value}.",
                 _rows(COMPLEXES, lambda e: cx(e)["hybridisation"]), distractors=("sp3", "dsp2", "d2sp3", "sp3d2")),
        Category("inorg_cx_geometry", (), "coordination_compounds", "the geometry of complexes",
                 "{item} has a {value} geometry.",
                 _rows(COMPLEXES, lambda e: cx(e)["geometry"]),
                 distractors=("octahedral", "tetrahedral", "square planar")),
        Category("inorg_cx_moment", (), "coordination_compounds", "spin-only magnetic moments of complexes",
                 "The spin-only magnetic moment of {item} is {value} BM.",
                 _rows(COMPLEXES, lambda e: f"{cx(e)['spin_only_moment_BM']:.2f}"),
                 distractors=("0.00", "1.73", "2.83", "3.87", "4.90", "5.92")),
        Category("inorg_mol_shape", (), "chemical_bonding", "the shapes of molecules and ions",
                 "The shape of {item} is {value}.", _rows(MOLECULES, lambda s: P.vsepr(s)["shape"]),
                 distractors=("linear", "bent", "trigonal planar", "trigonal pyramidal", "tetrahedral",
                              "see-saw", "T-shaped", "square planar", "square pyramidal", "octahedral")),
        Category("inorg_mol_hybrid", (), "chemical_bonding", "the hybridisation of the central atom",
                 "The central atom of {item} is {value} hybridised.",
                 _rows(MOLECULES, lambda s: P.vsepr(s)["hybridisation"]),
                 distractors=("sp", "sp2", "sp3", "sp3d", "sp3d2", "sp3d3")),
        Category("inorg_mol_polarity", (), "chemical_bonding", "the polarity of molecules",
                 "{item} is {value}.",
                 _rows(MOLECULES, lambda s: {True: "polar", False: "non-polar", None: None}[P.vsepr(s)["polar"]])),
        Category("inorg_mo_bond_order", (), "chemical_bonding", "MO bond orders of diatomic species",
                 "The bond order of {item} is {value}.",
                 _rows(DIATOMICS, lambda s: _bo_text(P.mo_diatomic(s)["bond_order"])),
                 distractors=("0", "0.5", "1", "1.5", "2", "2.5", "3")),
        Category("inorg_mo_magnetism", (), "chemical_bonding", "the magnetic behaviour of diatomic species",
                 "{item} is {value}.", _rows(DIATOMICS, lambda s: P.mo_diatomic(s)["magnetism"])),
        Category("inorg_cx_geo_isomers", (), "coordination_compounds", "geometrical isomers of complexes",
                 "{item} has {value} geometrical isomer(s).",
                 _rows(ISOMER_SETS, lambda e: str(P.count_isomers(*ISOMER_SETS[e])["geometric"])),
                 distractors=("1", "2", "3", "4", "5")),
        Category("inorg_cx_stereo_isomers", (), "coordination_compounds", "stereoisomers of complexes",
                 "{item} has {value} stereoisomer(s) in total (geometrical and optical).",
                 _rows(ISOMER_SETS, lambda e: str(P.count_isomers(*ISOMER_SETS[e])["stereo"])),
                 distractors=("1", "2", "3", "4", "5", "6")),
    ]


def _bo_text(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


FACTS = [t for t in _tables() if len(t.rows) >= 4]
BY_ID = {t.id: t for t in FACTS}
