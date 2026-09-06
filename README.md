# Prahlada — JEE Advanced Chemistry Question Generator

A pipeline that **synthesises** JEE-Advanced-style chemistry questions with LLMs and
**validates** each one before it enters the dataset. Validation is deliberately
adversarial: the models that *write* a question are never the models that *clear* it, the
solvers work **blind** (they never see the answer key), and a **deterministic gate** catches
whole classes of error with no model in the loop. Supports **organic, inorganic, physical**.

> **Read the code, not old prose.** This README was rewritten to match the current build.
> Where a doc and the code disagree, the code wins. See `ChangeLog.md`, `Decisions.md`,
> `Flow.md`, and the live diagram in `pipeline_overview.html`.

---

## What actually runs

The recommended entrypoint is **`run_groundup_final.py`** (OpenRouter-backed). It is the
path that carries the current architecture below. `run_graph_final.py` is the older
graph-wired path and is **not** yet on the new roster (see [Two entrypoints](#two-entrypoints)).

### The generation loop (`run_groundup_final.py`)

```
Coverage picks least-covered chapter/archetype
   │
   ▼
Concept-reasoner  (DeepSeek-V3)   selects 3–4 transforms from the chapter's concept-book slice
   │
   ▼
Generator         (DeepSeek-V3)   writes the question + a reference solution
   │
   ▼
Verifier (2-tier, core/verifier.py)
   ├─ Tier 1  deterministic, NO LLM: hash numeric inputs + formula signature;
   │          hard-FAIL if identical inputs ever produced a different final answer
   └─ Tier 2  Qwen2.5-72B: solve the problem BLIND, then judge the candidate
              (arithmetic, out-of-regime formulas, impossible results, non-circularity)
   │
   ▼
Weak solver   (Llama-3.2-3B)   solves BLIND (no answer key)   ─┐
Strong solver (Qwen3-235B)     solves BLIND (no answer key)   ─┤
   │                                                           ▼
   │                            Grader (GPT-4o) compares each blind answer
   │                            to the reference → 0–100 score  (solver ≠ grader)
   ▼
4-gate check:  verifier PASS  ·  strong ≥ 85  ·  weak ≤ 60  ·  reference_correct
   │           (an UNMEASURED score — None — can never satisfy a gate)
   ├─ all pass → compute 6 difficulty meta-tags → append to generated_questions_<subject>.json
   └─ any fail → record on blackboard → REFINE IN PLACE (≤ 4 attempts total)
```

**Two design commitments enforced in code:**

1. **No producer clears itself.** Generator (DeepSeek) ≠ verifier (Qwen2.5-72B) ≠ strong
   solver (Qwen3-235B) ≠ grader (GPT-4o) ≠ weak (Llama-3B) — five roles, four families.
2. **Solvers are blind, and a separate grader scores them.** A solver never sees the
   reference; it produces an answer cold, and the grader compares that answer to the
   reference. This replaces the old self-scoring, which pinned the strong score at ~100
   because the solver was shown the answer it was meant to reproduce.

### Closed-book solving

Both solvers run **closed-book**: they are handed the chapter's concept-book knowledge
(the same `valid_transformations` used to build the question — organic reactions, inorganic
structure/reactivity facts, physical formulas) and instructed to **use only that, not their
pretrained memory**, citing the index of each item used. See `build_knowledge_sheet()`.

---

## Quick start

**Prereqs:** Python 3.9+, an [OpenRouter](https://openrouter.ai/) key.

```bash
pip install -r requirements.txt
cp .env.example .env         # then put your key in it:  OPENROUTER_KEY=...
```

`.env` is **gitignored** — never commit keys.

**Generate (ground-up, all three subjects):**
```bash
python run_groundup_final.py --subject organic
python run_groundup_final.py --subject inorganic
python run_groundup_final.py --subject physical --chapter "Chemical Kinetics"
```
Each invocation attempts **one** accepted question (up to 4 refine-in-place attempts) and
appends it to `generated_questions_<subject>.json`.

**Note on Ollama:** the weak solver runs on **OpenRouter** (`meta-llama/llama-3.2-3b-instruct`),
*not* local Ollama — Ollama's `llama3.2` returns an empty JSON object under
`response_format=json_object`, which silently broke the weak gate.

---

## Models (live roster, all via OpenRouter)

| Role | Model | Family | Why |
|------|-------|--------|-----|
| Concept-reasoner | `deepseek/deepseek-chat-v3-0324` | DeepSeek | selects reaction steps |
| Generator | `deepseek/deepseek-chat-v3-0324` | DeepSeek | writes question + reference solution |
| **Verifier** (Tier 2) | `qwen/qwen-2.5-72b-instruct` | Qwen | blind-judge (≠ generator) |
| **Strong solver** | `qwen/qwen3-235b-a22b-2507` | Qwen | blind expert solver |
| **Grader** | `openai/gpt-4o` | OpenAI | scores solver answers (≠ solvers, ≠ generator) |
| Weak solver | `meta-llama/llama-3.2-3b-instruct` | Llama | blind non-expert floor |

Model assignments live at the top of `run_groundup_final.py`; the verifier model lives in
`core/verifier.py`. Change them there.

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
items blind. Generated items, by contrast, are solved at ~100 — so **current generation
lands around Intermediate, with a measured gap to Advanced.** That gap is the honest,
reportable finding, not a bug to hide.

> ⚠️ **The `STRONG_FLOOR = 85` / `WEAK_CEILING = 60` gate thresholds are stale.** They were
> fit to the *old self-scoring* calibration (strong "scored" 96 % with the answer visible).
> Under blind grading the strong model averages ~60 on real Advanced, so 85 no longer means
> "expert-level." Re-derive them from the blind distributions before relying on them.

**Caveats:** n = 54 is a numeric-only subset (MCQ/MSQ excluded — the dataset lacks option
text; 19 figure-dependent items dropped as unsolvable text-only). The anchor uses
`gpt-oss-120b` as strong solver while generation now uses `qwen3-235b`; reconcile the two if
you need the same expert across both.

---

## Two entrypoints

| Entrypoint | Knowledge | Provider | Architecture |
|------------|-----------|----------|--------------|
| `run_groundup_final.py` | concept-book slice (no graph) | OpenRouter | **current**: blind solvers, 2-tier verifier, per-role models, closed-book |
| `run_graph_final.py` | reaction graph (organic) | SambaNova | **older**: blind strong solver + None-safe gates, but single-model (DeepSeek-V3.2) and not on the new roster |

The graph path constrains each step to a real reaction edge (prevents invented chemistry)
but has not been migrated to the diversified roster or the two-tier verifier, and its
SambaNova keys may be unfunded. Prefer `run_groundup_final.py`.

---

## Repository layout

```
run_groundup_final.py    ← recommended entrypoint (OpenRouter, current architecture)
run_graph_final.py       ← graph-wired entrypoint (SambaNova, older)
subject_config.py        ← per-subject paths/prompts/filtering (source of truth)
core/
  verifier.py            ← two-tier verifier: deterministic dedup + blind LLM judge
  blackboard.py          ← shared attempt history (enables refine-in-place); None-safe scores
  coverage.py            ← inverse-frequency diversity tracker
  meta_tags.py           ← 6-axis difficulty labels (z-scored within archetype)
  graph_traversal.py     ← reaction-graph queries (graph path)
knowledge/               ← per-subject concept books + organic reaction graph + orders/tests
calibration/
  anchor_calibration.py  ← blind solve-rate of strong/weak on REAL JEE Advanced (the anchor)
  calibrate_thresholds*.py ← OLD threshold derivation (self-scoring; see stale-thresholds note)
data/                    ← JEE Advanced papers, seeds, Mains contrast set (read-only inputs)
pipeline_overview.html   ← live architecture diagram
ChangeLog.md / Decisions.md / Flow.md
```

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

**Tier 2 — independent blind judge (Qwen2.5-72B).** Solves the problem cold, then compares
to the candidate and checks arithmetic, out-of-regime formula use, physically impossible
results, uniqueness, and **non-circularity** (the product must differ from the starting
material). Returns PASS/FAIL + actionable feedback that feeds refine-in-place.

The verifier is the **binding quality gate**: a circular/inconsistent chain that a strong
model still "solves" (strong = 100) is now rejected here, where the old pipeline would have
emitted it. Acceptance rate dropped from ~100 % to ~20 % accordingly — fewer, cleaner items.

---

## Known limitations (honest status)

- **Generation reaches Intermediate, not Advanced.** Measured against the anchor above.
- **Gate thresholds (85/60) are stale** — see the calibration note.
- **The anchor is numeric-only (n = 54)** and uses a different strong solver than generation.
- **Closed-book with a full-chapter sheet doesn't add difficulty** for a strong model (the
  sheet is complete) — it demonstrates the capability; it bites only when knowledge is
  withheld or the question needs genuine multi-step reasoning.
- **The graph path (`run_graph_final.py`) is not migrated** to the current architecture.
- **Provenance typing, an RDKit-level deterministic chemistry checker, and a multi-model
  verifier council are not built** — future work.

---

## Operational notes

```
Python:     python / python3 (platform-independent)
Env:        .env — OPENROUTER_KEY required (gitignored)
Vision:     NO OCR anywhere. Figure/scheme-dependent questions are excluded, not guessed.
IUPAC:      generated questions use IUPAC nomenclature throughout.
```
