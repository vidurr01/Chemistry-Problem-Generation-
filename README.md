# JEE Advanced Chemistry Question Generator

A pipeline that **synthesises** JEE-Advanced-style chemistry questions with LLMs and
**validates** each one before it enters the dataset. Validation is deliberately
adversarial: no model grades or clears its own output, the solvers work **blind** (they
never see the answer key), the verifier commits its own answer before it is shown the
candidate, and a **deterministic gate** catches whole classes of error with no model in
the loop. Supports **organic, inorganic, physical**.

---

## What actually runs

The recommended entrypoint is **`run_groundup_final.py`** (OpenRouter-backed). It is the
path that carries the current architecture below. `run_graph_final.py` is the older
graph-wired path and is **not** yet on the new roster (see [Two entrypoints](#two-entrypoints)).

### The generation loop (`run_groundup_final.py`)

```
Pending recheck   questions parked by an earlier council failure are rechecked first
                  (council only — the verifier already passed them)
   │
   ▼
Graph traversal   (core/graph_traversal.py, same for all 3 subjects)
                  BFS over the subject's WHOLE knowledge graph → multi-step chains that
                  follow node connections, across chapters; ranked by coverage weight
                  (least-used edges first); --chapter restricts them to one chapter
   │
   ▼
Concept-reasoner  (DeepSeek-V3)     picks one chain; its steps are concept-book entries
   │
   ▼
Generator         (Gemini 2.5 Flash)  writes the question + a reference solution
   │
   ▼
Verifier, two tiers, core/verifier.py (Gemini 3 Flash; verdict assembled in code)
   ├─ first   extract the candidate's final answer (one narrow call)
   ├─ Tier 1  deterministic, numeric answers only: hash the numeric inputs + formula
   │          signature; hard-FAIL if an ACCEPTED question with the same inputs has a
   │          different answer (> 1 %)
   └─ Tier 2  one narrow call per check:
              a) solve the problem BLIND (candidate solution withheld), commit an answer
              b) compare the two answers.  Disagreement (or no answer) => FAIL, stop here
              c) structural check: arithmetic, out-of-regime formulas, impossible
                 results, non-uniqueness, non-circularity
              d) rate difficulty
   │
   ▼
Council of 3 solvers, run in PARALLEL, each BLIND (no answer key) and closed-book:
   Llama-3.3-70B   ·   Mistral-Large   ·   Gemma-3-27B
   each one blind-solves, then Grader (GPT-4o) judges its answer against the reference
   all three must answer; if one call fails the question is PARKED and the run stops
   │
   ▼
Gate:  verifier PASS  ·  answer key not flagged wrong by 2+ graders  ·  at most 1 of 3 solved
   ├─ 2 or 3 solved  => too easy => refine for reasoning complexity
   ├─ key flagged    => refine with the graders' reasons
   ├─ gate passes    => save to outputs/generated_questions_<subject>.json (+ 6 meta-tags),
   │                    copy to results/ with empty human-eval slots
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

The council members run **closed-book**. They are handed a knowledge sheet — the
concept-book entries behind the chapter's graph edges, plus the chain's own steps — and
instructed to use only that and not their pretrained memory, citing the index of each item
used. See `build_knowledge_sheet()`.

---

## Quick start

**Prereqs:** Python 3.9+, an [OpenRouter](https://openrouter.ai/) key.

Everything else in the repo needs more than that:

| Script | Needs |
|--------|-------|
| `run_groundup_final.py`, `generate_questions.py`, `calibration/anchor_calibration.py`, `calibration/council_eval.py` | `OPENROUTER_KEY` |
| `run_graph_final.py` | `SAMBANOVA_KEY_1`…`_5` (at least one) **and** a local [Ollama](https://ollama.com/) server with `llama3.2` pulled (`ollama pull llama3.2`), for its weak solver |
| `calibration/calibrate_thresholds*.py` | `SAMBANOVA_KEY_1` **and** Ollama with `llama3.2` |
| `calibration/calibrate_solver_metatags.py`, `tools/extract_notes.py` | `SAMBANOVA_KEY_1`… |
| `tools/make_approach_pdf.py` | `reportlab` (in `requirements.txt`) |

```bash
pip install -r requirements.txt
cp .env.example .env         # then put your key in it:  OPENROUTER_KEY=...
                             # (Windows PowerShell: Copy-Item .env.example .env)
```

`.env` is **gitignored** — never commit keys.

**Generate one question:**
```bash
python run_groundup_final.py --subject organic
python run_groundup_final.py --subject inorganic
python run_groundup_final.py --subject physical --chapter "Chemical Kinetics"   # optional: one chapter only
```
Each invocation attempts **one** accepted question and appends it to
`outputs/generated_questions_<subject>.json`, with every attempt (pass or fail) logged to
`outputs/generated_questions_<subject>_attempts.jsonl`.

**Generate many, across subjects:** `generate_questions.py` runs the entrypoint once per
question in a fresh subprocess.
```bash
python generate_questions.py --organic 5 --inorganic 5 --physical 10
```
It takes a target count per subject, resumes from the current accepted counts, kills and
retries a hung question after `--child-timeout` seconds, and moves on from a subject after
`--max-consecutive-failures` runs in a row accept nothing. It appends the full run console
to `outputs/batch_run.log`, never overwriting, and each run gets a `RUN <timestamp>` separator.
Launch it without shell redirection to that log.

---

## Curated Question Datasets

The final question sets are in `results/`. Every question in them was generated and accepted by
`run_groundup_final.py`. On each acceptance the question is written to `outputs/` (the raw run log)
and also copied into `results/generated_questions_<subject>_final.json` with empty human-eval
slots (`human_eval_score`, `human_eval_level`, `human_eval_rationale`). Existing results and their
scores are never overwritten. Manage the review with `tools/results.py`:

```bash
python tools/results.py pending                                   # questions still awaiting a human score
python tools/results.py score <question_id> 3 --rationale "..."  # 0-3; level label set from the score
python tools/results.py reject <question_id> --reason "..."      # remove from the final set; never re-added
python tools/results.py promote                                   # copy any missing accepted questions over
```

`results/rejected.json` lists the questions left out of the final sets, so `promote` never adds them back.

| File | Subject | Count | Chapter |
|---|---|---|---|
| `results/generated_questions_organic_final.json` | Organic Chemistry | **10** | Hydrocarbons |
| `results/generated_questions_inorganic_final.json` | Inorganic Chemistry | **10** | Hydrolysis |
| `results/generated_questions_physical_final.json` | Physical Chemistry | **7** | Chemical Kinetics & Nuclear Chemistry |

The raw acceptance logs and attempt histories from generation runs are written to `outputs/`:
- `generated_questions_<subject>.json`: All accepted candidates passing the gate during runs.
- `generated_questions_<subject>_attempts.jsonl`: Full trace of every iteration attempt (passes, verifier rejections, council ratings, blackboard state).
- `batch_run.log`: Timestamped run logs from `generate_questions.py`.

### Human Evaluation & Scoring (n = 27)

All 27 curated benchmark items were evaluated and tagged with expert human scores:
- **0 = Wrong**: Question generated is chemically or mathematically incorrect / contradictory.
- **1 = JEE Mains level**: Multi-step competition level (standard reaction mechanisms, typical regioselectivity, multi-formula calculations).
- **2 = Between JEE Mains and JEE Advanced level**: Questions that are medium level JEE Mains and easy level JEE Advanced (or borderline JEE Advanced)
- **3 = JEE Advanced level**: Multi-concept integration, deep stereochemical/conformational analysis, complex coupled kinetics, or non-obvious inorganic equilibria.

| Subject | Total | Score 0 (Wrong) | Score 1 (JEE Mains) | Score 2 (Between JEE Mains and JEE Advanced) | Score 3 (JEE Advanced) | Mean Score (0–3) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Organic Chemistry** | 10 | 0 (0.0%) | 1 (10.0%) | 7 (70.0%) | 2 (20.0%) | **2.10** |
| **Inorganic Chemistry** | 10 | 0 (0.0%) | 2 (20.0%) | 5 (50.0%) | 3 (30.0%) | **2.00** |
| **Physical Chemistry** | 7 | 0 (0.0%) | 2 (28.6%) | 3 (42.9%) | 2 (28.6%) | **1.71** |
| **Overall Dataset** | **27** | **0 (0.0%)** | **5 (18.5%)** | **15 (55.6%)** | **7 (25.9%)** | **1.96** |

Each item in `results/generated_questions_*_final.json` contains `human_eval_score`, `human_eval_level`, and `human_eval_rationale`.

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
All three members must work. If any member's solve or grade call fails, the run stops
at once (exit code 3) and the question, which already passed the verifier, is parked in
`outputs/pending_questions_<subject>.json` — neither accepted nor rejected.
`generate_questions.py` then stops the whole batch. The next run for that subject rechecks
parked questions first (council only), before generating anything new: accepted if all
three work and at most one solves; dropped and logged (`pending_too_easy` /
`pending_reference_wrong`) if the recheck gives a real non-acceptance; kept, and the run
stops again, if a member fails again. An API outage therefore cannot produce accepted
questions. (Each call still retries 429/503 with backoff before it counts as failed.)

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
**official key** with deterministic numeric matching. `--strong` / `--weak` choose the models
(defaults: `openai/gpt-oss-120b`, `meta-llama/llama-3.2-3b-instruct`); each strong model's run is
saved to its own `calibration/anchor_calibration_results_<model>.json`. Current results,
**n = 54** numeric items, 2021–2025:

| Run (results file) | Strong solver | Strong solve rate | Weak (`llama-3.2-3b`) solve rate |
|--------------------|---------------|-------------------|----------------------------------|
| `…_gpt_oss_120b.json` | `gpt-oss-120b` | **50 %** (27/54) | **7 %** (4/54) |
| `…_qwen3_235b_a22b_2507.json` | `qwen3-235b-a22b-2507` | **37 %** (20/54) | **6 %** (3/54) |

**What it means:** a strong reasoning model solves only *half* of real Advanced numeric
items blind. Generated items are solved more often, so **generation lands around
Intermediate, with a measured gap to Advanced.** That gap is the honest, reportable
finding, not a bug to hide.

> The 0-100 thresholds `STRONG_FLOOR = 85` and `WEAK_CEILING = 60` from this calibration
> are used only by `run_graph_final.py`. `run_groundup_final.py` gates on the council
> solve-count instead.

**Caveats:** n = 54 is a numeric-only subset. MCQ and MSQ are excluded because the dataset
lacks option text, and 19 figure-dependent items were dropped as unsolvable text-only. The
anchor still blind-solves with `gpt-oss-120b` and `llama-3.2-3b`, which are no longer the
generation solvers. Re-run it with the current council models before comparing directly.

---

## Two entrypoints

| Entrypoint | Knowledge | Provider | Architecture |
|------------|-----------|----------|--------------|
| `run_groundup_final.py` | knowledge graph (all 3 subjects) | OpenRouter | **current**: answer-first 2-tier verifier, 3-model parallel council, per-role models, closed-book |
| `run_graph_final.py` | knowledge graph (all 3 subjects) | SambaNova | **older**: blind strong solver + None-safe gates, single-model (DeepSeek-V3.2), not on the new roster |

Both use the same graph traversal, so every step of a chain is a real edge in the
subject's graph (prevents invented chemistry). `run_graph_final.py` has not been migrated
to the diversified roster or the two-tier verifier, and its SambaNova keys may be
unfunded. Prefer `run_groundup_final.py`.

### Knowledge graphs

Each subject has one graph with the same schema, built from its concept book by
`tools/build_graph.py`, and traversed by the same code:

| Subject | Graph file | Nodes are | Size |
|---------|-----------|-----------|------|
| Organic | `knowledge/reaction_graph.json` | functional-group classes (alkene, alcohol, …) | 57 nodes / 199 edges |
| Inorganic | `knowledge/reaction_graph_inorg.json` | chemical species (K₂Cr₂O₇, CaO, …) | 363 nodes / 415 edges |
| Physical | `knowledge/reaction_graph_physical.json` | physical quantities (moles, rate constant, …) | 119 nodes / 147 edges |

An edge is one concept-book transformation (reaction, or formula step for physical). A
chain is a walk through the graph: each step starts at the node where the previous one
ended, whatever chapter its edge belongs to, so a question can run e.g. Gaseous State →
Stoichiometry. A question's `chapter` is the chapters its chain passes through, in order
(also stored as the list `chapters`), and the solvers' closed-book sheet covers those
chapters. `--chapter` restricts chains to one chapter instead (chains that start in it and
continue elsewhere top up a chapter with few chains).

Each step is backed by one concept-book entry. Where an edge has several, `chain_txs()` picks
the entries so that, wherever possible, step N's product is literally step N+1's substrate.
Organic and physical nodes are classes, so most steps still join only by class; the
generator is told to apply each step to the actual product of the step before it.
Inorganic edges take substrate and product from both sides of the reaction together, so
the two always share an element (a reagent written first is not mistaken for the substrate).
A soluble salt is also linked to the ion it releases (K₂Cr₂O₇ → Cr₂O₇²⁻), so a chain can
continue with the ion's reactions. These 22 links are not concept-book entries; they are
marked `"synthetic": true`, follow standard solubility rules (no AgCl → Cl⁻), and are
added to the solvers' knowledge sheet when a chain uses one. A `--chapter` value must name a
chapter on the graph's edges; a wrong value prints the valid ones.

```bash
python tools/build_graph.py --subject inorganic   # rebuild after editing concept_book_inorg.json
python tools/build_graph.py --subject physical
```

Rebuilding organic needs `--subject organic --overwrite-organic`, because it replaces the
curated graph.

The inorganic and physical rules live in `tools/graph_rules_inorganic.py` and
`tools/graph_rules_physical.py`. Entries that are facts rather than steps (shapes,
trends, classifications) stay out of the graph and are listed in
`knowledge/graph_unmapped_{inorg,physical}.json`. The organic graph was curated by hand
after it was built; `build_graph.py` no longer reproduces it exactly, so it refuses to
rebuild organic without `--overwrite-organic`.

---

## Repository layout

```
run_groundup_final.py    ← recommended entrypoint (OpenRouter, current architecture)
run_graph_final.py       ← graph-wired entrypoint (SambaNova, older)
generate_questions.py    ← batch driver: N questions per subject
subject_config.py        ← per-subject paths/prompts/defaults (source of truth)
requirements.txt / .env.example
core/
  verifier.py            ← two-tier verifier: deterministic dedup + answer-first LLM checks
  blackboard.py          ← shared attempt history (enables refine-in-place); None-safe scores
  coverage.py            ← inverse-frequency diversity tracker
  meta_tags.py           ← 6-axis difficulty labels (z-scored within archetype)
  graph_traversal.py     ← knowledge-graph traversal + chain sampling (all subjects)
  llm.py                 ← model-call helpers: transient-error retries, JSON calls
knowledge/               ← per-subject concept books + knowledge graphs + orders/tests
data/
  jee_advanced/          ← JEE Advanced papers 2012-2025 (read-only inputs)
  seeds/                 ← seed corpora + meta_tag_norm_stats_{inorganic,physical}.json
  chapterwise/           ← per-chapter concept maps (concepts, estimated weightage) — reference
  notes/                 ← chapter notes (OCR text) for tools/extract_notes.py
calibration/
  anchor_calibration.py  ← blind solve-rate on REAL JEE Advanced (the anchor)
  council_eval.py        ← council solve-rate on real Advanced / Mains (--mains-file)
  calibrate_thresholds*.py ← OLD threshold derivation (self-scoring; see calibration note)
  calibrate_solver_metatags.py ← meta-tag norm stats (`--subject`)
tools/
  extract_notes.py       ← chapter notes → concept-book entries (`--notes FILE --topic NAME [--dry-run]`)
  build_graph.py         ← concept book → knowledge graph (`--subject`)
  graph_rules_inorganic.py, graph_rules_physical.py ← node rules for the two newer graphs
  evaluate.py            ← summary report over any generated_questions_*.json
  results.py             ← review of results/: promote, pending, score, reject
  make_approach_pdf.py   ← writes docs/QuestionGen_Approach.pdf
results/                 ← final question sets with human-eval slots (+ rejected.json); filled on acceptance
outputs/                 ← live run output (appended on every run): generated_questions_<subject>.json, coverage_state_<subject>.json,
                           pending_questions_<subject>.json, *_attempts.jsonl, verifier_seen_inputs.json, batch_run.log
docs/
  pipeline_overview.html ← live architecture diagram
  ChangeLog.md / Decisions.md / Flow.md
```

All scripts resolve paths from their own location, so they can be run from any working
directory, and every script reads `.env` from the repo root.

### Reference data (not read by the pipeline)

Kept as source material for building or extending the knowledge base:

| Path | Contents |
|------|----------|
| `data/chapterwise/*.json` | 25 per-chapter concept maps (concepts, estimated weightage) |
| `data/seeds/arihant_seeds.json` | 42 Arihant questions with topic, answer, archetype |
| `data/seeds/merged_SEED.json` | 120 seed questions with topic and answer (no archetype) |
| `data/seeds/jic_chemistry_stats.json` | 474 JEE chemistry questions with paper/year/topic statistics |
| `data/notes/` | chapter notes (OCR text) for `tools/extract_notes.py` |
| `knowledge/molecule_constructor.json`, `knowledge/qualitative_tests.json` | organic node templates; qualitative test results |

`data/seeds/meta_tag_norm_stats_{inorganic,physical}.json` are the per-subject z-score
baselines the inorganic and physical paths load at acceptance. Without them those subjects
save accepted questions with `meta_tags: null` and a `meta_tags_error`. Organic uses `calibration/meta_tag_norm_stats.json`.

### `knowledge/` files

| File | Role |
|------|------|
| `concept_book.json` | Organic: 657 reaction transforms + 605 fragile concepts + 502 exceptions + 470 distractors |
| `concept_book_inorg.json` | Inorganic concept book (904 transforms + facts/exceptions) |
| `concept_book_physical.json` | Physical concept book (348 transforms incl. formulas) |
| `reaction_graph.json` | Organic reaction graph (57 nodes / 199 edges) |
| `reaction_graph_inorg.json` | Inorganic species graph (363 nodes / 415 edges, 22 of them salt → ion links) |
| `reaction_graph_physical.json` | Physical quantity graph (119 nodes / 147 edges) |
| `graph_unmapped*.json` | Concept-book entries left out of each graph (facts, not steps) |
| `reaction_orders.json` | 14 ordering dimensions (acidity, nucleophilicity, …) with JEE traps |
| `node_labels.json` | display names and example compounds for organic graph nodes (`core/graph_traversal.py`) |
| `molecule_constructor.json`, `qualitative_tests.json` | reference data (organic node templates; Tollens, Fehling's, iodoform, … test results); not read by the pipeline |

---

## Verification (`core/verifier.py`) — details

**Tier 1 — deterministic comparison, numeric answers only.** One extraction call reads the
candidate's final answer; `parse_numeric_answers()` turns it into numbers ("2.08 × 10⁹ years",
"Ea = 293.95 kJ/mol, t = 10.4 s") or decides it is not numeric (a compound name such as
2-methylbut-2-ene, whose digits are locants). For numeric answers, `check_duplicate_inputs()`
hashes the problem's numeric inputs + formula signature and compares it, read-only, with the
ACCEPTED questions stored in `outputs/verifier_seen_inputs.json` (gitignored). If an attempt
shares the hash of an accepted question but its answer differs by more than 1% (per part),
it hard-FAILs — at least one must be wrong, and no LLM is needed to know that. Non-numeric
answers skip Tier 1 and are judged by Tier 2 alone. Only acceptance writes to the
store (`record_accepted_inputs()`, with the question id), so a rejected attempt's wrong
answer can never block the corrected refine of the same numbers. Entries without a question
id (written by the old store-every-attempt code) are ignored. This was written to catch a real bug where two identical U-Pb dating
questions produced two different ages, both stamped PASS by the previous mock verifier.

**Tier 2 — answer-first checks (Gemini 3 Flash), one narrow call each.** The verdict is
assembled in code from discrete results, not written by the model.

1. `_extract_candidate_answer` reads the candidate solution and returns only its answer
   (this also feeds Tier 1, which runs next).
2. `_blind_solve` solves the problem with the candidate solution withheld and commits a
   final answer.
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
- **Graph nodes are coarse.** Organic and physical nodes are classes (alkene, moles), so
  consecutive steps connect by class, not by exact compound; the generator still has to
  pick concrete compounds and data that make the chain work, and the verifier catches
  chains it cannot. Inorganic nodes are exact species but cover only the reaction entries
  (about half the inorganic concept book).
- **The generator (Gemini 2.5 Flash) and verifier (Gemini 3 Flash) are both Google models.**
  Different versions, and neither grades its own output, but family separation is weaker
  than the earlier roster.
- **The anchor is numeric-only (n = 54)** and blind-solves with models that are no longer
  in the generation loop.
- **`run_graph_final.py` is not migrated** to the current verifier and council.
- **Provenance typing and an RDKit-level deterministic chemistry checker are not built.**
  Future work.

---

## Operational notes

```
Python:     python / python3 (platform-independent)
Env:        .env — OPENROUTER_KEY required (gitignored)
Vision:     no OCR in the pipeline (tools/extract_notes.py takes text OCR'd elsewhere).
            Figure/scheme-dependent questions are excluded, not guessed.
IUPAC:      generated questions use IUPAC nomenclature throughout.
```
