# Flow

This is a live description of the current system. It explains what happens first, which function calls which, how data moves, which component depends on which, and where an error can originate. Update it when structure or execution flow changes.

## Overview

The system builds JEE Advanced chemistry questions. It supports three subjects: organic, inorganic, and physical. There are three phases. Phase 0 and Phase 1 outputs are committed to the repository. Phase 2 is what you run.

- Phase 0: build the knowledge base.
- Phase 1: calibrate thresholds and norm stats.
- Phase 2: generate questions.

## Phase 0: knowledge build

`tools/extract_notes.py` reads teacher PDFs and writes `knowledge/concept_book*.json`. Each file holds per-subject reaction transformations.

`tools/build_graph.py` reads the concept book and writes `knowledge/reaction_graph.json`. It also writes `knowledge/graph_unmapped.json` as a diagnostic of transformations it could not map.

Organic has a real graph. Inorganic graph input is not built yet. Physical has no graph.

## Phase 1: calibration

`data/jee_advanced/*.json` holds the JEE Advanced papers from 2012 to 2025.

`calibration/calibrate_thresholds*.py` runs real questions through the old weak and strong solvers to derive two 0-100 thresholds. The values 85 and 60 are baked into each entrypoint as `STRONG_FLOOR` and `WEAK_CEILING`. The ground-up path no longer gates on them. It gates on the council solve-count instead, so those constants are vestigial there. `run_graph_final.py` still uses them.

`calibration/calibrate_solver_metatags*.py` measures solution length and distractor count over the seed corpus. It writes the per-subject z-score parameters to `data/seeds/meta_tag_norm_stats_<subject>.json`.

## Phase 2: generation

Two entrypoint families run the same core loop. They differ in knowledge source and subject.

- `run_graph_final.py` uses the reaction graph. Subjects: organic and inorganic.
- `run_groundup_final.py` builds from a filtered slice of the concept book. Subjects: all three.

`subject_config.py` is the single source of truth for per-subject paths, prompts, and default values. `get_subject_config(subject)` returns a config dict.

`generate_questions.py` is an optional batch driver on top of `run_groundup_final.py`. It takes a target count per subject. For each question it runs the entrypoint in a fresh subprocess, then compares the record count in `generated_questions_<subject>.json` before and after to see whether that run accepted a question. It retries a subject until the target is met or a consecutive-failure limit is reached, kills a hung question after `--child-timeout`, and appends the full run console to `batch_run.log` in append mode. It does not change the generation loop.

### Ground-up flow in `run_groundup_final.py`

This is the file you run most often. It supports all three subjects.

1. `main()` reads the CLI args and checks `OPENROUTER_KEY`. It returns early if the key is missing or still the placeholder.
2. It loads the subject config and picks the default chapter and archetype.
3. It checks that the subject concept book exists. If not, it prints an error and returns.
4. It loads the concept book and calls `filter_txs_for_subject()` to keep only the transformations for the chosen chapter and archetype.
5. It loads or creates the coverage state with `load_coverage_for_subject()`.
6. It builds a `Blackboard` from a topic anchor and a target difficulty profile.
7. The loop tries up to `MAX_LINEAGES` (3) fresh question ideas, with a hard cap of `MAX_ITERS` (4) total generate-check iterations.

Inside each iteration:

1. `concept_reasoner()` (`deepseek/deepseek-chat-v3-0324`) selects a subset of transformations and returns a chain description. This runs once per lineage.
2. `generator()` (`google/gemini-2.5-flash`) writes a question and a reference solution.
3. `verify_problem()` in `core/verifier.py` runs. Tier 1 is a deterministic duplicate-input check with no model. Tier 2 is a sequence of narrow `google/gemini-3-flash-preview` calls: blind-solve the problem with the candidate withheld, extract the candidate's final answer, compare the two answers, and only if they agree, check for structural flaws and rate difficulty. The PASS or FAIL verdict is decided in code from those results. A disagreeing answer is an immediate FAIL. On the second consecutive FAIL of a lineage (`VERIFIER_FAIL_MAX` is 2, so one refine pass) the lineage is abandoned and a new idea starts.
4. On verifier PASS, `council_solve()` runs the three council models (`meta-llama/llama-3.3-70b-instruct`, `mistralai/mistral-large-2407`, `google/gemma-3-27b-it`) in parallel on a thread pool. Each member blind-solves closed-book, then `grade_answer()` (`openai/gpt-4o`) judges its answer against the construction steps. The count of members that solved is the difficulty signal.
5. The attempt is recorded on the blackboard.
6. Gates: verifier PASS, `reference_correct` true, and at most one of three council members solved. Two or three solved means too easy, so the loop refines for reasoning complexity.

On acceptance the loop calls `compute_meta_tags_for_subject()` for the six-axis difficulty label, updates coverage, and appends a record to `generated_questions_<subject>.json`.

### Graph flow in `run_graph_final.py`

`coverage.py` selects the least-covered edge, chapter, and archetype. `graph_traversal.py` runs a breadth-first search to build a candidate reaction path. The rest of the loop is the older weak-solver plus strong-solver two-pass protocol with the 85 and 60 gates. This path has not been moved to the answer-first verifier or the council.

## How data moves

The inputs are the concept book, the reaction graph, the seed corpus, and the norm stats. The pipeline reduces those to a validated question record.

The `Blackboard` is the shared working object. It carries the seed, the archetype, the target profile, and the full attempt history. It records each problem, solution, verifier result, and a score slot. In the ground-up path that slot holds the council solve-count, not a 0-100 score.

The coverage object tracks which chapters and archetypes have been accepted. It is saved to `coverage_state_<subject>.json` after each acceptance.

The output is `generated_questions_<subject>.json`. Each record holds the question, solution, meta-tags, council detail, verifier detail, and attempt history. Every attempt, accepted or not, is also written to `generated_questions_<subject>_attempts.jsonl`.

## Where an error can originate

- A missing or placeholder API key stops the run before generation.
- A missing concept book stops the run early.
- An empty transformation list stops the run early.
- A missing `data/seeds/meta_tag_norm_stats_<subject>.json` (inorganic, physical) crashes the run at the meta-tag step, after the item has already passed the gate.
- The inorganic graph entrypoint fails if `knowledge/reaction_graph_inorg.json` does not exist.
- Every LLM role reads the OpenRouter API. Rate limits and 503s are retried with backoff. A key over its spend limit returns 403 and every call then fails fast.
- A council member that returns malformed JSON is recorded as not solved, which biases the difficulty signal toward "harder".

## Component dependencies

- Entrypoints depend on `subject_config.py`, `core/meta_tags.py`, `core/coverage.py`, `core/blackboard.py`, and `core/verifier.py`.
- Graph entrypoints also depend on `core/graph_traversal.py`.
- `core/meta_tags.py` depends on the committed norm stats.
- `core/verifier.py` is live. It holds the two-tier verifier and its own `VERIFIER_MODEL` (`google/gemini-3-flash-preview`), which is the authoritative value.
- `core/blackboard.py`, `core/coverage.py`, `core/meta_tags.py`, and `core/graph_traversal.py` are live. The generation, solving, and grading logic is defined inline in the entrypoints, not in `core/`.
