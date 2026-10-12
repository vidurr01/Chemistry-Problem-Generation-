# Decisions

This file records the reasoning behind meaningful technical choices. Each entry explains why an implementation was chosen, not just what was implemented.

## Council stops early when the last member cannot change the decision

Date: 2026-10-13
Context: at live prices Qwen3-235B-Thinking is about 60% of a pass's cost; the verifier (Haiku 5.5) is about 4%.
Decision: GPT-OSS-120B and GLM-4.7-Flash solve first; Qwen-Thinking is called only when exactly one of them solved, the only case in which it can move the solved count across the too-easy line (2). The verifier keeps reading every attempt.
Alternatives: verify only mismatches (saves ~₹0.1 per pass and lets lucky matches count as solved); swap Qwen for a cheaper model (needs calibration first, may lower the bar); lower Qwen's reasoning effort (lowers the bar for every question).
Trade-off: when Qwen is not called its objection is not heard. Two members agreeing with the engine make an engine error unlikely; when both fail, the insight-hint test and the verifier re-check still guard acceptance. Per-member statistics are over the questions each member was called on, and the 3-member solve count is not known for every question.

## Concept-book audit flags entries instead of deleting them

Date: 2026-10-13
Context: the inorganic audit found wrong, duplicate, misfiled and unconfirmed entries. Graph edges, fact sources and audit notes all refer to entries by index.
Decision: fix wrong text in place. Mark entries that must not be used with `status` (removed, moved_to_organic, duplicate) or `unverified`, and leave them where they are; the graph build skips them. Multi-step entries keep their first step, and later steps are appended as new entries. Unconfirmed claims stay in the book but are never used in a question.
Alternatives: delete entries, which renumbers everything after them and breaks references; drop unconfirmed claims, which loses them before anyone can check them.
Trade-off: the book carries dead entries; readers must respect the flags (`build_graph.build_edges` does).

## Answer keys come from a deterministic engine, inputs first

Date: 2026-10-13
Context: model-written answer keys were the main source of wrong questions; the verifier and council could only catch some of them, and a model judging another model's key reintroduces the bias the blind design was meant to remove.
Decision: each subject gets an engine that computes the answer, the worked trace and the traps from the question's inputs. The inputs are fixed first (graph walk plus pool molecules or proposed numbers), the engine computes, and only then is the stem written; a gate checks the stem states exactly those inputs. Question-first stays available as a comparison if inputs-first underperforms.
Alternatives: question-first (a model reads the facts back out of free text for the engine) — a misreading silently produces a key for a different question; model-computed keys — no deterministic ground truth.
Trade-off: questions are limited to chemistry the engine can compute, so every graph edge needs an implemented step; much more code per subject.

## The physical graph is defined by the engine

Date: 2026-10-13
Context: the graph walk must never produce a chain the engine cannot compute ("no UNKNOWN").
Decision: physical graph edges are generated from the engine's steps (each step declares its two nodes); concept-book entries without a step are facts and stay out of the graph.
Alternatives: keep the hand-written raw-name table and check computability at run time — chains would be picked and then discarded.
Trade-off: adding an entry to the graph now means implementing it in the engine first.

## Chains must be coherent, not just computable

Date: 2026-10-13
Context: wiring steps by quantity name alone produced chains such as "mass of Na2CO3 softener → volume of N2 from sodium azide" — each step correct, no sensible question containing them.
Decision: three code rules (distinct names for different quantities, role tags carried along substance-preserving steps, cross-chapter links only along listed bridges) plus a generator veto when picking inputs.
Alternatives: generator veto only (many wasted walks, a model decides); single-chapter chains (coherent but loses cross-chapter questions).
Trade-off: role tags and bridges are hand-maintained; untagged values still fit any input, so the veto remains the last line.

## Traps are wrong answers run through the rest of the chain

Date: 2026-10-13
Context: a trap is only useful if it is the answer a student who made that mistake would actually write.
Decision: each step lists typical mistakes as alternative computations; the engine runs each mistaken value through all later steps unchanged and keeps it only if the final answer differs by more than 1%.
Alternatives: traps as text descriptions written by the generator — not checkable.
Trade-off: trap coverage depends on the mistakes listed per step.

## Council measures difficulty; one cheap verifier explains every attempt

Date: 2026-10-13
Context: the earlier loop had a model-written key, an LLM verifier, a GPT-4o grader and a Mains-level non-reasoning council; a reviewer pointed out that models judging their own work, refinement against a fixed council, and a frontier check that also judges difficulty all bias the result.
Decision: the council is three reasoning models (GPT-OSS-120B, Qwen3-235B-Thinking, GLM-4.7-Flash; effort medium) solving closed book. Answers are graded in code against the engine's answer. One mismatch verifier (Claude Haiku 5.5) reads every member's attempt next to the engine's trace and labels it (correct, right answer by wrong reasoning, wrong, reference wrong; for wrong: genuine difficulty, unclear wording, missing knowledge, slip). Removed: concept-reasoner (the walk's weighting chooses), the LLM verifier (the engine and the gate cover correctness), the GPT-4o grader (code compares), the wording verifier (unclear wording shows up as a diagnosed failure plus a clarification test), the solution model (the engine's trace is the solution; a cheap model writes the readable text after acceptance), the objection router (members label their own objections), the holdout solver, and run_graph_final.py.
Alternatives: keep a frontier model to re-solve (the engine and gate already prove correctness), a separate failure-analysis model (one verifier call gives both who is wrong and why).
Trade-off: every acceptance rests on the verifier's labels being right where code cannot check them; slips and hints are checked in code to limit that.

## Closed book means the question only; knowledge gaps are tested with a hint

Date: 2026-10-13
Context: the old closed-book sheet told solvers to stop when a fact was missing from it, so strong models failed for lack of a listed fact rather than for the chemistry.
Decision: members get only the question. A failure diagnosed as missing knowledge is retested with the chain's relations as a knowledge hint; solving then tags the question "recall" and the member still counts as failed. Genuine difficulty is always confirmed with an insight hint written by code from the failing step and its listed mistake (never the result); a member who still fails is re-read by the verifier.
Alternatives: open-book sheet (less realistic), counting recall failures as solved (loses legitimately hard recall questions).
Trade-off: more re-solves per accepted question.

## A slip counts as solved only when code confirms it

Date: 2026-10-13
Context: a member that understood the chemistry but miscalculated did not find the question hard; but a verifier calling every failure a slip could hide real difficulty.
Decision: the verifier writes the arithmetic the member set up (with any miscopied number corrected); code evaluates it safely, and only if it gives the engine's answer does the member count as solved. The record keeps answer_matches (fact) beside counts_as_solved (judgement), and council_n_correct beside council_n_solved; acceptance uses council_n_solved.
Alternatives: count every wrong answer as failed (accepts questions that are hard only by accident); trust the label (a model decides).
Trade-off: slips with no evaluable expression (a mistyped structure) count as failures.

## Caps and queues

Date: 2026-10-13
Context: every retry costs council calls; some outcomes cannot be settled by code.
Decision: 3 chains per run; at most 3 refinements per chain (too easy, or reworded for clarity), then the chain is dropped; stems get the original + 2 rewrites to pass the gate; 3 input proposals per round. Unsettled cases go to separate review queues per reason (engine_unknown, gate_unreadable, engine_wrong, objection_unresolved) and the run moves on. The batch driver stops at a spending cap (--max-spend), summing the cost each run reports.
Alternatives: one shared queue (harder to work through by type); stopping the run on any queue item.
Trade-off: an engine bug costs one chain per occurrence until someone reviews the queue.

## Tier 1 becomes an exact duplicate check

Date: 2026-10-13
Context: Tier 1 hashed the numbers in a stem to catch two keys disagreeing for the same inputs; with engine-computed keys that cannot happen.
Decision: the signature is the subject, the engine steps and every given value; an accepted question with the same signature is a duplicate and the chain gets new inputs.
Alternatives: drop Tier 1 entirely.
Trade-off: two different wordings of the same inputs are caught; two different inputs that make the same question are not.

## Fact questions are built by code, in a fixed share of runs

Date: 2026-10-13
Context: about a quarter of the physical concept book is facts, classifications and plot readings that no computation covers, and a free-text answer to them cannot be graded reliably in code.
Decision: facts become MCQ/MSQ questions whose four statements and answer letters are built by code from category tables or true/false statement pools; the generator only adds a lead-in, and the gate checks in code that the question and options appear verbatim. A fixed 25% of physical runs make a fact question (the user's choice); coverage picks the source.
Alternatives: free answers normalised against synonyms (some correct wordings marked wrong); letting coverage alone decide the mix (the share drifts).
Trade-off: statements are hand-written data that must be unambiguous; a category table is only used where categories are mutually exclusive.

## Steps that cannot join a chain are asked alone

Date: 2026-10-13
Context: 38 physical engine steps have no step that can follow or precede them coherently (Bohr radius, Carnot efficiency, Le Chatelier); with a two-step minimum they would never be asked.
Decision: such steps are offered as single-step questions at half the coverage weight of multi-step chains; the council decides whether each is hard enough like any other question.
Alternatives: leave them out (unused knowledge); force them into chains (incoherent problems).
Trade-off: more questions are rejected as too easy, which costs council calls.

## Use a single per-subject config file

Date: 2026-09-01
Context: the pipeline supports organic, inorganic, and physical chemistry. Each subject needs its own concept book, seed file, norm stats, default chapter, and filtering field.
Decision: `subject_config.py` is the single source of truth for per-subject settings. All entrypoints read from it.
Alternatives: pass every value as a CLI flag, or hard-code each subject in each entrypoint.
Trade-off: a shared config avoids duplicated and drifting settings. It adds one indirection when tracing a value.

## Store per-subject norm stats, not one global set

Date: 2026-09-01
Context: the six difficulty meta-tags are computed as z-scores against a calibration corpus. A global corpus mixes subjects and distorts the baselines.
Decision: each subject has its own `meta_tag_norm_stats_<subject>.json` in `data/seeds/`. `core/meta_tags.py` accepts a `norm_stats_path` so the caller picks the right one.
Alternatives: reuse the organic corpus for every subject.
Trade-off: separate files cost a little storage. They keep each subject's difficulty labels calibrated to its own distribution.

## Use a hard difficulty gate rather than a soft target

Date: 2026-09-01
Context: an item is accepted only when it is both solvable by a strong model and hard for a weak model.
Decision: accept only when the strong solver scores at least 85 and the weak solver scores at most 60, and the verifier passes. Calibrated in `calibration/calibrate_thresholds*.py`.
Alternatives: accept a wide band and sort items afterwards.
Trade-off: the hard gate rejects borderline items. It keeps the accepted set clean for benchmarking.
Superseded 2026-10-13: the weak/strong thresholds belonged to run_graph_final.py, which was removed; acceptance uses the council solve count (see "Council measures difficulty").

## Map the four raw archetypes onto subject buckets for calibration

Date: 2026-09-01
Context: the raw JEE Advanced data uses the organic four-taxonomy archetype names. The inorganic and physical calibration scripts expect a six-taxonomy set per subject.
Decision: add a `RAW_ARCHETYPE_FALLBACK` map in `calibrate_thresholds_inorganic.py` and `calibrate_thresholds_physical.py`. Each raw name maps to the nearest subject bucket.
Alternatives: leave the scripts returning an empty sample.
Trade-off: the mapping is a judgement call. Buckets with no raw match warn and are skipped. This lets a re-run produce a stratified sample instead of nothing.

## Real pipeline logic lives in the entrypoints

Date: 2026-09-01, revised 2026-09-07
Context: the live generation, solving, and grading logic is defined inline in `run_*_final.py`. Some `core/` modules were reference stubs kept alongside it.
Decision: keep the entrypoints as the live source of truth. On 2026-09-07 the unused stubs `core/generator.py`, `core/concept_reasoner.py`, `core/strong_solver.py`, and `core/weak_solver.py` were deleted, along with `archive/` (`pipeline.py`, `run_live.py`), the only code that imported them. `core/blackboard.py`, `core/coverage.py`, `core/meta_tags.py`, `core/verifier.py`, and `core/graph_traversal.py` stay because the entrypoints import them.
Alternatives: keep the stubs as documentation of intent.
Trade-off: git history still holds the stubs if the inline logic is ever refactored back into `core/`. Keeping dead files in the tree just misleads a reader about what runs.
Superseded 2026-10-13: the pipeline now lives in core/engine/ and core/pipeline/; run_groundup_final.py only drives a run and saves results.

## Delete unused entrypoints and duplicate assets

Date: 2026-09-07
Context: `run_groundup.py` and `run_graph.py` were the pre-`_final` entrypoints. Nothing imported them, and the README, `Flow.md`, and the code paths only use `run_groundup_final.py` and `run_graph_final.py`. `pipeline_overview_standalone.html` duplicated `pipeline_overview.html` apart from an HTML wrapper and was referenced nowhere.
Decision: delete all three, plus the `archive/` directory.
Alternatives: keep them as historical reference.
Trade-off: git history preserves every deleted file. A repository that lists two runnable ground-up entrypoints when only one is maintained is a navigation hazard.

## Verifier verdict is assembled in code from single-purpose calls

Date: 2026-09-07
Context: the verifier passed some questions whose reference solution was wrong. One LLM call saw the candidate solution and returned PASS or FAIL, so a tidy but wrong solution could be rated correct, and a small model asked to do five things in one prompt drifts.
Decision: Tier 2 is now blind-solve, then extract the candidate's answer, then compare the two answers, then check structural flaws, then rate difficulty. Each is its own call with a short prompt. `verify_problem` combines the booleans; the model never writes the final verdict. Answer disagreement fails immediately and skips the rest.
Alternatives: keep one call and just harden its prompt. That does not fix the "looks fine" bias or the multi-task drift.
Trade-off: 3 to 5 verifier calls per check instead of 2, so more latency and cost. Accepted because a wrong answer passing the gate defeats the point of the gate, and Gemini 3 Flash calls are fast and cheap.
Superseded 2026-10-13: the LLM verifier was removed; the engine computes the key and the chemistry gate checks the stem.

## Verifier and one council model changed to working OpenRouter slugs

Date: 2026-09-06
Context: `core/verifier.py` used `nvidia/nemotron-3-ultra-550b-a55b` and the council used `google/gemma-2-27b-it`. On OpenRouter the first echoes the request back instead of answering, and the second returns HTTP 400 from its provider. Every verifier call failed, so no question could be accepted, and the council always ran a member short.
Decision: verifier is `qwen/qwen-2.5-72b-instruct`, the model the entrypoint and README already name for that role. The council's Google seat is `google/gemma-3-27b-it`.
Alternatives: keep the slugs and wrap every call in broad retries. That hides a dead model rather than fixing it.
Trade-off: the council is now Gemma 3 rather than Gemma 2, a small shift in the difficulty baseline. The "three different families" rule still holds: DeepSeek generator, Qwen verifier, Meta/Mistral/Google council, GPT-4o grader.
Superseded 2026-10-13: new roster in core/models.py.

## Council members solve in parallel

Date: 2026-09-06
Context: `council_solve()` looped over the three members one at a time. Each member makes two sequential API calls (blind solve, then grade), so a council pass took about the sum of three round trips.
Decision: run the three members on a `ThreadPoolExecutor`. The two calls within a member stay sequential because the grade needs the answer. Results are collected back in `COUNCIL` order so the log stays stable.
Alternatives: async/await would need the whole call path converted. Threads are enough because the work is HTTP I/O and the OpenAI client is thread-safe.
Trade-off: three concurrent requests instead of one raise the chance of a rate-limit reply. The existing per-call backoff already handles that.
Still holds for the new council (core/pipeline/stages.council_solve).

## Run the batch driver as subprocesses, not by importing main()

Date: 2026-09-06
Context: `generate_questions.py` needs to produce many questions in one call. The entrypoint `run_groundup_final.py` keeps state at module level and in a per-run `Blackboard`, and it reads `sys.argv`.
Decision: `generate_questions.py` shells out to `python run_groundup_final.py --subject ...` once per question and counts new records in the output file to tell whether a run accepted anything.
Alternatives: import `main()` and call it in a loop in one process.
Trade-off: subprocesses cost a little startup time each. They give each question the same clean state as a manual run, and one crashed attempt cannot end the batch.

## Encode files as UTF-8 and reconfigure the console

Date: 2026-09-01
Context: the repository uses box-drawing and arrow characters. The default Windows console code page 1252 cannot encode them.
Decision: open data files with `encoding="utf-8"` and call `sys.stdout.reconfigure(encoding="utf-8")` in scripts that print them.
Alternatives: strip non-ASCII characters.
Trade-off: keeping the characters preserves the diagrams. It requires the reconfigure call in each script that prints them.
