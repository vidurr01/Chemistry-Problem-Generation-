# Organic graph: suspect edges (decided 2026-11-20)

The user approved every proposed fix on 2026-11-20. Applied to `knowledge/reaction_graph.json` (199 → 179 edges):

- **Deleted (20):** the 19 edges whose fix below is "remove", plus `nitro_compound_to_substituted_benzene_snhcl`
  (a duplicate once the nitro → aniline edge uses Sn/HCl).
- **Product, start or reagent fixed and given a rule (12):** the Cannizzaro, Zn dehalogenation, 2-naphthol coupling,
  diol diacetate, ketal, CH2N2 ring expansion, Cu dehydrogenation, picric acid, alcohol + NH3, Sn/HCl, exhaustive
  methylation and o-xylene → phthalic anhydride edges. Edge ids are unchanged; each edge's `notes` starts with
  "fixed 2026-11-20".
- **Moved to the polymer lookups (1):** `lactam_to_lactam_heat` (caprolactam → Nylon-6, not 6,6).

The original list, as reviewed:

| # | Edge | Graph says | Proposed fix |
|---|---|---|---|
| 1 | `acid_chloride_to_ester_alclfriedelc` | acid_chloride → ester with AlCl₃ (Friedel-Crafts-like acylium mechanism) | AlCl3 alone gives no ester from an acid chloride. Fix: remove (Friedel–Crafts acylation of an arene is benzene_to_ketone_rcocl). |
| 2 | `alcohol_to_amine_al2o3450c` | alcohol → amine with Al2O3/450°C | Al2O3/450 °C alone dehydrates the alcohol. Fix reagent: NH3, Al2O3, 360 °C. |
| 3 | `alkane_to_carboxylic_acid_conch2so4` | alkane → substituted_benzene with conc H2SO4; delta (heat) | alkane + conc. H2SO4 does not give a substituted benzene. Fix: remove. |
| 4 | `alkane_to_cycloalkane_electrolysis` | alkane → cycloalkane with electrolysis; 5A current | electrolysis of an alkane gives no cycloalkane (Kolbe is for carboxylate salts). Fix: remove. |
| 5 | `aldehyde_to_substituted_benzene_naohaqueouss` | aldehyde → substituted_benzene with NaOH (aqueous, strong base) | conc. NaOH on an aldehyde without α-H is Cannizzaro: alcohol + carboxylate. Fix product: alcohol (acid as co-product). |
| 6 | `vicinal_dihalide_to_alkyne_zndeltaexces` | vicinal_dihalide → alkyne with Zn/Delta (excess Zn, heat); 2 equivalents Zn | Zn dehalogenates a vicinal dihalide to the ALKENE (alcoholic KOH then NaNH2 gives the alkyne). Fix product: alkene. |
| 7 | `alkyl_halide_to_ester_naoet` | alkyl_halide → ester with NaOEt; heat | NaOEt with an alkyl halide gives an ether (Williamson) or alkene, not an ester. Fix: remove (duplicate of alkyl_halide_to_ether_rona). |
| 8 | `alkyl_halide_to_geminal_dihalide_rliorganolit` | alkyl_halide → geminal_dihalide with RLi (organolithium); RNa (organosodium); n-BuLi; PhLi | RLi on an alkyl halide gives coupling/exchange, not a geminal dihalide. Fix: remove. |
| 9 | `amine_to_aldehyde_kmno4overoxi` | amine → aldehyde with KMnO4 (over-oxidation) | KMnO4 over-oxidation of an amine to an aldehyde is not a standard reaction. Fix: remove. |
| 10 | `amine_to_amine_heatsn2` | amine → amine with heat/SN2 | 'heat/SN2' names no reagent. Fix: amine + CH3I (excess) → quaternary salt, or remove. |
| 11 | `amine_to_aniline_heat200chofm` | amine → aniline with heat 200°C (Hofmann-Martius rearrangement) | Hofmann–Martius starts from N-alkylanilinium salts, not aliphatic amines. Fix: remove. |
| 12 | `amine_to_diazonium_salt_nano` | amine → diazonium_salt with NaNO₂; HCl; 0-5°C | aliphatic amines give no stable diazonium salt (that is aniline_to_diazonium_salt_nano2hclat05). Fix: remove. |
| 13 | `anhydride_to_ester_alcllewisaci` | anhydride → ester with AlCl₃ (Lewis acid) | AlCl3 alone gives no ester from an anhydride. Fix: remove. |
| 14 | `cycloalkane_to_cycloalkane_diazomethane` | cycloalkane → cycloalkane with diazomethane (CH2N2); UV light | CH2N2/hν C–H insertion is not JEE syllabus and unselective. Fix: remove. |
| 15 | `diazonium_salt_to_alcohol_howaterasnuc` | diazonium_salt → alcohol with H₂O (water as nucleophile) | the product of ArN2+ + H2O is a phenol, not an alcohol (duplicate of diazonium_salt_to_phenol_ho). Fix: remove. |
| 16 | `diazonium_salt_to_naphthalene_alkalinecoup` | diazonium_salt → naphthalene with alkaline coupling | coupling with 2-naphthol gives an azo dye, not naphthalene. Fix product: azo_compound (reagent 2-naphthol, NaOH). |
| 17 | `diol_to_aldehyde_cu` | diol → aldehyde with Cu; 300°C | Cu/300 °C dehydrogenates an ALCOHOL (1° → aldehyde, 2° → ketone). Fix start: alcohol. |
| 18 | `diol_to_diol_2eqchcooh` | diol → diol with 2 eq CH₃COOH; or Ac₂O | acetylating a diol gives a diester. Fix product: ester. |
| 19 | `ester_to_alkyl_halide_i2` | ester → alkyl_halide with I2; NaOH | I2/NaOH (iodoform) needs CH3CO– or CH3CH(OH)–; an ester gives none. Fix: remove. |
| 20 | `ester_to_substituted_benzene_alcl3` | ester → substituted_benzene with AlCl3 | duplicate of the Fries rearrangement (ester_to_ketone_alcl). Fix: remove. |
| 21 | `ketone_to_amine_hheat` | ketone → amine with H+/heat | H+/heat gives no amine from a ketone. Fix: remove. |
| 22 | `ketone_to_ether_roh` | ketone → ether with ROH; H⁺ | ROH/H+ with a ketone gives a ketal. Fix product: acetal. |
| 23 | `ketone_to_lactone_diazomethane` | ketone → lactone with diazomethane (CH₂N₂) | CH2N2 ring-expands a cyclic ketone to the next KETONE (lactone is Baeyer–Villiger). Fix product: ketone. |
| 24 | `ketone_to_phenol_h` | ketone → phenol with H⁺; Δ | H+/Δ gives no phenol from a ketone. Fix: remove. |
| 25 | `lactam_to_lactam_heat` | lactam → lactam with heat (Δ); n H₂O eliminated (Nylon-6,6) | caprolactam on heating gives Nylon-6 (not 6,6), a polymer. Fix: move to polymer lookups. |
| 26 | `nitrile_to_substituted_benzene_1ch3mgbr` | nitrile → ketone with (1) CH3MgBr; (2) H3O+ | duplicate of nitrile_to_ketone_12ch3mgbr. Fix: remove. |
| 27 | `nitro_compound_to_aniline_znnaoh2molor` | nitro_compound → aniline with Zn/NaOH (2 mol) or LAH | Zn/NaOH gives hydrazo/azo compounds and LiAlH4 gives azobenzene from ArNO2. Fix reagent: Sn/HCl or Fe/HCl (then this duplicates nitro_compound_to_substituted_benzene_snhcl; keep one). |
| 28 | `phenol_to_anhydride_ovoindustria` | phenol → anhydride with O₂/V₂O₅/Δ (industrial) | V2O5 air oxidation makes maleic/phthalic anhydride from benzene or naphthalene, not from phenol. Fix: remove. |
| 29 | `substituted_benzene_to_alkane_o3` | substituted_benzene → ketone with O3; Zn (reductive ozonolysis) | ozonolysis of an arene gives glyoxals (benzene) or mixtures. Fix: remove. |
| 30 | `substituted_benzene_to_anhydride_seecondition` | substituted_benzene → anhydride with see conditions | no reagent given. Fix: o-xylene, V2O5, air → phthalic anhydride, or remove. |
| 31 | `substituted_benzene_to_phenol_1conch2so4de` | substituted_benzene → phenol with (1)conc H2SO4/delta; (2)conc HNO3/conc H2SO4 | picric acid is made from PHENOL (sulphonation then nitration). Fix start: phenol. |
| 32 | `carbanion_to_nitro_compound_kmno4` | carbanion → nitro_compound with KMnO4 | not a reaction of a carbanion. Fix: remove. |

Concept edges (not reaction steps; to become question types or polymer lookups, no approval needed):

- `alkane_to_alkane_samemolecula`: structural isomers of C5H12 (question type, not a reaction)
- `alkyl_halide_to_carbanion_mgdelta`: intermediate (carbanion)
- `alkyl_halide_to_carbocation_alckohdeltae`: intermediate (carbocation) and ring expansion analysis
- `alkyne_to_acetylide_ion_nanh`: intermediate (acetylide); the next step (alkylation) is not in the graph
- `amino_acid_to_amino_acid_cipsequencer`: R/S assignment (question type)
- `aryl_halide_to_aryl_halide_anynu`: SNAr mechanism analysis (the reaction itself is aryl_halide_to_substituted_benzene_naome)
- `carbanion_to_carbanion_conceptualme`: mechanistic analysis only
- `carbanion_to_cycloalkane_mgdelta`: intermediate
- `carbanion_to_substituted_benzene_ohdelta`: intermediate (H/D exchange analysis)
- `carbene_to_carbanion_naohstrongba`: intermediate (carbene from CHCl3)
- `carbene_to_carbene_uvhvfordiazo`: intermediate (carbene generation)
- `carbocation_to_carbocation_conceptualme`: mechanistic analysis only
- `ether_to_ether_oairslowradi`: peroxide formation (safety concept)
- `nitrile_to_nitrile_rlinbutyllit`: α-deprotonation (intermediate)
- `oxime_to_oxime_notinterconv`: E/Z of oximes (question type)
- `phenol_to_phenol_naornaoh`: phenoxide formation (acid–base)
- `radical_to_radical_benzoylperox`: radical initiation (intermediate)
- `aldehyde_to_phenol_hcatalystnov`: polymer (Novolac/Bakelite): lookup, not a molecule
- `phenol_to_polymer_h`: polymer (Bakelite): lookup
- `polymer_to_carbocation_lewisacidbfa`: polymer (cationic polymerisation): lookup
- `polymer_to_diene_conjugated_radicaliniti`: polymer (rubber): lookup
- `polymer_to_polymer_nassodiumdis`: polymer (Thiokol): lookup
- `polymer_to_radical_radicaliniti`: polymer (polythene): lookup
