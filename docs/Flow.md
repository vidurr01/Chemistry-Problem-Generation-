# Flow

This is a live description of the current system. It explains what happens first, which function calls which, how data moves, which component depends on which, and where an error can originate. Update it when structure or execution flow changes.

## Overview

The system builds JEE Advanced chemistry questions for organic, inorganic and physical chemistry. There are three phases. Phase 0 and Phase 1 outputs are committed to the repository. Phase 2 is what you run.

- Phase 0: build the knowledge base (concept books, knowledge graphs).
- Phase 1: calibrate (meta-tag norm stats; anchor solve rates).
- Phase 2: generate questions.

The answer to every question comes from a deterministic engine (`core/engine/`), never from a model. Models pick inputs, write the stem, read facts back out of it, solve it as students would, and diagnose failures; every decision is made in code.

Engine status: physical is wired end to end. Inorganic and organic engines are being built; until they are, `run_groundup_final.py` exits with code 2 for those subjects and `generate_questions.py` skips them before launching any run.

## Phase 0: knowledge build

`tools/extract_notes.py` reads teacher notes and writes `knowledge/concept_book*.json`, the per-subject concept books.

`tools/build_graph.py --subject <s>` reads a subject's concept book and writes its knowledge graph, plus a `graph_unmapped*.json` list of entries left out. All three graphs share one schema:

- Organic: `knowledge/reaction_graph.json`, functional-group class nodes. This file was curated after it was built; the script no longer reproduces it exactly.
- Inorganic: `knowledge/reaction_graph_inorg.json`, species nodes, rules in `tools/graph_rules_inorganic.py`.
- Physical: `knowledge/reaction_graph_physical.json`, physical-quantity nodes. Its edges come from the physical engine: `tools/graph_rules_physical.py` exposes `tx_nodes()`, which returns the two nodes a computed concept-book entry connects, so the graph holds exactly the entries the engine can compute. A step that keeps the same quantity (a dilution, Boyle's law) is a self-loop. Entries the engine does not compute (facts, classifications, plot readings) are listed in `graph_unmapped_physical.json`.

## Phase 1: calibration

`data/jee_advanced/*.json` holds the JEE Advanced papers from 2012 to 2025.

`calibration/calibrate_solver_metatags.py --subject <s>` measures solution length and distractor count over the seed corpus and writes per-subject z-score parameters to `data/seeds/meta_tag_norm_stats_<subject>.json` (organic: `calibration/meta_tag_norm_stats.json`). Stats are written only for archetypes with at least two successful solver runs; a run stops without writing after five consecutive API failures.

`calibration/anchor_calibration.py` blind-solves real JEE Advanced numeric questions to measure how hard they are for strong models; `calibration/council_eval.py` does the same with the generation council (it imports `COUNCIL` from `core/models.py`).

`calibration/calibrate_thresholds*.py` derived the 0-100 thresholds of the earlier weak/strong-solver loop. That loop has been removed; their results are kept for reference.

## The engine (`core/engine/`)

`base.py` defines `Step`: one concept-book entry as a computation between two graph nodes, with its inputs (`Param`), answer field, typical mistakes (`Trap`), the constants the question must state, a role per output and a topic. `plan_chain(steps)` wires each step's outputs into the next step's inputs by field name; every input that is not wired is a "given" the question must state, and a chain whose steps share nothing is refused. `run_chain(plan, values)` computes the answer, a step-by-step trace and the traps: each trap's wrong value is run through the rest of the chain, so a trap is the final answer a student making that mistake would write.

Coherence: `links(a, b, bridges)` lets step b follow step a only if b uses one of a's outputs, no wired value carries a role b's input rejects, and their topics are equal or bridged. `assign_steps()` picks one concept-book entry per graph edge so the whole chain links, and `roles_consistent()` follows roles through substance-preserving steps (`keeps_role`).

A question never states a value its other data already fix. A step hands on what it fixes (a Nernst step's 298 K, a cell step's ΔS, which Kirchhoff moves to T₂), derives what follows from earlier values (`Derive`: ΔS of a gas takes n from P₁V₁/RT₁), and roles keep apart quantities with the same field name but different meaning (K° from ΔG° is not K_c; the rate of reaction is not −d[A]/dt). `plan_tree()` refuses a tree in which two branches supply, or could supply, the same input of the merging step (a step that only hands on a value it read does not count as supplying it). `tools/audit_engine.py` checks every chain of up to three steps offline for unit mismatches and repeated values and runs it on sampled inputs.

`chem.py` holds the formula parser, equation parsing/balance checks, redox balancing (SymPy nullspace), atomic masses and the physical constants with the wording a question uses to state them.

`physical/` holds 311 physical steps across all chapters (`advanced.py`, tx 348-392, adds every formula the JEE Advanced 2012-2025 physical questions use; see `docs/advanced_formula_map.md`), the topic of each step (chapter, with nuclear entries split from kinetics) and `BRIDGES`, the chapter pairs a chain may cross. `can_follow()` and `chain_steps()` are what the walk uses.

`facts.py` builds fact questions: four statements from a category table or a true/false pool (`physical/facts_data.py`, 36 sources), in one of three modes (one or more correct, exactly one correct, exactly one incorrect); the answer is the set of option letters.

## Phase 2: generation

`run_groundup_final.py --subject <s> [--chapter C] [--seed N] [--kind auto|chains|facts]` generates at most one question per run. With `--kind auto` a fact question is made in the subject's `fact_share` of runs (physical: 25%; ignored for a subject with no fact adapter), otherwise a chain question. `generate_questions.py` runs it repeatedly in fresh subprocesses (`--physical 5` etc.), stops a subject after `--max-consecutive-failures`, kills a hung run after `--child-timeout`, stops the batch at `--max-spend` US dollars (summing each run's "Spend this run" line) and appends all output to `outputs/batch_run.log`.

### Question first (default for computed questions)

`run_groundup_final.py --flow question` (the default) sends chain runs to `qfirst.run()` (`core/pipeline/qfirst.py`); `--flow engine` keeps the engine-first run described under "One run". Fact runs are unchanged.

1. **Formulas.** `PhysicalAdapter.random_formulas()` draws 3-5 distinct steps at random, connected: the first from all of the engine's steps (with `--chapter`, from that chapter), each next one among those sharing a quantity (a graph node) with one already drawn. No order and no chain. A run stops starting new draws or rounds once it has spent `--max-run-spend` (default $0.45, about ₹40: 3–4 draws; it was $0.12, which one long design used up). Sets tried earlier in the run are excluded; up to `MAX_DRAWS` (6) draws per run. (`all_chains()` / `random_chain()`, every linked chain of 3-5 steps, are kept for subjects whose questions are chains, e.g. organic sequences; the physical flow does not use them.)
2. **Twist.** One of `TWISTS` at random: inverse, two-state ratio, two-state difference, simultaneous, condition.
3. **Design** (`qf_design.design_question`, `models.DESIGNER` = Gemini 3.1 Pro at thinking level "low", once per draw): ONE design built around a hidden link (how the formulas meet through a quantity the question never names, what the student must notice, the trap there); it may reply `impossible` (new draw). It sees each formula's limits (`qf_draw.formulas_text`). Jev then checks the design (`design_problems`) with cut-offs calibrated on reverse-designs of real JEE Advanced questions (`knowledge/design_coherence_calibration_physical.json`); a rejected design means a new draw (`DESIGN_TRIES` = 1).
4. **Write** (`qf_writer.write_question`, `models.GENERATOR`, up to `WRITE_TRIES` 3 per question): the question with every number as a blank `[[name]]` (`BLANK_RULES`). Each blank gets a `"range"` (any value that could be many things: amounts, masses, temperatures, measured results) or a `"value"` (only a value of the substance or situation itself: a molar mass, E°, a tabulated ΔfH°, the 8 corners of a cube); a count is marked `"whole": true`; the constants of the Given line are blanks with their standard value; `"answer_range"` bounds the answer. `parse_values` reads them; `blank_problems` sends the writer back, before any program is paid for, for a number written out, a blank with no range, the asked quantity shown as a blank, a power of ten beside a blank or a reserved name. Jev's level check (`qf_checks.level_problem`, floor calibrated on real papers by `tools/calibrate_level.py`; each range blank read at a typical value) sends a JEE Main-level draft back.
5. **Solve: coder 2** (`qf_coder.solver_program`, `models.CODER` = GPT-6 Luna, up to `CODE_TRIES` 3): `write_blank_program` writes `solve()` from the question WITH ITS BLANKS, before any number exists; each blank is a variable of the program. It is shown only the drawn steps (chapter, formula, inputs, outputs, the engine's own code) and their exact forward and backward calls (`exact_calls`). A probe (`sandbox.search_numbers(probe=True)`) runs it on value sets from the ranges: a program that does not run, assigns to a blank, never reads a picked value, or leaves out a drawn formula that cannot be dropped goes back to the coder with the error; twice no value set runnable at all → the ranges are impossible, back to the writer; `cannot` → back to the writer.
6. **Numbers: coder 1** (`qf_numbers.pick_numbers` → `sandbox.search_numbers`; code, no model): up to `PICK_TRIES` 200 value sets are drawn in the ranges (log-uniform over a wide positive range, 3 significant figures as printed, counts whole) and run through coder 2's program. A set is taken when the answer is in `answer_range`, rounding the steps to 3 figures moves it by at most `FRAGILE_TOL` (2 %), at least `MIN_TRAPS` (2) typical mistakes change it, and every picked (range) value is used (the writer's fixed values may be background, as "standard conditions, 298 K" in a real paper). `filled_question` prints exactly those values in the question. No set works → back to the writer with the furthest failure in its terms (`numbers_problem`); a program that breaks or hangs on other values → back to the coder once (`numbers_for`).
7. **Checks** (`qf_checks`): drawn formulas the program did not need are dropped while 3 remain (`unneeded`); `question_problems` sends back a question whose formula does not change the answer, that states an intermediate, misses a constant, or is too close to an example or an accepted question; then Jev's coherence check (`coherence_problems`: invented relation, glued parts, arbitrary condition; cut-offs calibrated on real questions, the 95th percentile; a looser 99th-percentile cut-off is under trial in `tools/step_by_step.py check`). Jev unreachable: skipped.
8. The stem gets the answer-format sentence; the result (`make_result`) carries the trace, traps, constants, tolerance and `solver_code`; the blackboard notes `qfirst` with the values the question prints (`preset`). Then `dedup` on the formulas and those values, and `flow.judge()` (ladder, verifier, hints).
9. **Too easy** (`refine_round`, `core/pipeline/refine.py`): Jev (TypeSafe's System One decision model, `models.JEV_MODEL`, through OpenRouter's Decisions API with `OPENROUTER_KEY`) reads the question, the drawn formulas and the working of the solver that solved it, and answers one yes/no ("noul") question per case in one request, giving each of the 8 `CASES` a probability: `cue_word` (a word named the method), `ready_data` (data in the form the formulas use), `shortcut_worked`, `plugin_order` (straight plug-in), `one_system`, `too_few_steps`, `textbook_pattern`, `trivial_units`. `pick()` takes the single likeliest unused case (`PER_ROUND` = 1); a case is never applied twice to one question, and `too_few_steps` is not offered once 5 formulas are drawn. Code applies what a case needs first: `plugin_order` switches the twist to inverse or condition, `one_system` to a two-state or simultaneous twist, `too_few_steps` draws one more formula at random. The writer (Gemini 3.7 Flash) then rewrites with `instructions()`: a fixed header and the picked case's fixed instruction only (if/else: the writer never sees the other cases). The rewrite goes through every check again. If Jev cannot be reached an unused case is chosen at random. At most `MAX_ROUNDS` (3) rounds; when every case is used the run draws new formulas. **Unclear wording / duplicate**: the writer rewrites (keeping the values, or choosing new ones).

A parked question-first item stores its code, stem, twist and the values the question prints (`preset`); `rebuild_result()` runs the program again on those values. `qfirst.py` runs these stages (`write_and_solve`, `run`); `docs/PIPELINE.md` maps each to its file.

### One run (engine first, `--flow engine`)

1. `main()` checks `OPENROUTER_KEY` (`core/models.key_is_set()`), loads the subject config and graph, and builds the subject adapter (`core/pipeline/adapters.py`; only physical exists, the others exit 2). A `--chapter` not on the graph exits 2.
2. `recheck_pending()` judges parked questions first (see "Parking"). An acceptance ends the run.
3. `flow.run()` (`core/pipeline/flow.py`) tries up to `MAX_CHAINS` (3) chains:
   1. **Walk.** `adapter.candidates()` calls `sample_chains()` with the engine's `can_follow` and a validator, assigns one engine step per edge, plans the chain, and ranks candidates by coverage weight × trap-type weight (rarer trap types first). Steps that cannot join any chain are added as single-step candidates at half weight. Chains tried earlier in the run are skipped. For a fact run, `PhysicalFactsAdapter.candidates()` builds one question per fact source and ranks them by coverage.
   2. **Blackboard.** `Blackboard.start_chain()` opens the chain's notebook; every later stage writes to it with `note()`.
   3. **Inputs.** `stages.propose_inputs()` (generator, Gemini 3.7 Flash) either vetoes the chain as incoherent or proposes a scenario and a value for every given. `coerce_values()` types them, and the engine computes. An `EngineError` (impossible values) goes back to the generator, up to `INPUT_TRIES` (3); an unexpected engine exception queues `engine_unknown`.
   4. **Duplicate check.** `dedup.signature()` hashes the subject, the engine steps and every given; an accepted question with the same signature sends the chain back for new inputs before any stem is written (rewording would keep the same inputs).
   5. **Stem and gate.** (Fact questions: `stages.write_fact_stem()` adds at most a sentence of context to the code-built question and options, and `gate.compare_fact()` checks in code that they appear verbatim; no input proposal or extraction.) Chains: `stages.write_stem()` (generator) writes the question around the fixed values, constants and asked quantity, told the trap descriptions so it does not give them away. `stages.gate_extract()` (extractor, DeepSeek V4 Flash) copies the stated values, the asked quantity (from shuffled options) and the stated constants into a form; `gate.compare()` (code) requires every value within 0.1%, the right quantity, and every constant. A mismatch rewrites the stem with the mismatches as feedback (original + `GATE_RETRIES` 2); an unreadable form queues `gate_unreadable` and drops the chain. For a non-numeric answer the stem ends with a fixed answer instruction from `physical.ANSWER_FORMATS` (e.g. "Answer yes or no.", "Answer with exactly one of: forward, backward, no shift.", a nuclide as symbol and mass number); the gate checks in code that it is copied exactly.
   6. **Ladder.** `models.LADDER` = Granite 4.2 8B (bottom step since 2026-11-19; it was Llama 3.3 70B) → GLM-5.3-Flash → MiniMax M3 (top step since 2026-11-19; it was GPT-6 Luna, the coder's own model) (Llama replaced Phi-4 on 2026-11-17: Phi-4 is not on airouter.in), weakest first, closed book (question only). Each step is solved and graded before the next is called, and the next is called only if every step below failed; steps not called are recorded in `council_skipped`. Calibration on real papers (`calibration/ladder_separation.py`): Llama 3.3 70B fails 29 % of easy/medium Mains numericals but 66 % of hard Mains and Advanced ones (a 37.6-point gap; Phi-4's was 38.7, with 14 % / 53 %); GLM and Luna barely separate the two and serve as labels. Each returns working, final answer, unit and an optional objection (chemistry or wording).
   7. **Grading (code only; no verifier since 2026-11-19).** `answers.matches()` compares each final answer with the engine's → `answer_matches`. Numbers within 1% and option letters are code only. Non-numeric answers are compared by code where their shape allows (`answers.text_answers_match`: formulas by element counts, nuclides by symbol and mass number, configurations, balanced equations up to a common factor, and categories such as forward / backward / no shift, precipitate / no precipitate, isotopes / isobars / isotones with synonyms and yes/no); an answer code cannot read counts as not matched. Solvers end with one answer line `[TYPE] [CALC_VALUE] [CALC_UNIT] [SUBSTANCE]` (`answers.spec_instruction`); code fills TARGET_UNIT from the question, FINAL_VALUE by converting CALC_VALUE with pint (`core/units.py`) and RENDER, and compares FINAL_VALUE with the engine (`flow._code_match`). For options and letters CALC_VALUE is the option itself; the stem ends with the matching instruction ("Give the answer in L.", "Answer yes or no."), checked by the gate in code. A reply that breaks the spec gets one short repair request (`stages._repair_format`) to restate the same answer; it is never graded on its form. Solved = the answer matches (`counts_as_solved` = `answer_matches`). Objections are kept in the record; they no longer drop a chain.
   8. **Decision.** The first step (Granite 4.2 8B) solves it: too easy. The refiner (`models.REFINER`, Gemini 3.8 Flash) takes over for that round, with the solvers' working: `stages.choose_refinement()` picks new inputs or rewording (physical allows both), then `propose_inputs(refine=...)` designs inputs where the solvers' route fails, or `write_stem(solved=...)` rewrites the stem without the cue that made it easy. The first draft and clarity rewording stay with the generator; each refinement is a round, at most `MAX_ROUNDS` (3), after which the chain is dropped. The first step fails: the difficulty label is the first step that solved it (`models.DIFFICULTY_LABELS`: GLM → advanced or mains_hard, decided by Jev's level check, advanced_or_mains_hard while it is not calibrated; MiniMax M3 → advanced_medium; none → hard_advanced), and each step that did not solve gets the insight hint (written by code from a step and its listed mistake) and solves again, graded by code; the question is accepted either way (the hint result is recorded).
4. **Acceptance.** `save_accepted()` builds the record (with the readable solution from `stages.write_solution()`, `models.SOLUTION_WRITER` = Gemini 3.8 Flash, checked in code and by the solution checker (Claude Haiku 5.5), and the meta-tags), writes it atomically to `outputs/generated_questions_<subject>.json` — the only step whose failure means "not accepted" — then updates coverage (edges, concepts, trap types), the duplicate store, `results/` (`tools/results.py promote`) and the attempt log; failures there only warn.

### Parking

Every council member called must be measured. If a solver call (ladder or hint re-solve) fails after retries, `flow.judge()` raises `flow.Parked`; the question (engine steps, givens, scenario, stem) goes to `outputs/pending_questions_<subject>.json` and the run exits 3 (the batch stops). The next run recomputes the engine result and runs `flow.judge()` on the stored stem; accept saves it; too easy removes it from pending. After `MAX_RECHECK_FAILURES` failed rechecks, or when it can no longer be recomputed, it moves whole to `outputs/on_hold_questions_<subject>.json` (never dropped); `--rerun-held` judges those again.

## How data moves

Inputs: the concept book, the knowledge graph, the engine steps, and the meta-tag norm stats. Per question, the `Blackboard` holds the chain and every stage's events; it is saved in the accepted record.

Outputs:
- `outputs/generated_questions_<subject>.json`: accepted questions. Each record holds the question, the engine answer and unit, the readable solution, `tags` (knowledge: recall or closed_book; trap types), `council_n_correct` (raw answer matches) and `council_n_solved` (what acceptance used), each member's answer with `answer_matches`, verdict, failure type, `slip_confirmed` and `counts_as_solved`, the hint tests, the engine part (steps, edges, scenario, givens, constants, trace, traps), rounds, meta-tags, model roster, spend and the Blackboard history.
- `outputs/generated_questions_<subject>_attempts.jsonl`: one line per event (veto, gate failure, decision per round, queue entries, acceptance).
- `outputs/queue_<reason>_<subject>.json`: review queues; `tools/results.py queue` lists them, `dismiss` removes a reviewed item.
- `outputs/verifier_seen_inputs.json`: the duplicate store.
- `outputs/coverage_state_<subject>.json`: coverage counters, including trap types.
- `results/generated_questions_<subject>_final.json`: the review set with human-eval slots (`tools/results.py score`).

`tools/evaluate.py` reports acceptance, solved vs correct, per-member rates, rounds, knowledge tags, trap-type spread, failure labels, hint outcomes and spend.

## Where an error can originate

- A missing or placeholder API key stops the run (exit 2); `generate_questions.py` also checks it before starting.
- A missing graph, a subject whose engine is not wired yet, or an unknown `--chapter` exits 2; the batch driver reports a subject with no engine before launching anything and skips it.
- Every model call goes through `core/models.ask_json()`: transient errors (429, 5xx, timeouts) are retried with backoff, an unusable reply is asked for again twice; other errors raise.
- A generator veto, three rejected input proposals, a failed gate or exhausted rounds only drop the current chain.
- An unexpected exception inside the engine queues `engine_unknown`; the chain is dropped.
- A failed solver call parks the question (exit 3, batch stops). A save failure exits 4.
- A solution-writer or meta-tag failure never blocks acceptance: the record is saved without the solution / with `meta_tags_error`.

## Component dependencies

- `run_groundup_final.py` depends on `core/pipeline/` (flow, stages, gate, adapters, queues), `core/models.py`, `core/dedup.py`, `core/blackboard.py`, `subject_config.py` and `tools/results.py`.
- `core/pipeline/adapters.py` depends on `core/engine/` and `core/graph_traversal.py`.
- `core/pipeline/flow.py` depends on `core/answers.py` (answer parsing, safe arithmetic), `core/dedup.py` and the stages.
- `core/models.py` holds the roster and the call helper; it uses `core/llm.py` (`.env`, JSON parsing, retries, atomic writes), which the tools and calibration scripts also use.
- `core/coverage.py`, `core/meta_tags.py` (with the committed norm stats) and `core/graph_traversal.py` are shared by every subject.
