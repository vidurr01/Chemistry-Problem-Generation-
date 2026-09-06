# JEE Advanced Chemistry Question Generator

A pipeline that **synthesises** JEE-Advanced-style chemistry questions with LLMs and
**validates** each one before it enters the dataset. Validation is deliberately
adversarial: no model grades or clears its own output, the solvers work **blind** (they
never see the answer key), the verifier commits its own answer before it is shown the
candidate, and a **deterministic gate** catches whole classes of error with no model in
the loop. Supports **organic, inorganic, physical**.

> **Read the code, not old prose.** This README was refreshed on 2026-09-07 to match the
> build. Where a doc and the code disagree, the code wins. See `ChangeLog.md`,
> `Decisions.md`, `Flow.md`, and the live diagram in `pipeline_overview.html`.

---

## What actually runs

The recommended entrypoint is **`run_groundup_final.py`** (OpenRouter-backed). It is the
path that carries the current architecture below. `run_graph_final.py` is the older
graph-wired path and is **not** yet on the new roster (see [Two entrypoints](#two-entrypoints)).

### The generation loop (`run_groundup_final.py`)

```
Coverage picks the least-covered chapter/archetype
   │
   ▼
Concept-reasoner  (DeepSeek-V3)     selects 3-4 transforms from the chapter's concept-book slice
   │
   ▼
Generator         (Gemini 2.5 Flash)  writes the question + a reference solution
   │
   ▼
Verifier, two tiers, core/verifier.py
   ├─ Tier 1  deterministic, NO LLM: hash the numeric inputs + formula signature.
   │          Hard-FAIL if identical inputs ever produced a different final answer.
   └─ Tier 2  Gemini 3 Flash, one narrow call per check, verdict assembled in code:
              a) solve the problem BLIND (candidate solution withheld), commit an answer
              b) extract the candidate's final answer
              c) compare the two answers.  Disagreement => FAIL, stop here
              d) structural check: arithmetic, out-of-regime formulas, impossible
                 results, non-uniqueness, non-circularity
              e) rate difficulty
   │
   ▼
Council of 3 solvers, run in PARALLEL, each BLIND (no answer key) and closed-book:
   Llama-3.3-70B   ·   Mistral-Large   ·   Gemma-3-27B
   each one blind-solves, then Grader (GPT-4o) judges its answer against the reference
   │
   ▼
Gate:  verifier PASS  ·  reference_correct  ·  at most 1 of 3 council members solved
   ├─ 2 or 3 solved  => too easy => refine for reasoning complexity
   ├─ gate passes    => compute 6 difficulty meta-tags => append to generated_questions_<subject>.json
   └─ verifier FAIL  => record on blackboard => REFINE IN PLACE
```

Refine-in-place caps live at the top of `main()`: `MAX_LINEAGES = 3` fresh ideas,
`MAX_ITERS = 4` total generate-check iterations, `VERIFIER_FAIL_MAX = 2` (one refine pass
per idea before it is abandoned).

**Two design commitments enforced in code:**

1. **No producer clears itself.** Concept-reasoner (DeepSeek), generator (Gemini 2.5 Flash),
   verifier (Gemini 3 Flash), grader (GPT-4o), council (Meta, Mistral, Google). The
   generator and verifier are both Google models now, but different versions, and neither
   solves nor grades its own output.
2. **The verdict is answer-driven and assembled in code.** The verifier solves the problem
   without seeing the candidate solution, then a wrong reference answer FAILs immediately
   even if the candidate's own reasoning looks consistent. The model never writes the
   PASS/FAIL string; the code does, from discrete booleans.

### Closed-book solving

The council members run **closed-book**. They are handed the chapter's concept-book
knowledge, the same `valid_transformations` used to build the question, and instructed to
use only that and not their pretrained memory, citing the index of each item used. See
`build_knowledge_sheet()`.

---

## Quick start

**Prereqs:** Python 3.9+, an [OpenRouter](https://openrouter.ai/) key.

```bash
pip install -r requirements.txt
cp .env.example .env         # then put your key in it:  OPENROUTER_KEY=...
```

`.env` is **gitignored** — never commit keys.

**Generate one question:**
```bash
python run_groundup_final.py --subject organic
python run_groundup_final.py --subject inorganic
python run_groundup_final.py --subject physical --chapter "Chemical Kinetics"
```
Each invocation attempts **one** accepted question and appends it to
`generated_questions_<subject>.json`, with every attempt (pass or fail) logged to
`generated_questions_<subject>_attempts.jsonl`.

**Generate many, across subjects:** `generate_questions.py` runs the entrypoint once per
question in a fresh subprocess.
```bash
python generate_questions.py --organic 5 --inorganic 5 --physical 10
```
It takes a target count per subject, resumes from the current accepted counts, kills and
retries a hung question after `--child-timeout` seconds, and moves on from a subject after
`--max-consecutive-failures` runs in a row accept nothing. It appends the full run console
to `batch_run.log`, never overwriting, and each run gets a `RUN <timestamp>` separator.
Launch it without shell redirection to `batch_run.log`.

---

## Curated Question Datasets

The final curated benchmark sets are located in the repository root:

| Dataset File | Subject | Count | Status / Curation Notes |
|---|---|---|---|
| `generated_questions_organic_final.json` | Organic Chemistry | **10** | Curated from 13 raw accepted questions. Pruned 3 items: circular hydrogenation (`GEN_20260906T093311`), invalid sulfuric acid hydration of alkyl halide (`GEN_20260906T182711`), and ambiguous ozonolysis product naming (`GEN_20260906T182848`). |
| `generated_questions_inorganic_final.json` | Inorganic Chemistry | **10** | Curated from 11 raw accepted questions. Pruned 1 defective MCQ with no valid option (`GEN_20260906T203528`). |
| `generated_questions_physical_final.json` | Physical Chemistry | **7** | All 7 questions accepted from Chemical Kinetics & Nuclear Chemistry retained. |

The raw acceptance logs and attempt histories from generation runs remain in:
- `generated_questions_<subject>.json`: All accepted candidates passing the gate during runs.
- `generated_questions_<subject>_attempts.jsonl`: Full trace of every iteration attempt (passes, verifier rejections, council ratings, blackboard state).
- `batch_run.log`: Timestamped run logs from `generate_questions.py`.

### Human Evaluation & Scoring (n = 27)

All 27 curated benchmark items were evaluated and tagged with expert human scores:
- **0 = Wrong**: Question generated is chemically or mathematically incorrect / contradictory.
- **1 = CBSE level**: Standard Class 12 board exam level (direct textbook recall, straightforward conversions, single-formula arithmetic).
- **2 = JEE Mains level**: Multi-step competition level (standard reaction mechanisms, typical regioselectivity, multi-formula calculations).
- **3 = JEE Advanced level**: Multi-concept integration, deep stereochemical/conformational analysis, complex coupled kinetics, or non-obvious inorganic equilibria.

| Subject | Total | Score 0 (Wrong) | Score 1 (JEE Mains) | Score 2 (Between JEE Mains and JEE Advanced) | Score 3 (JEE Advanced) | Mean Score (0–3) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Organic Chemistry** | 10 | 0 (0.0%) | 1 (10.0%) | 7 (70.0%) | 2 (20.0%) | **2.10** |
| **Inorganic Chemistry** | 10 | 0 (0.0%) | 1 (10.0%) | 5 (50.0%) | 3 (30.0%) | **2.00** |
| **Physical Chemistry** | 7 | 0 (0.0%) | 0 (0.0%) | 3 (42.9%) | 2 (28.6%) | **1.71** |
| **Overall Dataset** | **27** | **0 (0.0%)** | **2 (7.4%)** | **15 (55.6%)** | **7 (25.9%)** | **1.96** |

Each item in `generated_questions_*_final.json` contains `human_eval_score`, `human_eval_level`, and `human_eval_rationale`.

---

## Models (live roster, all via OpenRouter)

| Role | Model | Family | Why |
|------|-------|--------|-----|
| Concept-reasoner | `deepseek/deepseek-chat-v3-0324` | DeepSeek | selects reaction/formula steps |
| Generator | `google/gemini-2.5-flash` | Google | writes question + reference solution (cheaper than the verifier) |
| **Verifier** (Tier 2) | `google/gemini-3-flash-preview` | Google | blind-solves, then answer-first checks (≠ generator version) |
| **Grader** | `openai/gpt-4o` | OpenAI | scores council answers (≠ council, ≠ generator) |
| Council solver 1 | `meta-llama/llama-3.3-70b-instruct` | Meta | blind, Mains-level |
| Council solver 2 | `mistralai/mistral-large-2407` | Mistral | blind, Mains-level |
| Council solver 3 | `google/gemma-3-27b-it` | Google | blind, Mains-level |

The council replaced the earlier single weak solver plus single strong solver. The count of
council members that solve a question is the difficulty signal: **2 or 3 solved means too
easy** (refine), **0 or 1 solved means hard enough** (accept if the verifier passed).

Model assignments live at the top of `run_groundup_final.py`. The verifier model lives in
`core/verifier.py` and is the authoritative value. Change them there.

---

## Difficulty calibration & the anchor result

To know how hard a *real* JEE Advanced question is for these models — the yardstick
generated items are compared against — run the **anchor calibration**:

```bash
python calibration/anchor_calibration.py
```

It blind-solves real JEE Advanced questions (no answer key) and grades against the
**official key** with deterministic numeric matching. Current result
(`calibration/anchor_calibration_results.json`), **n = 54** numeric items, 2021–2025:

| Solver | Blind solve rate | Mean 0–100 score |
|--------|------------------|-------------------|
| Strong (`gpt-oss-120b`) | **50 %** | 60 |
| Weak (`llama-3.2-3b`) | **7 %** | 19 |

**What it means:** a strong reasoning model solves only *half* of real Advanced numeric
items blind. Generated items are solved more often, so **generation lands around
Intermediate, with a measured gap to Advanced.** That gap is the honest, reportable
finding, not a bug to hide.

> ⚠️ **`STRONG_FLOOR = 85` and `WEAK_CEILING = 60` are vestigial in the ground-up path.**
> That path now gates on the council solve-count, not on a 0-100 score. The constants and
> the "Weak/Strong Solver Score" lines in the refine prompt are leftovers from the old
> weak/strong design. `run_graph_final.py` still uses them.

**Caveats:** n = 54 is a numeric-only subset. MCQ and MSQ are excluded because the dataset
lacks option text, and 19 figure-dependent items were dropped as unsolvable text-only. The
anchor still blind-solves with `gpt-oss-120b` and `llama-3.2-3b`, which are no longer the
generation solvers. Re-run it with the current council models before comparing directly.

---

## Two entrypoints

| Entrypoint | Knowledge | Provider | Architecture |
|------------|-----------|----------|--------------|
| `run_groundup_final.py` | concept-book slice (no graph) | OpenRouter | **current**: answer-first 2-tier verifier, 3-model parallel council, per-role models, closed-book |
| `run_graph_final.py` | reaction graph (organic) | SambaNova | **older**: blind strong solver + None-safe gates, single-model (DeepSeek-V3.2), not on the new roster |

The graph path constrains each step to a real reaction edge (prevents invented chemistry)
but has not been migrated to the diversified roster or the two-tier verifier, and its
SambaNova keys may be unfunded. Prefer `run_groundup_final.py`.

---

## Repository layout

```
run_groundup_final.py              ← recommended entrypoint (OpenRouter, current architecture)
run_graph_final.py                 ← graph-wired entrypoint (SambaNova, older)
generate_questions.py              ← batch driver: N questions per subject, appends to batch_run.log
subject_config.py                  ← per-subject paths/prompts/filtering (source of truth)
generated_questions_*_final.json   ← curated benchmarks (10 organic, 10 inorganic, 7 physical)
core/
  verifier.py            ← two-tier verifier: deterministic dedup + answer-first LLM checks
  blackboard.py          ← shared attempt history (enables refine-in-place); None-safe scores
  coverage.py            ← inverse-frequency diversity tracker
  meta_tags.py           ← 6-axis difficulty labels (z-scored within archetype)
  graph_traversal.py     ← reaction-graph queries (graph path)
knowledge/               ← per-subject concept books + organic reaction graph + orders/tests
calibration/
  anchor_calibration.py  ← blind solve-rate on REAL JEE Advanced (the anchor)
  calibrate_thresholds*.py ← OLD threshold derivation (self-scoring; see calibration note)
data/
  jee_advanced/          ← JEE Advanced papers 2012-2025 (read-only inputs)
  seeds/                 ← seed corpora + meta_tag_norm_stats_{inorganic,physical}.json
  chapterwise/           ← chapter-tagged question banks
pipeline_overview.html   ← live architecture diagram
ChangeLog.md / Decisions.md / Flow.md
```

`data/seeds/meta_tag_norm_stats_{inorganic,physical}.json` are the per-subject z-score
baselines the inorganic and physical paths load at acceptance. Without them those subjects
crash at meta-tag computation. Organic uses `calibration/meta_tag_norm_stats.json`.

### `knowledge/` files

| File | Role |
|------|------|
| `concept_book.json` | Organic: 657 reaction transforms + 605 fragile concepts + 502 exceptions + 470 distractors |
| `concept_book_inorg.json` | Inorganic concept book (904 transforms + facts/exceptions) |
| `concept_book_physical.json` | Physical concept book (348 transforms incl. formulas) |
| `reaction_graph.json` | Organic reaction graph (57 nodes / 199 edges) |
| `reaction_orders.json` | 14 ordering dimensions (acidity, nucleophilicity, …) with JEE traps |
| `node_labels.json`, `molecule_constructor.json`, `qualitative_tests.json` | graph/labelling support |

---

## Verification (`core/verifier.py`) — details

**Tier 1 — deterministic, no LLM, no randomness.** `check_duplicate_inputs()` hashes a
problem's extracted numeric inputs + formula signature and persists them to
`verifier_seen_inputs.json` (gitignored). If two accepted questions share that hash but
disagree on the final answer, both hard-FAIL — at least one must be wrong, and no LLM is
needed to know that. This was written to catch a real bug where two identical U-Pb dating
questions produced two different ages, both stamped PASS by the previous mock verifier.

**Tier 2 — answer-first checks (Gemini 3 Flash), one narrow call each.** The verdict is
assembled in code from discrete results, not written by the model.

1. `_blind_solve` solves the problem with the candidate solution withheld and commits a
   final answer.
2. `_extract_candidate_answer` reads the candidate solution and returns only its answer.
3. `_answers_equivalent` compares the two answers. If they disagree, the candidate's
   reference solution is not trustworthy, so the item FAILs and the later calls are skipped.
4. `_structural_check` looks only for arithmetic errors, out-of-regime formula use,
   physically impossible results, non-uniqueness, and non-circularity.
5. `_rate_difficulty` runs only on a clean PASS.

This replaced a single `_judge` call that saw the candidate solution and returned the
verdict itself. That call would pass a tidy but wrong solution. Splitting the work into
short single-purpose prompts is where a small model drifts least, and moving the PASS/FAIL
decision into code removes the "looks fine" failure mode.

The verifier is the **binding quality gate**. A circular or inconsistent chain that a
solver still "solves" is rejected here. The FAIL feedback names both the independent answer
and the candidate answer, so the generator can correct its key on the refine pass.

---

## Known limitations (honest status)

- **Generation reaches Intermediate, not Advanced.** Measured against the anchor, though the
  anchor now uses different solver models than generation, so the gap is less precisely
  quantified.
- **`STRONG_FLOOR` / `WEAK_CEILING` are vestigial** in the ground-up path. See the
  calibration note. The council solve-count is the real difficulty gate.
- **The concept-reasoner sometimes picks a chain that does not connect** (product of step N
  is not the substrate of step N+1). The verifier catches the resulting broken question,
  but it costs refine iterations. A deterministic adjacency check is not built because the
  concept book's `from`/`to` fields are free text, not typed tokens. This is what the graph
  path solves structurally.
- **The generator (Gemini 2.5 Flash) and verifier (Gemini 3 Flash) are both Google models.**
  Different versions, and neither grades its own output, but family separation is weaker
  than the earlier roster.
- **The anchor is numeric-only (n = 54)** and blind-solves with models that are no longer
  in the generation loop.
- **The graph path (`run_graph_final.py`) is not migrated** to the current architecture.
- **Provenance typing and an RDKit-level deterministic chemistry checker are not built.**
  Future work.

---

## Operational notes

```
Python:     python / python3 (platform-independent)
Env:        .env — OPENROUTER_KEY required (gitignored)
Vision:     NO OCR anywhere. Figure/scheme-dependent questions are excluded, not guessed.
IUPAC:      generated questions use IUPAC nomenclature throughout.
```
