# Decisions

This file records the reasoning behind meaningful technical choices. Each entry explains why an implementation was chosen, not just what was implemented.

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

## Map the four raw archetypes onto subject buckets for calibration

Date: 2026-09-01
Context: the raw JEE Advanced data uses the organic four-taxonomy archetype names. The inorganic and physical calibration scripts expect a six-taxonomy set per subject.
Decision: add a `RAW_ARCHETYPE_FALLBACK` map in `calibrate_thresholds_inorganic.py` and `calibrate_thresholds_physical.py`. Each raw name maps to the nearest subject bucket.
Alternatives: leave the scripts returning an empty sample.
Trade-off: the mapping is a judgement call. Buckets with no raw match warn and are skipped. This lets a re-run produce a stratified sample instead of nothing.

## Real pipeline logic lives in the entrypoints

Date: 2026-09-01
Context: some `core/` modules are reference stubs, while the live generation logic is defined inline in `run_*_final.py`.
Decision: keep the entrypoints as the live source of truth and leave the `core/` modules as reference implementations.
Alternatives: move the logic into `core/` and call it.
Trade-off: the current split is a known debt. The entrypoints work end to end. Consolidating into `core/` is a future refactor, noted in the README.

## Verifier verdict is assembled in code from single-purpose calls

Date: 2026-09-07
Context: the verifier passed some questions whose reference solution was wrong. One LLM call saw the candidate solution and returned PASS or FAIL, so a tidy but wrong solution could be rated correct, and a small model asked to do five things in one prompt drifts.
Decision: Tier 2 is now blind-solve, then extract the candidate's answer, then compare the two answers, then check structural flaws, then rate difficulty. Each is its own call with a short prompt. `verify_problem` combines the booleans; the model never writes the final verdict. Answer disagreement fails immediately and skips the rest.
Alternatives: keep one call and just harden its prompt. That does not fix the "looks fine" bias or the multi-task drift.
Trade-off: 3 to 5 verifier calls per check instead of 2, so more latency and cost. Accepted because a wrong answer passing the gate defeats the point of the gate, and Gemini 3 Flash calls are fast and cheap.

## Verifier and one council model changed to working OpenRouter slugs

Date: 2026-09-06
Context: `core/verifier.py` used `nvidia/nemotron-3-ultra-550b-a55b` and the council used `google/gemma-2-27b-it`. On OpenRouter the first echoes the request back instead of answering, and the second returns HTTP 400 from its provider. Every verifier call failed, so no question could be accepted, and the council always ran a member short.
Decision: verifier is `qwen/qwen-2.5-72b-instruct`, the model the entrypoint and README already name for that role. The council's Google seat is `google/gemma-3-27b-it`.
Alternatives: keep the slugs and wrap every call in broad retries. That hides a dead model rather than fixing it.
Trade-off: the council is now Gemma 3 rather than Gemma 2, a small shift in the difficulty baseline. The "three different families" rule still holds: DeepSeek generator, Qwen verifier, Meta/Mistral/Google council, GPT-4o grader.

## Council members solve in parallel

Date: 2026-09-06
Context: `council_solve()` looped over the three members one at a time. Each member makes two sequential API calls (blind solve, then grade), so a council pass took about the sum of three round trips.
Decision: run the three members on a `ThreadPoolExecutor`. The two calls within a member stay sequential because the grade needs the answer. Results are collected back in `COUNCIL` order so the log stays stable.
Alternatives: async/await would need the whole call path converted. Threads are enough because the work is HTTP I/O and the OpenAI client is thread-safe.
Trade-off: three concurrent requests instead of one raise the chance of a rate-limit reply. The existing per-call backoff already handles that.

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
