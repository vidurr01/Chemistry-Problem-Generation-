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
}

SUSPECT = {
    "acid_chloride_to_ester_alclfriedelc": "AlCl3 alone gives no ester from an acid chloride. Fix: remove "
                                           "(Friedel–Crafts acylation of an arene is benzene_to_ketone_rcocl).",
    "alcohol_to_amine_al2o3450c": "Al2O3/450 °C alone dehydrates the alcohol. Fix reagent: NH3, Al2O3, 360 °C.",
    "alkane_to_carboxylic_acid_conch2so4": "alkane + conc. H2SO4 does not give a substituted benzene. Fix: remove.",
    "alkane_to_cycloalkane_electrolysis": "electrolysis of an alkane gives no cycloalkane (Kolbe is for "
                                          "carboxylate salts). Fix: remove.",
    "aldehyde_to_substituted_benzene_naohaqueouss": "conc. NaOH on an aldehyde without α-H is Cannizzaro: "
                                                    "alcohol + carboxylate. Fix product: alcohol (acid as co-product).",
    "vicinal_dihalide_to_alkyne_zndeltaexces": "Zn dehalogenates a vicinal dihalide to the ALKENE "
                                               "(alcoholic KOH then NaNH2 gives the alkyne). Fix product: alkene.",
    "alkyl_halide_to_ester_naoet": "NaOEt with an alkyl halide gives an ether (Williamson) or alkene, not an "
                                  "ester. Fix: remove (duplicate of alkyl_halide_to_ether_rona).",
    "alkyl_halide_to_geminal_dihalide_rliorganolit": "RLi on an alkyl halide gives coupling/exchange, not a "
                                                     "geminal dihalide. Fix: remove.",
    "amine_to_aldehyde_kmno4overoxi": "KMnO4 over-oxidation of an amine to an aldehyde is not a standard "
                                      "reaction. Fix: remove.",
    "amine_to_amine_heatsn2": "'heat/SN2' names no reagent. Fix: amine + CH3I (excess) → quaternary salt, or remove.",
    "amine_to_aniline_heat200chofm": "Hofmann–Martius starts from N-alkylanilinium salts, not aliphatic amines. "
                                     "Fix: remove.",
    "amine_to_diazonium_salt_nano": "aliphatic amines give no stable diazonium salt (that is "
                                    "aniline_to_diazonium_salt_nano2hclat05). Fix: remove.",
    "anhydride_to_ester_alcllewisaci": "AlCl3 alone gives no ester from an anhydride. Fix: remove.",
    "cycloalkane_to_cycloalkane_diazomethane": "CH2N2/hν C–H insertion is not JEE syllabus and unselective. "
                                               "Fix: remove.",
    "diazonium_salt_to_alcohol_howaterasnuc": "the product of ArN2+ + H2O is a phenol, not an alcohol "
                                              "(duplicate of diazonium_salt_to_phenol_ho). Fix: remove.",
    "diazonium_salt_to_naphthalene_alkalinecoup": "coupling with 2-naphthol gives an azo dye, not naphthalene. "
                                                  "Fix product: azo_compound (reagent 2-naphthol, NaOH).",
    "diol_to_aldehyde_cu": "Cu/300 °C dehydrogenates an ALCOHOL (1° → aldehyde, 2° → ketone). Fix start: alcohol.",
    "diol_to_diol_2eqchcooh": "acetylating a diol gives a diester. Fix product: ester.",
    "ester_to_alkyl_halide_i2": "I2/NaOH (iodoform) needs CH3CO– or CH3CH(OH)–; an ester gives none. Fix: remove.",
    "ester_to_substituted_benzene_alcl3": "duplicate of the Fries rearrangement (ester_to_ketone_alcl). Fix: remove.",
    "ketone_to_amine_hheat": "H+/heat gives no amine from a ketone. Fix: remove.",
    "ketone_to_ether_roh": "ROH/H+ with a ketone gives a ketal. Fix product: acetal.",
    "ketone_to_lactone_diazomethane": "CH2N2 ring-expands a cyclic ketone to the next KETONE (lactone is "
                                      "Baeyer–Villiger). Fix product: ketone.",
    "ketone_to_phenol_h": "H+/Δ gives no phenol from a ketone. Fix: remove.",
    "lactam_to_lactam_heat": "caprolactam on heating gives Nylon-6 (not 6,6), a polymer. Fix: move to polymer lookups.",
    "nitrile_to_substituted_benzene_1ch3mgbr": "duplicate of nitrile_to_ketone_12ch3mgbr. Fix: remove.",
    "nitro_compound_to_aniline_znnaoh2molor": "Zn/NaOH gives hydrazo/azo compounds and LiAlH4 gives azobenzene "
                                              "from ArNO2. Fix reagent: Sn/HCl or Fe/HCl (then this duplicates "
                                              "nitro_compound_to_substituted_benzene_snhcl; keep one).",
    "phenol_to_anhydride_ovoindustria": "V2O5 air oxidation makes maleic/phthalic anhydride from benzene or "
                                        "naphthalene, not from phenol. Fix: remove.",
    "substituted_benzene_to_alkane_o3": "ozonolysis of an arene gives glyoxals (benzene) or mixtures. Fix: remove.",
    "substituted_benzene_to_anhydride_seecondition": "no reagent given. Fix: o-xylene, V2O5, air → phthalic "
                                                     "anhydride, or remove.",
    "substituted_benzene_to_phenol_1conch2so4de": "picric acid is made from PHENOL (sulphonation then "
                                                  "nitration). Fix start: phenol.",
    "carbanion_to_nitro_compound_kmno4": "not a reaction of a carbanion. Fix: remove.",
}
