# Organic rule scope — for approval (layers plan, step 1)

**APPROVED by the user on 2026-11-22: every GAP proposal and every DECIDE proposal, as written below.**
**Step 2 DONE (2026-11-23):** the scopes are in `knowledge/reaction_graph.json` (`chemoselectivity.requires_absent`,
`firing_condition`), written by `tools/apply_rule_scope.py` from group names in `core/engine/organic/scope.py`;
`rules.apply()` refuses any molecule outside them. Approved choices that needed code are in `rules.py`:
1,2-shift refusal (acid hydration, HBr addition, acid dehydration; dehydration keeps a shift that gives the same
alkene), unsymmetrical 1°/2° epoxide + HX refused, Mg ring closure 1,3 only, anhydride 1,4-diacids only,
Wolff–Kishner also reduces CHO. HONO is limited to CH3NH2, CH3CH2NH2 and ArCH2NH2 (no shift possible).

For each of the 155 ruled edges:
- **Book**: the substrate scope the edge's concept-book entries (`tx_ids`) state.
- **Rule**: what `core/engine/organic/rules.py` accepts today.
- **Gap → proposal**: where they differ, and the scope I propose (a proposal, yours to accept or change).
- **St**: `OK` = book and rule agree, nothing to add. `GAP` = clear fix (follows the book or a standard rule). `DECIDE` = book silent, too literal, wrong or in conflict: your call.

## Summary

- **155 ruled edges**: 59 OK, 68 GAP, 28 DECIDE.
- The book almost never lists groups that must be absent. Most GAP rows are that: the reagent also attacks another group the rule ignores.
- Approved scopes go into `chemoselectivity.requires_absent` and `firing_condition` (step 2, after approval).

## Four rule bugs found in passing (FIXED 2026-11-22, tests in `tests/test_engine_organic.py` RuleBugs)

- `ketone_to_alcohol_nabh`: every ketone gives propan-2-ol (butanone, cyclohexanone, acetophenone → `CC(C)O`). The SMARTS has unmapped `[#6]` atoms, so RDKit drops the rest of the molecule.
- `ketone_to_alkane_nhnh` (Wolff–Kishner): the same bug; every ketone gives propane.
- `isocyanide_to_amine_hydrolysis`: gives R–NH–CH3 (the reduction product). Hydrolysis gives R–NH2 + HCOOH.
- `ester_to_carboxylic_acid_h3odiluteaci` / `ester_to_ester_aqnaoh`: a diester gets only one ester hydrolysed (the old "one site only" fault).

## Group sets used below (to keep rows short)

- **PROTIC**: O–H (alcohol, phenol, COOH), N–H, S–H, terminal ≡C–H.
- **C=O SET**: CHO, ketone, ester, COCl, anhydride, amide, nitrile.
- **LAH SET**: C=O SET + COOH, epoxide, aliphatic NO2.
- **NaBH4 SET**: CHO, ketone, COCl.
- **OXIDISABLE**: C=C, C≡C, CHO, 1°/2° OH, benzylic C–H, phenol, NH2.
- **ACYLATABLE**: alcohol OH, phenol OH, NH2/NH.
- **MANY-SITE rule**: `one`/`exhaust` already react at every equivalent site; this is fine where the reagent is in excess.

---

## Hydrocarbons

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| alkane_to_alkyl_halide_x | Br2, hν | any alkane; Br2 picks 3° > 2° > 1° | no heteroatom; most-substituted C–H | rule lets aromatic C through. Propose: no ring C=C, no aromatic ring, no C=C | GAP |
| alkane_to_benzene_al2o3cr2o3 | Al2O3–Cr2O3, 600 °C | hexane | straight C6–C8 | none | OK |
| alkene_to_alcohol_ho | H2O, H+ | Markovnikov; "rearrangements possible" | one C=C, Markovnikov, no shift | rule ignores 1,2-shifts (3,3-dimethylbut-1-ene gives the unshifted alcohol). Propose: refuse when a 1,2-H/CH3 shift gives a more stable cation | GAP |
| alkene_to_aldehyde_o | O3, Zn/H2O | any alkene | exactly one C=C | none (C≡C also reacts; propose C≡C absent) | GAP |
| alkene_to_alkane_h | H2, Pd/C | any alkene | every C=C | H2/Pd also reduces C≡C, NO2 (rule left `C#CCCC` with C≡C). Propose: C≡C, NO2, CHO absent | GAP |
| alkene_to_alkyl_halide_hx | HBr (no peroxide) | Markovnikov; "rearrangements possible" | one C=C, Markovnikov, no shift | 3-methylbut-1-ene gives 2-bromo-3-methylbutane; true major is 2-bromo-2-methylbutane. Propose: refuse when a shift is possible | GAP |
| alkene_to_carboxylic_acid_hotkmno4acid | hot KMnO4/H+ | internal alkene → 2 acids; =CH2 → CO2 | every C=C cleaved | also oxidises benzylic C–H, OH, CHO. Propose: OXIDISABLE absent (except the C=C) | GAP |
| alkene_to_diol_oso | OsO4/NMO | any alkene, syn | every C=C | none | OK |
| alkene_to_epoxide_mcpba | mCPBA | any alkene | every C=C | ketone also present → Baeyer–Villiger competes. Propose: ketone absent | GAP |
| alkene_to_ether_hgoacrohorhg | Hg(OAc)2/CH3OH, NaBH4 | Markovnikov, no rearrangement | one C=C, Markovnikov | none | OK |
| alkene_to_halohydrin_br | Br2/H2O | OH at more substituted C, anti | one C=C | phenol/aniline ring also brominated. Propose: phenol, ArNH2 absent | GAP |
| alkene_to_vicinal_dihalide_x | Br2/CCl4 | any alkene, anti | every C=C | C≡C, phenol, aniline also react. Propose: those absent | GAP |
| cycloalkene_to_alkane_o3 | O3, Zn/H2O | cyclopentene → dialdehyde | one C=C (shared rule) | none | OK |
| diene_conjugated_to_alkyl_halide_hbr1eq | HBr (1 eq), −40 °C | 1,2 at low T; 1,4 at RT | 1,2-adduct, needs terminal =CH2 | none (edge states low T) | OK |
| alkyne_to_alkane_o3 | O3, Zn | internal alkyne → 1,2-dione | internal C≡C only | none | OK |
| alkyne_to_alkene_h | H2, Lindlar | any alkyne → cis alkene | every C≡C | none | OK |
| alkyne_to_carboxylic_acid_hotkmno4acid | hot KMnO4/H+ | pent-2-yne → 2 acids | every C≡C | as hot KMnO4 on alkene. Propose: OXIDISABLE absent | GAP |
| alkyne_to_geminal_dihalide_hxexcess2equ | HBr (2 eq) | two Markovnikov additions | one C≡C | none | OK |
| alkyne_to_ketone_ho | HgSO4, H2SO4 | Markovnikov; ethyne → ethanal | one C≡C | none | OK |
| alkyne_to_vinyl_halide_hx1equiv | HBr (1 eq) | Markovnikov | one C≡C | C=C also present adds HBr too. Propose: C=C absent | GAP |

## Alkyl halides

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| alkyl_halide_to_alcohol_naoh | aq NaOH | 1°/2° SN2; entry 16: 3° gives E2; entry 258: 3° gives SN1 alcohol | all but neopentyl, gem-dihalide | book conflicts on 3°. Options: (a) 1°/2° only (b) 3° allowed (SN1 alcohol, JEE usual). Proposal: (b) | DECIDE |
| alkyl_halide_to_alkane_zn | Zn/H+ | R–X → R–H | every C–X | vicinal dihalide gives the alkene with Zn, not the alkane (rule gave `CCC` from 1,2-dibromopropane). Propose: vicinal dihalide absent | GAP |
| alkyl_halide_to_alkene_alckoh | alc. KOH | E2, Saytzeff | one C–X, Zaitsev | none | OK |
| alkyl_halide_to_alkyl_halide_nai | NaI/acetone | SN2: 1° > 2° >> 3° | all but neopentyl (tBuBr → tBuI accepted) | Propose: 1°/2° only; 3° refused | GAP |
| alkyl_halide_to_amine_excessnh | excess NH3 | "primary preferred" | all but 3°, neopentyl | Options: (a) 1° only (b) 1°/2°. Proposal: (b) | DECIDE |
| alkyl_halide_to_cycloalkane_mgmagnesiumm | Mg, ether | 1,3-dibromopropane → cyclopropane | 1,3- or 1,4-dihalide | book silent on 1,4 (cyclobutane). Proposal: 1,3 only | DECIDE |
| alkyl_halide_to_ether_rona | CH3ONa | "MUST use primary R-X" (2° gives E2) | all but 3°, neopentyl (2-bromopropane accepted) | Propose: CH3/1° only, neopentyl refused | GAP |
| alkyl_halide_to_grignard_mg | Mg, dry ether | "proton source destroys Grignard" | one sp3 C–X (4-bromobutan-1-ol accepted) | Propose: PROTIC and C=O SET absent, NO2 absent | GAP |
| alkyl_halide_to_ketone_dmsodimethyl | DMSO, heat | 2° halide → ketone | 2° C–X | none | OK |
| alkyl_halide_to_nitrile_nacn | NaCN, DMSO | 1°/2° SN2 | all but 3°, neopentyl | none | OK |
| alkyl_halide_to_nitro_compound_agno2silvern | AgNO2 | R–X (N-attack) | all but 3°, neopentyl | book silent on 2°. Proposal: 1°/2° (as rule) | OK |
| alkyl_halide_to_acid_chloride_o2 | O2, hν | CHCl3 → COCl2 | CHCl3 only | none | OK |
| vicinal_dihalide_to_alkyne_zndeltaexces | Zn dust, CH3OH | entry 368 is tetrahalide → alkyne (does not match) | vicinal dihalide → alkene | book entry mislinked; book silent on the rule's reaction. Proposal: keep rule (vic-dihalide → alkene); relink to a matching entry | DECIDE |

## Alcohols, diols, ethers, epoxides

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| alcohol_to_aldehyde_pcc | PCC | 1° → CHO; 2° → ketone; 3° no reaction | every 1° OH; 2° OH left alone (butane-1,3-diol → `CC(O)CC=O`) | PCC also oxidises 2° OH. Propose: 2° OH absent (or oxidise both) | GAP |
| alcohol_to_ketone_pcc | PCC | 2° → ketone | every 2° OH | same in reverse. Propose: 1° OH absent | GAP |
| alcohol_to_carboxylic_acid_kmno | KMnO4/H+ | 1° → acid | every 1° OH | also oxidises 2° OH, C=C, CHO, benzylic C–H. Propose: OXIDISABLE absent (except the 1° OH) | GAP |
| alcohol_to_alkene_conchso | conc. H2SO4, 443 K | E1, Saytzeff; "rearrangements possible"; 3° > 2° > 1° | one OH; refuses only neopentyl CH2OH | 3,3-dimethylbutan-2-ol gives 3,3-dimethylbut-1-ene; true major is 2,3-dimethylbut-2-ene. Propose: refuse when a 1,2-shift gives a more stable cation | GAP |
| alcohol_to_alkyl_halide_socl | SOCl2, pyridine | any alcohol (SN2, inversion) | every C–OH | SOCl2 also makes COOH → COCl (rule kept COOH). Propose: COOH absent | GAP |
| alcohol_to_amine_al2o3450c | NH3, Al2O3 | entry 87: mixture, "preferentially tertiary" | 1° OH → RNH2 | book says a mixture, rule says one product. Options: (a) keep, 1° amine named "major" (b) drop the edge | DECIDE |
| alcohol_to_carbene_chndiazometh | CH2N2 | reactivity RCOOH >> ArOH > ROH | every C–OH (COOH left alone) | rule methylated the alcohol, not the acid. Propose: COOH, phenol absent | GAP |
| alcohol_to_ester_rcocl | CH3COCl, pyridine | any alcohol | every C–OH | NH2 acylated faster; phenol too. Propose: NH2/NH, phenol absent | GAP |
| alcohol_to_ether_na | Na, then CH3I | alkoxide + RX (SN2) | every C–OH | Na takes the acidic H first (COOH, phenol); CH3I alkylates amines. Propose: COOH, phenol, NH2/NH absent | GAP |
| alcohol_to_substituted_benzene_4methylbenze | TsCl, pyridine | any alcohol → tosylate | every C–OH | NH2 also sulfonated. Propose: NH2/NH absent | GAP |
| alcohol_to_sulfonate_conchso | conc. H2SO4, < 383 K | any alcohol → ROSO3H | every C–OH | none | OK |
| diol_to_aldehyde_hio4periodic | HIO4 | vicinal diol | vicinal diol | none | OK |
| diol_to_aldehyde_cu | Cu, 573 K | 1° → CHO, 2° → ketone | every 1° OH | 2° OH also dehydrogenated. Propose: 2° OH absent | GAP |
| diol_to_alkane_redp | red P/HI | glycerol → propane | every C–OH → C–H | book only shows glycerol. Proposal: any polyol, no other groups (C=O, halide) | DECIDE |
| diol_to_alkyl_halide_pi | PI3 (excess) | glycerol → allyl iodide (not triiodide) | every OH → I | book says glycerol ends as allyl iodide; rule gives 1,2,3-triiodopropane. Options: (a) refuse vicinal triols (b) follow book (allyl iodide). Proposal: (a) | DECIDE |
| diol_to_carboxylic_acid_kmno | hot KMnO4/H+ | glycol → 2 HCOOH (book) | cleave, CHO → COOH, HCHO → CO2 | book says HCOOH; rule says CO2 for a CH2OH end. Proposal: CO2 (standard: HCOOH is oxidised further) | DECIDE |
| diol_to_diol_2eqchcooh | Ac2O (excess), pyridine | entry 175: 2 eq, selective 1,3-diacetate | every OH (glycerol → triacetate) | edge reagent was fixed to excess Ac2O; entry is stale. Proposal: keep rule; relink entry | OK |
| diol_to_ester_conchno | conc. HNO3/H2SO4, 0 °C | glycerol → trinitrate | every OH | aromatic ring would also nitrate. Propose: aromatic ring absent | GAP |
| epoxide_to_alcohol_rnh | CH3NH2 | basic: less hindered C | one epoxide, less hindered | none | OK |
| epoxide_to_diol_ho | H2O, acid or base | any epoxide → anti diol | every epoxide | none | OK |
| epoxide_to_epoxide_h3odiluteaci | H3O+ | 18O labelling, symmetrical epoxide | same rule as above | none | OK |
| epoxide_to_halohydrin_hx | HBr (1 eq) | acid opens at more substituted C | 3° → at 3°; else less hindered | book says "more substituted" always; rule uses SN2 for 1°/2°. Options: (a) rule (b) book. Proposal: (a), and refuse 1°/2° unsymmetrical (textbooks disagree) | DECIDE |
| epoxide_to_vicinal_dihalide_hx | HBr (excess) | anti vicinal dihalide | every epoxide | none | OK |
| ether_to_alkyl_halide_conchxhihbra | HI (1 eq) | 3° SN1; else SN2 at less hindered; Ar–O never cleaved | same | benzylic/allylic ethers also go SN1 at that C. Propose: refuse benzylic/allylic ethers (or add SN1 there) | GAP |
| ether_to_ester_co | CO, BF3 | ether → ester (rare) | dialkyl ether; tie refused | book has one generic entry only. Proposal: symmetrical dialkyl ethers only | DECIDE |
| ether_to_phenol_thermalnocat | heat | allyl phenyl ether → 2-allylphenol | allyl aryl ether, free ortho H | none | OK |

## Phenols

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| phenol_to_aldehyde_naoh | CHCl3, NaOH | entry 385: guaiacol → vanillin (para) | CHO ortho to OH (guaiacol → o-vanillin) | conflict on guaiacol. Options: (a) ortho if free (rule) (b) book's para. Proposal: (a), refuse 2-substituted phenols | DECIDE |
| substituted_benzene_to_aldehyde_naoh | CHCl3, NaOH | phenol → salicylaldehyde (entry 391 Étard, mislinked) | same rule (needs phenol) | none | OK |
| phenol_to_aryl_halide_pclslowreact | PCl5 | phenol → PhCl, poor yield | every Ar–OH | CHO absent (PCl5 takes CHO → CHCl2 first; added 2026-11-24 after live run 6, the author) | OK |
| phenol_to_benzene_znreductionl | Zn dust, heat | phenol → benzene | every Ar–OH | none | OK |
| phenol_to_ester_rcoclacylchl | CH3COCl | phenol O-acylation | every Ar–OH | NH2 and alcohol OH also acylated. Propose: ACYLATABLE absent (except the phenol OH) | GAP |
| phenol_to_geminal_dihalide_kso | K2S2O8, KOH (Elbs) | entry says "catechol (… quinol)"; mechanism text says para | OH para; refuses if para taken | entry name wrong (catechol); rule is right (hydroquinone). Proposal: keep rule | OK |
| phenol_to_ketone_kmnoornacroh | Na2Cr2O7/H2SO4 | phenol → p-benzoquinone | phenol only | none | OK |
| phenol_to_substituted_benzene_chndiazometh | CH2N2 | COOH reacts before ArOH | every Ar–OH | Propose: COOH absent | GAP |
| substituted_benzene_to_carboxylic_acid_1naoh | NaOH, CO2 (Kolbe) | phenol → salicylic acid | COOH ortho; tie refused | none | OK |
| substituted_benzene_to_phenol_1conch2so4de | H2SO4, then HNO3 | phenol → picric acid | phenol only | none | OK |

## Aldehydes and ketones

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| aldehyde_to_acetal_roh2 | CH3OH (2 eq), dry HCl | aldehyde → acetal | every CHO | none | OK |
| aldehyde_to_alcohol_nabh | NaBH4 | reduces CHO and ketone, not ester/acid/amide | every CHO; ketone left (`CC(=O)CCCO`) | Propose: ketone, COCl absent (or reduce all NaBH4 SET) | GAP |
| aldehyde_to_aldehyde_naohdilute51 | dil. NaOH, heat | ethanal → but-2-enal | self-aldol, needs α-CH2/CH3 | book shows ethanal only. Proposal: one CHO, no other C=O SET, no other α-H carbonyl | DECIDE |
| aldehyde_to_alkane_znhg | Zn–Hg, conc. HCl | CHO → CH3; strongly acidic | every CHO | ketone also reduced; acid-labile groups (acetal, tBu ether) attacked. Propose: ketone absent | GAP |
| aldehyde_to_amine_h2ptornabh3c | NH3, H2/Pt | aldehyde or ketone + NH3 → 1° amine | every CHO | H2/Pt also reduces C=C; ketone also aminated. Propose: C=C, ketone absent | GAP |
| aldehyde_to_carboxylic_acid_kmnoortollen | "KMnO4 or Tollens'" | CHO → COOH | every CHO only | KMnO4 also attacks OXIDISABLE; Tollens' attacks CHO only. Proposal: fix reagent to Tollens' | DECIDE |
| aldehyde_to_cyanohydrin_hcn | HCN | aldehyde (> ketone) | every CHO | ketone also adds HCN. Propose: ketone absent | GAP |
| aldehyde_to_diol_lahallylalco | LiAlH4, then cold KMnO4 | acrolein → glycerol | any C=C–CHO | book shows acrolein only. Proposal: acrolein-type enals, no other LAH SET | DECIDE |
| aldehyde_to_geminal_dihalide_pcl5 | PCl5 | CHO or ketone → CCl2 | every CHO | PCl5 also attacks OH, COOH, ketone. Propose: those absent | GAP |
| aldehyde_to_imine_rnh | CH3NH2 | aldehyde → imine | every CHO | ketone also condenses. Propose: ketone absent | GAP |
| aldehyde_to_substituted_benzene_naohaqueouss | conc. NaOH (Cannizzaro) | entries 460/462 are deformylation exceptions (2,6-dimethyl-, 2,4,6-trinitrobenzaldehyde) | HCHO, ArCHO, R3C–CHO | rule accepts the book's exceptions (2,6-dimethylbenzaldehyde → alcohol). Propose: refuse 2,6-disubstituted and 2,4,6-trinitro ArCHO; relink a Cannizzaro entry | DECIDE |
| ketone_to_alcohol_nabh | NaBH4 | ketone → 2° alcohol | **BROKEN: every ketone → propan-2-ol** | fix the SMARTS first; then propose CHO, COCl absent (or reduce all) | GAP |
| ketone_to_aldehyde_seo2selenium | SeO2 | acetone → methylglyoxal | one C=O, oxidises α-CH3 | butanone: rule oxidises CH3; SeO2 prefers the CH2. Proposal: methyl ketones with no other α-H (acetone, ArCOCH3) | DECIDE |
| ketone_to_alkane_nhnh | NH2NH2, KOH | ketone → CH2; "base-sensitive substrates" | **BROKEN: every ketone → propane** | fix SMARTS; then propose CHO reduced too, ester and alkyl halide absent (hot KOH) | GAP |
| ketone_to_alkyl_halide_i2 | I2, NaOH (iodoform) | methyl ketone (entry 214 wrongly says cyclohexanone) | CH3CO– | none for the rule; entry 214 is wrong chemistry | OK |
| ketone_to_carboxylic_acid_x2cl2br2ori2 | X2, NaOH (haloform) | methyl ketone → acid (one C fewer) | CH3CO– | none (entry 471 Favorskii is mislinked) | OK |
| ketone_to_carbene_methylenepho | Ph3P=CH2 (Wittig) | ketone → C=CH2 | every ketone | CHO also reacts (faster). Propose: CHO absent | GAP |
| ketone_to_cyanohydrin_hcn | HCN | ketone; hindered ones lie left | every ketone | CHO also reacts. Propose: CHO absent; refuse di-tert-alkyl ketones | GAP |
| ketone_to_ester_mcpbametachl | mCPBA (Baeyer–Villiger) | H > 3° > 2° > cyclohexyl > Ph > 1° > CH3 | one ketone; 3° > 2° ≈ aryl > 1° > CH3 (tie refused) | C=C epoxidised first. Propose: C=C absent | GAP |
| ketone_to_ether_roh | CH3OH (excess), dry HCl | entry 42 says "enol ether" | ketal | entry is stale/odd; rule matches the edge's fixed reagent. Proposal: keep ketal; CHO absent | GAP |
| ketone_to_ketone_x2 | Br2, CH3COONa | entry 211: methyl ketone → RCOCH2X | one C=O; α-Br at more substituted α-C (butanone → 3-bromobutan-2-one) | book says CH2X on the methyl; rule picks the more substituted side. Options: (a) rule (acid enol rule) (b) book. Proposal: (a), or limit to symmetric ketones | DECIDE |
| ketone_to_lactone_diazomethane | CH2N2, BF3 | homologation; anti-periplanar group migrates | cyclic ketone + α-CH2; tie refused | book silent on which ring ketones. Proposal: symmetric cyclic ketones only (cyclohexanone, cyclopentanone) | DECIDE |
| ketone_to_oxime_nhohhcl | NH2OH·HCl | ketone → oxime | every ketone | CHO also condenses. Propose: CHO absent | GAP |
| nitrile_to_ketone_12ch3mgbr | CH3MgBr, then H3O+ | nitrile + RMgX → ketone | every nitrile | PROTIC and other C=O SET destroy / compete. Propose: PROTIC, C=O SET (other than the C≡N) absent | GAP |

## Acids and derivatives

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| acid_chloride_to_alcohol_1lialh4lithi | LiAlH4 | RCOCl → RCH2OH | every COCl | LAH also reduces other LAH SET. Propose: LAH SET absent (except COCl) | GAP |
| acid_chloride_to_amine_nan3h3o | NaN3, H3O+ (Curtius) | RCOCl → RNH2 | every COCl | none | OK |
| acid_chloride_to_ketone_dimethylcupr | Me2CuLi | RCOCl → ketone; no over-addition | every COCl | PROTIC destroys the cuprate. Propose: PROTIC absent | GAP |
| carboxylic_acid_to_acid_chloride_socl | SOCl2 | RCOOH → RCOCl | every COOH | alcohol OH also → Cl. Propose: alcohol OH absent | GAP |
| carboxylic_acid_to_alcohol_lialh | LiAlH4 | COOH → CH2OH | every COOH | Propose: LAH SET absent (except COOH) | GAP |
| carboxylic_acid_to_alkane_naoh | soda lime | RCOOH → RH | one aliphatic COOH | none | OK |
| carboxylic_acid_to_benzene_naoh | soda lime | PhCOOH → benzene | one aromatic COOH | none | OK |
| carboxylic_acid_to_alkyl_halide_agohtomakeag | Ag salt, Br2 (Hunsdiecker) | RCOOH → RBr | one aliphatic COOH | C=C would add Br2. Propose: C=C absent | GAP |
| carboxylic_acid_to_amide_nh | NH3, heat | RCOOH → RCONH2 | every COOH | ester would also be aminolysed. Propose: ester absent | GAP |
| carboxylic_acid_to_amine_hn3h2so4 | HN3, H2SO4 (Schmidt) | RCOOH → RNH2 | one COOH | ketone also undergoes Schmidt. Propose: ketone absent | GAP |
| carboxylic_acid_to_anhydride_hso | heat | phthalic acid; some 1,4-diacids | 1,4- or 1,5-diacid | book silent on glutaric (6-ring). Proposal: 1,4-diacids and phthalic only | DECIDE |
| carboxylic_acid_to_carboxylic_acid_x | Br2, red P (HVZ) | needs α-H | every COOH with α-H | none (entry 386 aspirin mislinked) | OK |
| carboxylic_acid_to_ester_roh | CH3OH, H+ | Fischer | every COOH | none | OK |
| anhydride_to_alkane_1lialh4exces | LiAlH4 (excess) | succinic anhydride → 1,4-diol | first anhydride only | Propose: one anhydride, other LAH SET absent | GAP |
| amide_to_amine_lah | LiAlH4 | 1°/2°/3° amide → amine (same C) | every amide | Propose: LAH SET absent (except amide) | GAP |
| lactam_to_amine_lah | LiAlH4 | lactam → cyclic amine | same rule | as above | GAP |
| ester_to_acid_chloride_pcl5 | PCl5 | "clean for primary R'" | any alkyl ester | Propose: R' = CH3 or 1° alkyl; OH, COOH, ketone absent | GAP |
| ester_to_aldehyde_dibalhdiisob | DIBAL-H, −78 °C | ester → CHO | first ester | Propose: one ester; CHO, ketone absent | GAP |
| ester_to_carboxylic_acid_h3odiluteaci | H3O+, heat | ester → acid + alcohol | **first ester only** | fix to every ester; then nitrile, amide absent | GAP |
| ester_to_ester_aqnaoh | aq NaOH | saponification | same rule (first ester only) | as above; plus alkyl halide absent | GAP |
| ester_to_ether_conchso | CH3OH, conc. H2SO4 | "only works for pivalate" (tBu pivalate) | any tBu ester | book narrower than rule. Options: (a) tBu pivalate only (book) (b) any tBu ester (AAl1, standard). Proposal: (b) | DECIDE |
| ester_to_ketone_alcl | AlCl3 (Fries) | book: low T → ortho, high T → para | para (low T), ortho trap | book has the temperatures reversed (standard: low T para). Proposal: keep rule; correct the book entry | DECIDE |
| carbohydrate_to_carbohydrate_ch3co2o | Ac2O (excess) | glucose → pentaacetate | every OH | none | OK |

## Aromatics

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| benzene_to_alcohol_oxirane | oxirane, AlCl3 | benzene → 2-phenylethanol | benzene only | none | OK |
| benzene_to_aldehyde_co | CO, HCl, AlCl3/CuCl | "only unactivated or slightly activated benzene (not alkoxy or amino)" | eas(): refuses phenol, aniline only | anisole and deactivated rings accepted. Propose: benzene and alkyl/halo benzenes only | GAP |
| benzene_to_alkyl_halide_3cl2 | 3 Cl2, UV | benzene → BHC | benzene only | none | OK |
| benzene_to_aryl_halide_x | Br2, FeBr3 | EAS halogenation | mono-substituted ring; o/p or m | side-chain C=C adds Br2. Propose: C=C absent | GAP |
| benzene_to_carboxylic_acid_fuminghsoole | oleum | EAS sulphonation | mono-substituted ring | none | OK |
| benzene_to_ketone_rcocl | CH3COCl, AlCl3 | "deactivated rings (NO2, COOH) fail" | refuses NO2, aryl-N only (benzonitrile accepted) | Propose: refuse every meta director (NO2, CN, COR, CHO, COOH, SO3H, NR3+), all amines, phenol | GAP |
| benzene_to_phenol_feso | FeSO4, H2O2 | benzene → phenol | benzene only | none | OK |
| benzene_to_substituted_benzene_conchno | conc. HNO3/H2SO4 | benzene → nitrobenzene | mono-substituted ring; refuses Ar–N=O, phenol, aniline | oxidisable side groups (CHO accepted → m-nitrobenzaldehyde). Proposal: CHO, C=C, alcohol OH absent; or allow CHO (m-nitro is a known JEE result) | DECIDE |
| substituted_benzene_to_substituted_benzene_conchno3 | conc. HNO3/H2SO4, stepwise heat | toluene → TNT; nitrobenzene + 2 Br2 (mislinked) | mono-nitration (same rule) | book says trinitration (TNT); rule mononitrates. Options: (a) mononitration, fix the reagent text (b) TNT for toluene only. Proposal: (a) | DECIDE |
| substituted_benzene_to_ketone_oradicalinit | O2, then dil. H2SO4 | cumene → phenol + acetone | cumene only | none | OK |
| substituted_benzene_to_anhydride_seecondition | O2, V2O5 | entry 608 (−M ordering) is unrelated | o-xylene only | book silent; relink. Proposal: keep (o-xylene only) | OK |
| naphthalene_to_anhydride_o2 | O2, V2O5 | naphthalene → phthalic anhydride | naphthalene only | none | OK |
| naphthalene_to_naphthalene_conch2so4 | conc. H2SO4, ≤ 383 K | 1-sulphonic acid (kinetic) | naphthalene only | none | OK |
| aryl_halide_to_grignard_mgmagnesiumm | Mg, dry ether/THF | 2-bromoanisole → ArMgBr | Ar–Br/I; refuses NO2 | Propose: PROTIC and C=O SET absent | GAP |
| aryl_halide_to_phenol_naoh | NaOH, 623 K, 300 atm (Dow) | chlorobenzene (benzyne) | any Ar–Cl/Br (p-chlorotoluene → p-cresol) | benzyne on a substituted ring gives isomer mixtures (cine). Options: (a) PhCl/PhBr only (b) allow o/p-NO2 rings (they go by SNAr). Proposal: (a) | DECIDE |
| aryl_halide_to_substituted_benzene_naome | NaOCH3 (SNAr) | needs EWG o/p to X | NO2 o/p to X | none (entries 409/412 Fittig/Ullmann mislinked) | OK |
| aniline_to_diazonium_salt_nano2hclat05 | NaNO2/HCl, 0–5 °C | ArNH2 → ArN2+ | every ArNH2 | aliphatic NH2 also reacts (→ alcohol + N2). Propose: aliphatic NH2 absent | GAP |
| aniline_to_ketone_kmno4heatorh | KMnO4/heat | aniline → p-benzoquinone | aniline only | none | OK |
| aniline_to_substituted_benzene_carosacidh2s | Caro's acid | entry 100: aniline → **nitrobenzene** | aniline → **nitrosobenzene** | conflict. Options: (a) nitroso (NCERT-style) (b) nitro (book). Proposal: (a); correct the book entry | DECIDE |
| diazonium_salt_to_aryl_halide_cuxsandmeyer | CuCl/HCl | ArN2+ → ArCl | ArN2+ | none | OK |
| diazonium_salt_to_azo_compound_arohorarnhco | phenol, alkaline | coupling para to OH | phenol fixed as partner | none | OK |
| diazonium_salt_to_naphthalene_alkalinecoup | 2-naphthol, NaOH | coupling at C-1 | 2-naphthol fixed | none | OK |
| diazonium_salt_to_nitrile_nacn | CuCN | ArN2+ → ArCN | ArN2+ | none | OK |
| diazonium_salt_to_phenol_ho | H2O, warm | ArN2+ → ArOH | ArN2+ | none | OK |
| diazonium_salt_to_substituted_benzene_hpo | H3PO2 | ArN2+ → ArH | ArN2+ | none | OK |
| nitro_compound_to_azo_compound_znnaoh1mol | Zn/NaOH (1 mol) | ArNO2 → azobenzene | ArNO2, self-coupling | two different NO2 groups give mixtures. Propose: exactly one ArNO2; CHO, ketone absent | GAP |
| nitro_compound_to_aniline_znnaoh2molor | Sn, conc. HCl | entries 78 (Zn/NaOH 2 mol → hydrazobenzene), 80 ((NH4)2S) | every ArNO2 → ArNH2 | edge was fixed to Sn/HCl; entries are stale. Proposal: keep rule; relink. Note Sn/HCl also reduces CHO/ketone sometimes: propose CHO absent | DECIDE |

## Amines, nitriles, organometallics

| Edge | Reagent | Book | Rule | Gap → proposal | St |
|---|---|---|---|---|---|
| amine_to_alcohol_nano | NaNO2, dil. HCl | 1° aliphatic RNH2 → ROH | every 1° alkyl NH2, "no rearrangement assumed" | propylamine gives propan-1-ol + propan-2-ol + propene in reality. Options: (a) only CH3NH2, EtNH2, PhCH2NH2 (no shift possible) (b) drop the edge. Proposal: (a) | DECIDE |
| amine_to_amide_rcocl | CH3COCl, pyridine | 1°/2° amine → amide | every alkyl N–H (1° or 2°) | alcohol/phenol OH also acylated (slower). Propose: OH absent | GAP |
| amine_to_amine_heatsn2 | CH3I (excess) | exhaustive alkylation → R4N+ | aliphatic amine | none | OK |
| amine_to_imine_rcho | benzaldehyde | 1° amine → imine; 2° gives enamine | 1° alkyl NH2 | none | OK |
| amine_to_nitro_compound_kmno4 | KMnO4 | entry 103: 2° amine → nitrosamine | t-alkyl NH2 → NO2 | book silent on the rule's reaction (t-alkyl amine → nitroalkane). Options: (a) keep, relink (b) drop | DECIDE |
| amine_to_isocyanide_carbylaminetest | CHCl3, alc. KOH | "primary amines ONLY" (entry 82 is isocyanide reduction, mislinked) | every 1° NH2 (alkyl or aryl) | none | OK |
| isocyanide_to_amine_hydrolysis | dil. HCl, H2O | no entry (tx_ids empty); edge: RNC → RNH2 + HCOOH | **gives R–NH–CH3 (wrong)** | fix product to RNH2 + HCOOH | GAP |
| nitrile_to_aldehyde_dibalhdiisob | DIBAL-H | RCN → RCHO | every nitrile | ester, ketone also reduced. Propose: those absent | GAP |
| nitrile_to_amine_h | H2/Ni | RCN → RCH2NH2 | every nitrile | C=C, C≡C, NO2 also reduced. Propose: those absent | GAP |
| nitrile_to_carboxylic_acid_ho | H3O+, heat | RCN → RCOOH | every nitrile | esters, amides also hydrolysed. Propose: those absent | GAP |
| grignard_to_alcohol_hcho | HCHO, then H3O+ | RMgX → RCH2OH (+1 C) | every C–Mg | none | OK |
| grignard_to_carboxylic_acid_co | CO2, then H3O+ | RMgX → RCOOH | every C–Mg | none | OK |

---

## Concept-book entries that do not support their edge (FIXED 2026-11-22)

- Done: the mislinked ids below were removed from their edges; 365, 383, 75, 143, 379 linked where they fit.
- Wrong entries corrected in place: 42 (ketal), 100 (nitroso), 115 (Fries temperatures), 128 (hydroquinone), 214 (no iodoform), 215 (one CHI3), 385 (guaiacol gives a mixture).
- New entries 657–660: Cannizzaro, o-xylene → phthalic anhydride, isocyanide hydrolysis, t-alkyl amine + KMnO4.
- Still open: other edges also carry entries for a different reagent (e.g. 3/183/184 peroxide HBr and NBS on the no-peroxide HBr edge, 9 hydroboration on acid hydration, 13 Na/NH3 on Lindlar, 305 on Fries, 88 Ritter, 205, 216, 217). Not yet audited.

The original list:

- Mislinked (entry is a different reaction): 37, 631 (NaBH4 edge); 445–447 (Perkin on the Tollens' edge); 460, 462 (Cannizzaro); 470 (Koch on hot KMnO4); 471 (Favorskii); 493 (adipic acid on Wolff–Kishner); 386 (aspirin on HVZ); 145, 198, 242, 598 (Fischer edge); 391 (Étard); 472, 473 (Kolbe edge); 368 (Zn edge); 409, 412 (SNAr edge); 82 (carbylamine); 608 (o-xylene); 78, 80 (Sn/HCl edge); 175 (diacetate); 42 (ketal); 395, 572 (nitration edge).
- Wrong chemistry in the book: 128 ("catechol"), 214 (cyclohexanone iodoform), 115 (Fries temperatures reversed), 100 (Caro's acid → nitro), 385 (guaiacol → para).

## What you decide

- Approve, change or reject each `GAP` proposal and pick an option for each `DECIDE` row.
- Then step 2 writes the approved scopes into the graph and makes each rule refuse outside them.
