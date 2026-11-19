# The question-first pipeline (physical chemistry): where everything is

One page to read the code by. Each stage names the function that does it and the file it is in.

The full run starts in `run_groundup_final.py` → `flow.run` (`core/pipeline/flow.py`) → `qfirst.run` (`core/pipeline/qfirst.py`). To go stage by stage, use `tools/step_by_step.py`; it calls the same functions.

## The stages

| # | Stage | Who | Function | File |
|---|---|---|---|---|
| 1 | **Draw** 3-5 random formulas; Jev scores 6 sets, the best is used | code + Jev | `best_draw`, `formulas_fit` | `core/pipeline/qf_draw.py` |
|   | pick a twist (inverse, ratio/difference, simultaneous, condition) | code | `TWISTS` | `qf_draw.py` |
| 2 | **Design** the question around one hidden link | Gemini 3.1 Pro | `design_question` | `qf_design.py` |
|   | Jev checks the design (calibrated cut-offs) | Jev | `design_problems` | `qf_design.py` |
| 3 | **Write** the question: every number a blank `[[name]]` with a range (or a fixed value for a value of the substance), plus a range for the answer | writer (Gemini Flash) | `write_question`, `BLANK_RULES` | `qf_writer.py` |
|   | read the ranges; send broken blanks back to the writer | code | `parse_values`, `blank_problems` | `qf_writer.py` |
|   | Jev's level check (JEE Advanced or not), before any program is paid for | Jev | `level_problem` | `qf_checks.py` |
| 4 | **Solve**: coder 2 writes the program from the blanks, before any number exists; a probe runs it on values from the ranges | Luna | `solver_program`, `write_blank_program` | `qf_coder.py` |
| 5 | **Numbers**: coder 1 picks values in the ranges until the program's answer is in the answer range, robust to rounding (≤ 2 %), changed by ≥ 2 typical mistakes, and every picked value is used; then prints them in the question | code (no model) | `pick_numbers` → `sandbox.search_numbers`, `filled_question` | `qf_numbers.py`, `core/engine/sandbox.py` |
| 6 | **Checks**: no stated intermediate, every formula matters, not a copy; Jev coherence | code + Jev | `question_problems`, `coherence_problems` | `qf_checks.py` |
| 7 | **Judge**: dedup → ladder (Granite 4.2 8B → GLM → MiniMax M3, closed book) → grading by code → insight-hint tests | models | `flow.judge` | `core/pipeline/flow.py` |
| 8 | **Refine** if too easy or unclear: a new twist or one more formula, then back to stage 3 (at most 3 rounds) | Jev + code | `refine_round` | `qfirst.py` |
| 9 | **Save** the accepted question and its readable solution | code + models | `save_accepted`, `flow.checked_solution` | `run_groundup_final.py`, `flow.py` |

Stages 2-6 for one question are `write_and_solve` in `qfirst.py`; the loop over draws and rounds is `run` in the same file.

## When a stage fails, who is told

| Failure | Goes back to |
|---|---|
| blanks broken (a number written out, a blank with no range, the answer shown as a blank) | the writer |
| the program crashes, assigns to a blank, ignores a picked value, or leaves out a formula it needs | the coder (up to 3 tries) |
| no value set in the ranges works (answer outside its range, too fragile, too few typical mistakes, a picked value unused, an impossible situation) | the writer, in those words |
| the program breaks on some values only | the coder, once |
| Jev: below JEE Advanced level, or incoherent | the writer |
| the design is incoherent, or the writer says the formulas cannot make one question | a new draw |

## The other files

- `core/engine/` holds the formulas (`physical/*.py`, each a `Step` with inputs, result, typical mistakes) and the sandbox that runs the programs (`sandbox.py`).
- `core/models.py` holds the model roster and the router (OpenRouter first, airouter when it runs out).
- `core/pipeline/refine.py` holds the Jev calls (`jev_decide`, `jev_score`) and the refinement cases.
- `qf_text.py` holds helpers: how numbers are printed (`fill_template`) and read back (`stated_numbers`), and the novelty check.
- `knowledge/*calibration*.json` holds the calibrated cut-offs. `tools/calibrate_*.py` writes them.
- `docs/ChangeLog.md` records what changed and why, with dates. The dated notes that used to sit in the code are there.
- The older flows (`core/pipeline/stages.py`, `forms_layer.py`, and the `given()`-style programs in `qf_coder.program_for`) are not used by the question-first run. They are kept for the old flow and its tests.

## Checking it yourself

- `python -m unittest discover -s tests` runs all 414 offline tests (no API calls, ~100 s).
- `python tools/step_by_step.py real` puts a random real JEE Advanced question through the pipeline (see the docstring of `tools/step_by_step.py`).
