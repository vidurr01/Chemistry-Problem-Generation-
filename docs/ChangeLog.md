# ChangeLog

This file records every repository change. Newest entries go at the top. Each entry lists which files changed, what changed, why when useful, and any behaviour or configuration impact.

## 2026-10-13

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
