# Concept-book coverage audit (2026-11-26)

The knowledge graphs use 47 % (organic), 44 % (inorganic) and 69 % (physical) of the concept book. Every unused entry
(`knowledge/graph_unmapped*.json`) was read by hand (Claude, after a code shortlist: `tools/audit_concept_coverage.py`,
`outputs/concept_coverage_audit.json`). A reaction missing from the graph is variety the pipeline can never produce.

## Physical — 82 unmapped

All qualitative facts (Tyndall effect, adsorption types, deviation from Raoult's law, Haber conditions ...). No formula is
missing. Nothing to add.

## Inorganic — 489 unmapped

Almost all are not reactions: comparisons (bond angles, boiling points, acidity, hydrolysis rates), structures, defects,
isomerism and ligand classes, metallurgy processes, alloys, periodic trends, salt-analysis procedures, quantum-number
rules. Of the specific reactions:

- already in the graph under other ids: NCl₃, SbCl₃, BiCl₃ hydrolysis (and others found by the code check: 15);
- product unknown to the species engine (cannot be asked without new engine data): HOCl, HOBr, [SbF₆]⁻, HgI₂,
  Ni(dmg)₂, PbCrO₄, PbSO₄, CaC₂O₄, I₂, NaH, NaOH, Mg₃N₂, MgO;
- wrong engine geometry: H₃B·NMe₃ (engine says trigonal planar; boron is tetrahedral) — not added;
- **added (approved)** as variants in `knowledge/inorg_condition_variants.json`, confirmed by the blind check:
  `cv_no3_cu` NO₃⁻ + Cu + conc. H₂SO₄ → NO₂; `cv_hgcl2_ki` HgCl₂ + excess KI → [HgI₄]²⁻;
  `cv_cro4_ba` CrO₄²⁻ + BaCl₂ → BaCrO₄.
- Not done (reviewer chose not to): engine data for Ni(dmg)₂, [SbF₆]⁻ and the H₃B·NMe₃ fix.

Checked while here: [Cu(NH₃)₄]SO₄·H₂O gets "tetrahedral" from the engine (JEE: square planar), but no question can ask
it (system facts drop the hydrate and skip shape for [Cu(NH₃)₄]²⁺; it is in no hidden-products row).

## Organic — 288 unmapped

Most are not new reactions: elimination stereochemistry (anti-periplanar cases, Hofmann/Saytzeff rules), carbocation
shifts, SN1/SN2 stereo variants, neighbouring-group participation, aromaticity, acidity and inductive/resonance
comparisons, nomenclature, degree of unsaturation, elemental analysis, carbohydrate and amino-acid tests.

**Status:** rows 1–8 built (commit be6ff83), rows 9–18 built in batch 2 (same day). All 18 have a rule, a graph
edge, a label, a scope, a golden case and a test.

**Missing reactions with no engine rule** (each needs an RDKit rule, a scope and a test before a graph edge). The trap
column is the existing reaction a student confuses it with — the engine's wrong turn.

| # | Reaction | Reagents / conditions | Trap against |
|---|---|---|---|
| 1 | Hydroboration–oxidation: alkene → anti-Markovnikov alcohol | BH₃·THF; H₂O₂, NaOH | acid hydration (Markovnikov) |
| 2 | Rosenmund: acid chloride → aldehyde | H₂, Pd/BaSO₄ | LiAlH₄ (alcohol) |
| 3 | Pinacol rearrangement: vicinal diol → ketone | conc. H₂SO₄ | which group migrates |
| 4 | Allylic chlorination: alkene → allyl chloride | Cl₂, 773 K | Cl₂/CCl₄ addition |
| 5 | Alcohol → symmetrical ether | conc. H₂SO₄, 413 K | alkene at 443 K |
| 6 | Grignard protonolysis: RMgX → RH / RD | H₂O / D₂O | Grignard + CO₂/HCHO |
| 7 | Sulfonate substitution: ROTs → RCN / RI / RN₃ | NaCN / NaI / NaN₃ | — (tosylate exists, nothing uses it) |
| 8 | Kolbe electrolysis: RCOONa → R–R | electrolysis | soda-lime decarboxylation (R–H) |
| 9 | Gabriel synthesis: RX → RNH₂ only | potassium phthalimide; then base | excess NH₃ (mixture) |
| 10 | Hofmann elimination: R–NMe₃⁺ OH⁻ → less substituted alkene | moist Ag₂O, heat | Saytzeff alkene |
| 11 | Alkyne trimerisation: ethyne → benzene | red-hot Fe tube, 873 K | — |
| 12 | Desulfonation: ArSO₃H → ArH | dil. H₂SO₄, steam, heat | — |
| 13 | Benzilic acid rearrangement: 1,2-diketone → α-hydroxy acid | NaOH, heat; H₃O⁺ | — |
| 14 | MnO₂: allylic/benzylic alcohol → aldehyde only | activated MnO₂ | KMnO₄ (acid) |
| 15 | Dry Ag₂O + RX → symmetrical ether | dry Ag₂O | moist Ag₂O (alcohol) |
| 16 | Isocyanide reduction → N-methyl secondary amine | H₂, Pt or LiAlH₄ | hydrolysis (primary amine) |
| 17 | Chloral → chloroform | NaOH (aq) | — |
| 18 | Adipic acid → cyclopentanone | heat (Ba(OH)₂) | — |
