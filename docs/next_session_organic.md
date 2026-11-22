# Organic: work for the next session (written 2026-11-23)

## Where it stands
- Rule scope (layer 1 + step 2) is done: `docs/organic_rule_scope.md`, approved by the author; every rule refuses molecules outside its scope.
- Start picker built (`core/pipeline/org_start.py`): Gemini Flash invents the starting molecule, the engine checks it (2+ reacting groups, branched 4–6 step scheme), Claude Haiku checks name = structure. On for organic (`subject_config.py` → `start_picker`).
- Schemes are 4–6 steps (was 5–8); every draw has a branch (200 offline draws: 135 with one branch point, 65 with two).
- NOT yet proven: no hard organic question has come out of the new flow. That proof is the next goal.

## To do, in order
1. **Picker batch** (paid, about ₹15 at ₹88/$, approved size 15 picks):
   `python tools/start_batch.py --yardstick --n 15 > outputs/start_batch_1.log`
   - Compares the picks with real JEE starts (JEE used only to measure) and with today's pool.
   - Needs `data/jee_advanced_organic_full.json` (another session's file, not committed yet).
   - The first attempt was stopped: its DeepSeek extraction had 800 tokens and 68 replies were cut off; now 3000, saved after every answer, progress in the log.
2. **Judge the picks by hand**: rich enough? real compounds? right names? If weak, try a stronger picker (`models.START_PICKER`; Flash costs about ₹0.55 per call).
3. **One live organic run** with the picker (one question per run):
   `python run_groundup_final.py --subject organic --max-run-spend 0.15`
   - Check every compound and claim by hand; only a hard, correct question counts as proof.
4. **Remaining layers** of the plan:
   - (2) reagent × functional-group table (reacts / tolerated / unknown), author approves;
   - (3) product checks; (4) wider audit incl. 2-step combinations;
   - (5) look-ahead counts only approved rules (`check_start` is a first version);
   - (6) hold an MCQ/MSQ key when every ladder model agrees on another option.
5. **Concept book**: audit the remaining alternate-reagent links (e.g. 3/183/184 peroxide HBr and NBS on the no-peroxide HBr edge, 9 hydroboration, 13 Na/NH3 on Lindlar, 305 on Fries, 88, 205, 216, 217).
6. **Reagents the graph lacks** that JEE schemes use (seen in the yardstick samples): hydroboration–oxidation, acetylide alkylation (NaNH2 then R–X), NBS, Hofmann bromamide, Gabriel. Adding them needs the author's approval, like the scope list.

## Open money questions
- Live run 5 (stopped) and the stopped batch: exact spend unknown (killed before the spend line); see the OpenRouter usage page.

## Not ours (another session, still uncommitted)
- `core/pipeline/qf_writer.py` (`WRITE_TRIES` 2, physical; wants a live physical run before commit), `tests/test_qfirst.py`.
- Organic level recalibration: `knowledge/level_calibration_organic.json` (floor 1.98), `tools/calibrate_level.py`, `data/jee_advanced_organic_full.json`, `outputs/calib_level_organic_full.log`, and its ChangeLog entry.
