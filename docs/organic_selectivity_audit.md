# Organic chemoselectivity audit (2026-11-24)

Found by `tools/audit_organic_selectivity.py` (log: `outputs/audit_organic_selectivity.log`) after live run 6
(PCl5 replaced a phenol OH while the CHO reacts first). The tool runs all 155 ruled edges on 638 molecules with
one or two groups. Every row below was checked by hand.

**Status (2026-11-24, approved by the author: A, then B):** A fixed in `core/engine/organic/rules.py`; B written as
`SELECTIVITY` in `tools/apply_rule_scope.py` (new group `methyl_carbinol` in `scope.py`). Audit flags 91 → 29
(`outputs/audit_organic_selectivity_after.log`); what is left is listed under C and "Not problems". The Schmidt row
was dropped: that edge already refused ketones.

## A. Rule bugs: wrong product even on a simple molecule

| Edge | Input → engine gives | Correct |
|---|---|---|
| `amine_to_isocyanide_carbylaminetest` | butanamide CCCC(N)=O → R–C(=O)–NC | no reaction: carbylamine needs a 1° **amine**; the SMARTS `[#6][NX3H2]` also matches amide N |
| `ether_to_alkyl_halide_conchxhihbra` (HI) | propylene oxide, ethylene oxide → CH3I | an epoxide is not a dialkyl ether: HI opens it to the iodohydrin; the rule needs epoxide absent |

## B. PCl5-type gaps: the edge fires, the same reagent attacks another group faster (high confidence)

| Edge (reagent) | Group it ignores | Why |
|---|---|---|
| `phenol_to_aryl_halide_pclslowreact` (PCl5) | alcohol, COOH, ketone | PCl5 takes ROH / COOH fast, C=O → CCl2; Ar–OH is the slow site |
| `ester_to_acid_chloride_pcl5` (PCl5) | CHO | CHO → CHCl2; also clashes: the CHO edge and this edge both fire on CH3COO(CH2)4CHO |
| `ketone_to_ester_mcpbametachl` (mCPBA) | CHO | aldehydes undergo Baeyer–Villiger faster than ketones |
| `alkene_to_epoxide_mcpba` (mCPBA) | CHO, amine | CHO → acid (B–V), amine → N-oxide |
| `aldehyde_to_acetal_roh2`, `ketone_to_ether_roh` (MeOH, dry HCl) | COOH, COCl, epoxide | COOH esterifies, COCl → ester at once, epoxide opens |
| `aldehyde_to_substituted_benzene_naohaqueouss` (conc. NaOH) | ester, COCl, alkyl halide | hydrolysis / substitution in hot conc. NaOH |
| `aldehyde_to_aldehyde_naohdilute51` (dil. NaOH, heat) | alkyl halide, ester | same |
| `alkyl_halide_to_alcohol_naoh` (aq. NaOH) | ester, COCl | saponified / hydrolysed |
| `alkyl_halide_to_alkene_alckoh` (alc. KOH) | ester, COCl | same |
| `alkyl_halide_to_amine_excessnh` (NH3) | COCl, CHO, epoxide | amide at once, imine, ring opening |
| `alkyl_halide_to_ether_rona` (CH3ONa) | ester, COCl | transesterification, ester at once |
| `alkene_to_alcohol_ho` (dil. H2SO4) | epoxide | opens to the diol |
| `alkene_to_alkyl_halide_hx` (HBr) | epoxide | opens first |
| `alkyne_to_vinyl_halide_hx1equiv`, `alkyne_to_geminal_dihalide_hxexcess2equ` (HBr) | alkene, epoxide | an alkene takes HBr faster than an alkyne |
| `epoxide_to_vicinal_dihalide_hx` (HBr excess) | alkene, alkyne, alcohol | excess HBr adds / substitutes too |
| `alkyne_to_ketone_ho` (HgSO4, H2SO4) | alkene | hydrated too |
| `benzene_to_aryl_halide_x` (Br2, FeBr3) | alkyne | Br2 adds to C≡C first |
| `carboxylic_acid_to_alkyl_halide_agohtomakeag` (Br2, Hunsdiecker) | alkyne | same |
| `alkene_to_halohydrin_br` (Br2, H2O) | CHO, alkyne | CHO oxidised; Br2 adds to C≡C |
| `ketone_to_ketone_x2` (Br2, AcOH) | alkene, alkyne, phenol, ArNH2 | Br2 adds / brominates the ring faster |
| `ketone_to_carboxylic_acid_x2cl2br2ori2` (Br2, NaOH) | CH3CH(OH)–, ester, phenol, ArNH2 | also gives haloform; hydrolysis; ring bromination |
| `carboxylic_acid_to_carboxylic_acid_x` (Br2, red P) | alcohol, alkene, alkyne, ketone | PBr3 makes RBr; Br2 adds; α-bromination of the ketone |
| `acid_chloride_to_alcohol_1lialh4lithi`, `carboxylic_acid_to_alcohol_lialh`, `amide_to_amine_lah`, `lactam_to_amine_lah` (LiAlH4) | alkyl halide | LiAlH4 reduces R–X to R–H |
| `ester_to_aldehyde_dibalhdiisob`, `nitrile_to_aldehyde_dibalhdiisob` (DIBAL) | COCl, C≡N | reduced too |
| `nitrile_to_amine_h` (H2, Ni) | CHO | reduced too |
| `aldehyde_to_amine_h2ptornabh3c` (NH3, H2/Pt) | alkyne, NO2, C≡N | reduced too |
| `nitrile_to_ketone_12ch3mgbr` (CH3MgBr) | epoxide | Grignard opens it |
| `ketone_to_carbene_methylenepho` (Wittig) | COOH, OH, phenol | acidic H destroys the ylide |
| `alkene_to_ether_hgoacrohorhg` (Hg(OAc)2; NaBH4) | CHO, ketone, alkyne | NaBH4 step reduces C=O; Hg²⁺ hydrates C≡C |
| `acid_chloride_to_ketone_dimethylcupr` (Gilman) | alkyl halide | Corey–House coupling |
| `phenol_to_aldehyde_naoh`, `substituted_benzene_to_aldehyde_naoh` (CHCl3, NaOH) | NH2 (aliphatic or aryl), ester | carbylamine reaction; hydrolysis |
| `amine_to_alcohol_nano` (NaNO2, HCl) | ArNH2 | diazotised too |
| `ester_to_carboxylic_acid_h3odiluteaci`, `nitrile_to_carboxylic_acid_ho` (H3O⁺, heat) | COCl, epoxide | hydrolysed / opened |
| `alcohol_to_substituted_benzene_4methylbenze` (TsCl) | phenol | tosylated too |
| `benzene_to_ketone_rcocl` (Friedel–Crafts) | alcohol | O-acylation, AlCl3 complexation |
| `diol_to_diol_2eqchcooh` (Ac2O, pyridine) | amine N–H, phenol | acetylated too |
| `phenol_to_substituted_benzene_chndiazometh` (Me2SO4, NaOH) | amine N–H, ester | N-methylation, hydrolysis |

Two Mg edges also both fire on BrCH2–C6H4–Br (benzylic and aryl Grignard: two answers).

## C. Lower confidence (harsh or rare conditions; JEE rarely combines them)
NH3/Al2O3 633 K, conc. H2SO4 383 K, AgNO2, fuming H2SO4, NaN3 (Curtius), Zn/NaOH, Fischer esterification with CHO,
aq. NaOH ester hydrolysis with epoxide, CH3I (excess) with other groups: these have no scope at all today.

Still open after B (not approved, lower confidence): HBr edges with a 2° alcohol present; carbylamine with an
alkyl halide, ester or COCl present; PCl5 on methyl 4-hydroxybenzoate (ester and phenol edges both fire);
NaNO2/HCl with a phenol present; Reimer–Tiemann with COCl; dil. NaOH aldol with an ester; aq. NaOH with an epoxide.

## Not problems (the tool's comparison, checked)
NaI leaves another C–X (it is still C–X), aldol and Reimer–Tiemann leave CHO / OH (the product has one by nature),
SeO2 leaves a ketone (product is a keto-aldehyde), nitration / FC leave the ring, alkyne 1 equiv vs 2 equiv HBr
(different reagents), aryl acetate matched as Ar–O–R.
