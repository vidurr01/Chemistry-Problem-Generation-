# Flow

This is a live description of the current system. It explains what happens first, which function calls which, how data moves, which component depends on which, and where an error can originate. Update it when structure or execution flow changes.

## Overview

The system builds JEE Advanced chemistry questions for organic, inorganic and physical chemistry. There are three phases. Phase 0 and Phase 1 outputs are committed to the repository. Phase 2 is what you run.

- Phase 0: build the knowledge base (concept books, knowledge graphs).
- Phase 1: calibrate (meta-tag norm stats; anchor solve rates).
- Phase 2: generate questions.

The answer to every question comes from a deterministic engine (`core/engine/`), never from a model. Models pick inputs, write the stem, read facts back out of it, solve it as students would, and diagnose failures; every decision is made in code.

Engine status: physical is wired end to end. Inorganic and organic engines are being built; until they are, `run_groundup_final.py` exits with code 2 for those subjects.

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

`chem.py` holds the formula parser, equation parsing/balance checks, redox balancing (SymPy nullspace), atomic masses and the physical constants with the wording a question uses to state them.

`physical/` holds 267 physical steps across all chapters, the topic of each step (chapter, with nuclear entries split from kinetics) and `BRIDGES`, the chapter pairs a chain may cross. `can_follow()` and `chain_steps()` are what the walk uses.

`facts.py` builds fact questions: four statements from a category table or a true/false pool (`physical/facts_data.py`, 36 sources), in one of three modes (one or more correct, exactly one correct, exactly one incorrect); the answer is the set of option letters.

## Phase 2: generation

`run_groundup_final.py --subject <s> [--chapter C] [--seed N] [--kind auto|chains|facts]` generates at most one question per run. With `--kind auto` a fact question is made in the subject's `fact_share` of runs (physical: 25%), otherwise a chain question. `generate_questions.py` runs it repeatedly in fresh subprocesses (`--physical 5` etc.), stops a subject after `--max-consecutive-failures`, kills a hung run after `--child-timeout`, stops the batch at `--max-spend` US dollars (summing each run's "Spend this run" line) and appends all output to `outputs/batch_run.log`.

### One run

1. `main()` checks `OPENROUTER_KEY` (`core/models.key_is_set()`), loads the subject config and graph, and builds the subject adapter (`core/pipeline/adapters.py`; only physical exists, the others exit 2). A `--chapter` not on the graph exits 2.
2. `recheck_pending()` judges parked questions first (see "Parking"). An acceptance ends the run.
3. `flow.run()` (`core/pipeline/flow.py`) tries up to `MAX_CHAINS` (3) chains:
   1. **Walk.** `adapter.candidates()` calls `sample_chains()` with the engine's `can_follow` and a validator, assigns one engine step per edge, plans the chain, and ranks candidates by coverage weight × trap-type weight (rarer trap types first). Steps that cannot join any chain are added as single-step candidates at half weight. Chains tried earlier in the run are skipped. For a fact run, `PhysicalFactsAdapter.candidates()` builds one question per fact source and ranks them by coverage.
   2. **Blackboard.** `Blackboard.start_chain()` opens the chain's notebook; every later stage writes to it with `note()`.
   3. **Inputs.** `stages.propose_inputs()` (generator, Gemini 2.5 Flash) either vetoes the chain as incoherent or proposes a scenario and a value for every given. `coerce_values()` types them, and the engine computes. An `EngineError` (impossible values) goes back to the generator, up to `INPUT_TRIES` (3); an unexpected engine exception queues `engine_unknown`.
   4. **Stem and gate.** (Fact questions: `stages.write_fact_stem()` adds at most a sentence of context to the code-built question and options, and `gate.compare_fact()` checks in code that they appear verbatim; no input proposal or extraction.) Chains: `stages.write_stem()` (generator) writes the question around the fixed values, constants and asked quantity, told the trap descriptions so it does not give them away. `stages.gate_extract()` (extractor, DeepSeek V4 Flash) copies the stated values, the asked quantity (from shuffled options) and the stated constants into a form; `gate.compare()` (code) requires every value within 0.1%, the right quantity, and every constant. A mismatch rewrites the stem with the mismatches as feedback (original + `GATE_RETRIES` 2); an unreadable form queues `gate_unreadable` and drops the chain.
   5. **Duplicate check.** `dedup.signature()` hashes the subject, the engine steps and every given; an accepted question with the same signature sends the chain back for new inputs.
   6. **Council.** `stages.council_solve()` runs GPT-OSS-120B and GLM-4.7-Flash (`models.COUNCIL_FIRST`) in parallel, closed book (question only), reasoning effort medium. After their verifier diagnoses and grading, Qwen3-235B-Thinking is called only if it could change the decision: with too easy at 2 solved, that is when exactly one of the first two solved. Otherwise it is recorded in `council_skipped`. The accept / too-easy outcome is the same as with all three; Qwen-Thinking is about 60% of a pass's cost. Each returns working, final answer, unit and an optional objection (chemistry or wording).
   7. **Mismatch verifier.** `stages.verify_member()` (Claude Haiku 5.5) reads every member's work against the engine's trace: verdict (correct, right answer by wrong reasoning, wrong, reference wrong), and for a wrong answer why (genuine difficulty, unclear wording, missing knowledge, slip), the step where it went wrong, and for a slip the arithmetic the member set up.
   8. **Grading (code).** `answers.matches()` compares each final answer with the engine's (numbers within 1%, text normalised) → `answer_matches`. A member counts as solved if it matches and the verdict is correct, or if a slip is confirmed by evaluating the member's own expression (`answers.safe_eval`). A "reference wrong" verdict or a valid objection queues `engine_wrong`; an objection the verifier is unsure about queues `objection_unresolved`; both drop the chain.
   9. **Decision.** 2 or more solved: too easy. `stages.choose_refinement()` picks new inputs or rewording (physical allows both); each refinement is a round, at most `MAX_ROUNDS` (3), after which the chain is dropped. 0 or 1 solved: hint tests on each member that did not solve:
      - unclear wording → clarification hint (generator); solved with it → reword and judge again (a round);
      - missing knowledge → knowledge hint (the chain's relations, written by code); solved with it → tagged recall;
      - otherwise (genuine difficulty, unconfirmed slip, right answer by wrong reasoning) → insight hint written by code from the step and its listed mistake; solved → difficulty confirmed; not solved → the verifier re-reads the hinted attempt: reference wrong → `engine_wrong`, unclear wording → reword, otherwise accepted as hard.
4. **Acceptance.** `save_accepted()` builds the record (with the readable solution from `stages.write_solution()`, Mistral Small 3.2, and the meta-tags), writes it atomically to `outputs/generated_questions_<subject>.json` — the only step whose failure means "not accepted" — then updates coverage (edges, concepts, trap types), the duplicate store, `results/` (`tools/results.py promote`) and the attempt log; failures there only warn.

### Parking

Every council member called must be measured. If a council call fails after retries, `CouncilMemberFailed` → `flow.Parked`; the question (engine steps, givens, scenario, stem) goes to `outputs/pending_questions_<subject>.json` and the run exits 3 (the batch stops). The next run recomputes the engine result and runs `flow.judge()` on the stored stem; accept saves it, any other outcome drops it from pending.

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
- A missing graph, a subject whose engine is not wired yet, or an unknown `--chapter` exits 2; the batch driver skips that subject.
- Every model call goes through `core/models.ask_json()`: transient errors (429, 5xx, timeouts) are retried with backoff, an unusable reply is asked for again twice; other errors raise.
- A generator veto, three rejected input proposals, a failed gate or exhausted rounds only drop the current chain.
- An unexpected exception inside the engine queues `engine_unknown`; the chain is dropped.
- A council failure parks the question (exit 3, batch stops). A save failure exits 4.
- A solution-writer or meta-tag failure never blocks acceptance: the record is saved without the solution / with `meta_tags_error`.

## Component dependencies

- `run_groundup_final.py` depends on `core/pipeline/` (flow, stages, gate, adapters, queues), `core/models.py`, `core/dedup.py`, `core/blackboard.py`, `subject_config.py` and `tools/results.py`.
- `core/pipeline/adapters.py` depends on `core/engine/` and `core/graph_traversal.py`.
- `core/pipeline/flow.py` depends on `core/answers.py` (answer parsing, safe arithmetic), `core/dedup.py` and the stages.
- `core/models.py` holds the roster and the call helper; it uses `core/llm.py` (`.env`, JSON parsing, retries, atomic writes), which the tools and calibration scripts also use.
- `core/coverage.py`, `core/meta_tags.py` (with the committed norm stats) and `core/graph_traversal.py` are shared by every subject.
