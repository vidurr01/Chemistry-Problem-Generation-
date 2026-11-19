# JEE Advanced Chemistry Question Generator

A pipeline that builds JEE-Advanced-style chemistry questions and **measures** how hard
each one is before it enters the dataset. The answer to every question comes from a
**deterministic chemistry engine**, never from a model; models only pick inputs, write
the question, read it back, solve it as students would, and explain their failures. A
question is kept when the weakest solver on the difficulty ladder **fails it**: the ladder
measures difficulty only (the answer is already the engine's, run by the solving program), and
the hint tests sort out failures caused by wording or by a wrong engine answer rather than
deciding acceptance. Subjects: **physical** (wired end to end), **inorganic** and **organic**
(engines being built; the batch driver reports and skips them until they exist).

---

## The generation loop (`run_groundup_final.py`)

Computed questions are made **question first** by default (`core/pipeline/qfirst.py`). `docs/PIPELINE.md`
maps every stage to the function and file that does it.

```
Draw               3-5 engine formulas at random (each shares a quantity with one already drawn);
   │               Jev scores 6 such sets and the best is used (core/pipeline/qf_draw.py)
Twist              drawn at random: inverse, two-state ratio, two-state difference, simultaneous,
   │               condition
Design             Gemini 3.1 Pro (thinking level "low") plans ONE design around a hidden link;
   │               Jev checks it with cut-offs calibrated on real JEE designs; rejected → new draw
Write              Gemini 3.7 Flash writes the question with every number as a blank [[name]] and a
   │               realistic range for it (a fixed value only for a value of the substance itself),
   │               plus a range for the answer; broken blanks go straight back to the writer;
   │               Jev's level check (calibrated on real papers) sends a JEE Main-level draft back
Solve (coder 2)    GPT-6 Luna writes solve() from the question WITH ITS BLANKS, before any number
   │               exists: it calls only the drawn formulas (step_<tx>), find(), solve_for() and
   │               simple relations; a probe runs it on values from the ranges (core/engine/sandbox.py)
Numbers (coder 1)  code, not a model: value sets drawn in the ranges run through that program until
   │               one gives an answer in the answer range that rounding moves by at most 2 %, that
   │               at least 2 typical mistakes change, and that uses every picked value; only then
   │               are the numbers printed in the question
Checks             every formula's result matters; no intermediate stated; constants stated; not a
   │               copy of an example or of an accepted question; Jev's coherence check (calibrated)
Duplicate check → ladder → grading (code) → hints → accept   (as below)
Too easy           Jev gives each of 8 cases the probability that it made the question easy; code
   │               applies the likeliest unused one (new twist, one more formula) and the writer
   │               rewrites (core/pipeline/refine.py); up to 3 rounds
Unclear wording / duplicate → the writer rewrites
```

The answer is the engine's: the program's chemistry is the engine's steps, run on exactly the values
the question prints. `--flow engine` runs the older engine-first loop:

```
Graph walk         the subject's knowledge graph; chains that the engine can compute and
                   that stay one coherent problem; least-used edges and rare trap types first
   │
Blackboard         per-question notebook every stage writes to
   │
Inputs             generator (Gemini 3.7 Flash) proposes a scenario and a value for every
                   input — or vetoes a chain it cannot make coherent
   │
Engine             code computes the answer, the step-by-step trace, and the traps (the
                   wrong final answers that typical mistakes lead to)
   │
Form               the chain asked forward, or backwards (an input from the result), in
                   two states (a ratio), or with two shared unknowns; trees and conditions
                   (two systems made equal) are their own question ideas
   │
Duplicate check    same engine steps and same inputs as an accepted question → new inputs,
                   before any model is paid to write or solve it
   │
Stem               generator writes the question around those exact inputs
   │
Chemistry gate     extractor (DeepSeek V4 Flash) copies the stated facts into a form;
                   code checks every value, constant and the asked quantity
   │
Ladder             Granite 4.2 8B → GLM-5.3-Flash → MiniMax M3, weakest first; each step is
                   called only if every step below failed; closed book (question only)
   │
Grading            code only: solved = the answer is within tolerance (1 %) of the key;
                   option letters and text answers by their shape; an answer code cannot
                   read counts as not solved
   │
   ├─ Granite solves    too easy → refiner (Gemini 3.8 Flash) reads how it solved it →
   │                    new inputs or reworded (at most 3 rounds per chain)
   └─ Granite fails     label = first step that solves it (GLM: advanced or hard Mains, decided
                        by Jev's level check; MiniMax: advanced medium; none: hard advanced);
                        hint test on each failed step: the insight hint (written by code)
                        names the kind of step; graded by code; the question is accepted
   │
Accept             record + readable solution (Gemini 3.8 Flash; every calculation checked
                   in code, then by the solution checker, Claude Haiku 5.5) + coverage + results/
```

**Commitments enforced in code**

1. **The answer key is computed.** The engine works from the inputs the question states;
   the gate proves the stem states exactly those inputs. No model writes or approves a key.
2. **No model checks its own family's work.** Gemini designs and writes, DeepSeek extracts,
   OpenAI (GPT-6 Luna) writes the solving program, IBM/Z.ai/MiniMax solve, Claude checks the
   written solution, Jev (TypeSafe) judges fit, level and coherence.
3. **Facts are never overwritten by judgements.** Each council member's record keeps the
   raw `answer_matches` and `counts_as_solved` (the same thing since grading is code only); a question keeps
   `council_n_correct` beside `council_n_solved`.

---

## Quick start

**Prereqs:** Python 3.12+ (the code uses f-string syntax older versions reject), an
[OpenRouter](https://openrouter.ai/) key (`OPENROUTER_KEY`). An [airouter.in](https://airouter.in/) key
(`AIROUTER_KEY`) is optional: it is used when OpenRouter runs out of credit.

```bash
pip install -r requirements.txt
cp .env.example .env         # then put your key in it:  OPENROUTER_KEY=...
```

`.env` is **gitignored** — never commit keys.

**Generate one question:**
```bash
python run_groundup_final.py --subject physical
python run_groundup_final.py --subject physical --chapter "Chemical Kinetics & Nuclear Chemistry"
```

**Generate several, with a spending cap:**
```bash
python generate_questions.py --physical 5 --max-spend 2.00
```

Each run prints what it spent (as OpenRouter reports it). The batch driver appends the full
console to `outputs/batch_run.log`, retries a subject until its target is met or
`--max-consecutive-failures` runs in a row accept nothing, and stops at `--max-spend`.

**Review:**
```bash
python tools/evaluate.py --subject physical       # acceptance, solved vs correct, traps, spend
python tools/results.py queue                     # items code could not settle
python tools/results.py pending                   # questions awaiting a human score
```

**One stage at a time** (prints everything each stage read and produced, and its cost):
```bash
python tools/step_by_step.py draw      # then design, write, solve, numbers, check, judge, save, solution
python tools/step_by_step.py real      # a random real JEE Advanced question through the pipeline (never saved)
```

**Tests (no API calls, about 100 s):**
```bash
python -m unittest discover -s tests -t .      # 414 tests
python tools/audit_engine.py                   # every physical chain of up to 3 steps; 0 flags expected
```

---

## Curated Question Datasets

The final question sets are in `results/`. The 27 questions below were generated and accepted by
the pipeline as it was before the engine redesign (model-written keys, Mains-level council); new
acceptances are added with the engine fields described above. On each acceptance the question is written to `outputs/` (the raw run log)
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
- `generated_questions_<subject>_attempts.jsonl`: Full trace of every iteration attempt (passes, rejections, council ratings, blackboard state).
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

## Models (OpenRouter first; airouter.in once OpenRouter runs out of credit)

| Role | Model | Does |
|------|-------|------|
| Designer | `google/gemini-3.1-pro-preview` (thinking level "low") | question first: one design per draw, around a hidden link |
| Writer (generator) | `google/gemini-3.7-flash` | question first: the question with blanks and ranges, every rewrite; engine first: inputs and stems; clarification hints |
| Coder | `openai/gpt-6-luna` | question first: writes `solve()` from the question with its blanks |
| Number step | code, no model | picks the values in the writer's ranges (`qf_numbers.pick_numbers`) |
| Jev | `typesafe/jev-1.14` (OpenRouter Decisions API) | formula fit, design check, level check, coherence check, why a question was too easy |
| Ladder | `ibm-granite/granite-4.2-8b` → `z-ai/glm-5.3-flash` → `minimax/minimax-m3` | closed-book solves, weakest first; the first step decides too easy / accepted, the first to solve gives the difficulty label |
| Solution checker | `anthropic/claude-haiku-5.5` | checks the written solution line by line, accepted questions only |
| Solution writer | `google/gemini-3.8-flash` | readable solution, accepted questions only; never grades |
| Refiner | `google/gemini-3.8-flash` | engine first only: too easy → new inputs or rewording |
| Extractor | `deepseek/deepseek-v4-flash-0731` | engine first only: chemistry gate, copies stated facts into a form |

The roster lives in `core/models.py`.

---

## The engine (`core/engine/`)

Every computable concept-book entry is a **step**: a computation between two graph nodes
with its inputs, its answer, the constants a question must state, and the typical mistakes
a student makes at that step. Chaining steps wires each step's outputs into the next by
name; the inputs left over are exactly what the question must give.

- **Traps** are computed, not described: each mistake's wrong value is run through the rest
  of the chain, so a trap is the final answer a student making that mistake would write.
- **Coherence**: steps link only through the same quantity (a rate-increase factor is not a
  rate constant; ΔT is not an osmotic pressure), role tags keep one substance through a chain
  (a titration's NaOH cannot become a dissociating gas), and chains cross chapters only along
  bridges where the quantity means the same thing.
- **Constants** (R, F, N_A, half-lives, molar volume, atomic masses) are always stated in the
  question, so a convention can never turn a right answer wrong. So is any value books
  disagree on (C_v of a linear triatomic gas is stated as 7R/2).
- **Nothing stated twice**: a question never states a value its other data already fix. A
  step hands on what it fixes (a Nernst EMF's 298 K, a cell's ΔS), derives what follows (n
  of a gas from P, V, T), and a tree is refused if two branches could supply the same input.
  `tools/audit_engine.py` checks every chain of up to three steps offline.

Physical: 311 steps across all twelve chapters, including every formula the JEE Advanced
physical questions of 2012-2025 use (`docs/advanced_formula_map.md`). Steps that cannot join a
chain are asked on their own. The 82 entries that are facts, classifications or plot readings become
**fact questions**: four statements built by code from category tables or true/false pools,
asked as "one or more correct", "exactly one correct" or "exactly one incorrect", with the
answer key as option letters. A quarter of physical runs make a fact question
(`--kind facts|chains` forces one kind).

---

## Gates and review

- **Chemistry gate** — a model only copies; code compares every stated value (within 0.1%),
  the asked quantity (picked from shuffled options) and every constant. A mismatch rewrites
  the stem (original + 2 retries); an unreadable form goes to a review queue.
- **Duplicate check** — a signature of the engine steps and every input; an accepted question
  with the same signature is the same question.
- **Review queues** — `outputs/queue_<reason>_<subject>.json` for `engine_unknown`,
  `gate_unreadable`, `engine_wrong` and `objection_unresolved`; list with
  `python tools/results.py queue`, clear a reviewed item with `dismiss`.
- **Parking** — every attempt must be measured; if a solver call (ladder or hint re-solve)
  fails, the question is parked in `outputs/pending_questions_<subject>.json` (exit 3) and judged
  first on the next run. After 3 failed rechecks, or when it cannot be recomputed, it goes to
  `outputs/on_hold_questions_<subject>.json`, never dropped; `--rerun-held` judges those again.

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
saved to its own `calibration/anchor_calibration_results_<model>.json`. `--council` solves with
the generation council's own call (same prompt, token cap and reasoning effort), `--workers N`
runs questions in parallel, and `--regrade` re-scores saved answers with the current keys and
grader without calling any model. Answers are read with `core.answers.numeric_value`
(fractions such as 11/51, × 10ⁿ, labels and units).

The question set is the 2021–2025 numeric items. Its answer keys were checked against
published solutions on 2026-10-14: eight keys were corrected and one transcription fixed
(each change keeps `was` / `now` / `sources` in the question record), and five items are
excluded via `exclude_reason` (missing paragraph text, a missing plot, or a disputed key).
Current results, **n = 49**:

| Results file | Solver | Solve rate |
|--------------|--------|------------|
| `…_gpt_6_luna_council.json` | `gpt-6-luna` (council) | **92 %** (45/49) |
| `…_qwen3_8_flash_council.json` | `qwen3.8-flash` (council) | **90 %** (44/49) |
| `…_glm_5_3_flash_council.json` | `glm-5.3-flash` (council) | **71 %** (35/49) |
| `…_gpt_oss_120b.json` | `gpt-oss-120b` | 61 % (30/49) |
| `…_qwen3_235b_a22b_2507.json` | `qwen3-235b-a22b-2507` | 47 % (23/49) |
| (weak baseline in the last two files) | `llama-3.2-3b` | 8 % (4/49) |

Council members solving each question: 3 of 3 for 33 questions, 2 of 3 for 12, 1 of 3 for 1,
0 of 3 for 3. So "too easy at 2 or more solved" would accept 4 of the 49 real Advanced
questions (8 %), and "too easy only at 3 of 3" would accept 16 (33 %).

**Caveats:** n = 49 is a numeric-only subset (MCQ and MSQ lack option text in the dataset;
figure-dependent items are dropped), so each rate is roughly ±7 points.

---

### Knowledge graphs

Each subject has one graph with the same schema, built from its concept book by
`tools/build_graph.py`, and traversed by the same code. The physical graph's edges are
generated from the physical engine, so every edge is a computation the engine can do:

| Subject | Graph file | Nodes are | Size |
|---------|-----------|-----------|------|
| Organic | `knowledge/reaction_graph.json` | functional-group classes (alkene, alcohol, …) | 57 nodes / 199 edges |
| Inorganic | `knowledge/reaction_graph_inorg.json` | chemical species (K₂Cr₂O₇, CaO, …) | 363 nodes / 415 edges |
| Physical | `knowledge/reaction_graph_physical.json` | physical quantities (moles, rate constant, …) | 185 nodes / 238 edges |

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
run_groundup_final.py    ← generate one question (question first; --flow engine for the older loop)
generate_questions.py    ← batch driver: N questions per subject, spending cap
subject_config.py        ← per-subject paths/defaults (source of truth)
core/
  engine/                ← deterministic engines: base (steps, chains, trees, traps), forms, chem (formulas,
                           equations, constants), physical/ (311 steps, topics, bridges)
  pipeline/              ← qfirst (question first: runs the stages) + qf_draw, qf_design, qf_writer,
                           qf_coder, qf_numbers, qf_checks, qf_text (one file per stage); refine (Jev);
                           flow (judging; engine-first loop), stages, gate, adapters, forms_layer, queues
  models.py              ← model roster, router (OpenRouter, airouter.in), call helper, spend tracking
  answers.py             ← reading and comparing final answers; safe arithmetic
  dedup.py               ← duplicate check on exact engine inputs
  blackboard.py          ← per-question notebook
  coverage.py            ← inverse-frequency diversity (edges, chapters, trap types)
  meta_tags.py           ← 6-axis difficulty labels
  graph_traversal.py     ← knowledge-graph walk + chain sampling (all subjects)
  llm.py                 ← .env, JSON parsing, retries, atomic writes
knowledge/               ← concept books, knowledge graphs, orders/tests
data/                    ← JEE Advanced papers, seeds + norm stats, chapter maps, notes
calibration/             ← anchor solve rates, council eval, meta-tag norm stats
tools/                   ← step_by_step (one stage at a time), calibrate_* (cut-offs), check_models,
                           extract_notes, build_graph (+ rules), evaluate, results, make_approach_pdf
tests/                   ← engine tests (textbook answers) and offline pipeline runs
results/                 ← final question sets with human-eval slots (+ rejected.json)
outputs/                 ← run output: accepted questions, attempt logs, queues, coverage,
                           pending, duplicate store, batch_run.log
docs/
  PIPELINE.md            ← where each stage lives (start here)
  pipeline_overview.html ← architecture page
  ChangeLog.md / Decisions.md / Flow.md
```

All scripts resolve paths from their own location and read `.env` from the repo root.

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
| `reaction_graph_physical.json` | Physical quantity graph (185 nodes / 238 edges), generated from the physical engine |
| `graph_unmapped*.json` | Concept-book entries left out of each graph (facts, not steps) |
| `reaction_orders.json` | 14 ordering dimensions (acidity, nucleophilicity, …) with JEE traps |
| `node_labels.json` | display names and example compounds for organic graph nodes (`core/graph_traversal.py`) |
| `molecule_constructor.json`, `qualitative_tests.json` | reference data (organic node templates; Tollens, Fehling's, iodoform, … test results); not read by the pipeline |

---

## Operational notes

```
Python:     python / python3 (platform-independent)
Env:        .env — OPENROUTER_KEY required (gitignored)
Vision:     no OCR in the pipeline (tools/extract_notes.py takes text OCR'd elsewhere).
            Figure/scheme-dependent questions are excluded, not guessed.
IUPAC:      generated questions use IUPAC nomenclature throughout.
```
