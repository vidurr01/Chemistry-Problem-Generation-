# Flow

This is a live description of the current system. It explains what happens first, which function calls which, how data moves, which component depends on which, and where an error can originate. Update it when structure or execution flow changes.

## Overview

The system builds JEE Advanced chemistry questions. It supports three subjects: organic, inorganic, and physical. There are three phases. Phase 0 and Phase 1 outputs are committed to the repository. Phase 2 is what you run.

- Phase 0: build the knowledge base.
- Phase 1: calibrate thresholds and norm stats.
- Phase 2: generate questions.

## Phase 0: knowledge build

`tools/extract_notes.py` reads teacher PDFs and writes `knowledge/concept_book*.json`. Each file holds per-subject reaction transformations.

`tools/build_graph.py --subject <s>` reads a subject's concept book and writes its knowledge graph, plus a `graph_unmapped*.json` diagnostic of entries left out (facts rather than steps). All three graphs share one schema:

- Organic: `knowledge/reaction_graph.json`, functional-group class nodes. This file was curated after it was built; the script no longer reproduces it exactly.
- Inorganic: `knowledge/reaction_graph_inorg.json`, species nodes, rules in `tools/graph_rules_inorganic.py`.
- Physical: `knowledge/reaction_graph_physical.json`, physical-quantity nodes, rules in `tools/graph_rules_physical.py`.

## Phase 1: calibration

`data/jee_advanced/*.json` holds the JEE Advanced papers from 2012 to 2025.

`calibration/calibrate_thresholds*.py` runs real questions through the old weak and strong solvers to derive two 0-100 thresholds. The values 85 and 60 are `STRONG_FLOOR` and `WEAK_CEILING` in `run_graph_final.py`, the only entrypoint that uses them. `run_groundup_final.py` gates on the council solve-count instead.

`calibration/calibrate_solver_metatags.py --subject <s>` measures solution length and distractor count over the seed corpus. Stats are written only for archetypes with at least two successful solver runs; the rest stay marked pending (`pending_calibration`), and a run stops without writing anything after five consecutive API failures. Errored seeds are retried on the next run. It writes the per-subject z-score parameters to `data/seeds/meta_tag_norm_stats_<subject>.json`.

## Phase 2: generation

Two entrypoint families run the same core loop. They differ in knowledge source and subject.

- `run_groundup_final.py`: the current architecture. Subjects: all three.
- `run_graph_final.py`: the older SambaNova weak/strong loop. Subjects: all three.

Both pick chains with the same traversal, `sample_chains()` in `core/graph_traversal.py`, on the subject's graph.

`subject_config.py` is the single source of truth for per-subject paths, prompts, and default values. `get_subject_config(subject)` returns a config dict.

`generate_questions.py` is an optional batch driver on top of `run_groundup_final.py`. It takes a target count per subject. For each question it runs the entrypoint in a fresh subprocess, then compares the record count in `outputs/generated_questions_<subject>.json` before and after to see whether that run accepted a question. It retries a subject until the target is met or a consecutive-failure limit is reached, kills a hung question after `--child-timeout`, and appends the full run console to `outputs/batch_run.log` in append mode. It does not change the generation loop.

### Ground-up flow in `run_groundup_final.py`

This is the file you run most often. It supports all three subjects.

1. `main()` reads the CLI args and checks `OPENROUTER_KEY`. It returns early if the key is missing or still the placeholder.
2. It loads the subject config and the archetype. Without `--chapter`, chains may come from anywhere in the graph.
3. It checks that the subject concept book and knowledge graph exist. If not, it prints an error and returns.
4. It loads the concept book and the graph (`load_graph()`), and loads or creates the coverage state with `load_coverage_for_subject()`.
5. `recheck_pending()` runs the council again on each parked question, oldest first, before anything new is generated. Accepted (via the same `save_accepted()` as a new question) ends the run; a too-easy or wrong-key result drops the question and logs `pending_too_easy` / `pending_reference_wrong`; another member failure keeps it parked and stops the run with exit code 3.
6. It checks that the graph has chains (in `--chapter`, if given); if not, it prints the chapters that do and exits with code 2.
7. It builds a `Blackboard` from a topic anchor and a target difficulty profile.
8. The loop tries up to `MAX_LINEAGES` (3) fresh question ideas, with a hard cap of `MAX_ITERS` (4) total generate-check iterations.

Inside each iteration:

1. Once per lineage, `sample_chains()` runs a breadth-first search over the whole graph from every start node and returns up to six chains of two or more steps, ranked by coverage weight (ties shuffled). Each step starts where the previous one ended, regardless of chapter; with `--chapter`, steps must stay in that chapter (topped up with chains that start in it). Chains used by an earlier lineage of the same run are skipped. The chain's chapters (`chain_chapters()`) become the question's chapter label and decide which concept-book entries go on the solvers' closed-book sheet. `concept_reasoner()` (`deepseek/deepseek-chat-v3-0324`) picks one; `chain_txs()` turns its edges into the concept-book entries the generator receives, and those entries are added to the solvers' knowledge sheet.
2. `generator()` (`google/gemini-2.5-flash`) writes a question and a reference solution.
3. `verify_problem()` in `core/verifier.py` runs. First one `google/gemini-3-flash-preview` call extracts the candidate's final answer. Tier 1 is a deterministic duplicate-input check on that answer, for numeric answers only (`parse_numeric_answers()`; compound names skip it): read-only, against accepted questions only (recorded on acceptance by `record_accepted_inputs()`), values equal within 1%. Tier 2 is a sequence of narrow calls: blind-solve the problem with the candidate withheld, compare the two answers, and only if they agree, check for structural flaws and rate difficulty. The PASS or FAIL verdict is decided in code from those results. A disagreeing answer is an immediate FAIL. On the second consecutive FAIL of a lineage (`VERIFIER_FAIL_MAX` is 2, so one refine pass) the lineage is abandoned and a new idea starts.
4. On verifier PASS, `council_solve()` runs the three council models (`meta-llama/llama-3.3-70b-instruct`, `mistralai/mistral-large-2407`, `google/gemma-3-27b-it`) in parallel on daemon threads. Each member blind-solves closed-book, then `grade_answer()` (`openai/gpt-4o`) judges its answer against the construction steps. The count of members that solved is the difficulty signal.
5. The attempt is recorded on the blackboard.
6. Gates: verifier PASS, `reference_correct` true (fewer than two of the three graders flagged the generator's answer key as wrong), and at most one of three council members solved. Two or three solved means too easy, so the loop refines for reasoning complexity. All three members must be measured: if any member's solve or grade call fails, `council_solve()` raises `CouncilMemberFailed` without waiting for the others, `park_pending()` saves the question with its verifier result, chain and knowledge sheet to `outputs/pending_questions_<subject>.json`, and the run exits with code 3. `generate_questions.py` stops the whole batch on that exit code.

On acceptance the loop calls `compute_meta_tags_for_subject()` for the six-axis difficulty label, updates coverage (including the chain's graph edges, which lowers their weight next time), and appends a record with its `graph_path` and `graph_edges` to `outputs/generated_questions_<subject>.json`.

### Graph flow in `run_graph_final.py`

Chain selection is the same `sample_chains()` call as above. The rest of the loop is the older weak-solver plus strong-solver two-pass protocol with the 85 and 60 gates. This path has not been moved to the answer-first verifier or the council.

## How data moves

The inputs are the concept book, the reaction graph, the seed corpus, and the norm stats. The pipeline reduces those to a validated question record.

The `Blackboard` is the shared working object. It carries the seed, the archetype, the target profile, and the full attempt history. It records each problem, solution, verifier result, and a score slot. In the ground-up path that slot holds the council solve-count, not a 0-100 score.

The coverage object tracks which chapters and archetypes have been accepted. It is saved to `outputs/coverage_state_<subject>.json` after each acceptance.

The output is `outputs/generated_questions_<subject>.json`. Each record holds the question, solution, meta-tags, council detail, verifier detail, and attempt history. Every attempt, accepted or not, is also written to `outputs/generated_questions_<subject>_attempts.jsonl`. Each accepted question is also copied into `results/generated_questions_<subject>_final.json` with empty human-eval slots, by `promote()` in `tools/results.py`; humans fill them with `tools/results.py score`.

## Where an error can originate

- A missing or placeholder API key stops the run before generation.
- Setup problems (missing key, concept book or graph; a `--chapter` with no chains) exit with code 2; `generate_questions.py` then skips that subject instead of retrying it.
- A missing concept book stops the run early.
- An empty transformation list stops the run early.
- A missing `data/seeds/meta_tag_norm_stats_<subject>.json` (inorganic, physical), or any other meta-tag error, no longer loses the item: it is saved with `meta_tags: null` and `meta_tags_error`.
- Saving an accepted question: `save_accepted()` builds the record, then writes it to the output file atomically — the only step whose failure means "not accepted". If that write fails, nothing else has changed; the question is parked in the pending file with its council result, and the run exits with code 4 (the batch stops). The next run retries only the save, with no new API calls. Coverage, the Tier 1 store, the `results/` copy and the attempt log come after the write; a failure in any of them only prints a warning.
- Both entrypoints stop early if the subject's graph file does not exist, or if it has no chains (in `--chapter`, if given).
- Every LLM role reads the OpenRouter API. Rate limits and 503s are retried with backoff. A key over its spend limit returns 403 and every call then fails fast.
- A council member whose call fails (after `api_call`'s 429/503 retries, or any other error such as a bad key or malformed JSON) stops the run and the batch; the question is parked in `outputs/pending_questions_<subject>.json` and rechecked first on the next run.

## Component dependencies

- Entrypoints depend on `subject_config.py`, `core/meta_tags.py`, `core/coverage.py`, `core/blackboard.py`, and `core/verifier.py`.
- `core/llm.py` is shared by the entrypoints, the verifier, the tools and the calibration scripts: `.env` loading, JSON parsing of model replies, atomic JSON writes, and retries on transient API errors.
- Both entrypoints also depend on `core/graph_traversal.py` and the subject's graph file.
- `core/meta_tags.py` depends on the committed norm stats.
- `core/verifier.py` is live. It holds the two-tier verifier and its own `VERIFIER_MODEL` (`google/gemini-3-flash-preview`), which is the authoritative value.
- `core/blackboard.py`, `core/coverage.py`, `core/meta_tags.py`, and `core/graph_traversal.py` are live. The generation, solving, and grading logic is defined inline in the entrypoints, not in `core/`.
