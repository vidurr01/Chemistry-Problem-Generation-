# ChangeLog

This file records every repository change. Newest entries go at the top. Each entry lists which files changed, what changed, why when useful, and any behaviour or configuration impact.

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
