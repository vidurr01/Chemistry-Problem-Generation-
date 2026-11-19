# ChangeLog

This file records every repository change. Newest entries go at the top. Each entry lists which files changed, what changed, why when useful, and any behaviour or configuration impact.

## 2026-11-19

### Organic question-first pipeline (same pattern as inorganic)
- `core/pipeline/org_qfirst.py` (new): draw → design → write → evaluate → `flow.judge` → save.
  - **draw**: a starting molecule from `core/engine/organic/pool.py` and a walk of 2–3 ruled edges, every step computed by `rules.apply`; kept only with at least 3 code-made distractors, one from a selectivity trap.
  - **options and key by code**: the final product, plus the products of one wrong turn (a step's selectivity trap carried through the later steps, a step ignored, stopping one step early). Printed as SMILES (a name could be wrong; a SMILES is the structure). The key is the letter of the code's product.
  - **design and write**: the shared designer plans the hidden intermediates and the trap; the writer writes the stem only (start compound by name, reagents in order, X/Y/Z), and code rejects a stem that does not name the start or shows a product.
- `OrganicAdapter` (`ADAPTERS["organic"]`, kind `org_qfirst`); `flow.run` dispatches to it, so `run_groundup_final.py --subject organic` runs. Organic has no level/design calibration yet, so those checks are off for it (per-subject calibrations).
- `rules.py`: AgNO2 refuses tertiary halides (SN1/E1, nitrite).
- `tests/test_org_qfirst.py` (3): computed draws with code options, stem checks and key, a whole run to a saved question with scripted models.

### Organic engine (RDKit), step 1: rules for the reaction edges
- `core/engine/organic/` (new): `mol.py` (canonical SMILES, `same`, formulas, `classes`: which graph nodes a molecule is in), `pool.py` (starting molecules with SMILES for every walkable node; the names already in `molecule_constructor.json` keep their formulas, checked by test), `react.py` (reaction SMARTS runner and the JEE selectivity rankings: Markovnikov, Saytzeff/Hofmann, EAS o/p vs meta on a monosubstituted ring), `rules.py` (one rule per reaction edge; each returns the product, co-products and traps = the products of the wrong selectivity), `edges.py` (edges with no rule: 23 concept/intermediate/polymer edges, 32 suspect edges).
- 144 of 199 edges have a rule. `rules.apply(edge, smiles)` refuses a molecule the edge does not apply to, one with no single major product (two equally favoured regioisomers), and one whose product falls outside the edge's end node (Clemmensen on benzaldehyde gives toluene, not an alkane).
- Generic reagents are fixed to the simplest member (CH3COCl, CH3OH, CH3NH2, CH3I, HBr, Br2) and listed in `rules.REAGENT_USED` so the question can state them. Phenols and anilines are refused by the generic EAS rules (they tribrominate, oxidise or protonate).
- `docs/organic_suspect_edges.md`: the 32 suspect edges with proposed fixes, for the user's approval. They have no rule until approved.
- `tools/audit_organic.py`: every rule on every pool molecule of its start node; 639 products, 0 crashes, every rule works on at least one molecule. `tests/test_engine_organic.py` (15). RDKit 2026.09.2 installed in `.venv`.

### Inorganic: wider species properties (questions were shallow)
- `core/engine/inorganic/species.py`: three new property families, all computed by rule, none typed in:
  - **Oxoacids and oxoanions** with one central atom (H2SO4, H3PO3, HNO2, H3BO3, HCO3⁻): `central_shape`, `central_hybridisation`, `basicity`. Each O–H is modelled as a single-bonded group; P keeps its P–H bonds (5-valent P: H3PO3 one, H3PO2 two, so dibasic and monobasic); boric acid is monobasic (Lewis acid). Peroxo acids (H2SO5) and organic acids (HCOOH) are refused.
  - **Salts' ions** (KClO3, CaSO4·2H2O, Ca(HCO3)2, NH4NO3, HBF4): `anion_shape`, `anion_hybridisation`, `cation_shape`, `cation_hybridisation`.
  - **3d metal ions** in simple ions and salts (Fe²⁺, FeCl3, Cr2(SO4)3, K2MnO4, CuCl): `metal_ion_d_electrons`, `metal_ion_unpaired` (free ion, Hund), `metal_ion_magnetism`, `metal_ion_spin_only_moment`. Averaged states (Fe3O4) and 4d/5d metals are not computed.
- Fixed: HNO2 (and other oxoacids) got a plain-VSEPR `shape` with the H bonded to the central atom (HNO2 "trigonal planar"); that shape is now dropped for oxoacids.
- Graph species with a property beyond oxidation state: 79 → 191 of 354 (any property: 236 → 269).
- `tests/test_engine_inorganic.py`: `SpeciesWider` (5).

### Calibrations are per subject
- Every calibration loader hard-coded `knowledge/*_calibration_physical.json`, so the inorganic run judged its designs by physical's design cut-offs (`qf_design.design_problems`) and labelled `advanced` vs `mains_hard` by physical's level floor (`flow._judge` → `qf_checks._level_floor`). The live inorganic question GEN_20261119T135749 was labelled with physical's floor.
- `core/pipeline/qf_draw.py`: `calibration_path(kind, subject)` → `knowledge/{kind}_calibration_{subject}.json`; a missing file prints a note once per run. `_fit_floor`, `qf_checks._coherence_cuts`, `coherence_problems`, `_level_floor`, `level_problem` and `qf_design.design_problems` take `subject` (default `physical`; physical behaviour unchanged). `best_draw` passes `adapter.subject`; `inorg_qfirst.run` and `flow._judge` pass theirs.
- A subject with no calibration file gets no calibrated check (design check off, level label `advanced_or_mains_hard`, generic coherence cut-off), never another subject's numbers. Inorganic has none yet.
- `tools/calibrate_level.py --subject {physical,inorganic,organic}`: scores that subject's real numerical questions (inorganic: 33 Main, 43 Advanced) and writes `level_calibration_{subject}.json`. `calibrate_coherence.py` and `calibrate_design.py` stay physical-only: their bad examples and reverse designs are physical and need the user's review for other subjects.
- `tests/test_inorg_qfirst.py`: `CalibrationPerSubject` (3). Test patches of the loaders accept the new argument. 478 tests pass.
- Inorganic level calibrated (`knowledge/level_calibration_inorganic.json`, log `outputs/calib_level_inorganic.log`): floor 1.59 (80 % of 43 real Advanced reach it, 33 % of 33 real Main do); physical's floor is 1.16, so the old borrowing was far too lenient for inorganic. GEN_20261119T135749 scores 1.62: still `advanced`, just above the floor. Two runs (the first crashed printing "≥" to a cp1252 pipe before writing; `calibrate_level.py` now reconfigures stdout to UTF-8): floors 1.61 and 1.59. $0.0032 ≈ ₹0.28 at ₹88/$.

### First live inorganic run
- $0.0503 ≈ ₹4.4: draw 1 (MgCl₂·6H₂O → MgCl₂ → Mg, msq) too easy (Granite solved); draw 2 (B₂H₆ → H₃BO₃ → HBF₄, msq, X and Y hidden) accepted as GEN_20261119T135749, key AB computed by code (B is +3 in both; hand check agrees), Granite failed (A), GLM solved → advanced (Jev level 1.62), Granite solved after the insight hint. The pipeline works end to end. The question is shallow: for H₃BO₃ and HBF₄ code can compute only oxidation states (VSEPR does not take OH groups or the HBF₄ salt form), so all four options were about one property.

### Inorganic question-first pipeline (same pattern as physical)
- `core/pipeline/inorg_qfirst.py` (new): draw → design → write → evaluate → `flow.judge` → save, as physical's `qfirst.run`. Only two parts differ from physical:
  - **draw**: a random connected walk of 2–4 reactions in the inorganic graph, kept when a species formed has a property code can compute;
  - **the answer key ("coder")**: the writer gives every option or item as a claim (species or hidden label, property key, value); code decides each with `core/engine/inorganic` and builds the key (letters, or an integer for count questions). Unreadable claims go back to the writer once with the exact problems.
- The designer (models.DESIGNER, cut-off designs finished, Jev's design check) plans which species are hidden, what is told, the format (msq, mcq_correct, mcq_incorrect, count, identify) and the trap. The writer may not name a hidden species in the stem (checked by code).
- `core/engine/inorganic/species.py` (new): graph ids → formula and charge (the graph writes `C2O42-` for C₂O₄²⁻, `NO2-` for NO₂⁻), complex charge from counter-ions (K₄[Fe(CN)₆] → [Fe(CN)₆]⁴⁻), `askable` (every computable property of a species: 236 of 354 graph species have one), `compare` / `check_claim`.
- Wiring: `InorganicAdapter` (`ADAPTERS["inorganic"]`, kind `inorg_qfirst`; fact questions stay available with `--kind facts`), `flow.run` dispatches to it, `flow.insight_hint` uses a flow's own hint, `build_record` keeps options from any run that supplies them. Parked inorganic questions cannot be recomputed yet: they go on hold, not lost.
- `tests/test_inorg_qfirst.py` (5): connected askable draws; graph charges; claims true/false by code, count answers, format rules, hidden species named in the stem; a whole run to a saved question with scripted models. A first version of the run test wrote its fake question into the real duplicate store (the store's default path was bound before the temporary path was patched): the entry was removed and the test fixed. 475 tests pass; physical engine audit 0 flags.

### Inorganic engine, step 2: fact questions wired into the pipeline
- `core/engine/inorganic/tables.py` (new): 12 fact tables (complex magnetism, unpaired electrons, hybridisation, geometry, spin-only moment; molecular shape, hybridisation, polarity; MO bond order and magnetism; geometrical and stereo isomers) over 27 complexes, 36 molecules and ions, 19 diatomics and 10 isomer sets. Every value is computed by `properties.py`; nothing is typed in. [Cu(NH₃)₄]²⁺ is left out (JEE calls it square planar, the d⁸ rule does not).
- `core/pipeline/adapters.py`: `InorganicFactsAdapter` (the physical fact adapter with the inorganic tables; `FACT_ADAPTERS["inorganic"]`); candidates carry their table (`_source`). `core/pipeline/flow.py` `_fact_source` reads it (physical candidates parked earlier still resolve). `run_groundup_final.py`: a subject with fact questions only (inorganic) makes a fact question on every run instead of stopping with "not wired".
- Physical unchanged: its fact adapter loads the same table, and the start-up switch never applies to it. `tests/test_pipeline_offline.py`: `InorganicFactQuestions` (an inorganic run end to end with scripted models). 470 tests pass; engine audit 0 flags.

### Inorganic engine, step 1: property functions
- `core/engine/inorganic/properties.py` (new), exact and offline, refusing (EngineError) what they cannot decide:
  - `vsepr(species)`: steric number, lone pairs, shape, hybridisation, polarity of a main-group molecule or discrete ion (central atom found by code; odd-electron species such as NO₂; ionic and transition-metal solids refused).
  - `mo_diatomic(species)`: MO configuration, bond order, unpaired electrons, magnetism for H–Ne diatomics, ions and CO, NO, CN⁻ (s-p mixing up to 14 electrons).
  - `parse_complex` / `complex_info("[Fe(CN)6]4-")`: oxidation state, d electrons, geometry (square planar for d⁸ with a strong field, Pd²⁺, Pt²⁺, Au³⁺), high or low spin by JEE rules (strong-field ligands; NH₃ and H₂O on M³⁺/Co³⁺; 4d and 5d always low spin; [CoF₆]³⁻ high spin), unpaired electrons, spin-only moment, CFSE, hybridisation.
  - `count_isomers(geometry, ligands)`: geometric and stereo isomers by enumerating every arrangement on the octahedron or square under its rotation (and reflection) group; chelates on cis positions.
  - `oxidation_state(formula, element)`: average oxidation state by the usual rules (Fe₃O₄ 8/3, S₄O₆²⁻ 5/2).
- `tests/test_engine_inorganic.py` (11 tests, ~90 cases): 31 VSEPR shapes, the book's MO diatomics and 12 ions, 20 complexes, 9 octahedral and 4 square-planar/tetrahedral isomer sets ([Ma₂b₂cd] 6 geometric / 8 stereo, [Mabcdef] 15 / 30), oxidation states. Against every concept-book shape fact naming one species: 49 of 49 molecules agree; 3 solids (fluorite, rutile, cristobalite) are now refused.

### Live run 9 (last physical run of the day)
- $0.1547 ≈ ₹13.6, cap $0.45: draw 1 and draw 2 (Atomic Structure) designs rejected by Jev (glued; invented relation / arbitrary condition); draw 3 (Ionic Equilibrium, two-state difference) was too easy (Granite 8.22 for 8.185); Jev picked `plugin_order`, the twist became `inverse`, the redesign was accepted as GEN_20261119T115635: H₂A concentration from the pH of NaHA (0.166 M, pH 8.41) and of the acid (pH 2.62); key 0.0253 M, hand check 0.02530 (exact, c = [H⁺]²/K_a1 + [H⁺]; the usual approximation gives 0.0229, 10 % off: α ≈ 9.5 %). Granite 1 M, GLM 110 M (objected), MiniMax 0.0253 → advanced_medium; GLM solved after the insight hint.

### Two guards against a wrong key (code only)
- `core/engine/sandbox.py` `check_code`: a program may not round or truncate a computed value (`round`, `int`, `math.floor/ceil/trunc` on anything but a written number); the formulas' own checks (a whole n, a fraction in 0–1) then catch impossible stated data, and the number step picks other values or the draw ends. The coder prompts say so. Why: n = round(2.59) = 3 turned impossible data into the wrong key of GEN_20261119T110902.
- `core/pipeline/flow.py` `_consensus_against_key`: when no ladder model solves a question, every model called (at least 2) gave the same answer within 2 %, and that answer is not one of the engine's own trap answers, the question is not accepted: it goes to the new review queue `ladder_consensus` (`core/pipeline/queues.py`; `tools/results.py queue`) and the run draws again. Replayed on the 21 questions judged since October: it holds the two with a wrong key (14 Oct, an inverted engine step; 19 Nov, the rounded n) and nothing else; the flask question (models 3 % apart) is not held.
- Tests: `NoRoundingInPrograms`, `LadderConsensus`. 457 tests pass.
- `tools/results.py reject GEN_20261119T110902` (the author): removed from `results/`, recorded in `results/rejected.json` with its reason; runs no longer count it as accepted.

### One typical mistake is enough
- `core/pipeline/qf_checks.py`: `MIN_TRAPS = 1` (was 2, the author's decision). At 2 it was the commonest way a draw died (3 of 5 draws in live run 8), it ignores the designer's conceptual trap, and some real JEE Advanced questions cannot meet it. Difficulty stays guarded by Jev's level check and the ladder. 453 tests pass.
- Live run 8 ($0.2136 ≈ ₹18.8, run before this change): accepted GEN_20261119T110902 as hard_advanced, but its key is WRONG. A hydrogen-like ion with KE 12.7 eV in the excited state emits a 72.7 eV photon to the ground state; the ionisation energy from the stated data is 85.4 eV, which all three ladder models gave (GLM also objected). The coder's program rounded n = round(√(85.4/12.7)) = 3 and recomputed the photon (75.91 eV), returning 88.61. The numbers code picked from the writer's ranges admit no whole n and Z (n² = 6.72, Z² = 6.28): the whole-number problem again, now hidden by a round() in the program. Nothing changed for it yet.

### One draft per draw
- `core/pipeline/qf_writer.py`: `WRITE_TRIES = 1`. Over 21 draws that reached the writer, 9 passed on the first draft, 12 failed all three, none was rescued by a rewrite (the run of 2026-11-19 added one more: an Atomic Structure draw failed three drafts on the same whole-number problem). A rejected draft now means a new draw. The too-easy refinement keeps its rounds.
- `core/pipeline/qfirst.py`: `UNREADABLE_RETRIES = 2`: a writer reply that cannot be read, or a blank-format slip found by code (numbers not written as `[[blanks]]`, with an exact fix), is asked again without using up the draft, so a design already paid for (~₹3.8) is not thrown away for a technical failure.
- Live run 7 ($0.1705 ≈ ₹15.0, cap $0.45): draw 1 (Atomic Structure) died on the whole-number problem in all three drafts; draw 2 the writer called impossible; draw 3 accepted GEN_20261119T104117 (galvanic cell precipitating M(OH)₂; −log K_sp = 26.86, hand check 26.86); Granite 1.84 failed, GLM solved → `advanced` (Jev level 2.65). First end-to-end question on the Granite → GLM → MiniMax ladder.
- `tests/test_qfirst.py`: `OneDraftPerDraw`. 453 tests pass.

### Run cap $0.45
- `run_groundup_final.py`: `--max-run-spend` default $0.45 (about ₹40 at ₹88/$, room for 3–4 draws), was $0.12, which one long design (~₹11) used up. The cap is checked between stages, so a run can still overshoot by one designer call. Flow.md updated.

### Live run 6 (new ladder, not reached)
- $0.1307 ≈ ₹11.5, no question: 6 fit batches under the floor, then one draw [391, 336, 234] (electrolysis). The design was cut off at the output limit and finished by `finish_design` (first live use: it worked); Jev then rejected it as an invented relation (37 %): it asked for "the electrical energy consumed for silver alone" as Q_Ag × V in a Cu/Ag co-deposition, a quantity with no physical meaning. The designer cost ~₹11.4 (cut-off call + finish), so the $0.12 cap allowed only this draw. The ladder was not reached.

### Ladder bottom step: Granite 4.2 8B (was Llama 3.3 70B)
- `core/models.py`: `LADDER` = Granite 4.2 8B (IBM, used nowhere else) → GLM-5.3-Flash → MiniMax M3 (the author: Llama "never a good option, it doesn't work": it never called the calculator unforced, wrote programs, replied empty, failed 54 % of easy Mains). README (family list IBM/Z.ai/MiniMax), Flow.md, PIPELINE.md, the overview page follow. 452 tests pass. Not yet run live; Granite and MiniMax are not in the airouter name tables, so a run that falls back to airouter (out of OpenRouter credit) has not been checked for them.

### Bottom-rung calibration with the forced calculator; one tool call per turn
- Reran the separation calibration (`calibration/anchor_calibration.py --council`, forced calculator) for Granite 4.2 8B and Llama 3.3 70B; the old results are in `calibration/backup_20261119_no_calculator/` (₹27.2 at ₹88/$; Granite's Advanced run stopped at 48 of 49 when a session ended). `ladder_separation.py`: Granite fails easy Mains 32.1 %, Advanced-level 52.2 % (gap 20.1, $0.00025 a question, 1 no-answer); Llama fails 53.6 % / 85.3 % (gap 31.7, $0.00298, 11 no-answers). Without the calculator (14 Oct): Granite 25.0 / 64.7 (39.7), Llama 28.6 / 66.2 (37.6).
- Llama's 11 no-answers were a bug: some hosts of Llama 3.3 on OpenRouter (AkashML, CoreWeave) refuse a turn with several tool calls ("This model only supports single tool-calls at once!"); in a live run the question would park. `core/models.py`: tool calls are made one per turn (`parallel_tool_calls=False`), and a turn that still has several keeps only its first. `tests/test_models.py`: `test_one_tool_call_per_turn`. 452 tests pass. Llama's numbers above include those failures, so they overstate how often it fails.

### Ladder top step: MiniMax M3 (was GPT-6 Luna)
- `core/models.py`: `LADDER` = Llama 3.3 70B → GLM-5.3-Flash → MiniMax M3; `DIFFICULTY_LABELS["minimax-m3"] = "advanced_medium"`. Why: Luna also writes the key (the coder), so a Luna "solve" was the key agreeing with itself (the PCl₅ question: both took van 't Hoff on K_c). Luna stays the coder. MiniMax is a family used nowhere else. README (the family list no longer has a known overlap), Flow.md, PIPELINE.md, the overview page follow. 451 tests pass. Not yet run live; MiniMax was measured on OpenRouter only.

### Top-rung comparison: MiniMax M3 against Qwen3.5-35B-A3B
- 10 real JEE Advanced physical numericals (same 10, seed 19), the pipeline's solver call with the forced calculator, graded with the fixed grader (₹42.7 at ₹88/$): MiniMax M3 9/10, ₹1.05 a question; Qwen3.5-35B-A3B 9/10, ₹3.22 a question. Both used the calculator on 10/10. MiniMax missed 2022P2_Q1 (PbSO₄ with HSO₄⁻; 3.2 % of candidates got full marks); Qwen missed 2024P2_Q11 (radioactive dating; 50.9 %). Nothing changed in the roster yet.

### Calibration grader reads fractions
- `calibration/anchor_calibration.py` `to_float`: reads an answer the way the pipeline does (`core.answers.numeric_value`: fractions, powers of ten, approximate signs), else the last number token as before. It took only the last token, so "11/51" (0.2157, right for a key of 0.22) was read as 51 and graded wrong (found in the MiniMax / Qwen comparison, 2021P2_Q7). The saved result files already held those gradings as right (`--regrade`: 0 changed). `tests/test_grading_stress.py`: `CalibrationGrader`.

### Ladder solvers must call the calculator
- `core/models.py`: `FORCE_FIRST_TOOL_CALL = ("council",)`: every ladder solve (and hint re-solve) sends `tool_choice="required"` on its first turn and `"auto"` after, so the calculator is used whatever the model. A provider that refuses `"required"` (400/404/422) is asked unforced and says so. Why: unforced, Llama called it 0/5, Granite and Qwen3.5 1/2, GLM 1/3; forced, Llama 5/5.
- `tests/test_models.py`: `ForcedCalculator` (required then auto; refused → unforced). 450 tests pass.

### Difficulty labels one step lower (the author's rule)
- `core/models.py` `DIFFICULTY_LABELS`: Luna (top step) first to solve → `advanced_medium` (was `hard_advanced`); no step solves → `hard_advanced` (was `frontier`); GLM unchanged (`advanced`, or `mains_hard` by Jev's level check). "Hard advanced" now means even the top step failed. `flow.judge` default, README, Flow.md, the overview page and two tests follow. Records saved before keep their old labels.
- Calculator probes (N₂O₄ question, `tool_choice=auto`, no nudge, 12000-token cap, so not the pipeline's own call): Luna called it 3/3 and was right 3/3 (₹0.76); GLM 1/3, two empty replies, right 0/3 (₹1.06); Qwen3.5-35B-A3B 3/5, three empty replies, right 1/5 (₹13.61); MiniMax M3 3/5, two empty, right 2/5 (₹4.41); Granite 4.2 8B two tries, both empty (the probe stopped there). Empty replies may come from the probe's cap and missing nudge.
- The same through the pipeline's own solver call (`stages._solve`: 32000-token cap, nudges, retries), 2 tries each (₹14.60): every model gave an answer. Qwen3.5-35B-A3B right 2/2, calculator calls 28 and 0 (₹7.29); MiniMax M3 right 2/2, calls 7 and 17, after several empty replies were nudged (₹7.08); Granite 4.2 8B wrong 2/2 (0.752, 0.751), calls 1 and 0 (₹0.03); GLM-5.3-Flash wrong 2/2 (0.255, 1.31), calls 5 and 6 (₹0.19). Luna, earlier: right 3/3, calls every time, ~₹0.25 a try.

### Live run 5; Llama and the calculator; the coder and the top ladder step are one model
- Live run ($0.0491 ≈ ₹4.3): draw [156, 154, 163], the designer chose `inverse`; accepted GEN_20261119T063151 (PCl₅: ΔH° of PCl₃ + Cl₂ ⇌ PCl₅ from K_c at 471 K and the total pressure at 539 K), key −81.58 kJ mol⁻¹; Llama −134, GLM +81.6, Luna −81.6 → hard_advanced. Hand check: −81.58 is van 't Hoff on K_c, which gives ΔU°; on K_p (ΔH°) it is −85.76 (ΔH° = ΔU° + Δn_g RT, Δn_g = −1), 5 % away. Luna wrote the key and Luna solved it the same way. Not changed: for the author's review.
- `core/models.py`: the calculator log line names the model.
- Probe (₹1.28, the N₂O₄ question, 5 tries each): Llama called the calculator 0/5 with today's prompt and 0/5 when told it MUST; forced to call it on its first turn (`tool_choice=required`) it called it 5–9 times every time. Right answers 0/5 in all three: its failures there are chemistry, not arithmetic.

### The designer may leave out one formula
- Funnel of the 28 draws in the current flow (both fit A/B runs and the live runs of 2026-11-19, no new spend): 7 finished questions (25 %); 7 "impossible", 7 designs rejected by Jev (glued / invented), 5 lost after 3 writer drafts, 2 stopped by the cap. Half died at design, after the designer (₹2–8 a call) was paid; 4-formula sets died there 60 % of the time, 3-formula sets 46 %.
- `core/pipeline/qf_design.py`: with 4 or 5 formulas drawn (`n_formulas`), the designer may leave ONE out that cannot belong to the same system (`drop_block`, reply field `"drop"`, validated: never with 3, never a number outside the set). `core/pipeline/qfirst.py`: the left-out formula is removed before the design checks and the writer (`formula_left_out` on the Blackboard); the draw stays random and never goes below 3.
- `tests/test_qfirst.py`: `test_the_designer_may_leave_out_one_of_four_formulas`, `test_a_left_out_formula_is_gone_before_writing`. 448 tests pass.

### A cut-off design is finished, not lost
- Third live run ($0.1837 ≈ ₹16.2, nothing accepted): draw 1's design was rejected by Jev (glued sub-problems); draw 2's design reply hit the 8000-token output limit after ~7000 tokens of thinking, with 1202 characters of the design written ($0.09 lost), and the run stopped at its cap before the ladder. The cap is checked only between stages, so one designer call can overshoot it.
- `core/llm.py`: `CutOffError(ValueError)` for a reply cut off at the output limit (`retry_cut_off=False`), carrying the text written (`partial`) and the thinking when the provider returned it (`reasoning`).
- `core/pipeline/qf_design.py`: `finish_design`: on a cut-off design, one call (thinking "low", `FINISH_CAP` = 4000 tokens) gets the original prompt, the partial JSON and the end of the thinking (`THOUGHT_CHARS`), and returns the complete design. If that fails too, the run writes without a design, as before.
- `tests/test_qfirst.py`: `test_a_cut_off_design_is_finished_not_lost`, `test_a_cut_off_reply_carries_what_was_written`. 446 tests pass.

### No mismatch verifier: ladder answers graded by code only (the author's decision)
- `core/pipeline/flow.py`: `_grade` is code only: solved = `answer_matches` (`_code_match`; an answer code cannot read is not matched). `judge` no longer calls a verifier: no "reference wrong" overrule or `engine_wrong` / `objection_unresolved` drops (objections stay in the record), no clarification or knowledge hints, no re-check after a hint; every failed step gets the code-written insight hint, graded by code, and the question is accepted. Removed `_verify`, `_text_match`, `_hint_solved`, `knowledge_hint`.
- `core/pipeline/stages.py`: `verify_member` and `clarification_hint` removed. `core/models.py`: `VERIFIER` removed; the same model stays as `SOLUTION_CHECKER` (checks the written solution after acceptance). `tools/check_models.py`, `tools/regress.py` (no verifier stage) follow.
- Why: the verifier called the flask question's right key wrong (50.31 mL) and the question was dropped instead of reworded; the author judged it too weak, the coder strong enough for the key, and a right number by wrong reasoning rare on a hard question.
- Tests: verifier tests removed (`VerifierReply`, reference-wrong overrule, verifier parks); grading tables updated (a matching answer is solved whatever a diagnosis says; run 5's −190.28 for −192.2 now counts). 444 tests pass. `README.md`, `docs/Flow.md`, `docs/PIPELINE.md`, `docs/pipeline_overview.html`, `docs/Decisions.md` updated.

### Live run: the parked flask question; an empty ladder reply; on hold instead of dropped
- Live run (`--kind chains`, $0.0112 ≈ ₹1): PENDING_20261118T183052 (key re-solved to 50.31 mL) was judged: Llama 22.9 mL (failed), GLM 54.6 mL (failed: the old key, the design's trap), Luna 50.3 mL (solved) → hard_advanced. Then Llama's hint re-solve wrote a program, was told, and answered with nothing; the call failed and the question was parked again (1 recheck failure), so no new draw ran.
- `core/models.py`: an empty final reply after calculator calls is now told too (`EMPTY_NUDGE`, same `FORMAT_NUDGES` budget, no empty assistant turn); before, it ended the call at once. `tests/test_models.py`: `test_a_program_then_an_empty_reply_is_still_answered`.
- Why Llama wrote programs: Llama 3.x's chat template adds "Environment: ipython" to the system prompt when tools are passed. Probe on the flask question, 5 tries each (₹1.61): with the calculator 0/5 usable (4 programs, 1 loop of 12 calls); without it 4/5 JSON; with the calculator and a "no Python interpreter, use calculate" line 5/5 JSON (no calculator calls; Llama did the arithmetic itself). `core/pipeline/stages.py`: `NO_CODE` is added to the solver system prompt on every solve that offers the calculator. `tests/test_models.py`: `SolverPrompt`. 448 tests pass.
- Second live run ($0.0562 ≈ ₹4.9): no Llama crash (one empty reply and one cut-off JSON were each answered after a nudge). The flask question was re-judged: Llama 56.3, GLM 54.6, Luna 54.6 mL, all taking the whole vessel as the gas volume; the verifier called the 50.31 mL key wrong, so it went to `outputs/queue_engine_wrong_physical.json` (kept, not lost). The key is right physically, but the question never says the gas occupies only the space left by the liquid. New draw [152, 154, 135, 137]: the designer chose `inverse`; accepted GEN_20261119T005804 (N₂O₄ ⇌ 2NO₂ from the maximum non-PV work, 0.431 mol, hand check 0.4311), hard_advanced (Luna only).
- `run_groundup_final.py`: a parked question is never dropped. After `MAX_RECHECK_FAILURES` failed rechecks, or when it cannot be recomputed, or when it is in the pre-engine format, it moves whole to `outputs/on_hold_questions_<subject>.json` with `hold_reason` (`_hold`, `on_hold_file`); runs carry on without it. `--rerun-held` moves every held question back to be judged first (failure count reset), to re-run them or to check that a code change fixed their error. A run says how many are on hold. `tests/test_pipeline_offline.py`: `test_parked_question_that_keeps_failing_is_put_on_hold` (held whole, then accepted with `--rerun-held`). 447 tests pass.

### The designer chooses the twist
- `core/pipeline/qf_design.py`: `design_question(..., twist=None)` shows the designer every twist with one level example each (`twist_block`) and asks it to choose the one that lets these formulas make the hardest real question; the design carries `"twist"`. A reply without a valid twist keeps the design (₹1–5 already paid) and the caller picks one at random. A fixed twist works as before.
- `core/pipeline/qfirst.py`: `run()` no longer draws the twist; `write_and_solve` lets the designer choose when none is fixed, notes it (`twist` on the Blackboard) and returns it on the candidate. A refinement that changes the twist still fixes it for the redesign. `tools/step_by_step.py` keeps its own twist.
- Why: a random twist chosen before the formulas were seen killed draws (a "condition" twist on pure Bohr-orbit formulas, fit A/B run of 2026-11-19). To watch: whether the designer always picks the same, easiest twist (Blackboard `twist` notes).
- `tests/test_qfirst.py`: `test_the_designer_chooses_the_twist_and_the_writer_uses_it`, `test_a_design_without_a_twist_is_kept_and_a_random_twist_used`. 446 tests pass.

### Jev formula-fit A/B test; steps 65/66 accept the value they ask for
- `tools/fit_ab.py` (new): draws with Jev's fit check off (first random set) and on (as the pipeline), interleaved, each taken to a finished question (no ladder, nothing saved). Results in `outputs/fit_ab/`.
- Live, 5 per arm (₹34.3 at ₹88/$): off built 2/5, on built 1/5; ₹17.1 each arm. Jev's score did not predict success (built at 34 %, 43 %, 57 %; failed at 65 %, 62 %, 59 %, 53 %). Too few draws to be sure; no sign that the check helps.
- Second run, 5 per arm (₹34.3): off built 0/5 (₹20.7), on 2/5 (₹13.6). Both runs together: off 2/10 (₹37.8, ₹18.9 per built question), on 3/10 (₹30.7, ₹10.2 per built question). Every off set Jev scored under 30 % died (4 of 4); above that its score did not separate built from failed. Most draws in both arms (15 of 20) died as "impossible" at the designer or writer.
- Tried and removed: drawing the next formula weighted by the rarity of the quantity it shares (α, E° over moles, ΔH). Jev on 100 draws each: old median 0.34 (10 over the floor), weighted 0.31 (14 over), real JEE 0.66; no real gain (₹0.46). Neither the weighting nor its comparison script is kept.
- Tried and removed (the author keeps the current draw): situation-first test, a chapter or a BRIDGES pair → Gemini 3.7 Flash invents one system and lists the engine quantities it involves → code picks 3–5 connected formulas among them → Jev scores. 20 situations, ₹10.1: 11 gave a formula set, Jev median 0.38 (2 of 11 over the floor) against 0.34 for random draws and 0.66 for real JEE. The systems were real but exotic (cryogenic ion trap, Burnett apparatus), and code still picked the formulas at random among the matching ones.
- Bug found by it, `core/engine/sandbox.py`: steps 65/66 (photon energy, wavelength) compute `electron_energy` from Z. Left out, the error asked for `electron_energy`; given, it was refused as an unknown input ("it takes ['n', 'lower_level']", Z not named). The coder went back and forth until 2 of the 10 draws died. A derived value is now accepted as an input (also by `find()`), the refusal names it and its params, and `library_doc` marks it REQUIRED (give it or Z).
- `tests/test_qfirst.py`: `FindWholeNumber.test_a_derived_input_may_be_given_itself`. 444 tests pass; engine audit 0 flags.

### solve_for finds whole-number unknowns
- `core/engine/sandbox.py`: when bisection fails because a step needs a whole number (n, Z, l, a line count), `solve_for` tries the whole numbers in [lo, hi] (`_whole_root`, at most `WHOLE_SCAN` = 200): f(n) zero, or under 1 % of the next best (rounded data). Other failures are unchanged. `find()` already did this (2026-11-17); `solve_for` did not.
- Why: run of 2026-11-15, an H-spectrum question (6 lines, smallest photon 0.306 eV): every program bisected n to 2.0000000000000004, steps 68/69 refused it, 9 programs failed and the question was dropped.
- `tests/test_qfirst.py`: `FindWholeNumber.test_solve_for_gives_a_whole_number_unknown` (n₁ = 2; no whole number for 0.5 eV). 443 tests pass.

### The coder sees the design
- `core/pipeline/qf_coder.py`: `design_block()`; `write_blank_program` and `solver_program` take `design` and show the coder its situation, route, the point a careful solver must notice and the typical mistake its program must not make. `qf_numbers.numbers_for`, `qfirst.write_and_solve` and `tools/step_by_step.py solve` pass it on.
- Why: the parked question PENDING_20261118T183052 (Mg + NaHSO₄ in a rigid flask) has a wrong key, 54.57 mL against 50.3 mL. The coder saw only the question, took the gas volume as the whole flask, and so made the very mistake the design named (the liquid takes up part of the flask).
- `tests/test_qfirst.py`: `test_the_coder_sees_the_design_route_and_trap`. 442 tests pass.
- `outputs/pending_questions_physical.json`: PENDING_20261118T183052 re-solved live by the coder with the design shown (one call, $0.0007): gas volume = V_flask − V_sol, answer 50.31 mL (hand check 50.31). The old program is kept as `qfirst.old_code_wrong_key`; `key_resolved` says why.

### Formula-fit floor: the calibrated 0.504
- `core/pipeline/qf_draw.py`: `FIT_FLOOR = None`, so the floor is read from `knowledge/fit_calibration_physical.json` (0.504, the 20th percentile of real JEE Advanced sets). The hard-coded 0.60 turned away 18 of 53 real sets (5 of 10 real 3-formula sets) and passed 2 of 60 random draws; a run drew 7 batches in a row under it. At 0.504: 42 of 53 real sets and 9 of 60 random draws pass (about 7 sets a draw).
- `tests/test_qfirst.py`: `FitFloor.test_the_floor_is_the_calibrated_one`.

### Ladder solver that answers with a program is told so
- `core/models.py`: a final reply after calculator calls that is not JSON is answered in the same conversation (`FORMAT_NUDGE`: no code, use the calculate tool, reply with only the JSON), up to `FORMAT_NUDGES` = 2 times, before the fresh retries. Llama 3.3 70B wrote a Python program three times on one question (run of 2026-11-18, parked as PENDING_20261118T183052); started afresh it repeated it; told so, it answered (55.8 mL against the engine's 54.57).
- `tests/test_models.py` patched `core.llm._log_unparseable`, but `core.models` holds its own reference: the tests wrote 11 fake replies into `outputs/unparseable_replies.jsonl`. Patched where it is used; the 11 records were removed.

### Rate constant per the reaction (JEE's convention)
- `core/engine/physical/kinetics.py`, step 208 (k from pressures): optional input `reactant_coefficient` a (default 1: every chain as before); k = (1/(a t)) ln(P₀/P_A), since JEE defines k for the reaction, rate = −(1/a) d[A]/dt. New trap `coefficient_ignored`. Real question 2019P2_Q13 (2N₂O₅): 2.30, as the official answer (4.605 before).
- `core/engine/sandbox.py`: an optional input with a plain default reads "(optional: if omitted it is 1)".
- `tests/test_engine_physical.py`: `Kinetics.test_rate_constant_from_pressures_and_the_jee_convention`.

### Coder prompt: two rules that caused wrong results
- `core/pipeline/qf_coder.py` (program_for path): "every value the question states must be used" made the coder force "log 2 = 0.30" into a right pH (10.02 → 10.62, 2022P1_Q3). Now: use the values the solution needs; leave out values given for hand arithmetic and constants the steps hold; never add a value only to have used it.
- `core/engine/sandbox.py`: an input's range reads "usual values lo–hi, not a limit: any value the question gives is accepted" (was "typically lo–hi"), and `lo=` / `hi=` are left out of the engine source shown to the coder. Both read as limits: the coder refused a solution density of 0.656 g/mL (2014P1_Q40). Nothing enforces them.

### Real-JEE coder test set curated
- `tools/calibrate_coder.py`: `EXCLUDED` (5 questions, with reasons: 3 whose figure, table or mechanism is missing from the text; 2017P1_Q26 and 2017P1_Q27, whose stored answer does not follow from the stored text) and `ADAPTED` (2018P2_Q10 and 2023P1_Q9 restated with the engine's R; answers −14.23 and 102.6). `data/jee_advanced/` is unchanged (eight other tools read it). `PAPER_SET` pins the coder table's 8 questions as the default set.
- Luna on all 44 usable questions: 44/44 after the fixes above (39/49 before; results in `knowledge/coder_calibration_physical_all49.json`). `tests/test_coder_test_set.py`.

## 2026-11-18

### Code review fixes
- `core/engine/sandbox.py`: frame, traceback, code-object and closure attributes (`gi_`, `cr_`, `ag_`, `f_`, `tb_`, `co_` prefixes, `cell_contents`) and `format` / `format_map` are refused by `check_code`: a generator's frame reached the module's builtins (`open`, `exec`).
- `run_groundup_final.py`: a parked question whose recheck fails `MAX_RECHECK_FAILURES` = 3 times is dropped (whole, into the attempt log); it stopped every later run and batch. Parked and crashed runs now save their Blackboard to `outputs/runs/` too.
- `core/models.py`: the calculator computes powers in floating point and caps `factorial` at 170 (`9**9**9` hung the tool loop); every call that gets a 402 moves to airouter (only the first did); calculator-tool calls get retries, re-asks and the router switch; `key_is_set` checks the key of the router the model goes to.
- `core/pipeline/qfirst.py`: a refinement that changes the twist or adds a formula drops the old design.
- `core/pipeline/stages.py`: the verifier's labels are read in any case and spacing ("Correct" was read as wrong); a `failed_step` that is not a finite number is left out.
- `core/pipeline/refine.py`: Jev's own pick is the case applied; a 400/401 from Jev is not retried; docstring updated.
- `core/pipeline/qf_writer.py`: reserved blank names are every name the sandbox defines; a rewrite keeps `"whole": true`.
- `core/answers.py`: "1,200 J", "≈ 0.25", "approximately 0.25" read as numbers.
- `core/pipeline/qf_draw.py`: "Jev could not score the formula sets" instead of an empty score list.
- `generate_questions.py`: each run keeps its spend in `SPEND_FILE`, so a run killed at the timeout is counted towards `--max-spend`.
- `core/engine/physical/gases.py`: an unused `_L_ATM_J = 101.325` removed (thermo's 101.3 is the one used).
- `calibration/calibrate_thresholds*.py`: import without `SAMBANOVA_KEY_1`; `main()` says it is missing.
- `tools/extract_notes.py`: examples no longer name the deleted `data/notes/amines_lec1.txt`.
- `README.md`: the ladder measures difficulty only; a question a failed insight hint did not confirm is still accepted unless the verifier re-check finds the engine or the wording at fault (as the code does).
- New tests: `tests/test_models.py`; additions to `test_qfirst.py`, `test_pipeline_offline.py`.

### Documents brought up to date with the pipeline
- **`README.md`:**
  - the question-first loop is rewritten: blanks, coder 2, the number step, the Jev checks, the designer;
  - the ladder is Llama 3.3 70B, not Phi-4;
  - the solution writer is Gemini 3.8 Flash;
  - the models table now has the designer, Luna as coder, the number step as code, Jev's roles and the airouter.in router;
  - the quick start has `step_by_step` and `real`, and 414 tests;
  - the layout lists the `qf_*` files and `docs/PIPELINE.md`.
- **`docs/Flow.md`:** the question-first section is rewritten (no number program, `construct_numbers` or Codestral), with the Llama ladder, its calibration and Jev's level label.
- **`docs/Decisions.md`:** six new entries: the designer, Llama replacing Phi-4, Luna as coder, numbers picked by code, only picked values must matter, and the coherence cut-off trial. The Phi-4 entry is marked superseded.
- **`docs/pipeline_overview.html`:** now shows the question-first flow (it showed only the engine-first one).
- **`core/models.py`:** the module docstring (router, families, the known Luna overlap) is corrected and the stale Codestral comment is removed.
- **`docs/inorganic_pipeline_plan.md`:** a note on the blank flow.

`docs/analysis_advanced_formula_use.md` keeps its Phi-4 measurements: they are a record of that analysis.

### Cleanup: `qfirst.py` split by stage (no behaviour change)
The 2,035-line `core/pipeline/qfirst.py` is split into one file per stage. Each block was moved verbatim:
- `qf_draw.py`, `qf_design.py`, `qf_writer.py`, `qf_coder.py`, `qf_numbers.py`, `qf_checks.py`: the stages.
- `qf_text.py`: the number-printing and novelty helpers.

`qfirst.py` keeps the orchestration (`write_and_solve`, `run`, `refine_round`, `rebuild_result`) and re-exports every moved name, so `qfirst.<name>` works as before.

Other changes:
- **Prompts:** every prompt is unchanged. The writer, designer and both coders' prompts were rendered before and after the split and compared: identical.
- **Dated notes:** those in comments and docstrings were shortened to the reason alone; the dates are in this log. Notes inside prompts are untouched.
- **Patch targets:** `flow.py` now reads the level floor from `qf_checks`. The tests patch `_level_floor`, `jev_level` and `_coherence_cuts` in `qf_checks`, and `formulas_fit`, `_fit_floor` and `FIT_*` in `qf_draw`, where the code uses them. A patch of `qfirst._level_floor` no longer reached the level check, and a test tried the network.
- **New page:** `docs/PIPELINE.md` maps every stage to its function and file.
- **Checks:** 414 tests pass, and a scripted dry run of every `step_by_step` stage ran end to end. No file was deleted.

### Third real-question check (2017P1_Q26): a broken database entry, a misleading message, an engine limit
- **The database entry is broken.** The stored text (cell constant 1000 m⁻¹, α = 0.01, Λ° in S m² mol⁻¹) gives 0.0333 by hand, which is what Luna's program gave. The official 6 belongs to the paper's own wording (120 cm electrodes, pH 4, Z × 10²), and the entry's solution note says so itself. It is excluded from `real` (`step_by_step.BROKEN_REAL`). The coder calibration pool is unchanged.
- **Bug fixed (`sandbox._search`).** The number step reported the most frequent failure (125 sets outside the answer range) instead of the furthest one (75 sets inside it, all failing the typical-mistake check). So the writer was told its answers were "never inside" the range. It now reports the furthest failure and mentions the out-of-range sets alongside.
- **Engine limit, not changed.** Formulas 247, 248 and 251 know two typical mistakes between them (none for α = Λm/Λ°). One of them pushes the backwards step out of range. So at most one mistake changes the answer, and `MIN_TRAPS = 2` can never be met for this formula set: rewriting cannot help.

### `real`: blanks with problems go back to the writer, as in the pipeline
Second real-question check (2023P2_Q11, He⁺ orbit radii → wavelength). The writer turned the answer blank "____" into a placeholder `[[blank]]`. `blank_problems` caught it, but `real` then said "next: solve".
- `real` now sends the writer back with the problem, up to `WRITE_TRIES` times, as `write_and_solve` does.
- After that it stops.
- `solve` refuses a question whose blanks still have problems.

Also seen in this run: the writer gave orbit radii continuous ranges (50–300 pm), though a radius exists only at 26.45 n² pm for He⁺. The engine catches this: `find(step_61, 'n')` accepts only whole n, so every value set fails and the number step would tell the writer the situation is impossible (checked offline). Nothing changed for it.

### Coherence cut-offs under trial: current (95th percentile) against looser (99th)
`step_by_step.py check` prints Jev's three coherence scores once and gives the verdict under both cut-offs:
- **Current:** the calibrated 95th percentile of the real questions' scores. 9 of 77 real questions are rejected; 14 of 14 bad ones are caught.
- **Looser:** the 99th percentile of the same scores. 2 of 77 real questions are rejected; 14 of 14 bad ones are still caught.

`--cut current|looser` decides the stage. The pipeline itself still uses the current cut-offs (`qfirst.COHERENCE_PERCENTILE = None`) until the author chooses, after two random real questions. Trigger: 2020P1_Q15, which is in the calibration set, rejected at glued 18 % and arbitrary 45 %. `real` now draws only from questions not tested yet (`output/step_by_step/real_tested.json`).

### Only the picked values must matter; a faked use is seen through
The first real-question check (`step_by_step.py real`, 2020P1_Q15, fuel cell → adiabatic compression) found three things:
- **Luna's program was right.** On the real numbers it gave 13.3248 against the official 13.32.
- **Our rule rejected a real JEE question.** The question states "standard conditions at 1 bar and 298 K", which the answer does not need, and our every-value rule rejected that.
- **The coder faked using the values.** To satisfy the rule, Luna wrote `(P / P) * (T / T)` into its program.

Changes:
- **The rule:** only the values the number step picks (range blanks) must matter. The writer's fixed values may be background, as in real papers (decided by the author). `pick_numbers` and the probe exempt every fixed value; the writer's rules say so.
- **The coder's prompt:** never put a value into the program only to have used it (`P / P`); a value the answer does not need is left out.
- **Bug fixed (`sandbox._input_role`):**
  - The check moved 1 bar to 0. `P / P` then failed, and the failure counted as "P matters".
  - A change the program cannot take now proves nothing; only a value that cannot be changed at all counts as used.
  - Only true counts (ints) move by one. A float such as 298.0 moves by a few per cent.
- **Replayed offline** on the user's run: the number step now passes (answer 9.561 K on new numbers, 4 typical mistakes, 1.0 % rounding). The fake `P / P` is reported as unused.

## 2026-11-17

### `step_by_step.py real`: a real JEE Advanced question through the pipeline (a check, never saved)
`python tools/step_by_step.py real [--id 2018P1_Q8]` takes a random real physical question from `data/jee_advanced` (the 49 whose formulas are all engine steps, as `tools/calibrate_coder.py` selects them). The pipeline's writer model puts its numbers into blanks with ranges under the same rules it writes with (`qfirst.BLANK_RULES`, moved out of the writer's prompt; the prompt is unchanged, checked character for character), and gives each blank's real number. Then the usual stages run: `solve`, `numbers`, `check`, `judge`. `solve` also runs coder 2's program on the real numbers and compares the result with the official answer. A real question is never saved to the question bank. The pipeline itself is not changed for this.

### New core flow: blanks → coder 2's program → code picks the numbers
The answer is no longer fixed before the solving program exists (the number program computed the "intended" answer and the solving program only had to reproduce it).
- **Writer:** every number in the question is a blank `[[name]]`. Each blank gets a realistic `"range"`, or a `"value"` only where the value belongs to the substance or situation (a molar mass, E°, ΔfH°, the 8 corners of a cube). A count is marked `"whole": true`. The writer also gives an `"answer_range"`. The constants of the Given line are blanks with their standard value. `qfirst.parse_values` and `blank_problems` handle this; problems with the blanks go back to the writer before any program is paid for.
- **Coder 2 (Luna)** writes the solving program from the question with its blanks and no numbers (`qfirst.write_blank_program` and `solver_program`). The blanks are variables of the program.
  - A probe runs the program on value sets from the ranges. A program that crashes, assigns to a blank, never uses one, or leaves out a drawn formula that cannot be dropped goes back to the coder with the error.
  - "cannot" goes to the writer.
  - If no value set runs twice in a row, the ranges are at fault and the writer is told.
- **Coder 1, the number step** (code, not a model: `qfirst.pick_numbers` → `sandbox.search_numbers`) draws value sets in the ranges. Wide positive ranges are drawn log-uniform, every value is rounded to 3 significant figures as printed, and counts are whole. Each set runs through coder 2's program. A set is taken only if:
  - the answer is in `answer_range`;
  - rounding the steps to 3 figures moves it by at most 2 % (`FRAGILE_TOL`; the 2.03 pm iron question);
  - at least 2 typical mistakes change it;
  - every blank is used (except stated constants the formulas hold).
- **Every blank must matter:** a blank the program never reads, or that feeds neither a formula nor the answer, is rejected. A blank that feeds the formulas but cancels in the answer (T in a ratio of two isothermal steps) is allowed: no value of it can contradict the others.
- The picked values are then printed in the question (`filled_question`), exactly the values the program ran on. Failures go to the writer in its own terms (answer range never reached and where the answers fell, too fragile, too few mistakes, a blank unused, an impossible situation). A program that breaks or hangs on other values goes back to the coder, never to the writer.
- **Removed:** the number program (`write_forward`, `construct_numbers`, `sandbox.run_forward`, `question_checks_from_numbers`, `forward_irrelevant`, `_find_hint`) and `models.NUMBER_CODER` (Devstral). Questions without blanks still go through the old `program_for` path only when `REQUIRE_PLACEHOLDERS` is off (tests).
- **Unchanged:** draw, design and the Jev design check, the Jev level check (it now reads each range blank at a typical value), the code checks, Jev coherence, the ladder (kept as it is), the verifier, refinement, saving and the solution. A rewrite sees the earlier blanks and ranges. A parked question stores its values (`qfirst.preset`) and is re-run on them.
- **`tools/step_by_step.py`:** the stages are now draw → design → write → solve → numbers → check → judge → save → solution. A program that breaks on the picked numbers sends you back to `solve`, with the error, instead of to `write`.
- **Verified offline** (no API call): 411 tests pass. A scripted dry run of every `step_by_step` stage from draw to solution ran end to end, including the "back to solve" path, and the coder's prompt contained no numbers.

### Jev's level check reads the question as it will be printed
`qfirst.preview_text` prints the writer's values the way `fill_template` does (a whole-number count as "8", not "8.00 corner positions"), so Jev's level check reads the same text the student will.

### Inorganic pipeline: plan
`docs/inorganic_pipeline_plan.md` (draft): the question-first pipeline for inorganic (multiple correct, single correct, integer count, numerical); the answer key from the inorganic reaction graph, new property functions (oxidation state, unpaired electrons, shape, MO bond order, CFSE, isomer counts) and fact tables. Physical's stages, roster and calibration tools carry over.

### One design per draw
`qfirst.DESIGN_TRIES = 1` (was 2): a design Jev rejects means a new draw, not a second design on the same formulas (a Gemini Pro design costs 4-8 cents; the K_p / K_c / Dalton draw gave the same contrived equality three times).

### The "condition" twist asks for a physical state, not an equality
`qfirst.TWISTS["condition"]`: the condition the experimenter sets brings the system to a physically meaningful state (a given degree of dissociation, a partial pressure or mole fraction reaching a value, a precipitate just forming, a reaction becoming spontaneous); never an equality of quantities of different kinds. "Two results become equal" drew "Kc numerically equal to a partial pressure" in three designs running (PCl₅, N₂O₄; Jev rejected the last: invented relation 76 %, arbitrary condition 72 %).

### Jev checks the design (calibrated), before anything is written
- `tools/check_design.py`: Jev's three coherence questions on the saved design. On the PCl₅ design ("Kc numerically equal to the partial pressure of PCl₅") Jev gave invented relation 78 %, arbitrary condition 71 %, glued parts 7 % (question cuts 18 / 31 / 13 %).
- `tools/calibrate_design.py reverse`: Gemini Flash describes ~30 real JEE Advanced questions (2+ engine formulas, `docs/advanced_formula_map.py`) in our design format, saved for review (`knowledge/design_calibration_designs_physical.json`): each checked against its question and official answer by Claude (AI assistant) as a suggestion (28 ok; 2 bad: 2018P2_Q12 has a sign error in ΔS° = ΔG°/T, 2020P1_Q16 names Al instead of H₂SO₄ as limiting), shown in `knowledge/design_calibration_review_sheet.md`; `accept` records them as the author's review, with who suggested them; `score`: Jev on the reviewed real designs and 10 bad ones (the three failed designs of 2026-11-16/17 and hand-written ones, by fault); per-fault cut = 95th percentile of the real designs; written to `knowledge/design_coherence_calibration_physical.json` only if it catches at least half of the bad ones.
- `qfirst.design_problems` (and `design_plan_text`): with that file, a design Jev flags is redesigned before writing (`write_and_solve`, `step_by_step.py design`); without it, no check (an uncalibrated design check rejected good designs, 2026-11-16). Tests added (399 pass).

### Designer Gemini 3: its own thinking level, room to finish
Gemini 3 models ignore numeric thinking budgets (reported by developers: a 32768 and a 1024 budget gave the same thinking; Google: use thinking_level). A Gemini 3 designer now gets no budget but a thinking level, "low" (`models.GEMINI3_DESIGN_LEVEL`, `step_by_step.py design --effort low|high`; the cheaper one, to be raised if its designs are shallow), and an 8000-token cap (`GEMINI3_DESIGN_CAP`, `--cap`); only the tokens used are paid.

### Design prompt: a length limit
The design prompt says the thinking and the full design together must not exceed 2500 words. Gemini 3 Pro ignores numeric thinking budgets (it thinks at its default "high" level); on OpenRouter too the design was cut off at 6500 tokens after ~6000 of thinking ($0.08, NOBr), as twice on airouter.

### Designer on airouter: an effort level, not a token budget
On the design prompt Gemini Pro on airouter ignored the 3000-token budget (the cut-off replies show ~4800 and ~6300 tokens of thinking and ~200 of design; $0.14). On airouter only, `design_question` sends `reasoning_effort` = `models.AIROUTER_DESIGNER_EFFORT` ("medium") with a reply cap `AIROUTER_DESIGN_CAP` (6500); OpenRouter keeps the token budget. `tools/step_by_step.py design --effort low|medium|high --cap N` for one run.

### Designer: room for Gemini Pro's longer design
The design call's reply limit is thinking + 3500 tokens (was + 2000): Gemini Pro on airouter kept to its thinking budget (854 of 1000 on `tools/check_thinking.py`) but its design text did not fit in 2000 (NH₄HS design cut off, $0.06). At most ~8 cents a design.

### find() for whole-number inputs; coders without thinking; number-coder candidates
- `sandbox` `find()`: a whole-number input (kinds integer/count/posint: x in AxBy, a charge) is found by trying the whole numbers in its range (up to 200) instead of bisection, which landed on 1.0000000000000002 and was refused by the step (Codestral, 2022P2_Q3). Test added (397 pass).
- `LLM_ROUTER=airouter` (environment) sends every call airouter carries to airouter even with an OpenRouter key: in PowerShell `$env:OPENROUTER_KEY=""` deletes the variable and .env sets it again. `tools/check_thinking.py` shows each call's router.
- `models.AIROUTER_STANDINS`: on airouter, Devstral (the number coder) is served by Qwen3 Coder Next; on OpenRouter Devstral itself. Every question record has `served_by` (`models.SERVED`: roster model → router:model that really answered), so the paper can say which model made each question's numbers. After the import line was named in the prompts, Qwen's 8-question run: 6/8, 1.25 tries a question (1.62 before), $0.0025 a question.
- Number-coder stand-in on airouter: Qwen3 Coder Next (`alibaba/qwen3-coder-next`, Alibaba, a family no checker uses, does not think): 6/8 real JEE Advanced questions right, 1.62 tries a question, $0.0032 a question, run one question at a time (`--parallel 1`: four at once, airouter dropped connections). Its basic slips (an import line in 5 of 8 first programs, one syntax error) are now named in both coder prompts: math is already there, any import line is rejected. Mistral Large 4 ignored a 1500-token thinking budget on the coder prompt (empty replies) and Mistral Medium 3.5 without thinking answered a test wrongly.
- `models._client`: timeout 180 s and no silent SDK retries (its defaults, 10 minutes and 2 hidden retries, let a stuck airouter call hang a run with no output); a timeout is retried by `core.llm.call_with_retry`, which prints it. `models.THINKING_BUDGET` and `tools/calibrate_coder.py --thinking N --verbose`.
- `models.THINKING_OFF` (models asked not to think when a call sets no thinking) and `tools/calibrate_coder.py --no-thinking`.
- Number coder on airouter (Devstral is not there), 8 real JEE Advanced questions: Mistral Large 4 returned nothing in 5 minutes (a thinking model; ~$0.05); Codestral 2/8 right (wrong formula use, solve_for brackets, the find() case above).
- `tools/calibrate_coder.py` keeps each coder's result beside the others' (a failed run had replaced Devstral's 8 programs); the junk Mistral Large 4 entry (invalid model ID) and Devstral's 2-question run were removed from the result files (backups kept outside the project).

### Ladder bottom step: Llama 3.3 70B instead of phi-4
phi-4 is not on airouter.in. From the saved calibration (`calibration/ladder_separation.py`, no new calls): phi-4 fails 14.3 % of easy Mains / 52.9 % of Advanced-level (gap 38.7); Llama 3.3 70B 28.6 % / 66.2 % (gap 37.6, $0.0010 a question); Llama 4 Scout gap 11.6; Llama 4 Maverick gap 13.7. `models.LADDER[0] = ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct")` (airouter: `meta/llama-3.3-70b`); Meta has no other role. Trade-off: twice as many easy Mains questions fail the bottom step and go on to the GLM label.

### Router: OpenRouter first, airouter.in when it runs out; Jev on airouter
- `models.router(model)`: OpenRouter while it has a key and credit; on its first HTTP 402 of a run (`openrouter_out()`) every later call goes to airouter.in, and the failed call is repeated there (`ask_json`, `refine._jev_post`). Models airouter does not carry (`AIROUTER_MISSING`: microsoft/phi-4, mistralai/devstral-2512) always go to OpenRouter.
- A model OpenRouter does not carry (HTTP 400 "not a valid model ID", e.g. Mistral Large 4) goes to airouter for the rest of the run, and the call is repeated there.
- Jev on airouter works (`tools/check_models.py --jev`: P = 0.93, choice "combustion" 100 %, level 0.04; OpenRouter gave 0.93, 100 %, 0.05 on the same questions). airouter's own decisions format, learnt from its errors (undocumented): `input` as text (the state as JSON), `questions` as a list with each question's id under `name`, yes/no as `predicate`, choice options as `choices: [{value, description}]`, score levels as `levels: [{label}]`; answers come back with `probability` and lists of probabilities (`refine._airouter_question`, `_airouter_answer`). The call goes through the openai client (`client.post("/decisions")`): airouter's Cloudflare closed urllib's connections. Retries pause 5/10/15 s.
- Jev on airouter (`typesafe-ai/jev-1.14.0`) answered "403 error code: 1010": Cloudflare refuses urllib's own User-Agent; `_jev_post` sends one.
- `tools/check_models.py` shows each model's router (`op`/`ai`) and its tokens out (a long wait with ~5 tokens is the router's delay, hundreds are thinking). Tests: 395 pass with OpenRouter only, airouter only, and both.

### airouter.in as a second router
OpenRouter needs an international card; airouter.in takes UPI. `core/models.py`: with `AIROUTER_KEY` set in .env every call goes to airouter (`router()`, `api_key()`, `_client()`, `decisions_url()`), the roster keeps OpenRouter's names and `route_model()` gives airouter's (`zai/`, `mistral/`, `typesafe-ai/jev-1.14.0`); OpenRouter-only request fields (fallback `models`, `usage.include`) are not sent; cost is read from `cost` or airouter's `total_cost`. Jev goes to airouter's `/v1/decisions` (`refine._jev_post`, which now reports the router's error text). `tools/check_models.py` prints the router and each model's routed name. Not on airouter (2026-11-17): microsoft/phi-4 and mistralai/devstral-2512. Tests: 394 pass, with and without an airouter key.

### Designer: Gemini 3.1 Pro, thinking 3000 tokens
The design decides whether a question is JEE Advanced, so it gets the strongest model of a maker-only family, cost second: `models.DESIGNER = "google/gemini-3.1-pro-preview"` (pinned, not "pro-latest", so the paper names one model), `DESIGNER_THINKING = 3000` (reply limit 5000; at most ~6 cents a design). Cheaper designers failed live: Gemini 3.8 Flash (a JEE Main design; an impossible one), Kimi K2.6 (ignored its thinking budget; with thinking off, a self-contradictory design). Run `tools/check_thinking.py google/gemini-3.1-pro-preview` before relying on the budget.

### Design prompt: a checklist; tools/check_thinking.py
- `qfirst.design_question`: before answering, the designer checks its design is physically real, determined by the given data, not a textbook one-liner, and that "hidden" is truly unstated yet not needed; each from a failed live design (N₂O₄ at T = 1/R ≈ 12 K, a volume with α unknown and no K, polonium "a = 2r" stated while hidden).
- `models.ask_json(reasoning_tokens=0)` switches thinking off; `tools/step_by_step.py design --thinking N` sets the designer's budget for one run (0 = off). Kimi K2.6 ignored a 1000-token budget (thought 1800, cut off, no answer); with thinking off it answered in 14 s.
- `tools/check_thinking.py MODEL...` (`--no-thinking`): one short chemistry task with a thinking budget (`reasoning.max_tokens`); reports tokens thought, whether the JSON came back, seconds and cost: whether a candidate designer (Kimi K2.6) keeps to a budget before it is used.

### Designer: a fixed thinking budget
At "medium" effort the designer thought until its 8000-token reply was cut off ($0.03, no design: phosgene ⇌ CO + Cl₂). `models.ask_json(..., reasoning_tokens=N)` sends OpenRouter `reasoning.max_tokens` (a thinking budget inside the reply's limit); the design call thinks for `models.DESIGNER_THINKING` = 3000 tokens with 2500 left for the design (~2 cents at most).

### Designer thinks less
`models.DESIGNER_EFFORT` "high" → "medium" and the design call's limit 16000 → 8000 tokens (at most ~3 cents): on its first live run (Solid State, inverse twist) Gemini 3.8 Flash at "high" spent all 16000 tokens ($0.06) thinking aloud in its reply and returned no design; at "low" it returned a JEE Main design (polonium, density → edge → radius, packing fraction unused; Jev's level check scored the written question 1.73, above the real Advanced median of 1.66, so it passed).

### The number program gets its own coder (Mistral Devstral 2)
The number program computes the question's numbers, so it is part of making the question; GPT-6 Luna wrote it and also sits on the ladder, so OpenAI judged what it had helped make. `models.NUMBER_CODER = "mistralai/devstral-2512"` (fallback Codestral) writes it now (`write_forward`, `coder_for(ladder_ok=False)`; the same failure twice stops, no escalation); Luna (`models.CODER`) writes only the solving program, with no fallback (Codestral is Mistral, now a maker). Mistral is used nowhere else. Makers: Google (design, writing, solution text) and Mistral (numbers); checkers: OpenAI, Microsoft, Z.ai, Anthropic, TypeSafe. Qwen3.8 Flash and DeepSeek V4 Pro, both thinking models, returned nothing within minutes (DeepSeek spent $0.05); Devstral 2 does not think: 2/2 real JEE Advanced questions right on the first try at $0.0012 each. `tools/check_models.py` checks it. Tests pass (393).

### The solving program only has to get the answer
On 4 real JEE Advanced questions (`tools/calibrate_coder.py --ids`) Luna reached the official answer every time, but our checks threw out 3 of the 4 programs: a formula used on both sides of a ratio looked unused, ²³⁸₉₂U was not read as 238 and 92, and "equimolar" was not read as 0.5.
- `qfirst.program_for(..., built=True)`: a program that runs is kept; its answer is compared with the engine's (or the official) one by the caller. `program_problems` (exact quotes, every formula called, dummy calls, every stated number taken) and `_quote_found` are removed. Without an independent answer (an old question without placeholders, `built=False`) the program is the answer key and must still call every formula.
- With numbers built by the engine, the number program decides which formulas matter: `construct_numbers` notes its irrelevant formulas, `forward_irrelevant(bb)` reads them, and formulas are dropped from those; `question_problems(..., built=True)` skips the formula and trap checks (`question_checks_from_numbers` already made them). `tools/step_by_step.py` the same.
- `sandbox`: a step's results are scaled for every call at once and then for each call alone (`_scalings`), so a formula on both sides of a ratio counts as used (number program and solving program).
- `tools/calibrate_coder.py --recheck` reruns the saved programs and compares with the official answer. Tests updated (393 pass).

## 2026-11-16

### Coder chosen on real JEE Advanced questions
`tools/calibrate_coder.py` (new): each candidate coder writes the solving program (`qfirst.program_for`, up to 3 tries, no hand-over) for 12 real JEE Advanced physical questions (default; `--limit`), the same set for every coder, spread over 2012–2024. Pool: numeric answer, every formula of the solution an engine step (`docs/advanced_formula_map.py`), no graph or figure (49 questions). An answer is right within 2 % of the official one or at its stated decimals. Reports per coder: right (some try reached the official answer), accepted (the pipeline's checks passed too), tries per question, cost; a coder stops at `--max-spend` (default $0.15). Written to `knowledge/coder_calibration_physical.json`. Supersedes `tools/compare_coders.py` (one generated question) for the choice.

### Bad questions rejected on review; honest difficulty labels
- `tools/results.py reject`: GEN_20261115T221723 (invented relation ΔG° = −(purity × peaks × 100)) and GEN_20261012T235813 (garbled LaTeX text) are in results/rejected.json with their reasons (outputs/ keeps the raw records; a backup was taken). `qfirst.accepted_questions` now skips every rejected question, so the writer is never shown one as a "used situation" and the copy check ignores them (two earlier smoke-test rejections were already in the list).
- Labels: by the ladder's own calibration, "phi-4 fails, GLM solves" happens to 47 % of hard Mains questions and 38 % of real Advanced ones, so GLM-first cannot mean "advanced" by itself. `flow._judge`: a GLM-first question is labelled by Jev's calibrated level check (`advanced` at or above the floor, `mains_hard` below); before calibration, or if Jev is down, `advanced_or_mains_hard`. The record keeps `jev_level`. Acceptance is unchanged. Luna-first stays `hard_advanced`, none `frontier`.

### Jev coherence check calibrated per fault
`tools/calibrate_coherence.py` (~1 cent): Jev's three coherence questions (invented relation, glued parts, arbitrary condition) on 77 real JEE Advanced physical numerical questions (GOOD) and 14 known bad ones (the two such questions the pipeline once accepted, and 12 hand-written ones, 4 per fault, labelled). Per fault, the cut is the 95th percentile of the real questions' scores (≤ 5 % of real questions flagged for it); the share of bad ones caught is reported, and compared with the old single 50 % cut. Written to `knowledge/coherence_calibration_physical.json` only if it catches at least half of the bad ones; `qfirst.coherence_problems` reads the per-fault cuts (`_coherence_cuts`), else 50 % as before.

### Jev level check after writing; solutions by Gemini, not Luna
- `qfirst.level_problem`: right after the writer (before any program is paid for), Jev's ordered-scale ("score") question places the question, as a reader sees it (`preview_text`: the writer's values in, values still to compute as "…"), on `LEVELS` (0 JEE Main easy … 4 JEE Advanced hard). Below the floor it goes back to the writer with what to change. The floor comes only from `tools/calibrate_level.py` (real physical numerical questions: 93 JEE Main, 77 JEE Advanced; floor = the 20th percentile of the Advanced scores; written only if at most half of the Main questions reach it); with no calibration file the check never blocks. The calibration also scores our accepted questions. `refine.jev_score`; `tools/check_models.py` checks a score question; the stage tool shows the preview and the level after `write`.
- `models.SOLUTION_WRITER` = google/gemini-3.8-flash (was GPT-6 Luna, also the coder and the ladder's top solver). Luna now: the coder and the top of the ladder.

### The design step: a stronger model, built around a hidden link; the writer writes it up
Review of the 11 accepted physical questions: 3 genuine JEE Advanced questions (each turns on one conceptual link), several Mains-level ones labelled "advanced", 3 flawed. The weak ones are long chains of plug-ins: the design was done by the writer's model (Gemini 3.7 Flash, reasoning "low") with a prompt asking for a scenario.
- `models.DESIGNER` = google/gemini-3.8-flash with reasoning "high" (Google: the family that only generates; OpenAI, Microsoft, Z.ai, Anthropic and TypeSafe judge). `--designer` on both scripts (e.g. ~google/gemini-pro-latest to compare).
- `design_question`: ONE design, chemistry only (no format rules), around a HIDDEN LINK: the quantity two formulas share but the question never states, what the student must notice there, the trap at it, what is given and what stays hidden; two real JEE Advanced questions with the twist set the level; no giveaways. Old two-design replies are still read.
- `write_question` with a design: its job is to WRITE UP the design faithfully: state exactly the "given" quantities, never the "hidden" ones or the point to notice, data not in the order used; no examples (the design carries the level). Both paths: no giveaways (ratios, n-factors, equivalent masses).

### Design gates off (`qfirst.DESIGN_GATES = False`)
Live run: the Jev plan check (uncalibrated 50 % cut-off) rejected 3 of 4 designs as "vague" at 50-61 %, concrete ones included, and the feasibility check (run by Luna since the coder change) rejected a design for needing a formula run backwards, which find() does. Two of three draws died before any question was written. Both checks are off; impossible designs are still caught after the number program (`question_checks_from_numbers`) and by Jev's check of the finished question. The functions stay (tests turn them on).

### Feasibility check: the coder's token budget
Live run: "[coder] unusable reply (empty completion (finish_reason=length))" twice: the design's feasibility check still allowed 800 tokens, enough for Codestral, but Luna (a thinking model) used them all thinking. It now gets `models.coder_tokens(CODER)` with reasoning effort "low", and a reply cut off at the limit is not asked again at the same limit. Every other coder call already had the full budget.

### Luna codes; the question's own flaws are found before the solving coder
Live run: every basic error (undefined names, find() misused, syntax errors, wrong units, wrong quotes) came from Codestral; the question-level rejections ("only 0 of the typical mistakes changes the answer", "step_72 … does not affect the answer") were found only after the solving coder and its stronger retry had been paid for.
- `models.CODER` = openai/gpt-6-luna for both programs (≈ the same price per call as Codestral, ~$0.0017 vs $0.0015; correct programs whenever it ran); Codestral only as the provider fallback; `CODER_STRONG` = None (no escalation).
- `sandbox.run_forward` also returns the formulas that change no stated or asked value (`irrelevant_steps`) and the typical mistakes that change one (`traps`), at no model cost. `qfirst.question_checks_from_numbers`: an unneeded formula (when dropping it would leave < 3) or fewer than `MIN_TRAPS` mistakes goes back to the writer at once, in plain words, with the mistakes it could use. The van der Waals question accepted today passes (4 mistakes); the photoelectric difference question of this run is caught (0 mistakes: the work function cancels).
- `explain`: "does not affect the answer" also becomes "your question does not need the formula …".

### Powers written as a^b
One plain form for every power: the code prints 5.20 × 10^14 (was 10¹⁴) and the writer is told to write every power as a^b (2^6, e^12, (1/2)^3). `stated_numbers` reads each power as the one number it is (10^-3 → 0.001, 2^6 → 64, e^12, (1/2)^3 → 0.125; superscripts too; Fe³⁺, cm³ are not powers of a number). A count the writer gives as a whole number (6 half-lives) is printed as 6, not 6.00.

### Powers of ten: the code prints them, the writer never writes them
Live run: the writer gave "… Hz (× 10¹⁴ Hz)": a placeholder followed by × 10¹⁴ and a unit with a power of ten, which code cannot use. The writer prompt still said "powers of ten as × 10ⁿ" (from before placeholders): removed; now a POWERS OF TEN rule (RIGHT "[[nu0]] Hz" with 5.2e14 in free; WRONG "[[nu0]] × 10¹⁴ Hz" with 5.2 or unit "× 10¹⁴ Hz"), free values are plain JSON numbers, the unit is plain. `construct_numbers` sends such a draft straight back before any coder call.

### The number program sees what each chosen value means
It got the writer's values as bare JSON ({"P_aq": 0.031, "R_const": 0.0821, ...}) and had to guess each name's meaning and unit. `qfirst.named_values`: each chosen value and each value to compute is listed with the words of the question around its placeholder (meaning and unit), or marked as the asked quantity / a value not shown.

### Coder prompts: the exact calls written out, and the mistakes named
Both coder prompts (number program and solving program) now carry EXACT CALLS (`qfirst.exact_calls`): for each drawn formula, the forward call and, for each numeric input, the backward find() call, with the engine's own argument and output names; a HOW TO PROCEED rule (all inputs known → forward line; output known → backward line; two unknowns → solve_for); and COMMON MISTAKES, each WRONG/RIGHT from today's runs (the output under its own name in find, an output passed as an input, an undefined name, typed formulas or dummy calls, positional arguments / C / imports). find() still accepts the output's own name as a safety net.

### find() forgiving; the writer is not sent backwards; the number program stops sooner
Live run (vapour density → α → Kp; ΔG° → K; wet H2 over water):
- `sandbox.find`: the target may be given under the formula's own output name (`equilibrium_constant=0.21`, written 5 times instead of `result=`); a wrong or missing input name is reported at once with the call to write (it was hidden inside "no value of … gives …").
- `construct_numbers`: the asked quantity in free with nothing derived now says "REMOVE it from free: the engine computes it". The old "list the observed results in derived" made the writer turn the stated zinc mass into a derived value (a backward construction: `NameError: mass_Zn` ×3). The writer prompt says when the asked quantity belongs in free.
- The number program stops after the same failure twice (it has no stronger coder to hand over to; it tried a third time).

### The first set over the floor is taken
`best_draw` scores a batch 3 at a time (`FIT_PARALLEL`) and takes the FIRST set at or over the floor; the sets of the batch not yet sent are cancelled (not scored, not paid).

### Formula-fit floor 0.60, drawn until reached
Calibration (Jev): real JEE Advanced sets median 66 %, random draws median 32 %. `qfirst.FIT_FLOOR` = 0.60 (66 % of real sets, 54 % of real 3+-formula sets and ~3 % of random draws reach it: ~30 sets, ~$0.001 a draw); new batches of 6 are drawn until one reaches it, `FIT_BATCHES` = 30 only as a stop if Jev never says yes. The calibrated 0.50 stays in the file.

### Formula-fit floor calibrated on real JEE Advanced sets
`tools/calibrate_fit.py`: Jev scores the formula sets of the 53 real JEE Advanced physical questions that use 2+ formulas (docs/advanced_formula_map.py) and 60 random draws; the floor is the 20th percentile of the real scores (80 % of real JEE sets reach it), with the share of random draws that reach it, written to `knowledge/fit_calibration_physical.json` (~half a cent). `qfirst.best_draw`: while the best of a batch of 6 is under the floor, another batch is scored (at most `FIT_BATCHES` = 3); the best set seen is written either way. Without the file: best of one batch, as before.

### Strong coder: back to GPT-6 Luna, with the number program kept off the ladder
Tried on the van der Waals solve: Grok Code Fast 1 is deprecated (404); Grok 4.3 costs ~3× Luna; MiniMax M2.5 spent 1.5¢ on one reply and returned the prompt's placeholder `{"cannot": "the reason"}`. Luna solved it for 0.35¢ (the stage). `CODER_STRONG` = openai/gpt-6-luna again, but `coder_for(ladder_ok=False)` for the number program: the answer the ladder is graded against never comes from a ladder model; the solving program, which Luna may write, only has to reproduce it. `write_program`: the format line no longer shows a placeholder reason, and a reply whose "cannot" is a placeholder (or too short, with no code) is an unusable reply, not a verdict.

### Refinement: one Jev choice question over the cases
`refine.classify` asked Jev 8 separate yes/no questions (each judged alone, probabilities not comparable). Now ONE `choice` question (Jev's own type: `criteria` = the unused cases; answer `choice`, `confidence`, `probabilities` summing to 1) via `refine.jev_choose`; `_jev_post` is the shared request. The pick prints "Jev's pick: <case> (confidence …)". `tools/check_models.py` checks a choice question too.

### The last coder try goes to xAI, not to a ladder member
`models.CODER_STRONG` = minimax/minimax-m2.5 ($0.15/$1.15 per M; Grok Code Fast 1 is deprecated and Grok 4.3 cost about 3× as much; was openai/gpt-6-luna, the ladder's top solver: a misreading shared by the solving program and the ladder would look like agreement). MiniMax is a family used nowhere else in the pipeline. In `tools/check_models.py` and `ROSTER`.

### Readable solutions: symbols are not units; no repeated steps
GEN_20261116T101250 was saved without a solution: (1) `solution_check.arithmetic_errors` read "8a/(27Rb) = (8 × 3.60)/(27 × 0.0821 × 0.0428) = 303.7" as 8/27 = 303.7, because `core.units` takes 'a' for a year and 'Rb' for a ronnabarn: a calculation is now checked only when every unit word is a chemistry unit (`_chem_unit`); false arithmetic is still caught. (2) `flow.trace_text` listed the Boyle step four times (the program's repeated calls) with 12-digit values: each distinct calculation once, values to 5 figures. `tools/step_by_step.py solution` writes the solution again for the question saved last.

### First question accepted stage by stage; `save` stage
Van der Waals (formulas 107, 106, 108, 105, 103): T_B and B → a, b; P from van der Waals; P_r = 0.841. Ladder: phi-4 and GLM failed (genuine difficulty), GPT-6 Luna solved; both solved with the insight hint → accept, hard_advanced. About 2.5¢ along the successful path. `tools/step_by_step.py`: `judge` keeps the whole decision; `save` writes an accepted question exactly as the full pipeline does (`run_groundup_final.save_accepted`: record, coverage, duplicate store, results/); the candidate carries the graph's own edge ids. A "reword" decision becomes the next `write`'s feedback.

### Coder escalation, a token cap for Codestral, built numbers are not "inconsistent"
Stage run (van der Waals solve): Codestral looped on one nested call (step_103(P=step_108(P=step_107(... ) until 12000 tokens, twice ($0.026, unparseable), then derived a negative a; the writer was told its data were inconsistent, though the engine had built them.
- `models.CODER_STRONG` (openai/gpt-6-luna): `qfirst.coder_for` gives the last coder try of a question (or the next one after the same failure twice) to it, with the errors so far; both the number program and the solving program. No escalation when --coder already names it.
- `models.coder_tokens`: 4000 for Mistral (non-thinking) coders, 12000 for thinking ones.
- `explain(..., consistent=True)` when the numbers were built by the engine: an impossible value in the solve means a misreading, and the writer is asked for plainer wording, not new data.

### Dummy calls are the coder's problem; relevance scales every result
Stage run: the solving program typed the van der Waals, Boyle and B formulas by hand and called steps 106, 105, 103 at the end with their results thrown away ("Call all required functions at least once"). `program_problems`: a drawn step that is called but irrelevant goes back to the CODER ("use each function's result instead of typing its formula"); both coder prompts say so. `sandbox`: the relevance test scales a step's other results too (formula 107's Tc and Pc beside its answer), not only the answer: an honest program using out['Pc'] made 107 look irrelevant. Tests with both programs.

### NameError hints for the solving coder
Stage run: the solving program failed three times on "name 'C' is not defined" (the coder wanted a constants module). `_coder_hint`: a NameError now says what is predefined, to define the name inside solve(), and, for C/R/F/N_A..., that constants are taken from the question with given(). Used by both coders.

### Unneeded formulas are dropped, not rejected
A drawn formula the solving program does not use, or whose result does not change the answer, is dropped while at least `FORMULAS_MIN` (3) remain (`qfirst.unneeded`; `program_problems(may_drop=True)`; `write_and_solve` keeps the rest as the question's formulas). With fewer left, the question is rejected as before. The stage tool does the same in `solve`.

### Number program: a find() hint, and the writer is not blamed
Stage run (van der Waals: a, b chosen; P from the vdW equation): the number program never ran formula 103 backwards and the writer was told its question "does not need" van der Waals, which it did. `find(step_103, 'P', result=a, ...)` computes it (P = 61.27 atm, P_r = 0.842). Now a "never calls step_N" in the number program gets `_find_hint` (the find() line to write) on the coder's retry, and its final failure is worded as the number program's, which `explain` does not turn into "your question does not need formula N".

### Jev checks the plan right after the design
Stage run: the next design used the K of 2CO + O2 ⇌ 2CO2 for FeO(s) + CO ⇌ Fe(s) + CO2 (an invented link) and offered alternative reactions; the feasibility check passed it (it asks only whether a program could run). `design_coherence`: Jev on the plan (invented relation, glued parts, vague reaction) before the feasibility check; a rejected plan is redesigned with the reason. Never blocks when Jev is down. In `tools/step_by_step.py design` too.

### The designer and writer see each formula's conditions
Stage run: the designer planned the Boudouard reaction C(s) + CO2 ⇌ 2CO for formula 154 ("all species gaseous") and formula 367 ("solid + X(g) ⇌ solid + Y(g)", Kp = p(Y)/p(X)), and the feasibility check passed it: both saw only "K_p = K_c (RT)^Δn_g". `formulas_text` now adds a "takes:" line per formula (each input's description and unit, where such conditions are written); the feasibility check rejects a situation that breaks a condition written in an input's description.

### Stage-by-stage runner; --coder
- `tools/step_by_step.py`: one stage per command (draw, design, write, numbers, solve, check, judge, show), each printing what it read and produced and its cost; state in `output/step_by_step/state.json`; a failed stage saves the writer-facing feedback for the next `write`. `draw --txs ... --twist ...` picks the formulas by hand. `--coder MODEL` on both scripts.
- Coder calls: 12000 max tokens (a thinking coder such as GPT-6 Luna was cut off at 4000).

### find(): a formula run backwards without hand-written mismatches
Live run: the number program for a conductivity question (Ka, C → α → Λm → κ → R) had to invert three formulas and failed eight times (NameError, α = 10⁷, wrong input names). `sandbox`: `find(step_N, "input", result=..., **other inputs)` solves one formula for one input over the input's own range; both coder prompts explain it. Round trip tested: forward R = 5199 Ω, the backward solve gives C = 0.0200 M. `clean_code`: subscript digits outside strings become ASCII ('CO₂ = ...' was a syntax error), quotes keep theirs.

### An unused formula is the writer's to fix, in the writer's words
Live runs: many questions failed with "the program never calls step_N" / "does not change the answer", and the message went to the coder (who cannot fix a question) and reached the writer only in the coder's words. Now:
- `explain(problem, drawn)` turns it into "Your question does not need the formula '<what it gives>: <formula>' … state the inputs this formula takes and make its result feed another formula or the answer"; an unused stated number becomes "remove that number".
- The writer plans `links` first: one line per formula saying what it takes and where its result goes; a formula whose result is known by heart (Z = 4 for fcc) must be made necessary.
- Both coder prompts: never type in a value a function computes (Z = 4, an n-factor, 22.4 L); call it.
- `call_json(retry_cut_off=False)` for the designer and the writer only (council members are still re-asked).

### Designer output limit
Live run: the designer's reply was cut off ("Could not parse JSON") and asked for again at the same limit. The designer now runs with reasoning effort "low" and 8000 max tokens (was 3000, which Gemini's thinking used up); `llm.call_json` no longer re-asks a reply cut off at the output limit (finish_reason "length"), it fails at once with that reason.

### Formula fit ranks instead of cutting off
Live run: with the cut-off at 0.5, eleven draws in a row were skipped (scores 18-49 %), among them the classic Z / van der Waals a / Boyle / critical-constants set at 37 %: Jev's probabilities are not calibrated. Now each draw scores `FIT_CANDIDATES` (6) random sets in parallel and writes the best (`best_draw`, `pick_best`); a low score never stops the writing; Jev down: the first set. About $0.0002 a draw.

### Formula-fit threshold 0.5
`FIT_REJECT_BELOW` 0.35 → 0.5 and `MAX_FIT_SKIPS` 12 → 20: a skipped draw costs about $0.00003, a written one several cents.

### The writer's values are variables of the forward program
Live run: the number program failed twice with "NameError: name 'P_wet_H2' is not defined" (it used the writer's names without defining them). `sandbox.run_forward(..., free=)` now defines every chosen value as a variable under its own name before solve() runs; the prompt says so; a remaining NameError lists the predefined names. A formula set Jev rated 28 % was skipped before any writing, as intended.

### Species names: states and subscripts
Live run: the engine said 'CH4(g)' "does not appear in" 'CH4(g) + CO2(g) → 2CO(g) + 2H2(g)': the equation parser drops "(g)", the comparison did not. `chem.species_key` (no spaces, no state, ASCII digits) is now used wherever a species is matched (stoichiometry, equilibrium, thermo, advanced), and `parse_formula` accepts a state suffix ('H2(g)' was "cannot read").

### Formula-fit check before writing; model check tool
- `qfirst.formulas_fit`: before any design or writing, Jev gives P(the drawn formulas make one natural problem); below `FIT_REJECT_BELOW` (0.35) the draw is skipped. Jev unreachable: the draw goes ahead. (A ppm + % w/V + softening + Faraday II set cost a design, three writes and a dozen coder calls before failing.)
- When the intended answer and the independent solve disagree, the writer is shown how the solver read each value.
- `tools/check_models.py`: one tiny call to every model the pipeline uses and to Jev; prints ✓/✗ and the spend.
- Draws Jev finds unfit do not count toward `MAX_DRAWS`; after `MAX_FIT_SKIPS` (12) the check stands aside, so a run always writes.
- `_fmt_number`: never Python notation (96500 had become "9.65e+04", 1000 "1.00e+03"); the writer's values keep all their digits (101325 had lost one).
- The forward coder is told the asked quantity's unit; the writer gives the intended value in the answer unit; a mismatch by exactly a power of ten tells the writer a unit is unclear.

### Placeholders required; fewer wasted calls (live run of 2026-11-16)
The writer ignored the placeholders and stated its own numbers (a negative equilibrium amount again); no question, $0.17.
- `qfirst.REQUIRE_PLACEHOLDERS`: a stem without `[[name]]` placeholders is sent back before any coder call.
- The coder stops after the same failure twice (it was 3 identical tries).
- The writer runs with reasoning effort "low" and 8000 max tokens (it was ~$0.02 a call).
- The spending cap is checked before every write attempt, not only per draw.
- Computed values are stated to 4 significant figures (at 3, a rounded EMF moved a K by ~2 %, past the intended-answer check).
- The forward (number) program also stops after the same failure twice; "comes out zero or negative" and "impossible result" now count as inconsistent data for the writer.
- `sandbox`: the wrong-unit hint is added only to out-of-range errors (it was also added to a species-name error, which misled the coder).
- Test: a stem with plain numbers is sent back once, then built from placeholders and accepted.
- Second live run: placeholders worked. Fixed: `solve_for` treats an overflow at the far end of the widened range as "no root" (it crashed with OverflowError); a wrong input kind names the input and the value passed ("input electrons must be a whole number, you passed 1e-07"); free values written as "5.0 × 10⁻³" or "300 K" are read (they were dropped); a value the writer also gave for a derived name is ignored (the engine computes it); the writer is told not to state a free value the answer follows from directly when an observation should lead to it.

### Numbers by construction
The most common live failure: the writer invents numbers that do not agree (a purity of 72264 %, a negative equilibrium amount) because it cannot do the arithmetic in its head.
- `core/pipeline/qfirst.py`: the writer writes every number as a placeholder `[[name]]`, gives values only for the independent ones (`free`, including the intended value of an asked input) and lists the ones that follow (`derived`: an observed EMF, a titre). `construct_numbers` has the coder write a forward program (`write_forward`) that computes the derived values (and the intended answer) through the engine's steps; `fill_template` puts them in (computed values to 3 significant figures, free ones with their figures). The independent solve() must then give back the intended answer (within 2 % or the rounding tolerance), or the question does not determine it and is rewritten. A question without placeholders goes the old way.
- `core/engine/sandbox.py`: `run_forward` (solve() returns a dict of named values; every drawn step must be called).
- Tests: a full run built this way; filling and refusals. Suite passes.

### Connected draws, a per-run spending cap, a cheaper designer
A run spent $0.21 on 6 draws and accepted nothing: most sets shared no quantity, so the writer refused them or the designer forced a link that then failed.
- `core/pipeline/adapters.py`, `random_formulas` **changed**: the first formula at random, each next one at random among those sharing a quantity (a graph node) with one already drawn. In a sample of 1000 draws, 91 % reach their size and use ~1.8 chapters.
- `run_groundup_final.py`: `--max-run-spend` (default $0.12; 0 for none); `qfirst.over_budget` stops new draws and refinement rounds once the run has spent it.
- `core/pipeline/qfirst.py`: the designer proposes 2 designs, briefly, with a 3000-token cap (it was 3 designs, 6000 tokens, 40 % of a run's cost).
- Tests: connected draws, the spending cap. Suite: 352 pass.

### From the live runs of 2026-11-16 (Codestral coder)
- `core/engine/sandbox.py`: only exact names `step_<number>` are formula calls (`step_100_result` is a variable).
- `core/pipeline/qfirst.py`: the feasibility check counts any value a question can state (an EMF or E°, a temperature, a mass) as provided and rejects only a formula that cannot fit the situation (it had rejected an Ag/Cu refining design for "no EMF given"); conversions and constants a question states (760, 101325, R, F, N_A ...: `STANDARD_NUMBERS`) need not be taken with given(); the coder is told that steps return dicts, that there is no `C` inside solve(), and to take givens before inner functions; an impossible engine value (a purity of 72264 %) is explained to the writer as inconsistent data (`explain`), and the coder stops retrying when it gets the same impossible value twice.
- `core/pipeline/gate.py`: given exponentials with superscripts or braces (`e² = 7.389`, `e^{2} = 7.389`).
- Tests: 6 more. Suite: 351 pass.

### Formula limits, feasibility check, wider root search, no LaTeX
A run designed around "an unknown metal sulfate" for formula 54, whose n-factor covers only MnO2/HCl and Cl2/hot alkali: 2 drafts and 6 programs failed before the draw was dropped.
- `core/pipeline/qfirst.py`: `formulas_text` lists each formula's limits (a "choice" input's cases), so the designer and the writer see them. `design_problem` (new): right after a design, the coder says whether a program could compute it with these formulas and their listed cases; if not, one redesign with the reason (`DESIGN_TRIES` 2), then a new draw. The writer is told never to use LaTeX.
- `core/engine/sandbox.py`, `solve_for`: `_bracket` scans the coder's range for a sign change and widens it up to 10⁶× before giving up.
- Tests: 4 more. Suite passes.

### Coder: Mistral Codestral, with a fallback; a coder failure no longer crashes a run
- `core/models.py`: `CODER` is `mistralai/codestral-2508` ($0.30/M in, $0.90/M out, no thinking); Qwen3 Coder Next's provider returned 502 on every call of its first live run. `CODER_FALLBACKS` (`mistralai/devstral-2512`) go to OpenRouter as `models`, tried in order if the coder fails. `ask_json` takes `fallbacks`.
- `core/pipeline/qfirst.py`, `program_for`: any coder error (a provider down after its retries) is a failed attempt, not a crash; out of credits (402) still stops the run.
- Tests: coder provider down; fallback named. Suite: 343 pass.

### Coder replaced; empty replies explained; discrete answers
- `core/models.py`: `CODER` is Qwen3 Coder Next (`qwen/qwen3-coder-next`, $0.12/M in, $0.80/M out, never thinks) instead of DeepSeek V4 Flash, which kept spending its whole budget thinking and replying empty even at low effort. `core/pipeline/qfirst.py`: coder output capped at 4000 tokens.
- `core/llm.py`, `call_json`: an empty reply says why (`finish_reason`), and an answer found in the model's reasoning field is used.
- `core/engine/sandbox.py`: "does each formula matter" scales a step's result by 1.001, then 0.5, 2, 0.1 and 10 (`RELEVANCE_FACTORS`): a discrete answer (a coordination number from a radius ratio) only moves when a result crosses a boundary.
- Tests: a step feeding a discrete answer. Suite: 341 pass.

### Design step, trimmed writer, stricter difficulty label
Compared with a reference question for the same draw, the pipeline's question was JEE Mains medium (straight plug-in, an arbitrary link, no concept trap) yet was labelled "advanced" because Phi-4 answered 3.8 × 10²⁸ L for 25.1 L.
- `core/pipeline/qfirst.py`, `design_question` (new): before writing, the generator (role "designer") proposes 3 designs (situation, links, the non-obvious insight, what is asked, the wrong routes it invites) and picks the best; the writer builds on it and must make the insight needed but never stated. Run once per draw (kept for rewrites and refinement rounds); "impossible" now usually comes from here, before any writing. The writer returns only stem, asks and unit (its hidden outline fields are gone; they were most of its output tokens).
- `core/pipeline/flow.py`: a bottom-step answer that is no number, or more than 1000× off the engine's (`_garbage`, `NONSENSE_FACTOR`), is asked again; nonsense twice means the bottom step's failure does not count, and a question the next step solves is too easy, not "advanced". Discarded attempts get no hint tests or engine-wrong checks.
- Tests: design runs once and reaches the writer; nonsense bottom answers; tests never call the real Jev. Suite passes.

### Second live run: coder cost, a give-away, an arbitrary link
Run cost $0.064; the Jev coherence check ran through OpenRouter ($0.00003).
- `core/pipeline/qfirst.py`: the coder runs at reasoning effort "low" (it spent 85k tokens, a third of the run, mostly on empty replies that ran out of room while thinking) and is told to call steps with keyword arguments; a third Jev coherence question, "arbitrary condition" ("until the heat absorbed equals 1.20 % of the electrical energy").
- `core/engine/sandbox.py`: a positional call to a step says how to call it (`step_117(n=..., T=..., V1=..., V2=...)`).
- `core/pipeline/gate.py`, `computed_values`: also catches given exponentials (`e^2.3214 = 10.19`, `exp(x) = y`).
- Tests: 3 more. Suite: 338 pass.

### Variety: no repeats of our own questions
- `core/pipeline/qfirst.py`: `accepted_questions` reads the subject's accepted computed questions; `question_problems` also rejects a draft too close to any of them (same test as for the two examples: 30 % of word 4-grams, or 3 distinctive values); `used_situations` gives the writer the openings of the 8 most recent accepted questions on the same chapters, as situations not to reuse.
- Tests: class `OwnQuestions` (3).

### First live run: an invented relation got through; three fixes
The first live run (cost $0.052) drew five formulas from three unrelated chapters; the writer joined them by a made-up law (ΔG° = −(purity × radial peaks × 100)) and the question was accepted as "frontier", hard only because it was not chemistry.
- `core/pipeline/adapters.py`, `random_formulas` **changed**: the first formula is drawn from all steps, the others from its topic and the topics bridged to it (`BRIDGES`).
- `core/pipeline/qfirst.py`: the writer's prompt forbids inventing any relation or gluing sub-problems (reply "impossible" instead); `coherence_problems` asks Jev two yes/no questions on every draft that passed the code checks ("invented relation", "glued parts"); 50 % or more on either sends it back to the writer. Jev unreachable: the check is skipped, never blocks. Spend under "coherence_check".
- `core/pipeline/refine.py`: `jev_decide` takes the spend role.
- Tests: class `Coherence` (4) and the related-chapters draw. Suite passes.

### Refinement loop: 8 cases decided by Jev, rewritten by the writer
- `core/pipeline/refine.py` (new): `CASES` (8 reasons a question was easy, each with a fixed instruction for the writer), `jev_decide` / `classify` (one Jev request, one yes/no question per unused case, probabilities only), `pick` (the likeliest unused case, one per round; the writer gets only that case's instruction), `instructions`.
- `core/pipeline/qfirst.py`: `refine_round` replaces the plain "too easy" rewrite: Jev decides, code picks and applies (a new twist for `plugin_order` / `one_system`, one more random formula for `too_few_steps`), the writer (Gemini 3.7 Flash, now for every rewrite) rewrites. No chat model takes part in the decision. Jev unreachable: a random unused case.
- `core/models.py`: `JEV_MODEL` (typesafe/jev-1.14), called through OpenRouter's Decisions API (`JEV_URL` = openrouter.ai/api/alpha/decisions; Jev is refused on /chat/completions) with the same `OPENROUTER_KEY`; $0.042 per million input tokens (spend under "refiner").
- Tests: `tests/test_qfirst.py` class `Refinement` (pick rules, Jev decides and the writer gets each case's instruction, one more formula, Jev unreachable, request shape) and the too-easy run. Suite: 328 tests pass.

## 2026-11-15

### Question first: examples, novelty, coder input
- `core/pipeline/qfirst.py`: the writer is told to write a hard JEE Advanced style question of its own and not to copy the two examples or put one of them into a different scenario; `too_close_to_past` compares the question only with those two examples (not every past paper).
- The coder sees, for each drawn formula, its chapter, formula, inputs, outputs and the engine's own code (`sandbox.step_source`: the `Step(...)` definition and the helpers its computation uses; trap code left out).
- Tests: `test_step_code_is_the_engines_own`, novelty against the shown examples only.

### Question-first generation for computed questions
Agreed flow: 3-5 formulas drawn truly at random (not a chain) → random twist → a model writes a new hard question on exactly those formulas → a second model writes a program that may only call those engine steps → code checks → ladder and verifier as before. Modelled on the "Infinite Problem Generator" paper (arXiv 2603.14486: formulas as code, 3-5 axioms, program-of-thought solving), with checks it lacks: the program must quote every value from the question, every step must feed the next, and the ladder and verifier still judge the result.
- `core/pipeline/qfirst.py` (new): the flow (`run`, `write_and_solve`, `program_for`), the writer and coder calls, the code checks (`program_problems`, `question_problems`), novelty against the two example questions the writer was shown (`too_close_to_past`), `rebuild_result` for parked items.
- `core/engine/sandbox.py` (new): `check_code` (static rules), `library_doc` (what the coder may call), `evaluate` (separate process, 30 s): answer, trace, givens, traps through the whole program, rounding tolerance, dependency depth, intermediates.
- `core/pipeline/adapters.py`: `random_formulas()` draws 3-5 steps uniformly from all 311, with no graph or chain condition; the writer connects them or replies `impossible` (redrawn, up to 6 draws per run). `all_chains()` / `random_chain()` (every linked chain of 3-5 steps; 6,994 physical) are kept for chain subjects such as organic, unused by the physical flow.
- The writer and the coder get only the drawn formulas (no catalogue: it cost ~5,000 words per call). The coder must call every drawn step and may write simple standard relations (n = m/M) and unit conversions itself, never a physical constant; any other graph step it calls still runs (`any_step=True`) and is recorded as `engine.extra_txs`.
- Check "every formula matters" (`sandbox`: each step's result scaled by 1.001 must move the answer) replaces "3 formulas in a row", which unrelated formulas cannot meet.
- `core/pipeline/flow.py`: `run()` hands chain runs to `qfirst.run()` when the config sets `question_first`.
- `run_groundup_final.py`: `--flow question|engine` (default question); records carry `generation_mode: question_first` and `engine.solver_code`; parking stores the program and recheck runs it again.
- `core/models.py`: `CODER` (DeepSeek V4 Flash, not the writer's family).
- `tools/build_twist_exemplars.py` (new) → `knowledge/jee_adv_twist_exemplars_physical.json`: real questions per twist (inverse 15, two-state ratio 15, simultaneous 10, condition 6, two-state difference 4).
- Tests: `tests/test_qfirst.py` (24: random formulas, another graph formula used by the program, an ignored step result, sandbox rules and timeout, checks, novelty, chain enumeration, full offline runs incl. coder retry, writer rewrite, too easy, park and recheck). `tests/test_pipeline_offline.py` runs the engine-first flow explicitly (`--flow engine`). Suite: 322 tests pass.
- Not yet run against the live models (no network from this machine). Refinement on "too easy" is a plain rewrite until the new refinement loop is designed.

### Physical engine: every formula of the JEE Advanced 2012-2025 physical questions
`docs/advanced_formula_map.py` listed 42 formulas real questions use that the engine had no step for. All are now steps, so all 91 mapped questions are made only of engine formulas.
- `core/engine/physical/advanced.py` (new, tx 348-392, 45 steps): molality ↔ mole fraction and molarity (348, 358, 362, 370, 373, 374), ΔT → molality (349), Bohr KE and Coulomb PE (350, 376), order from t₇₅/t₅₀ and from a mechanism (351, 390), ΔH per gram (352), acid-catalysis rate → pH (353), pH + C → K_a (354), Graham meeting point (355), energy balance between two processes (356), isothermal q = −w (357), mean free path and diffusion coefficient (359, 360), ICE from an extent (361), ΔG = −nFE non-standard (363), phase equilibrium under pressure (364), salt-of-weak-acid solubility at a pH (365), Hess on ΔG° (366), gas–solid partial pressure (367), K from A and E_a of both directions (368), ΔG° from K (369), residual ion after precipitation (371), rate from orders (372), adiabatic ΔT from useful work (375), ΔS° from an intercept (378), equivalents → moles with aliquot (379), photon recoil (380), calorimeter heat → ΔU, ΔfH by Hess (381, 382), E° from other couples (383), diprotic neutralisation → buffer (384), sulfate solubility with HSO₄⁻ (385), P from Z (386), area per adsorbed molecule (387), ΔS at another T via ΔC_p (388), ΔH = nC_pΔT (389), I = Q/t (391), w = −Δn_gRT (392).
- `core/engine/physical/equilibrium.py`, `tx 175` **changed**: [H⁺] of a weak acid now includes water's H⁺ (cubic, exact), so very dilute or very weak acids (2025 Q9) come out right; new trap `ignores_water`.
- Chain wiring for the new steps: `gives`/`carries`/`not_after` on existing steps so a chain never states a value twice or passes one on in another meaning (e.g. 356 only after a driven half-reaction, 357 and 375 not after 392, 361 not after 32, 369 not after 135).
- `core/engine/base.py`, `plan_tree`: a step that hands on a value it read (113 passing on the equation) no longer counts as computing it, so tree 113 + 131 → 132 is allowed again.
- `knowledge/concept_book_physical.json`: 45 entries (index 348-392) with their chapters; `knowledge/reaction_graph_physical.json` rebuilt: 185 nodes, 238 edges (was 174 / 199; no edge removed, ids stable).
- `docs/advanced_formula_map.py/.md`: MISSING entries replaced by tx ids; a `DATA:` mark for what a question needs that no formula gives (2013 P1 Q21 reads its order from a graph). 91/91 questions have every formula in the engine; 57 could be built by the walk as one chain (the rest are two-state, simultaneous or inverse uses).
- `tools/audit_engine.py`: units for the new outputs; expected repeats. Audit: 311 steps, 536 pairs, 998 triples, 0 flags.
- Tests: `tests/test_engine_advanced.py` (41) reproduces each question's published answer; `tests/engine_samples.py` fixtures for the new text/dict inputs. Suite: 298 tests pass.

### README and Flow brought up to date
- `README.md`: generation loop gains the Form step and the duplicate check before the stem; ladder bottom step Phi-4 (was Llama 3.3) and solution writer GPT-6 Luna (was Mistral Small 3.2) in the loop, the commitments and the models table; the verifier also checks the written solution; prerequisite Python 3.12+ (was 3.9+; `core/pipeline/stages.py` uses f-string syntax 3.10 rejects); tests run the whole suite plus `tools/audit_engine.py`; engine section adds the "nothing stated twice" rule and corrects the step count to 266; parking covers hint re-solves and the verifier; layout lists `forms` and `forms_layer`.
- `docs/Flow.md`: the same ladder and solution-writer corrections; duplicate check moved before the stem; the "nothing stated twice" rule in the engine section; parking, error sources and the organic/inorganic skip as above.

### Physical engine: chains that stated a value twice or passed one on in the wrong meaning
Found by reading every physical step and every pair of steps the walk can link (395 pairs), plus the 6 items in `queue_engine_wrong_physical.json`. The formula inside each step was correct in every case; the errors were in how steps join.
- `core/engine/physical/thermo.py`, `tx 114` (Kirchhoff) **bug fixed**: after a cell step (240), which fixes ΔS = nF(∂E/∂T), the ΔG step stated a second, free ΔS at T₂. Kirchhoff now carries a known ΔS and moves it to T₂ (ΔS(T₁) + ΔC_p ln(T₂/T₁)); with no ΔS known before it, ΔS stays a given. Accepted question GEN_20261014T021446 (240 → 114 → 132) was consistent only because its stated ΔS happened to equal the computed one.
- `core/engine/physical/electro_solutions.py`, `tx 239, 241` (Nernst, concentration cell) **bug fixed**: E from 0.0591/n is at 298 K, but the next step (240, ΔH from (∂E/∂T)) asked for a temperature that could differ. Both now hand T = 298 K on.
- `core/engine/physical/thermo.py`, `tx 125` (ΔS of an ideal gas) **bug fixed**: after a gas-law step had fixed P, V and T, the question also stated n, which could contradict PV/RT. n is now derived from the initial state (n = P₁V₁/RT₁) and never stated. A standalone ΔS question now states the initial pressure instead of the amount.
- `core/engine/physical/kinetics.py`, `tx 200 → 201` **bug fixed**: the rate of reaction −(1/a)Δ[A]/Δt was read as −d[A]/dt, so d[C]/dt came out too small by the factor a. The two rates now carry different roles and no longer link. `tx 200 → 202`: [A] of run 1 was stated twice; 200 now hands it on.
- `core/engine/physical/thermo.py`, `tx 135 → 154` **bug fixed**: K from ΔG° = −RT ln K is K° (K_p for a gas reaction) and was then treated as K_c in K_p = K_c(RT)^Δn. 135's K carries the role "K°"; 136 (van 't Hoff) and 155 (K_p → K_x) accept it, 154 does not.
- `core/engine/base.py`, `plan_tree` **bug fixed**: a tree could take an input from one branch when another branch's last step already computes it (van 't Hoff gives ΔS with ΔH; a redox-reagent step gives its molar mass with its n-factor). Such trees are refused.
- `core/engine/physical/thermo.py`: C_v of a linear triatomic gas is 5R/2 or 7R/2 depending on the book; the engine uses 7R/2 and now states it in the question's constants (`tx 115, 123, 125`). The other gas types are standard and are not given away.
- `tools/audit_engine.py`: unit of the new `concentration` output.
- The 6 queued engine_wrong items: 135 → 136 → 133 and 160 → 136 → 133 (a free ΔS stated next to two K values) were already fixed earlier (ΔS now comes from the van 't Hoff data); 155 → 136 → 133, 264 → 95 → 96 and 170 → 84 → 125 are already refused; 148 → 144 → 216 was the verifier misreading a trace that rounded 298.15 K, fixed earlier. None needed a new change.
- Tests: `tests/test_engine_audit.py` class `ChainMeaning` (7); each fails on the previous code. Audit: 597 triples (was 604), 0 flags.

### Duplicate check before any question call
- `core/pipeline/flow.py` **bug fixed**: the duplicate check ran after the stem was written and the gate had read it back, and the refiner could then choose "reword", which keeps the inputs and so hits the same duplicate on every later round. The check now runs first in each round (it needs only the steps and values), and a duplicate always asks for new inputs.
- Tests: `test_duplicate_inputs_cost_no_question_calls` (a repeat run makes only input-proposal calls).

### Unmeasured attempts park the question; organic and inorganic reported up front
- `core/pipeline/flow.py` **bug fixed**: `CouncilMemberFailed` from a hint re-solve (`stages.solve_with_hint`), and any failure of the mismatch verifier, were not caught: the run crashed with a traceback and the question was lost. `judge()` now turns any unmeasured solver or verifier call into `Parked` (exit 3, judged again next run). A failed clarification-hint call falls back to the verifier's own clarification, as a cut-off reply already did.
- `run_groundup_final.py` **bug fixed**: a parked fact question whose subject has no fact adapter raised `NotImplementedError` on every later run; it is now dropped like any question that cannot be recomputed. `--kind auto` ignores a `fact_share` on a subject with no fact adapter instead of exiting 2.
- `generate_questions.py`: a subject with no engine in `core/pipeline/adapters.py` (organic, inorganic) is reported before any run is launched, skipped, and marked "no engine for this subject" in the summary; the batch exits 1 at once if no requested subject has an engine.
- `subject_config.py`: removed keys nothing reads (`chemist_role`, `default_chapter`, `seed_id_prefix`, `start_nodes`, `mandatory_checks_block`, `verifier_checks_block`); the check blocks were prompts of the pre-engine pipeline and remain in git history.
- `core/graph_traversal.py`: removed the LLM tool-call layer of the pre-engine pipeline (`get_edges_from`, `get_paths`, `get_node`, `get_coverage` wrappers, `dispatch_tool`, `GRAPH_TOOLS`); nothing called them. `get_ordering()` (reads `knowledge/reaction_orders.json`) is kept.
- Tests: `test_hint_resolve_failure_parks`, `test_verifier_failure_parks`, `test_parked_fact_without_a_fact_engine_is_dropped`; 257 in total.

## 2026-10-14

### Trees and conditions in the pipeline; K_b of a solvent no longer read as a base's K_b
- `core/engine/base.py`: a step may read any earlier step's output (`("step", (j, field))` wiring), so a plan can be a tree. `plan_tree(branches, final, feeds, share, merge)` joins chains computed separately into one merging step; the same given in two branches (same field, description, unit) becomes one value; a tree is refused when one branch states a value another computes. run_chain, traps, rounding tolerance and the forms all run trees unchanged. Reproduces 2020 P2 Q17 (T = ΔH/ΔS = 935 K) as one plan.
- `core/engine/forms.py`: `compare_step` and `plan_condition`: two systems, the last step their difference.
- `core/pipeline/forms_layer.py`: condition form: the generator's value of the unknown is kept, one stated condition of the second system (a temperature, pressure, amount, never a substance property) is set to 3 s.f. so the two results are equal there, and exactly one value of the unknown in its range must then give equality (else refused). Traps, tolerance from 4-s.f. statement shifts. A tree is asked as itself (form "tree") or in another form; a condition only as a condition.
- `core/pipeline/adapters.py`: question ideas are now 25% trees and 10% conditions. A tree's parts each feed the merging step their own result (never a value they were given and hand on) and stay within the merging step's topic; two parts never end in the same step. A condition asks for a temperature, time or pressure (never a constant or a half-life), compares a quantity that changes with conditions (not a molar mass), and is offered only if it can be posed for 3 of 8 random value sets (no generator call is spent on one that cannot). Repeated input descriptions are labelled (first system / second system / for the ΔH). Generator text says which part each step belongs to.
- `core/pipeline/flow.py`: a tree or condition is never shortened like a chain; a condition that cannot be posed with the generator's values drops the idea. **Bug fixed**: a parked question asked in a form was judged again as the forward chain (wrong answer for the stem); the form's stated values and result are now parked and restored (`run_groundup_final.py`), with the shape to rebuild the plan. Records gain `engine.shape`.
- `core/engine/physical/electro_solutions.py` **bug fixed**: ΔT_b = i K_b m handed its ebullioscopic K_b on as "Kb", which the pH steps (176, 181, 183) read as a base's dissociation constant; a walk could build ΔT_b -> pH of a salt. Only K_f is handed on now.
- Coverage check on the 91 mapped Advanced questions: 26 can be built now (25 chain + form, 1 tree); 41 need a missing formula, 14 have their formulas but the steps do not join, 8 read a graph / want an expression / need calculus, 2 conditions not reachable.
- Tests: `tests/test_forms_shapes.py` (12); 246 in total; audit 0 flags.

### Question forms: chains are used backwards, in two states and simultaneously, not only forwards
- Why: of 91 real JEE Advanced questions mapped (`docs/advanced_formula_map.md`, `docs/analysis_advanced_formula_use.md`), only 25 use their formulas as a forward chain; the rest hide an input, compare two states, or solve two statements together. Phi-4 fails 22% of forward vs 53% of non-forward Advanced questions. With the forms, 39 of the 91 can be made from engine formulas (was 9).
- `core/engine/forms.py` (new): `Inverse` (state the result, ask an input; unique root in a realistic range by sign-change scan + bisection, else refused; trap roots kept), `TwoState` (ratio of the result in two cases differing in one input), `Simultaneous` (two cases, two shared unknowns; Jacobian condition check, refused if not unique or ill-conditioned), `Condition` and `Tree` (multi-chain; engine only, not yet in the pipeline). `tests/test_engine_forms.py` reproduces 9 real Advanced answers (2016P2Q21, 2012P1Q36, 2024P2Q9, 2014P1Q38, 2015P2Q27, 2020P2Q14, 2020P2Q17, 2021P2Q17, 2023P2Q11).
- `core/pipeline/forms_layer.py` (new): after the generator's values run forward, `apply_form` picks a form (weights inverse 3, two-state 3, simultaneous 2, forward 1; a fragile inverse with tolerance > 2% is skipped) and returns the stated spec/values the gate checks, the answer, traps, tolerance, a note for the stem writer (never the answer) and a note for the verifier/answer key. Falls back to forward when nothing fits.
- `core/pipeline/flow.py`: form applied after the inputs and again after a "new inputs" refinement, avoiding the form the ladder just solved; the stem writer gets the form's note and asks; the trace given to the verifier and answer key ends with the form note.
- `run_groundup_final.py`: records `form`, `form_detail`, `form_note`.
- Tests: `tests/test_forms_pipeline.py` (160 sampled engine chains: inverse fits 141, two-state 145, simultaneous 46; stated values match the gate spec, hidden inputs never stated, gate and grading round trips, wiring through `flow.run`); 234 tests in total. `requirements.txt` adds scipy.

### Ladder bottom step Phi-4; answer key by GPT-6 Luna; replies read more robustly
- `core/models.py`: `LADDER` = Phi-4 → GLM-5.3-Flash → GPT-6 Luna (was Llama 3.3 70B at the bottom); `SOLUTION_WRITER` = GPT-6 Luna (was Mistral Small 3.2). Calibration of Phi-4, Llama 4 Scout and Granite 4.2 8B on the 96 saved JEE questions ($0.15 in all); `calibration/ladder_separation.py` (new) prints each model's failure rate on easy/medium Mains, hard Mains and Advanced, the gap and the cost per question. See Decisions.
- `core/models.py`: `MAX_OUTPUT_TOKENS` caps the output for models with a small context (Phi-4, Scout: 8000); `NO_JSON_MODE` asks for JSON in the prompt only where the providers refuse JSON mode (Scout: every call was a 404 "no endpoints").
- `core/llm.py`: `parse_json` reads replies with quotes left unescaped inside a string (`the "crossed Cannizzaro" reaction`), raw line breaks and LaTeX backslashes, alone or together (Phi-4 lost one calibration answer this way; 4 more were saved by retries). Every reply that still cannot be read is kept whole in `outputs/unparseable_replies.jsonl` with model and finish reason. `tests/test_json_parsing.py` (9 tests, incl. 5000 random valid replies unchanged).
- Granite's "blank" answers were debugged: the replies are complete JSON with `final_answer: null` and an "insufficient data" objection on solvable questions, not a parsing fault.

### Answers stated as the question asks (3 s.f.) to the solution writer, checker and verifier
- Run 13: the engine keeps 4 significant figures (1.538) but the stem asks for 3 (1.54). The checker rightly called "1.538 to three significant figures" false, then called the writer's 1.54 a mismatch with the reference; all three drafts failed and the question was saved without a solution. `flow.stated_answer` rounds numbers to `answers.SIG_FIGS` (whole numbers, text and letters unchanged); the trace's final line, the solution writer and checker, the mismatch verifier and the record's `answer_text` use it ("Final answer: 1.54 (as the question asks; unrounded 1.538)"). Grading still compares with the engine's value.

### Engine audit: every chain checked offline, every error found fixed
- Run 12 lost two of three chains to engine errors (K_x fed into van 't Hoff; ΔS° stated alongside K₁ and K₂, contradicting them). Both were of a kind already known (the over-determined PCl5 chain). `tools/audit_engine.py` (new) now checks every chain the walk can build (266 single steps, 382 pairs, 604 triples) before any model is paid: a value passed in another unit than the next step reads, a value a later step asks for again, and a run of every chain on 20 sampled inputs (`tests/engine_samples.py`) that must give a finite answer with a readable unit or refuse cleanly. Result: 0 flags, every chain runs.
- Engine mechanics (`core/engine/base.py`): a role may be a tuple of accepted roles and `strict` (an untagged value is refused); `Step.not_after` / `not_after_any` refuse pairs (or earlier steps anywhere in the chain) that are valid by field name but wrong in meaning; `Step.carries` passes on a value a step holds constant (Charles's law at constant P hands that P on); an answer unit may depend on the inputs.
- Wrong numbers fixed: Kp from α for any single-reactant dissociation (A ⇌ B + C and A ⇌ 2B differ by 4×); separation factor ≥ 1 whichever gas is called 1 (0.25⁶ was reported for 4⁶); ion notation 'Fe2+', 'Fe²⁺', 'SO42-', 'Cr2O72-' read by the exam convention (Fe2+ was Fe₂⁺ and Fe²⁺ crashed, so redox balancing failed or balanced nonsense); eudiometry no longer fed a volume in L into its mL input.
- Contradictory or repeated data removed: van 't Hoff gives ΔS° (ΔG°(T₁) = −RT₁ ln K₁) so T = ΔH/ΔS and ΔG = ΔH − TΔS never state a second ΔS; ΔS = nF(∂E/∂T) likewise from the EMF step; ΔH stated once is never recomputed from two K values later in the chain; temperatures are carried (ΔG° -> K -> van 't Hoff T₁, K at T₂ -> K_p, Kirchhoff T₁/T₂, isotonic T, gas processes); total pressure is the sum of the partial pressures; vapour density's D and n come from the equation; the equation, solution density, solute molar mass, water mass, K_f, electrons, atoms per formula and a reagent's molar mass (from its formula) are passed on instead of asked again.
- Wrong meanings refused: K_p/K_x compared with a Q from concentrations (157 needs K_c); K_x into van 't Hoff; ΔS of the surroundings wired in as the system's; a non-standard EMF into ΔG° or K_sp; neutralisation/hydration/dilution/atomization ΔH into ΔG, T = ΔH/ΔS, Kirchhoff or E_a; Kirchhoff after a constant-ΔH (van 't Hoff) result; an nth-order half-life into λ = 0.693/t½; a common-ion, mixed-salt or complex solubility back into K_sp; molar mass from ΔT after a ΔT computed with i ≠ 1; a pure liquid's vapour pressure as a solution's total (and back); an element's atoms as gas molecules; an ionic compound as a gas; fixed substances (ethanol, antifreeze, a deposited metal, the azide) only where they belong; a solid-decomposition equilibrium pressure into Boyle/Charles/Dalton; van der Waals a from ideal-gas-law results; Amagat's total volume as a component; K_b of a conjugate base as a weak base's; circular pairs (peaks -> orbital, π -> C -> π).
- Units: x/m in g g⁻¹; a critical constant in K, atm or L mol⁻¹ by the one asked; K_p in atm^Δn and K_c in (mol L⁻¹)^Δn (no more "cannot be converted to ''" restates); the nth-order rate constant's units stated.
- Prompts: the generator now reads, for each step, what it takes from the step before ("takes from step 2: 'amount of Cr2O7²⁻ reduced to Cr³⁺'"), so it picks substances that make the chain literally true; the stem's "Given:" line may hold only listed values, never a computed one; the gate refuses a stem that gives the logarithm of anything but a table number (run 12's "ln(13.25) = 2.584").
- Tests: `tests/test_engine_audit.py` (38 tests) pins every fix and runs the whole audit; 201 tests in total.

### Written solutions are checked step by step; gate reads formulas, not exact strings
- Run 11's published solution was wrong although its final answer was right ("0.025 mol × 46 g mol⁻¹ = 1.725 g", "1 mol K2Cr2O7 to 4 mol ethanol"); run 10's had "(0.028005 − 0.0115) / 2 = 0.016505". Nothing checked the solution writer.
- `core/solution_check.py` (new), in code: every written calculation "<expression> = <number>" must be true, units allowed in the expression ("0.025 mol × 46 g mol⁻¹"), powers of ten read as one number ("963.2 / 5.226 × 10⁻²"), unit exponents ("day^-1") and "(0.4)²" read, chained equalities each checked, rounding of the stated result allowed. Lines that cannot be read with certainty are left alone: reactions, formulas or variables inside a calculation, "log 2" without brackets, LaTeX, unit statements ("1 L = 10^-3 m³"), and results that an unstated unit change could explain (J -> kJ, days -> s, a kJ + J sum). Also: each step's result from the engine trace and the final answer must appear, and the last line must give the final answer.
- `stages.check_solution`: the mismatch verifier (Claude Haiku, role `solution_checker`) reads the numbered solution against the exact computation and returns each wrong line (wrong ratio / n-factor / molar mass, false arithmetic, mislabelled quantity, contradiction, wrong final answer). An error counts only if its quote is in the solution (near word for word) or it names an existing line.
- `flow.checked_solution`: write -> code check -> verifier (only for drafts code finds clean) -> rewrite with the errors listed, at most 2 rewrites. Only a draft that passes both is saved; otherwise `solution` is empty and `solution_check` records why (verified / failed_check / writer_failed / checker_failed) with every draft and error. The writer prompt now asks for each step's arithmetic written out and true, and ratios derived from the step's formula.
- Real data: run over all 34 solutions saved in the repo, the code check flags exactly the two wrong ones (runs 10 and 11); its first version also flagged 13 correct lines, now regression cases.
- Gate (`gate._eq_text`): species compared as formulas ignoring notation (subscripts, superscripts, state labels, "·", charge written "2-" / "^2-" / "²⁻"; isomers stay different), also when the stem's name comes with it ("iron (Fe)", "Fe (iron)"). Equations compared species by species, any order or arrow. A reaction told in words with formulas ("Fe3O4 is converted into Fe2(SO4)3") states an equation whose coefficients are all 1, reactants before products. Comma lists of species compare in any order. Names alone are not read (no name table).
- Generator prompt: every element, compound or ion named in words gets its formula in brackets after the name ("iron (Fe)", "potassium dichromate (K₂Cr₂O₇)"), as JEE papers do. Extractor: copies the formula the stem gives, and writes a reaction told in words as "X -> Y".
- Tests: `tests/test_solution_gate_stress.py` (34 tests): 55 true lines, 20 false, 15 unreadable, 2000 random calculations (true always pass; 6 % off, ×10, sign, /1.07 caught), garbage fuzz, trace/final checks, number formats, several values and letter answers, the write/check/rewrite loop (8 cases incl. failures and reply shapes), name+formula forms, notation variants, charges, 6 equations × 20 shuffled variants, reactions in words, lists, the run-11 gate form (166 tests in total).

### Generator prompt: exam-style wording
- `stages.write_stem`: the stem in run 10 read "a mass of the substance equal to 2.719 g of pure sulfamic acid" and "Assuming each formula unit of NaOH ... yields 2 ions". The prompt now says the value labels are generic internal names and each thing must be called by its actual name from the scenario; it gives bad → good phrasing examples ("2.719 g of sulfamic acid", "100.0 mL of the Ag⁺ solution", "0.05 M acetic acid"); supporting data (molar/equivalent masses, dissociation, stoichiometric factors) goes in one closing "(Given: ...)" line instead of "Assuming ..." sentences; no filler; and it ends with an examiner re-read that may rewrite phrasing but not values. The values, gate and refiner path are unchanged.

### Slip confirmation for every value; per-value units; more multi-value tests
- Slip confirmation applies to every value (`flow._slip_confirmed`): the verifier gives one set-up expression per value (a list in the reference's order, null where the value is right; a string for one value). Each wrong value must be explained by its own expression, evaluating to the engine's value and grounded in the working; one unexplained value fails the attempt.
- Per-value target units (`answers.target_units`): a question can ask ΔH in kJ mol⁻¹, ΔS in J K⁻¹ mol⁻¹ and ΔG in kJ mol⁻¹ in one answer; stems read "Give the 3 answers to 3 significant figures, in the order: ΔH in kJ mol⁻¹; ΔS in J K⁻¹ mol⁻¹; ΔG in kJ mol⁻¹."
- Bug found by the new tests: values listed in another order than the question's (labelled) were converted to the target unit by position, before pairing. `complete_answer` now reorders by label first. Labels compare case-insensitively unless that makes the question's own labels collide (T and t, K and k).
- `answers.align_values / value_ok / label_keys` shared by matching and slip confirmation.
- Tests: 12 realistic multi-value examples with 40+ answer lines (Haber partial pressures in atm/torr/mmHg/kPa/bar, ΔH/ΔS/ΔG with own units, buffer ion concentrations, masses in series cells, electrolysis gas volumes, mixed mol/mmol, boiling/freezing points in °C, rates per min, complex ions with brackets, named substances, Kp/Kc in Pa⁻² and dm⁶ mol⁻², four unlabelled values); 1500 random shuffled answers whose values are all different kinds of quantity; ten per-value slip cases (132 tests).

### Several values in one answer
- Grading only ever compared one value; a correct multi-substance answer would have been graded wrong. `answers.numeric_values` / `values_match`: an engine answer may be a list (optionally labelled with `answer_substances`). Values are paired by substance when both sides name them (formula keys, so N₂, N2 and N2(g) agree; the member must name the same substances, no duplicates) and by position otherwise; each value is checked against the tolerance (0 needs |x| ≤ 1e-9); the count must match, and a wrong count is a restate request, not a grade.
- `answer_spec(..., substances)` carries the count and substances; the solver prompt asks for exactly that many values and the order; stems end with "Give the 2 answers in atm, to 3 significant figures, in the order: N2, H2."; `answer_text` lists "N2: 0.75 atm, H2: 0.25 atm". Slip confirmation stays single-value only.
- Stress tests: the user's example and variants (swapped labelled order, one shared unit, subscripts, state labels, unlabelled), wrong value, wrong or duplicate substance, forgotten unit conversion, wrong counts, zero values, 1500 random 2–4-value permutations in other units (and each with one value 5 % off), stem/prompt text, `_solve` repair and grading; the fuzzer includes a two-value spec (119 tests).

### Grading stress suite
- `tests/test_grading_stress.py` (new, offline): every engine unit parses and round-trips; 100+ plain-text writings of the engine units (caret, `**`, `·`, slash forms) convert to exactly 1; 38 known conversion factors including offset temperatures; different kinds are refused; 14 formatting variants of the answer line (case, spacing, field order, code fences, Unicode minus, trailing text, JSON objects) parse the same; brackets and commas inside values; 4000 random correct answers across 60 orders of magnitude in other units match and 28000 wrong ones (unit factors, ±10×, 2.2× tolerance off, sign) never do; number formats that must trigger a restate; choice, yes/no, letters and text shapes; every row of the decision table; malformed verifier replies; 3000+ fuzzed inputs through parsing, completion, matching and grading without an exception; seven solver reply shapes through `stages._solve`.
- Fixes it found: values containing brackets (`[SUBSTANCE: K4[Fe(CN)6]]`) cut at the first `]`; Unicode minus rejected; answers given as a JSON object not read; text answers with commas split; `_grade` raised on a verifier reply without `verdict`; an engine answer of exactly 0 could only match 0 exactly (now |x| ≤ 1e-9).
- 112 tests across the three suites.

### Structured answer line and pint unit conversion (user's design)
- Solvers now end with one line `[TYPE: …] [CALC_VALUE: …] [CALC_UNIT: …] [SUBSTANCE: …]`: the number they calculated, as a plain decimal or e-notation number, and the unit of exactly that number. Code fills `TARGET_UNIT` (from the question), `FINAL_VALUE` (CALC_VALUE converted, `core/units.py`) and `RENDER` (final value + target unit); anything a solver writes in those three fields is ignored. Lists (several substances) are compared element by element.
- `core/units.py` (new): conversion on the pint library (`pint>=0.26`, added to requirements.txt with sympy, which the engine already used). Exam notation ("kJ mol⁻¹", "g mL⁻¹", "dm³", "°C", "mm Hg", "M", "% w/W", "ppm (as CaCO3)", "g eq⁻¹") and plain text ("kJ/mol", "mol L^-1", "s-1") are both read; all 73 units used by the physical engine parse. Different kinds of quantity are refused (L → kg, eV per particle → kJ mol⁻¹). The hand-written unit table in `answers.py` is gone; `convert_unit` wraps pint.
- `answers.parse_answer_line / complete_answer`: a line that cannot be used (no CALC_VALUE, not a plain number, unreadable or inconvertible unit, wrong number of values, not an allowed option) gives a reason; `stages._repair_line` sends one restate-only request with that reason. Only if that fails too does grading fall back to the verifier's `answer_equivalent`.
- Numeric stems end with "Give the answer in <unit>, to 3 significant figures." (or "as an integer" for counts), checked by the gate.
- `flow._code_match` compares FINAL_VALUE with the engine's answer directly.
- Tests rewritten for the line, including the user's two examples (89 tests).

### Run 8: trace precision, overruled reference-wrong claims, every run saved
- Run 8 (no question accepted, $0.131): all numeric gradings were right (within 0–0.7 % or confirmed slips). One chain was dropped wrongly as engine_wrong: the engine was right (q = 0.795 × 3.60 = 2.862 kJ → Eₐ,back = 69.74 kJ mol⁻¹), but the trace shown to the verifier rounded the given 298.15 K / 301.75 K to 298.1 / 301.8, so the verifier saw an "inconsistent reference" when GLM slipped.
- `base.run_chain`: trace inputs exactly as given; intermediate outputs at 5 s.f.
- `flow.judge`: a "reference wrong" judgement is overruled (recorded as `reference_wrong_overruled_by`) when another step reached the engine's answer with a "correct" verdict.
- `run_groundup_final._save_run_blackboard`: every run's full Blackboard goes to `outputs/runs/` (next to the configured output file), accepted or not, for auditing.
- Tests (88).

### Slip confirmation must be grounded in the solver's own working
- Run 7 (no question accepted, $0.088): Llama 3.3 answered 0.2915 kJ for 307.4 kJ and was counted as solved because the verifier labelled it a slip and wrote the correct set-up (0.45 × 6 × 96500 × 1.18) itself. `flow._grounded()`: a slip is confirmed only if every number in the verifier's expression appears in the member's working (within 0.5 %), apart from powers of ten (unit factors) and at most one substituted value (the miscopied number).
- The rest of run 7 graded correctly: answers within 0.04–0.13 % with a slip counted as solved; two chains went to `engine_wrong`, both engine or chain faults the verifier explained — the separation-factor step computes the inverse of the ratio the question asks ("methane relative to the solute": 4⁶, not 0.25⁶), and the 170 → 84 → 125 chain wired V₁ = V₂ = 12.5 L although the stem states 5.0 L.
- Tests updated: slip rows carry working; the run-7 case and a genuine miscopy (86 tests).

### Writer replies cut off by thinking no longer crash a run
- Run 6: answer matching held (Llama's "2" and "2.0" read correctly; too easy twice), then the refiner's input proposal was cut off mid-JSON three times (its thinking used the 3000-token cap) and the run crashed.
- Token caps raised for thinking writers and checkers (inputs and stems 16000; refinement choice, fact stems, gate extraction, verifier and solutions 8000; clarification hints and format repair 4000). Only tokens used are billed.
- An unusable writer reply is a failed attempt: input proposals count toward `INPUT_TRIES`, stems toward the gate retries; a failed refinement choice or clarification hint falls back to a default. Test for cut-off replies (86 tests).

### Answer form fixed at the source; complete decision table
- `answers.answer_spec / spec_instruction / format_ok`: each solver gets the exact form of its final answer — a JSON number in the asked unit, one of the listed options (parsed from the answer instruction), or option letters. `stages._repair_format()`: a reply that breaks the form gets one short request to restate the same answer (it must not re-solve); the raw answer is kept (`raw_final_answer`, `format_repaired`). Grading falls back to the verifier's `answer_equivalent` only if the repair fails too.
- Numeric stems must end with "Give the answer in <unit>." (`flow._answer_instruction`), checked verbatim by the gate like the option instructions.
- Decision table: within tolerance by a wrong method (run 5: −190.28 vs −192.2 kJ mol⁻¹ by linear extrapolation) or by wrong reasoning is not solved; within tolerance with only a slip is solved.
- `_fmt_value` always writes scientific notation correctly (0.00035 was printed "0.00035 × 10⁰").
- Run 5 accepted GEN_20261014T021446 as advanced (cell EMF and dE/dT → ΔH, Kirchhoff with ΔCp, ΔG = ΔH − TΔS); Llama 3.3 failed conceptually, GLM solved. Cost $0.036.
- Tests: `AnswerSpec`, `GeneratedVariants` (many writings of correct answers match; every trap value does not; units by stated unit), decision-table rows (85 tests).

### Answer matching audited end to end
- Numeric answers in the pipeline now use `answers.numeric_value` (it was only in calibration): fractions (11/51), expressions (ln(4)/2), × 10ⁿ in every form. Superscript exponents are read as powers (1.51×10⁻¹⁵ was being read as 1.51 × (10 − 15)).
- A number in another unit than the one asked is converted using the unit the member STATED (`answers.convert_unit`: length, volume, mass, amount, concentration, time, energy, pressure, potential, charge, conductance), so 156100 J mol⁻¹ matches 156.1 kJ mol⁻¹ but 156100 "kJ mol⁻¹" (the not-converted trap) does not.
- When code cannot read a numeric answer at all (a number wrapped in words), the verifier's `answer_equivalent` decides, as for text answers; when code can read it, code decides.
- Hint re-solves use the same rule.
- `GradingStress` tests cover every answer form seen in live runs (76 tests). Re-grading the stored council answers of all three wrongly accepted live questions now marks each as solved by its solvers, i.e. too easy.

### First live run with the ladder
- Run 4 (airbag: NaN₃ solution → N₂ → Amagat with argon) was accepted as "advanced", wrongly: Llama 3.3 answered 29.52 L against 29.79 L, inside tolerance, but the verifier labelled a slip on the way and a matching answer only counted with verdict "correct". Rejected (GEN_20261014T020357).
- `flow._grade()`: a final answer within tolerance counts as solved unless the verdict is "right answer by wrong reasoning".
- The new prompts gave a realistic, cue-free stem, but the chain is still a three-step plug-in. Cost $0.028.

### Difficulty ladder replaces the council; prompts aimed at harder questions
- `core/models.py`: `LADDER` = Llama 3.3 70B (Meta) → GLM-5.3-Flash (Z.ai) → GPT-6 Luna (OpenAI); `COUNCIL` is now an alias of it; Qwen3.8-Flash removed. `DIFFICULTY_LABELS`.
- `flow.judge()`: each step is called only after every step below failed. The bottom step solving it means too easy; otherwise the question is accepted (after hint tests) and labelled by the first step that solved it: advanced (GLM), hard_advanced (Luna), frontier (none). Records gain `ladder_first_solver` and `difficulty_label`.
- Why: on real papers (Mains n = 47, Advanced n = 49) Llama 3.3 fails 29 % of easy/medium Mains but 66 % of Advanced-level questions (Advanced plus the hardest third of Mains by `calculated_difficulty`); GLM, Qwen3.5-35B, Llama 4 Maverick and Luna separate the two far less. Calibration runs added for Qwen3.5-35B, Llama 4 Maverick and Llama 3.3 70B.
- `stages.propose_inputs()` gets the chain's trap descriptions and is told to pick values where shortcuts and approximations mislead and each mistake gives a different, believable answer. `write_stem()` must not name the method or hint at steps, must not list data in solution order, must frame a concrete system, asks only the final quantity, and lists the cues it avoided (`easy_cues_avoided`).
- Tests rewritten for the ladder (69).

### JEE Mains calibration set; ladder candidates
- `data/jee_mains/` (new): 24 JEE Main papers, 2020–2026, same schema as the Advanced set. Eight 2024–2026 numerical items whose structure or scheme is not in the text carry `exclude_reason`.
- `anchor_calibration.py --set mains [--years]` (default 2024–2026, the papers least likely to be in training data; numerical "NAT" items only). Mains answers are integers, so the grader rounds the model's answer to the nearest integer for that set. Results files get a `_mains` suffix.
- Results (council settings): Mains n = 47 — GLM-5.3-Flash 87 %, GPT-6 Luna 96 %; Advanced n = 49 — GLM 71 %, Luna 92 %. MiniMax M3 on Advanced: 36/49 with 10 unanswered, $0.53 — not stronger than Luna, not used.

### Calibration set cleaned; council calibrated on real JEE Advanced
- `data/jee_advanced/2023.json`, `2024.json`: answer keys checked against published solutions. Eight keys corrected (e.g. U-238 age 13.5 → 143, monolayer area 2.5 → 2500, pentaerythritol ketal 8 → 18) and one transcription fixed ("dimethylchlorosilane" → "dimethyldichlorosilane"); each record keeps `key_correction` / `text_correction` with the old value, sources and date. Five items carry `exclude_reason` (missing paragraph text, a missing plot, a disputed or unconfirmed key) and are skipped by both calibration loaders.
- `core/answers.numeric_value()`: one reader for final answers — safe arithmetic first (so "11/51" is 0.216, not 51), then labels, units and × 10ⁿ. Used by `calibration/anchor_calibration.py` and `calibration/council_eval.py`.
- `anchor_calibration.py --regrade`: re-scores a saved results file with the current keys and grader, no API calls.
- Council results (n = 49, council settings): GPT-6 Luna 45/49 (92 %), Qwen3.8-Flash 44/49 (90 %), GLM-5.3-Flash 35/49 (71 %); older runs re-scored: GPT-OSS-120B 30/49 (61 %), Qwen3-235B 23/49 (47 %). Members solving each question: 3 → 33, 2 → 12, 1 → 1, 0 → 3. Calibration cost $0.31.
- README and the approach PDF text updated with these figures.

## 2026-10-13

### Fixes from reviewing the third question: fragile asks, solution text, trap labels
- `flow._stable_ask()`: when a numeric answer's rounding tolerance is above 2 % (`FRAGILE_TOL`), the chain drops its last step and asks the previous result with the same inputs (run 3: e^(−Eₐ/RT) = 1.5 × 10⁻¹⁵ becomes "activation energy" = 156 kJ mol⁻¹), as a JEE paper would. Applied after the first inputs and after every refinement; noted on the Blackboard as `shortened`.
- `stages.write_solution()` asks for one plain-text string; `_solution_text()` flattens a structure (`{"step1": {...}}`) into numbered lines if one comes back anyway.
- `base.run_chain()`: when two steps of a chain share a trap description, each names its step ("uses log₁₀ without 2.303, when finding the activation energy"). Trap ids for the same mistake unified (`log10`, `forgets_2303` → `log10_without_2303` in kinetics), so coverage counts one trap type.
- Tests: 67.

### Third live run: rounding tolerance, blank replies, slip expressions, LaTeX JSON
- Run: a kinetics chain (rate law → k → Eₐ → fraction above Eₐ) was too easy for three rounds; round 3 was accepted with 1/3 solved, wrongly. Cost $0.0875 for four rounds (refiner 41 %, council 25 %, generator 20 %, verifier 12 %). The question (GEN_20261013T135458) is rejected.
- Why it was wrong: Qwen3.8-Flash sent a blank reply, graded as a failure; GLM-5.3-Flash was off 3 % only because the answer is e^(−34.1) (rounding the exponent by 0.03 moves it 3 %), and the slip check could not read the verifier's "a = b ≈ c" expression.
- `core/engine/base.py`: `ChainResult.tolerance`. `rounding_tolerance()` re-runs the chain with every intermediate rounded to 3 significant figures; if that moves the answer more than 1 %, the tolerance is 1.5× that shift (max 10 %). Traps inside the tolerance are dropped. `answers.matches(..., rel_tol)` and grading use it.
- `flow._eval_expression()`: the slip check evaluates the first plain-arithmetic segment of an expression written as a chain of = / ≈.
- `stages._solve()`: a blank reply (no answer, no working) is asked again twice; still blank raises, so the question parks instead of being graded.
- `core/llm.parse_json()`: invalid JSON escapes from LaTeX (\Delta, \ce) are repaired; valid escapes are kept.
- Refiner suggestions the engine cannot express yet (modified Arrhenius k = A·Tᵐ·e^(−Eₐ/RT); following a reaction by total pressure in a rigid vessel) are noted for the planned harder-engine work.
- Tests: 64.

### Out of credits stops cleanly
- `run_groundup_final.py`: an OpenRouter 402 (no credits) ends the run with `EXIT_NO_CREDITS` (5) and a message instead of a traceback; a council 402 parks the question as before. `generate_questions.py` stops the batch on exit 5.
- Found in the second live run, which also queued its first `engine_wrong` item (an over-determined thermodynamics chain, see Decisions / pending engine fix).

### Stems state the answer format for non-numeric answers
- `core/engine/physical/__init__.py` `ANSWER_FORMATS`: one instruction per text-answer step (all 23): allowed options for categories ("Answer yes or no."; "Answer with exactly one of: forward, backward, no shift."; isotopes / isobars / …), and a form for formulas, nuclides (symbol and mass number), orbitals, configurations and balanced equations.
- `PhysicalAdapter.answer_format()`; `write_stem(answer_format=…)` ends the stem with it; `flow._stem_and_gate` fails the gate in code if it is not copied exactly.
- Matcher: "at equilibrium" (step 157) counts as "no shift"; for directions and nuclide relations exactly one category must match, otherwise the verifier decides ("the system at equilibrium shifts forward" is ambiguous).
- Tests: every text step has a format; new matcher cases (60 tests).

### Non-numeric answers: code first, then a narrow verifier field
- `core/answers.py` `text_answers_match()`: code comparison by answer shape — formulas by element counts (CH₂O ≠ C₆H₁₂O₆), nuclides by symbol and mass number (²³⁴₉₀Th = Th-234), electronic configurations, balanced equations up to a common factor, orbital labels and "not allowed", and categories with synonyms and yes/no (forward / backward / no shift; precipitate forms / no precipitate; isotopes / isobars / isotones / isodiaphers). Returns None when it cannot tell.
- `stages.verify_member()` adds `answer_equivalent`: does the final answer state the same result, ignoring working and notation. Grading (`flow._text_match`) uses code when it decides, else this field (no extra call); the verdict stays a judgement of the reasoning. Hint re-solves use the same rule.
- Tests: 21 answer-shape cases and both decision paths (59 tests).

### First live run (smoke test) and the bugs it found
- All 8 models answer with valid JSON (ping cost $0.0003). One physical run cost $0.011 (generator 70 %, verifier 17 %, council 9 %).
- Bug: non-numeric answers were matched by exact text, so "Yes" to "determine whether a precipitate forms" counted as wrong although the verifier judged it correct; the question (GEN_20261012T235813) was accepted as hard. Rejected with `tools/results.py reject`.
- Fix (`core/pipeline/flow.py`): a non-numeric answer that code cannot match falls back to the verifier's verdict (`match_by: "verifier"` in the record); numbers stay code-matched. Hint re-solves use the same rule, and an insight re-check that says "correct" now counts as solved instead of "still wrong".
- Stems: values print as exam notation (4 × 10⁻⁵, not 4e-05); the generator is told not to copy internal labels or template symbols (AxBy, x, y) and that writing the formula states its subscripts; the extractor counts formula subscripts as stated.
- Tests: grading of text and numeric answers, value formatting (57 tests).

### Frontier refiner for too-easy rounds
- `core/models.py`: `REFINER = "google/gemini-3.8-flash"` (GPQA Diamond 95.6 %, top of OpenRouter's leaderboard at flash pricing). Spend is tracked under its own role, `refiner`.
- When the council finds a question too easy, the refiner handles that round: `choose_refinement` (now with room to think), `propose_inputs(refine=...)` (new inputs; it now sees the solvers' working, not just a one-line summary) and `write_stem(solved=...)` / `write_fact_stem(solved=...)` (rewording without the cue that made it easy). First drafts and clarity rewording stay with the generator (Gemini 3.7 Flash).
- Tests: the fakes answer both roles; the too-easy test checks the refiner makes 2 calls per round and the generator only the first draft.

### Council and generator swapped for stronger, cheaper models
- `core/models.py`: council is now GPT-6 Luna (`openai/gpt-6-luna`), GLM-5.3-Flash (`z-ai/glm-5.3-flash`) and Qwen3.8-Flash (`qwen/qwen3.8-flash`), replacing GPT-OSS-120B, GLM-4.7-Flash and Qwen3-235B-Thinking. Early stop runs GPT-6 Luna and GLM-5.3-Flash first. Generator is Gemini 3.7 Flash (was Gemini 2.5 Flash).
- Why (OpenRouter GPQA Diamond leaderboard, 2026-10-13): old council 72.7 / 52.8 / 77.8 % at $0.007 / $0.017 / $0.056 per question; new council ~87–90 / 85–91 / 88.6 % at $0.003 / $0.005–0.014 / $0.021. Generator 72.6 % at $0.060 → 93.9 % at $0.029. Family separation is unchanged (OpenAI, Z.ai, Qwen solve; Google writes; DeepSeek extracts; Anthropic verifies; Mistral writes solutions).
- Pending: JEE calibration of the new council (`calibration/anchor_calibration.py --council --skip-weak`).
- README, `docs/Flow.md`, `docs/pipeline_overview.html`, `tools/make_approach_pdf.py` updated.

### Council-candidate calibration
- `calibration/anchor_calibration.py --council [--skip-weak]`: solves the 54 JEE Advanced numeric questions with the generation council's own call (`stages._solve`: same prompt, 16k token cap, reasoning effort, temperature) and reports spend per question; results go to `..._<model>_council.json`. The earlier runs capped answers at 2,500 tokens with no reasoning effort, which truncates thinking models, so they cannot compare council candidates.

### Early-stop council
- `core/models.py`: `COUNCIL_FIRST` (GPT-OSS-120B, GLM-4.7-Flash). `stages.council_solve(stem, names)` solves a named subset.
- `core/pipeline/flow.py` `judge()`: the first two members solve and are verified and graded; Qwen3-235B-Thinking is called only when it could change the decision (exactly one of the first two solved). The accept / too-easy decision is unchanged. At live OpenRouter prices (Qwen-Thinking $0.45 / $3.50 per M tokens) Qwen is ~60% of a pass, so the saving is roughly a third of council spend.
- Records gain `council_n_called` and `council_skipped`; `tools/evaluate.py` reports members called and skipped. The verifier still reads every attempt (Haiku 5.5 is ~4% of a pass).
- Tests: Qwen skipped when both first members solve or both fail; called when they split (54 tests).

### Inorganic concept-book audit applied
- `knowledge/concept_book_inorg.json`: approved fixes from `docs/audit_inorganic.md` (new). 44 entries with wrong chemistry corrected (e.g. NCl₃ hydrolysis gives HOCl, CCl₄ + steam gives COCl₂, zinc uranyl acetate is the Na⁺ test, isomer counts for [Ma₂b₂cd] and [M(AA)₂a₂]); every corrected equation passes `chem.check_balanced`. Leftover thinking text removed from 71 entries. Entries are never deleted, so indexes stay stable: removed, moved-to-organic and duplicate entries carry `status` (plus `duplicate_of`); 5 unconfirmed claims carry `unverified`; 4 structure facts carry `kind: "fact"`; 5 multi-step entries keep step 1 and gained later steps as new entries 904–908 (`split_from`). Each touched entry has an `audit_note`.
- `tools/build_graph.py`: entries with `status` or `unverified` feed neither edges nor facts; `kind: "fact"` entries go to the facts list.
- `knowledge/reaction_graph_inorg.json` rebuilt: 354 nodes, 407 edges; `graph_unmapped_inorg.json`: 489 facts. Borax is now a single node.
- `knowledge/concept_book_physical.json` entry 165: solids that contract on melting are ice, Ga, Bi, Ge, Si (was ice, diamond, quartz, Mg₃N₂, carborundum). `facts_data.py` gained a gallium statement.

### Fact questions, Le Chatelier steps, single-step questions (physical)
- `core/engine/facts.py` (new): fact questions built entirely by code. Facts are kept as category tables (mutually exclusive categories, so a swapped category is always false) or pools of true/false statements; a question is four statements in one of three modes (one or more correct; exactly one correct; exactly one incorrect). The key is the set of option letters; each wrong choice is a trap. `letters_of()` reads letter answers.
- `core/engine/physical/facts_data.py` (new): 36 sources covering every physical concept-book entry that is not a computation (gas analysis, indicators, Maxwell distribution, real gases, systems and properties, second law, equilibria, acids and bases, salt solutions, buffers, mechanisms and plots, nuclear, electrolysis, cells and batteries, conductance, Raoult deviations, azeotropes, solids, crystal systems, defects, adsorption, catalysis, colloids). Entry 165's list of solids that contract on melting was not used beyond ice, gallium and bismuth (quartz in particular expands on melting).
- Le Chatelier entries 161, 162, 164, 166, 167 are now engine steps (`equilibrium_reaction → direction_of_shift`): the shift is computed from Δn_g and the sign of ΔH; traps for counting solids/liquids in Δn and for inert-gas confusion.
- Pipeline: `PhysicalFactsAdapter`; `stages.write_fact_stem()`; `gate.compare_fact()` (code checks that the question sentence and all four options appear verbatim and the answer is not revealed — no extractor call); grading compares option letters; knowledge and insight hints for fact questions; refinement rebuilds the question from fresh statements.
- `run_groundup_final.py --kind {auto,chains,facts}`; auto makes a fact question in `fact_share` of runs (`subject_config.py`: physical 0.25). Records carry `question_kind` and, for facts, the `options`.
- Engine steps that cannot join any chain (38 physical edges, e.g. Bohr radius, Carnot efficiency, Bragg's law, Le Chatelier) are offered as single-step questions at half the weight of multi-step chains.
- Tests: Le Chatelier rules, fact keys for every source and mode, letter parsing, and an offline fact-question run (52 tests).


### New generation pipeline (engine-first, council-measured)
`run_groundup_final.py` was rewritten around the engine. A run: graph walk (engine-computable, coherent chains, ranked by coverage and trap-type rarity) → Blackboard → generator proposes inputs or vetoes the chain → engine computes answer, trace and traps → generator writes the stem → chemistry gate (extractor copies facts, code compares values, constants and the asked quantity; original + 2 rewrites) → duplicate check → council of three reasoning models, closed book → mismatch verifier on every attempt → grading in code → hint tests (clarification, knowledge, insight) → accept with a readable solution. Details in `docs/Flow.md`; reasons in `docs/Decisions.md`.
- New modules: `core/models.py` (roster, OpenRouter call helper with reasoning effort, spend tracking), `core/pipeline/` (`flow.py` decisions, `stages.py` model calls, `gate.py` comparison, `adapters.py` subject interface, `queues.py` review queues), `core/answers.py` (answer parsing and comparison, safe arithmetic for slip confirmation), `core/dedup.py` (Tier 1 as an exact duplicate check on engine inputs).
- `core/blackboard.py` rewritten as the per-question notebook (chain, events of every stage, rounds).
- `core/coverage.py` counts trap types; `trap_weight()` steers the walk towards rare ones.
- Records now carry the engine answer and unit, tags (recall / closed_book, trap types), `council_n_correct` and `council_n_solved`, per-member `answer_matches`, verifier labels and `counts_as_solved`, hint tests, the engine trace and traps, rounds, spend and the Blackboard history.
- Removed: `run_graph_final.py` (older SambaNova loop), `core/verifier.py` (LLM verifier; its numeric-answer parser moved to `core/answers.py`), the concept-reasoner, the generator-written solutions and the GPT-4o grader. Old pending questions without engine fields are dropped on the next run.
- `generate_questions.py`: `--max-spend` stops the batch once the runs have spent that much.
- `tools/evaluate.py` rewritten as the paper report; `tools/results.py` gained `queue` and `dismiss`.
- `calibration/council_eval.py` imports `COUNCIL` from `core/models.py`.
- `tests/test_pipeline_offline.py`: end-to-end runs with scripted model replies (acceptance with hint tests, confirmed slip, rounds running out, parking and recheck) and gate comparisons.
- Inorganic and organic exit with code 2 until their engines are wired.
- README, `docs/Flow.md`, `docs/Decisions.md` (new entries; superseded notes on the old verifier, grader, threshold and entrypoint decisions) and `docs/pipeline_overview.html` (the agreed flowchart) updated.


### Physical chemistry engine (new)
First part of the engine/council redesign: every computable physical concept-book entry is now a deterministic computation, so a physical question's answer key comes from code instead of a model.
- `core/engine/base.py`: `Step` (one concept-book entry as a computation between two graph nodes: inputs, answer field, traps, constants the question must state), `plan_chain()` (wires each step's outputs into the next step's inputs by name; every other input is a "given" the question states; refuses chains whose steps share nothing), `run_chain()` (answer, step-by-step trace, and traps: each typical mistake is run through the rest of the chain, so a trap is the final answer a student making that mistake would write), `answers_match()` (purely relative 1% tolerance), `assign_steps()` / `roles_consistent()` (pick one entry per graph edge so the chain links up and no value is reused as a different substance).
- `core/engine/chem.py`: formula parser (brackets, hydrates, ionic charges with `^`), equation parsing and balance check, redox balancing via SymPy nullspace, JEE atomic masses, physical constants with the wording a question uses to state them.
- `core/engine/physical/`: 262 steps over all 12 chapters (stoichiometry, atomic structure, gaseous state, thermodynamics and thermochemistry, chemical and ionic equilibrium, kinetics and nuclear chemistry, electrochemistry, dilute solutions, solid state, surface chemistry). 87 entries are facts, classifications or plot readings and stay out (they become fact questions later).
- Coherence rules so a chain is one problem, not just computable: quantities that only shared a name were split (rate-increase factor vs rate constant; ΔT vs osmotic pressure vs vapour-pressure lowering; total vs per-mole entropy; gas-phase vs electrolyte degree of dissociation), role tags (a NaOH amount from a titration cannot become a dissociating gas; a softener mass cannot become sodium azide), roles carried through substance-preserving steps, and topic bridges (chains cross chapters only where the quantity means the same on both sides; nuclear entries are their own topic).
- `tests/test_engine_physical.py`: 41 tests against textbook results (e.g. 98% H2SO4 at 1.84 g/mL is 18.4 M, U-238 → Pb-206 is 8α + 6β, Hess's law gives ΔfH(CH4) = −74.8 kJ, 10⁻⁸ M HCl has pH 6.98), plus checks that every sampled chain links and plans.

### Physical graph built from the engine
`tools/build_graph.py` takes an optional `tx_nodes(index, tx)` from a subject's rules; `tools/graph_rules_physical.py` provides it from the engine, so the physical graph has an edge exactly for each entry the engine computes (198 edges, 173 nodes; was 147/119). A step that keeps the same quantity (dilution, Boyle's law, K manipulations) is now a self-loop edge instead of being dropped.

### Chain walk
`core/graph_traversal.py`: `get_paths()` may take a self-loop edge once per path, accepts `can_follow(prev_edge, edge)` to prune the walk, and de-duplicates paths by edges instead of nodes (two different reactions between the same two nodes are two chains). `sample_chains()` passes `can_follow` through and accepts `validate(edges)`. Callers that pass neither behave as before.


### Physical concept book: audit fixes
First step of the engine/council redesign: every physical graph edge was checked before it becomes a computed engine step. Fixed in `knowledge/concept_book_physical.json`, then `reaction_graph_physical.json` rebuilt with `tools/build_graph.py --subject physical` (a rebuild of the unchanged book had reproduced the committed graph exactly, so only these edges changed):
- Buffer example (moles → buffer_ratio): "0.2M HA 100mL + 0.1M NaOH 200mL" is 20 mmol of each, i.e. full neutralisation, not a buffer. Now 100 mL NaOH (20 vs 10 mmol, half-neutralised, pH = pKa).
- Strong acid + strong base neutralisation (heat → delta_h): "-56 kJ (-13.7 kcal)" disagreed with itself; now -57.3 kJ (-13.7 kcal), also in its note.
- ΔS = nR ln(V2/V1) (thermodynamic_process → delta_s) now states that it holds only for an isothermal ideal gas.
- C-14 half-life: 5730 y (older texts use 5770 y); the entry says the question must state the value used. Same fix in the unmapped radiocarbon entry.
- Molar volume 22.4 L/mol: the condition now names 1 atm, 273 K, notes the IUPAC 1 bar value (22.7 L/mol), and says the question must state the conditions used.
- Pressure-based rate constant (partial_pressure → rate_constant): "style relations" replaced by the general relation P_A = (nP0 - Pt)/(n - 1) for A(g) → nB(g).
- Vapour pressure: "NOT a surface phenomenon" reworded to "independent of surface area and amount of liquid".

Impact: two edge ids changed with their reagent text (`heat_to_delta_h_sasbh573kjpe`, `partial_pressure_to_rate_constant_k1tlnp0papaf`); no saved question or coverage file referenced the old ids.

### Physical concept book: entries outside the graph
The 155 physical entries the graph build leaves out (`graph_unmapped_physical.json`) were audited too, since they are being brought into the pipeline. Fixed in `knowledge/concept_book_physical.json`:
- H2O2 as oxidant: the half-reaction was unbalanced; now "H2O2 + 2H+ + 2e- -> 2H2O".
- Le Chatelier note: "never fully restores original Q" was wrong (Q returns to K); now "never restores the original concentrations".
- Nuclear stability: "n/p > 1.5 unstable" contradicted its own example (stable Pb-208 has n/p 1.54); now states that n/p rises to about 1.5 for the heaviest stable nuclei.
- "Kraft temperature" corrected to "Krafft temperature".

Impact: these entries are not graph edges, so the rebuilt graph is unchanged.


## 2026-10-12

### Chains follow graph connections across chapters
Every run used the subject's fixed `default_chapter` unless `--chapter` was given (the batch driver never passes one), so all physical questions came from "Chemical Kinetics & Nuclear Chemistry", all organic from Hydrocarbons, all inorganic from hydrolysis. Now, without `--chapter`, `sample_chains()` walks the whole graph from every start node: a step follows the previous one whenever they share a node, whatever chapter the edge is in; coverage weight (least-used edges first, ties shuffled) ranks the candidates. Each chain carries `chapters` (`chain_chapters()`, in order); that becomes the record's `chapter` label (e.g. "Gaseous State → Stoichiometry") and new `chapters` list, the generator's chapter line, and the scope of the solvers' closed-book sheet. `--chapter` still restricts a run to one chapter. Same in `run_graph_final.py`, which also gains `--chapter`. Simulated 20 physical runs: 20 distinct chains touching 11 of 12 chapters (before: 1 chapter).


### Full review: fixes
- **String booleans from models.** `bool("false")` is True in Python, and booleans read from model JSON went through `bool()` / truthiness: a council grade of `"final_answer_correct": "false"` counted as solved, `"reference_correct": "false"` was never counted as a flag, and in the verifier `"equivalent": "false"` would PASS a mismatched answer while `"blocking_flaw": "false"` would FAIL a clean one. New `core.llm.as_bool()` / `as_number()` read them strictly; used in `run_groundup_final.py` (council, `_score_from_rubric`), `core/verifier.py` and `run_graph_final.py` (where a string score like `"85"` also crashed the `>=` gate comparison).
- **Empty answers.** `verify_problem()` asked the model whether two answers were equivalent even when one or both were empty; now a missing candidate or blind-solve answer is a FAIL without that call.
- **Wrong-key refine had no information.** When graders flagged the answer key, the refine prompt's feedback was the verifier's (empty, it had passed). The graders' justifications now go into the feedback.
- **Exit codes.** Setup problems (key, concept book, graph, chapter without chains) exit with `EXIT_CONFIG_ERROR` (2) instead of 0; `generate_questions.py` skips that subject instead of retrying it up to `--max-consecutive-failures` times.
- **`run_graph_final.py` acceptance** set `accepted` before saving and updated coverage before writing the record (the same half-completion as #4 in the main pipeline). Meta-tag errors are now recorded on the record, the record is written first, and coverage follows.
- **`tools/build_graph.py`** defaulted to `--subject organic`, which overwrites the curated organic graph. `--subject` is now required, and organic also needs `--overwrite-organic`.
- **Attempt-log path** is derived with `os.path.splitext` instead of replacing ".json" anywhere in the path.
- **README** pipeline diagram brought in line with the code (pending recheck, Tier 1 on extracted numeric answers against accepted questions, extraction before the blind solve, majority key flag, parking, `results/`); closed-book paragraph and OCR note corrected.
- **Housekeeping (pyflakes clean):** unused imports removed across nine files; `f`-strings without placeholders; a dead variable in `build_graph.py`; unclosed files in `anchor_calibration.py` and `council_eval.py`; merged import lines in the `calibrate_thresholds*.py` scripts split; stale module docstring in `run_groundup_final.py`.


### Shared helpers instead of copies
`core/llm.py` gained `load_env()`, `parse_json()` (fences, prose, first balanced object, single-element list) and `write_json_atomic()`. They replace the copies of the `.env` loader, JSON parser and retry loop in `run_groundup_final.py`, `run_graph_final.py`, `generate_questions.py`, `core/verifier.py`, `tools/extract_notes.py` and every calibration script. Behaviour changes that came with it:
- `calibration/anchor_calibration.py` and `council_eval.py` turned an unparseable reply into an empty answer that was then graded as *wrong*, lowering the solve rate. They now re-ask (`call_json`) and, if the reply stays unusable, record an error, which is excluded from the rate.
- `calibration/council_eval.py` imports `COUNCIL` from `run_groundup_final.py` instead of keeping a copy ("keep in sync" — the copy had drifted before).
- The calibration scripts write their result, trace, norm-stats and seed files atomically.
- `calibrate_thresholds*.py` retry all transient errors and parse the strong solver's reply tolerantly.
- `calibration/calibrate_solver_metatags_inorganic.py` and `_physical.py` were merged into `calibrate_solver_metatags.py --subject {organic,inorganic,physical}`; the per-subject differences (files, archetype names, default archetype, prompt wording) are a config table. An offline test with a stubbed solver produced identical traces, norm stats and seed files to the three old scripts for all subjects. The three `calibrate_thresholds*.py` scripts stay separate: their question filtering and archetype mapping really differ, and they serve only `run_graph_final.py`.

### Wrong-subject fallbacks removed
`subject_config.py`: `compute_meta_tags_for_subject()` caught any `TypeError` and recomputed with the organic norm stats, and the coverage helpers fell back to a shared `coverage_state.json`; written for function signatures that no longer exist, they would also have hidden real errors behind the wrong subject's data. They now call the per-subject functions directly. `.gitignore` ignores `*.tmp` (left only by an interrupted atomic write).


### Architecture docs describe the current system
`docs/pipeline_overview.html` described the old pipeline (DeepSeek generator, Qwen verifier, weak/strong solvers with 85/60 gates, no council, "no graph" for inorganic/physical), and it never loaded Mermaid — it was an HTML fragment with no `<script>`, so both diagrams showed as source text. It is now a complete page (doctype, title, Mermaid from jsDelivr, SVG labels in the font Mermaid measures with) whose figures and stage cards follow the current loop: pending recheck → shared graph traversal → concept reasoner → generator → two-tier verifier → council + grader → gate → save/park. `tools/make_approach_pdf.py` described deleted files (`pipeline.py`, `run_live.py`, `strong_solver.py`, `classifier.py`), an all-SambaNova roster and threshold gating, and said meta-tags steer generation; its content now covers the current files, loop, council difficulty signal, per-subject concept books and graphs, archetypes, meta-tags (as labels), model roster and acceptance logic. README layout lists `core/llm.py`, `tools/results.py` and the pending files.


### extract_notes.py takes its notes from a file
`tools/extract_notes.py` ignored its `ocr_text` argument: the prompt was an f-string built at import with the hardcoded Amines OCR text. It now reads `--notes FILE` with `--topic NAME`, and `--dry-run` shows what would be merged without writing. The Amines OCR text moved to `data/notes/amines_lec1.txt`. Model output goes through `core.llm.call_json` (retries, tolerant JSON parsing); merge skips entries missing their key field instead of raising `KeyError`; the concept book is written atomically in its existing format (ASCII-escaped, indent 2).

### Reference data documented; verifier header corrected
README lists the data no code reads (`data/chapterwise/` — concept maps, not question banks as previously stated — `arihant_seeds.json`, `merged_SEED.json`, `jic_chemistry_stats.json`, `molecule_constructor.json`, `qualitative_tests.json`) as reference material, kept. `core/verifier.py`: the header comment described Claude as the verifier and referred to the deleted `strong_solver.py` / `weak_solver.py`; it is now an accurate module docstring. Running `python core/verifier.py` directly failed after `core.llm` was introduced (`core` not importable from a script); it now puts the repo root on `sys.path` when run as a script.


### Dead code removed
`run_groundup_final.py`: removed the unused `verifier()` (the old single-call verifier; `core/verifier.py` is the live one) and its own `VERIFIER_MODEL` constant — `VERIFIER_MODEL` is now imported from `core/verifier.py`, so a record's `models.verifier` always names the verifier that ran. Corrected comments that called the README stale and said the verifier was Qwen2.5 and the generator DeepSeek. `core/meta_tags.py`: removed the unused, organic-only `archetype_code_from_label()`.


### Answer key judged wrong by majority, not by one grader
`run_groundup_final.py`: `council_solve()` set `reference_correct = False` if any one of the three grades flagged the generator's key, forcing a refine even when the other two agreed with it. It now counts the flags (`n_reference_flags`) and the key counts as wrong only at `REFERENCE_WRONG_IF_FLAGGED_GE` (2) of 3.

### Unique question ids; atomic coverage saves
`run_groundup_final.py`: ids were `GEN_<timestamp to the second>`, so two acceptances in the same second shared an id and `tools/results.py promote` skipped the second (seen in testing). `unique_id()` appends `_2`, `_3`, ... when the id is already in the output file, `results/` or `rejected.json`; pending ids likewise. `run_graph_final.py` does the same for `GRAPH_` ids. `core/coverage.py` `save()` writes via a temp file.


### Requirements of the older scripts documented
README "Quick start" lists what each script needs: `run_graph_final.py` and `calibration/calibrate_thresholds*.py` need SambaNova keys and a local Ollama server with `llama3.2`; the solver meta-tag calibration and `tools/extract_notes.py` need SambaNova keys. `.env.example` explains the same.

### Anchor calibration: repo data path, per-model result files
`calibration/anchor_calibration.py` read `/Users/admin/Downloads/data/jee_advanced`; it now reads `data/jee_advanced` (54 numeric questions load, matching the published n = 54). It was set to qwen3-235b while the README reported the gpt-oss-120b run and cited the qwen file, and its summary printed "STRONG (405B)" / "WEAK (llama3.2)". Now `--strong` / `--weak` choose the models (default `openai/gpt-oss-120b`), each strong model writes `anchor_calibration_results_<model>.json`, and the summary prints the real model names. Renamed the existing results: `anchor_calibration_results.json` → `anchor_calibration_results_qwen3_235b_a22b_2507.json` (qwen run, 20/54) and `anchor_calibration_results_gptoss.json` → `anchor_calibration_results_gpt_oss_120b.json` (gpt-oss run, 27/54). The README table now lists both runs from those files; the "Mean 0–100 score" column (60 / 19) was dropped because no results file contains it.


### Retries cover every transient API error
New `core/llm.py`: `is_transient()` (429, 408/409/425, 5xx incl. 502/504/520-529, timeouts, dropped connections — by openai exception type, status code, or message), `call_with_retry()`, and `call_json()`, which also re-asks when the reply is empty or unparseable (twice). Previously only messages containing "429"/"503"/"rate_limit" were retried, so a 502, a timeout or a truncated JSON reply failed at once. Used by `run_groundup_final.py` (`api_call`, new `ask_json` for all five JSON model calls), `core/verifier.py` (`_call_with_retry`, new `_call_json`) and `run_graph_final.py` (key rotation on rate limits, backoff on other transient errors). 400/401/403/404 still fail immediately.


### Graph entrypoint survives malformed model output
`run_graph_final.py`: four calls parsed model output with bare `json.loads`, and the concept reasoner, generator and verifier calls had no error handling, so one fenced or malformed reply crashed the run. They now use `parse_llm_json()`; a failure in those calls costs only the current attempt. The model-written verdict is normalised ("PASS — ..." → PASS; anything else, including a missing verdict, → FAIL). The output file is written atomically.


### `--child-timeout` works
`generate_questions.py` read the child's output with `for line in proc.stdout` before calling `proc.wait(timeout=...)`, so the loop blocked until the child exited and a hung question was never killed. Output is now read on a daemon thread while the main thread waits with the timeout. A child that hangs is killed at the timeout (tested: two hung runs with `--child-timeout 3` took 8 s instead of 120 s).


### Prompts describe the council, not the old weak/strong solvers
`run_groundup_final.py` stored the council solve-count in the blackboard's `strong_score` slot, so the generator's refine prompt said "Weak Solver Score: None% (target ≤60%) / Strong Solver Score: 1% (target ≥85%)" and the attempt history shown to the models said "Weak=n/a | Strong=1%". `core/blackboard.py` now has `council_solved` / `council_size` (weak/strong stay optional for `run_graph_final.py`), and `score_summary()` prints whichever was recorded ("Council=1/3 solved"); the refine prompt says "Council result: 1/3 Mains-level solvers solved it (target: at most 1)". The unused `STRONG_FLOOR` / `WEAK_CEILING` constants were removed from `run_groundup_final.py`.


### Removed the mock seed classifier
Deleted `tools/classifier.py` (a `MockOpenAI` keyword matcher, not a real classifier) and its output `data/seeds/classified_seeds.json` (all 120 seeds labelled "Counting/Enumeration"). Nothing read either file; seed archetypes come from `data/seeds/jeeadv_*_seeds.json`. `data/seeds/merged_SEED.json`, its input, is kept.


### Solver meta-tag calibration no longer fakes success
`calibration/calibrate_solver_metatags{,_inorganic,_physical}.py`: when every solver call failed, the stats step fell back to `[0]`, wrote mean 0 / std 1 as calibrated values, cleared `pending_calibration`, and back-filled every seed's `model_solution_length` / `distractor_plausibility` from those placeholders. Resume also skipped errored seeds, so they were never retried; there was no key check and no stop on repeated failures; the inorganic/physical scripts cleared the pending status of `number_of_exceptions`, which they never compute. Now: exit early without SambaNova keys; retry errored seeds on resume; stop after `MAX_CONSECUTIVE_ERRORS` (5) failures in a row without writing stats; write stats only for archetypes with `MIN_SAMPLES` (2)+ successful traces and list the rest in `pending_calibration`; leave `number_of_exceptions` alone; back-fill seed tags only from successful traces and remove placeholder ones.
Data repaired (no API calls): `calibration/meta_tag_norm_stats.json` — the 8 placeholder entries (`model_solution_length`, `distractor_plausibility` for I–IV) reset to `mean: null, status: PENDING_SOLVER_TRACES`, `pending_calibration` restored; `data/seeds/jeeadv_organic_seeds.json` — 306 placeholder tags removed from the 153 seeds (all 153 traces in `solver_traces.json` are errors). Meta-tags of generated questions are unchanged, since null stats already fall back to mean 0 / std 1.


### Acceptance cannot half-complete
`run_groundup_final.py`: `accepted = True` was set before saving, so an error while saving (meta-tags, coverage, file write) was caught by the iteration's generic handler, which regenerated and kept looping — a second question could be verified and saved, or the run ended with nothing saved and no "not accepted" message; coverage could also count a question that was never written. Now `save_accepted()` builds the record, then writes the output file atomically as the only step that decides acceptance, and only then updates coverage, the Tier 1 store, `results/` and the attempt log, each of which only warns on failure. Meta-tag errors are recorded (`meta_tags: null`, `meta_tags_error`) instead of losing the question. `accepted` is set only after the write succeeds. If the write fails, the question is parked in the pending file with its council result (`council_result`, `save_error`) and the run exits with `EXIT_SAVE_FAILED` (4); `recheck_pending()` retries only the save, with no API calls. `generate_questions.py` stops the batch on exit code 3 or 4 (`STOP_EXIT_CODES`, `BatchStop`).


### Tier 1 dedup: numeric answers only, compared as numbers
`core/verifier.py`: Tier 1 took "the last number in the solution" as the final answer. For organic that is a locant (the -1 in 2-methylprop-1-ene), so two different questions with the same input numbers and operator names were failed against each other; numeric answers were compared as strings ("2.08e9" ≠ "2.080e9"). Now `verify_problem()` first extracts the candidate's answer (the existing `_extract_candidate_answer` call, moved ahead of the blind solve), and `parse_numeric_answers()` reads it as one or more numbers with units, or rejects it as non-numeric. Non-numeric answers skip Tier 1. Numeric ones are compared per part within 1%. Input numbers in the hash are normalised (1.00 = 1.0, 4.468 × 10^9 = 4.468e9). `record_accepted_inputs()` now takes the extracted answer text (`candidate_final_answer`) and stores only numeric answers. `_extract_final_answer()` is removed. On the 27 result questions, 0/21 organic, 2/24 inorganic and 9/18 physical solver answers read as numeric.


### Tier 1 dedup stores accepted questions only
`core/verifier.py`: `check_duplicate_inputs()` recorded every attempt's answer, including attempts the verifier rejected, so refining a wrong numeric answer while keeping the numbers was hard-failed forever by the stored wrong answer. It is now read-only and compares only with accepted questions; the new `record_accepted_inputs()` stores `{question_id, final_answer}` and is called from `save_accepted()` in `run_groundup_final.py` (new and pending-rechecked acceptances). Legacy entries without `question_id` are ignored. Store writes are atomic, the store path resolves at call time, and the module's `__main__` demo now runs offline on a temporary file instead of making API calls and writing to the live store.


### Council failures no longer produce accepted questions
`run_groundup_final.py`: a council member that errored was counted as "did not solve", so if all three calls failed (outage, rate limit, spent key) the item scored 0/3 and was accepted as hard. Now all three members must be measured. The first member whose solve or grade call fails raises `CouncilMemberFailed` without waiting for the others (daemon threads instead of a thread pool); the question, which already passed the verifier, is parked in `outputs/pending_questions_<subject>.json` (new `pending_file` in `subject_config.py`) — neither accepted nor rejected — and the process exits with `EXIT_COUNCIL_FAILED` (3). The next run for that subject calls `recheck_pending()` before generating: the council is rerun on each parked question, oldest first; accepted questions go through the same `save_accepted()` as new ones (record gains `pending_id`, `rechecked_from_pending`); too-easy or wrong-key results are dropped and logged (`pending_too_easy`, `pending_reference_wrong`); a repeat failure keeps the question parked (`recheck_failures`) and stops again. The acceptance code moved into `save_accepted()`, and the output file is now written atomically. `generate_questions.py` stops the whole batch on exit code 3 and prints the summary. Per-call 429/503 retries in `api_call` are unchanged.

### Chains join on the actual compound
- `core/graph_traversal.py`: `chain_txs()` picks, among each edge's concept-book entries, the sequence where the most consecutive steps join on the same compound (`compound_key()`); each step carries `step` and `joins_previous_compound`. Organic compound-level joins: 820 → 984 of 3,714 step pairs (the data allows about 1,028).
- Generator prompt (both entrypoints): the steps are one ordered chain; apply each step to the actual product of the previous step, not to the example compound in its entry.
- `tools/graph_rules_inorganic.py`: substrate and product are chosen from both sides of a reaction together and must share an element other than H/O. Before, the first-written species was used, which made 25 wrong edges (e.g. `CO + H₂O → H₂ + CO₂` gave CO → H₂; thermite gave Al₂O₃ → Fe). EAN calculations, "X vs Y" comparisons and placeholder formulas are rejected as facts. Inorganic graph rebuilt: 363 nodes, 393 edges, 0 edges without a shared element.
- Salt → ion links: `graph_rules_inorganic.extra_edges()` adds a "dissolves to" edge from a soluble salt to the ion it releases when the salt is a fixed-charge cation plus exactly that ion, charges balance, and the ion has onward steps. 22 links (e.g. K₂Cr₂O₇ → Cr₂O₇²⁻, so Na₂Cr₂O₇ → K₂Cr₂O₇ → Cr₂O₇²⁻ → Cr³⁺ now exists). Insoluble salts get none (AgCl, CaSO₄, ZnS, CaC₂O₄). The edges are marked `synthetic`, have no `tx_ids`, and are added to the solvers' knowledge sheet when used. Inorganic graph: 363 nodes, 415 edges.


### One graph traversal for all three subjects
Before: organic picked steps by keyword-matching the concept book, inorganic and physical by its chapter field, and only the older `run_graph_final.py` used a graph (organic only).
Now every subject has a knowledge graph with the same schema, and both entrypoints choose chains with the same code.
- New graphs: `knowledge/reaction_graph_inorg.json` (372 species nodes, 402 edges) and `knowledge/reaction_graph_physical.json` (119 quantity nodes, 147 edges), built by `tools/build_graph.py --subject inorganic|physical` using rule tables in `tools/graph_rules_inorganic.py` and `tools/graph_rules_physical.py`. The organic graph is unchanged (the builder no longer reproduces the curated file, so it was not rebuilt).
- `core/graph_traversal.py`: `KnowledgeGraph` / `load_graph(path)` per subject instead of the organic graph loaded at import; shared `sample_chains()` and `chain_txs()`; `chapter_scope` on `get_paths()`; Python 3.9-safe annotations. LLM tool functions keep their signatures.
- `run_groundup_final.py`: chains come from `sample_chains()`; the concept reasoner picks one; records gain `graph_path` / `graph_edges` and `generation_mode: graph_council`; coverage now counts the chain's edges. `filter_txs_for_subject()` and the `tx_filter_*` config fields are removed. `--chapter` now works for organic too, and an unknown chapter prints the valid ones.
- `run_graph_final.py`: uses the shared traversal; accepts `--subject physical`.
- `subject_config.py`: physical gets `graph_path`; `start_nodes` is empty for all subjects (any node marked `can_be_start`).
- `core/coverage.py`: `weight()` no longer writes zero entries for every candidate it scores.


### Human review of results
Added `tools/results.py` (`promote`, `pending`, `score`, `reject`). `run_groundup_final.py` now copies each accepted question into `results/generated_questions_<subject>_final.json` with empty `human_eval_*` slots; a failure there only warns. Added `results/rejected.json`, seeded with every ID in `outputs/` that is not in the final sets, so they are never re-added.
`GEN_20260906T101607` added too, since it is not in the final set. Example IDs and pruned-item IDs removed from the README. Some existing human-eval level labels do not match the README scale (score 2 labelled "JEE Mains" ×10, score 1 labelled "CBSE" ×1); left unchanged. New scores take their label from the score.


### Repository layout cleanup
Moved `ChangeLog.md`, `Decisions.md`, `Flow.md`, `pipeline_overview.html` into `docs/`. Moved the final `generated_questions_*_final.json` sets into `results/`. Runtime files (`generated_questions_<subject>.json`, `coverage_state_<subject>.json`, `*_attempts.jsonl`, `verifier_seen_inputs.json`, `batch_run.log`) now go to `outputs/`.
Impact: `subject_config.py` defines `OUTPUT_DIR` and creates it on import. `core/verifier.py` and `core/coverage.py` default paths point into `outputs/`. `generate_questions.py` reads its output paths from `subject_config.py` instead of duplicating them. README and `Flow.md` updated.

### Fixes so scripts run cleanly
- `tools/extract_notes.py` and all `calibration/calibrate_*.py` looked for `.env` in their own folder; they now read the repo-root `.env` like every other script.
- `calibration/council_eval.py`: replaced hardcoded `/Users/admin/...` data paths with `data/jee_advanced` and a `--mains-file` option (or `JEE_MAINS_FILE`); council roster now matches `run_groundup_final.py` (`gemma-3-27b-it`).
- `tools/evaluate.py` crashed on council-era records (no `strong_score`); it now reports the council solve-count and handles both schemas. Default input is `outputs/generated_questions_organic.json`.
- `core/coverage.py`: added `from __future__ import annotations` so `Path | str` hints work on Python 3.9 (README minimum).
- Entrypoints read/write `.env` and output JSON as UTF-8 explicitly (Windows default codepage).
- `tools/make_approach_pdf.py` writes to `docs/` instead of `~/Downloads`.
- Removed the unused Ollama `weak_client` from `run_groundup_final.py`; fixed stale `run_groundup.py` / `build_graph.py --subject` references in messages and docstrings.
- `results/generated_questions_inorganic_final.json` was invalid JSON (a `human_eval` block missing its closing brace); fixed.
- Added `.env.example` (referenced by the README and error messages but missing).

## 2026-09-07

### Removed unused files
Deleted the pre-`_final` entrypoints `run_groundup.py` and `run_graph.py`, the `archive/` directory (`pipeline.py`, `run_live.py`), the four `core/` stubs those imported (`generator.py`, `concept_reasoner.py`, `strong_solver.py`, `weak_solver.py`), and `pipeline_overview_standalone.html` (a wrapper-only duplicate of `pipeline_overview.html`).
Reason: an import trace showed nothing in the live path or in `tools/` and `calibration/` referenced any of them. The docs already pointed only at the `_final` entrypoints.
Impact: none on behaviour. `subject_config.py` comments updated to name `run_*_final.py`. `Decisions.md` and `Flow.md` updated. Git history retains every deleted file.

### README.md
Refreshed the design doc to match the build. The generation-loop diagram, the model roster, the "no producer clears itself" note, the verifier section, the calibration note, the two-entrypoints table, the repository layout, and the known-limitations list all still described the old weak-solver plus strong-solver architecture with a Qwen verifier and a DeepSeek generator.
Now documents: Gemini 2.5 Flash generator, Gemini 3 Flash answer-first verifier (the five-call flow), the 3-model parallel council with the solve-count difficulty signal, the `MAX_LINEAGES`/`MAX_ITERS`/`VERIFIER_FAIL_MAX` caps, `generate_questions.py`, the `data/seeds/meta_tag_norm_stats_*` files, and the append-only `batch_run.log`. Notes `STRONG_FLOOR`/`WEAK_CEILING` as vestigial in the ground-up path and the chain-coherence limitation.
Impact: documentation only.

### generate_questions.py — append-only run log
The driver now writes `batch_run.log` itself, opened in append mode, with a `RUN <timestamp> :: <args>` separator per run. The child subprocess is run via `Popen` and its output is tee'd to both the console and the log line by line. Added `--log` (path, or empty to disable). Parent stdout/stderr are reconfigured to UTF-8 so the child's box-drawing characters do not raise `UnicodeEncodeError` when tee'd.
Reason: earlier runs were launched with `> batch_run.log`, so each relaunch overwrote the previous run's console output and one run's log was lost.
Impact: relaunching never clobbers earlier output. Launch the driver without shell redirection to `batch_run.log`.

### core/verifier.py — answer-first, one job per call
Rebuilt Tier 2 so a wrong reference solution cannot pass. Before, one `_judge` call received the candidate solution and decided PASS/FAIL, so a solution that read as internally consistent was accepted even when its final answer was wrong. Now the verdict is assembled in code from separate single-purpose calls:
1. `_blind_solve` solves the problem with the candidate withheld and commits to a `final_answer`.
2. `_extract_candidate_answer` reads the candidate solution and returns only its final answer.
3. `_answers_equivalent` compares the two answers. Disagreement is a decisive FAIL and the remaining calls are skipped.
4. `_structural_check` looks only for arithmetic, regime, impossible-result, uniqueness, and circularity flaws.
5. `_rate_difficulty` runs only on a clean PASS.
Reason: splitting the work into short, single-purpose prompts is where a small model hallucinates least, and moving the PASS/FAIL decision into code removes the "looks fine" failure mode. Requested.
Impact: 3 verifier calls on a fast FAIL, 5 on a PASS (was 2). `verify_problem` now also returns `independent_final_answer`, `candidate_final_answer`, and `answers_agree`. FAIL feedback names both answers so the generator can correct its key.

### run_groundup_final.py — generator model
`GENERATOR_MODEL` changed from `deepseek/deepseek-chat-v3-0324` to `google/gemini-2.5-flash`.
Reason: requested a Gemini generator cheaper than the Gemini 3 Flash verifier. Gemini 2.5 Flash is cheaper on both input and output token price and returns clean `json_object` output.
Impact: the generator and verifier are now both Google models (different versions). The concept-reasoner (DeepSeek), grader (GPT-4o), and council (Meta/Mistral/Google) are unchanged, so no model still certifies its own output.

## 2026-09-06

### generate_questions.py (new)
Added a batch driver for Phase 2 generation. It runs `run_groundup_final.py` in a fresh subprocess once per requested question and takes counts for each subject, for example `--organic 5 --inorganic 3 --physical 2`. Per-subject chapter overrides and a consecutive-failure cutoff are supported.
Reason: the entrypoint produces at most one accepted question per invocation, so making a set of questions previously meant running it by hand many times.
Impact: no change to the pipeline or its outputs. Questions are still appended to `generated_questions_<subject>.json` by the entrypoint.

Then hardened the driver for visibility. The child now runs with `-X utf8` and `PYTHONUNBUFFERED=1`, and the driver prints timestamped lines around every child run (launch, finish, duration, whether a question was saved). Added `--child-timeout` (default 1800s) so one hung question run is killed and retried rather than stalling the whole batch.
Reason: a first run stalled with no visible output because the child's stdout was buffered while it sat in a long rate-limit wait, and the driver said nothing between steps.
Impact: batch progress is now visible in real time. A hung run costs at most `--child-timeout` seconds.

### core/verifier.py
Fixed the verifier, which failed on every call. `VERIFIER_MODEL` was `nvidia/nemotron-3-ultra-550b-a55b`. On OpenRouter that slug does not answer, it echoes the request message list back as the completion, so every `verify_problem()` raised one of: JSON `Extra data`, `KeyError: 'independent_solution'`, `NoneType ... has no attribute 'strip'`, or `list indices must be integers`. Changed the model, first to `qwen/qwen-2.5-72b-instruct` and then, as requested, to `google/gemini-3-flash-preview`. Both return clean `json_object` output; Gemini 3 Flash is faster and reasons well enough to blind-solve multi-step chemistry. `run_groundup_final.py`'s own `VERIFIER_MODEL` constant was updated to match, though the live value is the one in `core/verifier.py`.
Also hardened the parsing so a single bad response degrades instead of aborting the run: `_parse_json` now extracts the first balanced `{...}` block (brace counting with string awareness) when a model appends trailing text, and rejects non-objects clearly; `_call_with_retry` retries on an empty completion instead of calling `.strip()` on `None`; `_blind_solve` falls back to any string field if the expected key is absent; `verify_problem` normalises the verdict and treats anything that is not a clear PASS as FAIL.
Reason: the pipeline could not accept any question because Tier 2 always threw.
Impact: verification now runs. Acceptance is possible again. A malformed judge reply now fails closed (FAIL), not open.

### run_groundup_final.py — loop caps
Tightened the generation state machine: `MAX_LINEAGES` 4 to 3, `MAX_ITERS` 8 to 4, `VERIFIER_FAIL_MAX` 2 to 1, then `VERIFIER_FAIL_MAX` back to 2.
Reason: requested, to spend fewer model calls per question. `VERIFIER_FAIL_MAX` at 1 abandoned every question idea on its first verifier FAIL, so the generator never saw the verifier's fix feedback and a test batch accepted nothing across many attempts. At 2 the generator gets one refine pass, which is the point of the verifier feedback channel.
Impact: a single question run does at most 3 fresh ideas and 4 total generate-check iterations. Each idea gets one refine attempt against verifier feedback before being abandoned.

### run_groundup_final.py
Made progress visible during the generation loop. `sys.stdout`/`sys.stderr` are now reconfigured with `line_buffering=True` so prints flush to a pipe or file per line. Added five step markers per attempt: `[1/5] concept-reasoner`, `[2/5] generator`, `[3/5] verifier`, `[4/5] council`, `[5/5] accepted`, each printed before the slow API call it names.
Reason: each step makes one or more model calls that can take one to three minutes, and the script printed nothing while a call was in flight, so a run looked hung.
Reason for line buffering: without it the step markers sat in a block buffer when stdout was redirected, which is exactly how the batch driver runs it.
Impact: output only. The generation logic is unchanged.

## 2026-09-01

### Root cleanup
Removed the stray empty file named `python` from the repository root.
Reason: it was an accidental artifact with zero bytes and no purpose.
Impact: none on behaviour.

Removed `solver_traces.json` from the repository root.
Reason: it was a 103 KB runtime artifact that no script reads. The calibration script reads `calibration/solver_traces.json` instead.
Impact: none. The referenced file in `calibration/` is unchanged.

Removed all `__pycache__` directories.
Reason: they are build artifacts. `.gitignore` already excludes `__pycache__/`.
Impact: none. Python regenerates them on next run.

### Documentation
Added the three maintenance documents required by the repository conventions.
- `ChangeLog.md` records every change. This file.
- `Decisions.md` records why meaningful technical choices were made.
- `Flow.md` describes how the system works and how data moves through it.

Reason: the repository previously kept only the `README.md` design doc. The conventions require all four documents.
Impact: documentation only. No runtime effect.
