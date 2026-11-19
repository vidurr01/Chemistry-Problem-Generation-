"""
Organic graph edges that get no reaction rule (yet).

CONCEPT: not a step a walk can take (a concept, an intermediate, a polymer or an analysis); per the redesign
these become question types of their own, not reaction steps.

SUSPECT: the graph entry looks wrong (reagent, product or start). Each has the proposed fix. Nothing in the graph
file changes until the user approves the list (docs/organic_suspect_edges.md); until then the edge has no rule and
a walk skips it.
"""

CONCEPT = {
    "alkane_to_alkane_samemolecula": "structural isomers of C5H12 (question type, not a reaction)",
    "alkyl_halide_to_carbanion_mgdelta": "intermediate (carbanion)",
    "alkyl_halide_to_carbocation_alckohdeltae": "intermediate (carbocation) and ring expansion analysis",
    "alkyne_to_acetylide_ion_nanh": "intermediate (acetylide); the next step (alkylation) is not in the graph",
    "amino_acid_to_amino_acid_cipsequencer": "R/S assignment (question type)",
    "aryl_halide_to_aryl_halide_anynu": "SNAr mechanism analysis (the reaction itself is aryl_halide_to_substituted_benzene_naome)",
    "carbanion_to_carbanion_conceptualme": "mechanistic analysis only",
    "carbanion_to_cycloalkane_mgdelta": "intermediate",
    "carbanion_to_substituted_benzene_ohdelta": "intermediate (H/D exchange analysis)",
    "carbene_to_carbanion_naohstrongba": "intermediate (carbene from CHCl3)",
    "carbene_to_carbene_uvhvfordiazo": "intermediate (carbene generation)",
    "carbocation_to_carbocation_conceptualme": "mechanistic analysis only",
    "ether_to_ether_oairslowradi": "peroxide formation (safety concept)",
    "nitrile_to_nitrile_rlinbutyllit": "α-deprotonation (intermediate)",
    "oxime_to_oxime_notinterconv": "E/Z of oximes (question type)",
    "phenol_to_phenol_naornaoh": "phenoxide formation (acid–base)",
    "radical_to_radical_benzoylperox": "radical initiation (intermediate)",
    "aldehyde_to_phenol_hcatalystnov": "polymer (Novolac/Bakelite): lookup, not a molecule",
    "phenol_to_polymer_h": "polymer (Bakelite): lookup",
    "polymer_to_carbocation_lewisacidbfa": "polymer (cationic polymerisation): lookup",
    "polymer_to_diene_conjugated_radicaliniti": "polymer (rubber): lookup",
    "polymer_to_polymer_nassodiumdis": "polymer (Thiokol): lookup",
    "polymer_to_radical_radicaliniti": "polymer (polythene): lookup",
    "lactam_to_lactam_heat": "polymer (Nylon-6 from caprolactam): lookup",
}

# All 32 were decided by the user on 2026-11-20 (docs/organic_suspect_edges.md): 20 edges deleted from the graph,
# 12 fixed and given rules, caprolactam -> Nylon-6 moved to the polymer lookups above.
SUSPECT: dict = {}
