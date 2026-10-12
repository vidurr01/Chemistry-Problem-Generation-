# JEE Advanced Chemistry Question Generator

A pipeline that builds JEE-Advanced-style chemistry questions and **measures** how hard
each one is before it enters the dataset. The answer to every question comes from a
**deterministic chemistry engine**, never from a model; models only pick inputs, write
the question, read it back, solve it as students would, and explain their failures. A
question is kept when strong models **fail it for chemistry reasons** that a targeted
hint confirms. Subjects: **physical** (wired end to end), **inorganic** and **organic**
(engines being built).

---

## The generation loop (`run_groundup_final.py`)

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
Stem               generator writes the question around those exact inputs
   │
Chemistry gate     extractor (DeepSeek V4 Flash) copies the stated facts into a form;
                   code checks every value, constant and the asked quantity
   │
Duplicate check    same engine steps and same inputs as an accepted question → new inputs
   │
Council            GPT-6 Luna · GLM-5.3-Flash first, in parallel; Qwen3.8-Flash
                   only when exactly one of them solves (otherwise it cannot change the
                   decision); closed book (question only), reasoning effort medium
   │
Mismatch verifier  Claude Haiku 5.5 reads every attempt against the engine's trace:
                   correct / wrong (genuine, unclear wording, missing knowledge, slip) /
                   reference wrong
   │
Grading            code: answer within 1% of the engine's; a slip counts as solved only if
                   the member's own arithmetic, re-evaluated in code, gives the answer
   │
   ├─ 2+ solved      too easy → new inputs or reworded (at most 3 rounds per chain)
   ├─ reference wrong / unsettled objection → review queue, next chain
   └─ ≤1 solved      hint tests on each failed member:
                      clarification hint solves → reworded, judged again
                      knowledge hint solves     → accepted, tagged "recall"
                      insight hint (written by code) → difficulty confirmed → accepted
   │
Accept             record + readable solution (Mistral Small 3.2) + coverage + results/
```

**Commitments enforced in code**

1. **The answer key is computed.** The engine works from the inputs the question states;
   the gate proves the stem states exactly those inputs. No model writes or approves a key.
2. **No model checks its own family's work.** Gemini writes, DeepSeek extracts, OpenAI/Qwen/
   Z.ai solve, Claude diagnoses, Mistral writes the solution text.
3. **Facts are never overwritten by judgements.** Each council member's record keeps the
   raw `answer_matches` beside the verifier's label and `counts_as_solved`; a question keeps
   `council_n_correct` beside `council_n_solved`.

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

**Tests (no API calls):**
```bash
python -m unittest tests.test_engine_physical tests.test_pipeline_offline
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

## Models (all via OpenRouter)

| Role | Model | Does |
|------|-------|------|
| Generator | `google/gemini-3.7-flash` | proposes inputs (or vetoes a chain), writes stems, clarification hints, refinement choice |
| Extractor | `deepseek/deepseek-v4-flash-0731` | chemistry gate: copies stated facts into a form |
| Council | `openai/gpt-6-luna`, `qwen/qwen3.8-flash`, `z-ai/glm-5.3-flash` (GPQA Diamond ~87–90%) | closed-book solves, reasoning effort medium |
| Mismatch verifier | `anthropic/claude-haiku-5.5` | diagnoses every council attempt against the engine's trace |
| Solution writer | `mistralai/mistral-small-3.2-24b-instruct` | readable solution, accepted questions only |

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
  question, so a convention can never turn a right answer wrong.

Physical: 267 steps across all twelve chapters. Steps that cannot join a chain are asked
on their own. The 82 entries that are facts, classifications or plot readings become
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
- **Parking** — every council member called must be measured; if a call fails the question is
  parked in `outputs/pending_questions_<subject>.json` (exit 3) and judged first on the next run.

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

> The 0-100 thresholds this calibration once produced belonged to the earlier
> weak/strong-solver loop, which has been removed; generation now gates on the council.

**Caveats:** n = 54 is a numeric-only subset. MCQ and MSQ are excluded because the dataset
lacks option text, and 19 figure-dependent items were dropped as unsolvable text-only. The
anchor still blind-solves with `gpt-oss-120b` and `llama-3.2-3b`, which are no longer the
generation solvers. Re-run it with the current council models before comparing directly.

---

### Knowledge graphs

Each subject has one graph with the same schema, built from its concept book by
`tools/build_graph.py`, and traversed by the same code. The physical graph's edges are
generated from the physical engine, so every edge is a computation the engine can do:

| Subject | Graph file | Nodes are | Size |
|---------|-----------|-----------|------|
| Organic | `knowledge/reaction_graph.json` | functional-group classes (alkene, alcohol, …) | 57 nodes / 199 edges |
| Inorganic | `knowledge/reaction_graph_inorg.json` | chemical species (K₂Cr₂O₇, CaO, …) | 363 nodes / 415 edges |
| Physical | `knowledge/reaction_graph_physical.json` | physical quantities (moles, rate constant, …) | 173 nodes / 198 edges |

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
run_groundup_final.py    ← generate one question (engine-first pipeline)
generate_questions.py    ← batch driver: N questions per subject, spending cap
subject_config.py        ← per-subject paths/defaults (source of truth)
core/
  engine/                ← deterministic engines: base (steps, chains, traps), chem (formulas,
                           equations, constants), physical/ (262 steps, topics, bridges)
  pipeline/              ← flow (decisions), stages (model calls), gate, adapters, queues
  models.py              ← model roster, OpenRouter call helper, spend tracking
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
tools/                   ← extract_notes, build_graph (+ rules), evaluate, results, make_approach_pdf
tests/                   ← engine tests (textbook answers) and offline pipeline runs
results/                 ← final question sets with human-eval slots (+ rejected.json)
outputs/                 ← run output: accepted questions, attempt logs, queues, coverage,
                           pending, duplicate store, batch_run.log
docs/
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
| `reaction_graph_physical.json` | Physical quantity graph (173 nodes / 198 edges), generated from the physical engine |
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
