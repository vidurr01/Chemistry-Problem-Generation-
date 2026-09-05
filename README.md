# Prahlada — JEE Advanced Chemistry Question Generator

Automated generation of JEE Advanced-level chemistry questions, validated by a three-gate
pipeline (chemical verifier + expert solver floor + weak-solver ceiling) and labelled with
six calibrated difficulty meta-tags. Supports **Organic, Inorganic, and Physical** chemistry.

## Quick Start

**Prerequisites**
- Python 3.9+
- [Ollama](https://ollama.com/) running locally with `llama3.2` pulled (`ollama pull llama3.2`)
- An [OpenRouter](https://openrouter.ai/) API key (required for all solver/generator roles)
- Optional: SambaNova API keys (fallback for the graph-wired path — see below)

**Setup**
```bash
git clone <repo-url>
cd Prahlada_Question_Generator
pip install -r requirements.txt
cp .env.example .env
# Edit .env and fill in OPENROUTER_KEY (required).
```

**Run the graph-wired pipeline (organic / inorganic)**
```bash
python run_graph_final.py --subject organic
python run_graph_final.py --subject inorganic
```
Generates one accepted JEE Advanced-level question and saves it to
`generated_questions_<subject>.json`. Retries up to 3 times; accepted questions must pass all
gates (verifier PASS + strong solver ≥85% + weak solver ≤60%).

**Run the ground-up pipeline (organic / inorganic / physical)**
```bash
python run_groundup_final.py --subject physical --chapter "Chemical Kinetics"
```
Ground-up skips the reaction graph and builds the problem directly from a filtered slice of
the subject's concept book. Supported for all three subjects.

**Note on `python` vs `python3`:** use whichever command your environment provides; both
`run_*.py` scripts are platform-independent (the macOS-only `python3` note in older docs no
longer applies).

---

## How It Works — End-to-End Workflow

The system has three phases. Phase 0 and 1 outputs are committed to the repo; you run Phase 2.

```
╔══════════════════════════════════════════════════════════════════════════╗
║  PHASE 0 — Knowledge Build  (one-time; outputs committed to repo)        ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  Teacher PDFs (local, not in repo)                                       ║
║         │                                                                ║
║         ▼  tools/extract_notes.py                                        ║
║  knowledge/concept_book*.json          ← per-subject reaction transforms ║
║         │                                                                ║
║         ▼  tools/build_graph.py                                          ║
║  knowledge/reaction_graph.json        ← organic reaction graph           ║
║  knowledge/graph_unmapped.json        ← diagnostic: unmapped TXs         ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  PHASE 1 — Calibration  (one-time; outputs committed to repo)            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  data/jee_advanced/  (JEE Advanced papers 2012–2025)                     ║
║         │                                                                ║
║         ▼  calibration/calibrate_thresholds[_subject].py                ║
║  Sets STRONG_FLOOR=85, WEAK_CEILING=60  (baked into each entrypoint)     ║
║                                                                          ║
║  data/seeds/*_seeds.json  → calibration/calibrate_solver_metatags.py     ║
║  data/seeds/meta_tag_norm_stats[_subject].json  ← per-subject z-scores   ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  PHASE 2 — Generation  (run repeatedly; this is what you run)            ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  knowledge/reaction_graph.json   ──┐                                     ║
║  subject_config.py (per-subject)   │                                     ║
║  calibration / norm stats files    ├──► run_graph_final.py (organic,     ║
║  core/ modules (graph_traversal,   │     inorganic) or                   ║
║     coverage, blackboard, meta_tags)│    run_groundup_final.py (all 3)   ║
║                                    ▼                                     ║
║              generated_questions_<subject>.json                           ║
║              coverage_state_<subject>.json                                ║
╚══════════════════════════════════════════════════════════════════════════╝
```

**Inside each generation loop** (one accepted question = up to 4 attempts):

```
  coverage.py picks the least-covered edge/chapter/archetype
        │
        ▼
  graph_traversal.py BFS → candidate reaction path (organic/inorganic only)
        │
        ▼
  Generator  (DeepSeek-V3.2)          → writes question + solution
        ▼
  Verifier   (DeepSeek-V3.2)          → blind-solves, checks chemistry, PASS/FAIL
  Weak Solver (llama3.2, Ollama local)→ score ≤ 60% required (hard enough)
  Strong Solver (DeepSeek-V3.2)       → score ≥ 85% required (solvable)
        │
        ▼  all gates must pass
  meta_tags.py computes 6-axis difficulty label (subject-specific norm stats)
        │
        ▼
  record appended to generated_questions_<subject>.json
  coverage_state_<subject>.json updated
```

---

## Entrypoints

All generation entrypoints share the same pipeline; they differ only in knowledge source and
subject. `subject_config.py` is the single source of truth for per-subject settings.

| Entrypoint | Subjects | Graph | Model provider | Output file |
|------------|----------|-------|----------------|-------------|
| `run_graph_final.py --subject organic` | organic | yes | SambaNova (+ OpenRouter fallback) | `generated_questions_organic.json` |
| `run_graph_final.py --subject inorganic` | inorganic | yes* | SambaNova (+ OpenRouter fallback) | `generated_questions_inorganic.json` |
| `run_groundup_final.py --subject {organic,inorganic,physical}` | all | no | OpenRouter | `generated_questions_<subject>.json` |
| `run_graph.py` | organic only | yes | SambaNova | `generated_questions.json` |
| `run_groundup.py` | organic only | no | OpenRouter | `generated_questions.json` |

\* Requires `knowledge/reaction_graph_inorg.json` (Phase 0 — not yet built; the script errors
cleanly if missing).

The **`*_final.py` variants are the current recommended entrypoints** — they are
subject-parameterized. The non-final `run_graph.py` / `run_groundup.py` are the original
organic-only scripts, retained for compatibility.

### CLI options

**`run_graph_final.py`**
```
--subject {organic,inorganic}   default: organic
```

**`run_groundup_final.py`**
```
--subject {organic,inorganic,physical}   default: organic
--chapter <name>                         override default chapter/sub-topic
```

---

## Repository Layout

```
subject_config.py        ← per-subject paths, prompts, filtering (source of truth)
run_graph*.py            ← graph-wired entrypoints
run_groundup*.py         ← ground-up entrypoints
core/                    ← runtime pipeline modules
knowledge/               ← per-subject structured chemistry knowledge
calibration/             ← one-time scripts + committed calibration outputs
tools/                   ← utilities for rebuilding knowledge / auditing output
data/                    ← question corpora (read-only inputs)
archive/                 ← deprecated scripts
ChangeLog.md             ← what changed, when (every change)
Decisions.md             ← why meaningful choices were made
Flow.md                  ← how the system works and how data moves
```

### `core/` — Runtime pipeline modules

| File | Role in the workflow |
|------|----------------------|
| `graph_traversal.py` | Loads `reaction_graph.json` and answers queries: BFS paths, node lookup, edge-from-node list. Entrypoints call `get_paths()` to pick the reaction chain. |
| `coverage.py` | Tracks how many times each edge/chapter/archetype is used; inversely weights selection toward least-covered areas. Persists to `coverage_state_<subject>.json`. |
| `blackboard.py` | Shared state object passed between all pipeline stages. Accumulates full attempt history so the generator can "refine in place" on retries. |
| `meta_tags.py` | Computes the 6-axis difficulty label via z-scores against a calibration corpus. Accepts a `norm_stats_path` so subject-specific norm stats are used. |
| `concept_reasoner.py` | Selects reaction operators (used by the ground-up path). |
| `generator.py` / `verifier.py` / `strong_solver.py` / `weak_solver.py` | Modular stage wrappers (the entrypoints also inline their own live versions). |

> **Note:** the `core/` stage modules (`generator.py`, `verifier.py`, `strong_solver.py`,
> `weak_solver.py`, `concept_reasoner.py`) ship with **mock** implementations for reference.
> The live entrypoints define their own real-logic versions inline and do not import these.

### `knowledge/` — Structured chemistry knowledge (edit to extend coverage)

| File | Role |
|------|------|
| `concept_book.json` | Organic: 657 reaction transforms + 605 fragile concepts + 502 exceptions + 470 distractors. Source of truth; the graph is built from this. |
| `concept_book_inorg.json` | Inorganic concept book (same schema, TXs carry a `source_chapter` field). |
| `concept_book_physical.json` | Physical concept book (same schema). |
| `reaction_graph.json` | Organic reaction knowledge graph (nodes = functional-group classes, edges = reactions with conditions/chemoselectivity). |
| `node_labels.json` | IUPAC/common names + example molecules per graph node. |
| `reaction_orders.json` | 14 ordering dimensions (acidity, nucleophilicity, etc.) with tiers/exceptions/JEE traps — used for Archetype IV (GOC). |
| `molecule_constructor.json` | Concrete molecule pools per node + "interesting_when" annotations. |
| `qualitative_tests.json` | Qualitative chemical tests (Tollens, Fehling, etc.) with scope/exceptions/JEE traps. |
| `graph_unmapped.json` | Diagnostic: TXs that couldn't be mapped to graph edges. |

### `calibration/` — One-time scripts + committed outputs

| File | Role |
|------|------|
| `calibrate_thresholds*.py` | Run solvers on real JEE questions to derive STRONG_FLOOR=85, WEAK_CEILING=60. Inorganic/physical variants map the raw 4-taxonomy archetype labels onto subject-specific 6-taxonomy buckets (unmatched buckets warn and are skipped). |
| `calibrate_solver_metatags*.py` | Measure solution length / distractor count → produce norm stats. |
| `meta_tag_norm_stats.json` / `*_inorganic/physical.json` in `data/seeds/` | Per-subject z-score parameters read at runtime. |
| `calibration_results.json`, `solver_traces.json` | Reference outputs from calibration runs. |

**Per-subject norm stats** live in `data/seeds/meta_tag_norm_stats[_inorganic|_physical].json`;
`subject_config.py` and `core/meta_tags.py` route to the correct one per subject.

### `tools/` — Utility scripts (run manually)

| File | When to run |
|------|-------------|
| `extract_notes.py` | New teacher notes PDFs → merge structured transforms into `concept_book*.json`. |
| `build_graph.py` | After editing concept book → rebuild `reaction_graph*.json` + `graph_unmapped.json`. |
| `classifier.py` | Label raw JEE questions by archetype → `data/seeds/classified_seeds.json`. |
| `evaluate.py` | Audit pipeline output (`generated_questions*.json`, default `generated_questions.json`). |
| `make_approach_pdf.py` | Generate an architecture overview PDF (needs `reportlab`). |

### `data/` — External question corpora (read-only inputs)

| Folder | Contents |
|--------|----------|
| `jee_advanced/` | JEE Advanced papers 2012–2025 (used by calibration). |
| `seeds/` | Subject seed corpora + `meta_tag_norm_stats[_subject].json` + `jic_chemistry_stats.json` (fragility weights). |
| `chapterwise/` | Chapterwise question banks across subjects. |

### `archive/` — Deprecated

| File | Why archived |
|------|-------------|
| `run_live.py` | Pre-graph, single-seed pipeline, no coverage tracking. |
| `pipeline.py` | Original mock-based augmentation pipeline (hardcoded scores, cannot run live). |

---

## Models Used

| Role | Model | Provider |
|------|-------|----------|
| Generator / Verifier / Strong Solver | DeepSeek-V3.2 | SambaNova (`run_graph*`) or OpenRouter (`run_groundup*`) |
| Weak Solver | llama3.2 | Ollama (local, `localhost:11434`) |

**OpenRouter** (used by `run_groundup*.py` and as fallback in `run_graph*.py`):
- Requires `OPENROUTER_KEY` in `.env`.
- Strong model slug: `deepseek/deepseek-chat-v3-0324`.
- Retry wrapper backs off exponentially on HTTP 429/503.

**SambaNova** (used by `run_graph*.py`):
- Requires `SAMBANOVA_KEY_1`..`5` in `.env` (uncomment the example block).
- 4–5 key rotation on 429, exponential backoff when all keys are exhausted.

**Ollama** (weak solver only):
- `ollama pull llama3.2`, base URL `http://localhost:11434/v1`, API key literal `"ollama"`.
- No rate limits.

---

## Full Architecture Reference

> Technical deep-dive for contributors. The sections below document exact schemas, calibration numbers, known issues, and design decisions made during the June 2026 build session.

---

## Table of Contents

1. System Purpose and Goals
2. Pipeline Overview
3. Component: run_groundup.py — Full Code Detail
4. Component: blackboard.py
5. Component: meta_tags.py
6. Data Files — Exact Schemas
   - jeeadv_organic_seeds.json
   - concept_book.json
   - meta_tag_norm_stats.json
   - generated_questions.json
7. API Configuration and Rate Limits
8. Calibrated Thresholds
9. Reaction Knowledge Graph — Design Reference
   - Node Schema
   - Edge Schema (conditions_variants + chemoselectivity)
   - Traversal State
10. Orders JSON
11. Molecule Constructor
12. Coverage and Sampling
13. Pending Work

---

## 1. System Purpose and Goals

Prahlada generates JEE Advanced-level organic chemistry questions programmatically.
The system is not a fine-tuner and not a simple prompt wrapper — it is a pipeline that:
- Constructs a question attempt along a valid reaction graph path
- Validates it chemically (verifier, blind-solve protocol)
- Confirms it is solvable by an expert (strong solver ≥ 85%)
- Confirms it is hard enough to challenge a non-expert (weak solver ≤ 60%)
- Labels it with 6 calibrated difficulty meta-tags
- Saves the full attempt history for every accepted question

Target exam: JEE Advanced organic chemistry (Paper 1 and Paper 2).
Seed corpus: 153 real JEE Advanced organic questions from 2013–2025.

---

## 2. Pipeline Overview

```
GRAPH-WIRED (run_graph*.py):
  coverage.py picks target: archetype + chapter + entry edge (inverse-frequency weighting)
  ↓
  graph_traversal.py BFS → candidate path (3–5 edges)
  ↓
  Blackboard(path, archetype, target_profile)
  ↓
  Loop (max 4 attempts: 1 initial + 3 retries):
    │
    ├── Generator (DeepSeek-V3.2, temp=0.7)
    │     attempt 1: creates question from reaction path
    │     attempt 2+: "REFINE IN PLACE" — fixes only what verifier flagged
    │
    ├── Verifier (DeepSeek-V3.2, temp=0.0)
    │     blind-solve protocol: solves independently, then compares to candidate
    │     writes: verdict (PASS/FAIL), semantic_flaws, feedback_for_generator
    │
    ├── Weak Solver (llama3.2/Ollama, temp=0.7)
    │     score ≤ 60% required
    │
    ├── Strong Solver (DeepSeek-V3.2, temp=0.0)
    │     score ≥ 85% required
    │
    └── 4-Gate Check:
          verifier.verdict == "PASS"
          strong.score >= 85
          weak.score <= 60
          reference_correct == True
          ↓ ALL PASS:
            compute_meta_tags() → build output record → append to generated_questions.json
            coverage.on_acceptance() → save coverage_state.json
          ↓ ANY FAIL:
            blackboard.record_attempt() → loop continues

GROUND-UP FALLBACK (run_groundup*.py):
  No graph. Topic anchor only (chapter + archetype).
  Filter concept_book to chapter + archetype subset (organic: regex; inorg/physical: source_chapter).
  Concept Reasoner selects 3-4 TX ids → chain description.
  Generator creates question FROM SCRATCH (no graph constraints).
  Same verifier + solver + gate flow.
  Demonstrated: Hydrocarbons / Archetype I → accepted on attempt 4.
```

---

## 3. Component: run_groundup.py — Full Code Detail

**Entry point:** `python run_groundup_final.py --subject organic` (or `run_groundup.py`)
**Status:** LIVE. Demonstrated successfully.

### OpenRouter retry wrapper

`run_groundup*.py` runs all roles through **OpenRouter** (strong model
`deepseek/deepseek-chat-v3-0324`), with the weak solver on local Ollama:

```python
OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

def openrouter_client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

def api_call(fn, retries=5, base_wait=10):
    """Retry wrapper for OpenRouter calls. Backs off on 429/503."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower() or "503" in msg:
                wait = base_wait * (2 ** attempt)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("OpenRouter: max retries exceeded")
```

(The graph-wired `run_graph*.py` instead uses SambaNova key rotation — see section 7.)

### Filtered concept book — not the full dump

```python
HYDRO_TERMS = re.compile(r'\b(alkan|alken|alkyn|cycloalk|methane|...|hydroboration)\b', re.IGNORECASE)

def filter_hydrocarbon_txs(concept_book):
    txs = concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"]
    return [tx for tx in txs
            if "I" in tx.get("archetype", [])
            and HYDRO_TERMS.search(f"{tx['from']} {tx['to']} {' '.join(tx['reagents'])}")]
    # Result: 110 TXs from 657 total
```

### Demonstrated Run (Hydrocarbons / Archetype I)

```
Attempt 1: propene → allyl chloride → allyl alcohol → glycerol → propane
  Verifier: PASS, Intermediate
  Weak: 0% ✓    Strong: 70% ✗  (below 85 floor) → Refine

Attempt 2: terminal alkyne → amine → allyl chloride → cyclobutyl ring expansion
  Verifier: FAIL — cyclobutyl chemistry not supported by the chain; 4 specific flaws
  Weak: 0% ✓    Strong: 65% ✗ → Refine

Attempt 3: alkane → alkyl halide → anti-Markovnikov → acetylide → trans-alkene
  Verifier: FAIL — NaNH2/NH3 on tertiary bromide gives elimination not alkyne formation
  Weak: 0% ✓    Strong: 70% ✗ → Refine

Attempt 4: propene → allyl chloride → allyl alcohol → glycerol → propane (refined)
  Verifier: PASS, Intermediate
  Weak: 0% ✓    Strong: 100% ✓  → ACCEPTED

  Meta-tags: question_length_scope=5, semantic_obfuscation=2, conceptual_fragility=3,
             number_of_exceptions=3, model_solution_length=2, distractor_plausibility=1
```

Attempts 2 and 3 show exactly why the knowledge graph is needed: the model invented
chemistry not supported by the selected TXs. Graph traversal prevents this — each hop
is a valid edge by construction.

---

## 4. Component: blackboard.py

**Location:** `core/blackboard.py`

```python
class Blackboard:
    def __init__(self, seed: dict, archetype: str, target_profile: dict):
        self.seed = seed              # full seed dict or topic_anchor
        self.archetype = archetype    # full archetype label string
        self.target_profile = target_profile
        self.attempts = []

    def record_attempt(self, problem, solution, operators_used,
                       verifier_result, weak_score, strong_score):
        """Appends one attempt record to self.attempts."""

    def operators_tried(self) -> list:
        """Deduplicated flat list of all operators used across all attempts."""

    def last_attempt(self) -> dict | None:
        """Returns self.attempts[-1] or None."""

    def context_summary(self) -> str:
        """One-line-per-attempt summary for Generator prompt on retries.
           Format: 'Attempt N: Verdict=X | Weak=Y% | Strong=Z% | Operators=[...] | Feedback=...'"""

    def history(self) -> list:
        """Returns full self.attempts list. Saved verbatim in output record."""
```

---

## 5. Component: meta_tags.py

**Location:** `core/meta_tags.py`

### compute_meta_tags() — Public API

```python
def compute_meta_tags(
    question_text: str,
    archetype_code: str,        # "I" | "II" | "III" | "IV"
    solver_trace: str = None,   # strong solver's attempted_solution field
    fragility_weight: float = None,  # 1 - (pct_full_marks/100); None for ground-up
    norm_stats_path: str = None,     # optional subject-specific norm stats JSON
) -> dict:
    # Returns: 6 keys, values 1-5 integers
```

### Z-score Formula

```python
def _zscore_to_15(z: float) -> int:
    return max(1, min(5, round(z * 1.5 + 3)))
# z=0 (corpus mean) → 3 | z=+1 → 5 | z=-1 → 1
```

### Six Tags

| Tag | Raw Signal | Normalization |
|-----|-----------|---------------|
| `question_length_scope` | word count of question_text | per-archetype from norm_stats |
| `semantic_obfuscation` | IUPAC token density (IUPAC words / total words) | global |
| `conceptual_fragility` | fragility_weight = 1 − (pct_full_marks/100) from JIC data | per-archetype |
| `number_of_exceptions` | exception/rejection keyword count in solver_trace | per-archetype |
| `model_solution_length` | word count of solver_trace | per-archetype (from solver_traces.json) |
| `distractor_plausibility` | explicit path-rejection phrase count in solver_trace | per-archetype (from solver_traces.json) |

---

## 6. Data Files — Exact Schemas

### jeeadv_organic_seeds.json

**Path:** `data/seeds/jeeadv_organic_seeds.json`
**Entries:** 153 | All 6 meta-tags calibrated.

```json
{
  "question_index":    "JADV_2023_P1_C5",
  "year":              2023,
  "paper":             "P1",
  "topic":             "Organic Chemistry",
  "chapter":           "Aromatic Compounds",
  "archetype":         "Long Reaction Chains",
  "archetype_code":    "I",
  "question_text":     "...",
  "pct_full_marks":    34.2,
  "fragility_weight":  0.658,
  "meta_tags": {
    "question_length_scope":   3,
    "semantic_obfuscation":    4,
    "conceptual_fragility":    4,
    "number_of_exceptions":    3,
    "model_solution_length":   3,
    "distractor_plausibility": 2
  }
}
```

**14 Canonical JEE Chapters:**
Hydrocarbons | IUPAC & Isomerism / Stereochemistry | Aromatic Compounds |
Biomolecules | Aldehydes & Ketones | Amines | Alkyl Halides |
Named Reactions & Multi-step Synthesis | Alcohols, Phenols & Ethers | GOC |
Carboxylic Acids & Derivatives | Reaction Mechanisms | Polymers | Organometallics & Grignard

### concept_book.json

**Path:** `knowledge/concept_book.json`

```json
{
  "structural_operators": {
    "add_reaction_step":       { "valid_transformations":  [ ...657 TX entries... ] },
    "expand_comparison_set":   { "valid_modifications":   [ ...470 entries... ] }
  },
  "interpretive_operators": {
    "conceptual_fragility":    { "concepts":   [ ...605 entries... ] },
    "number_of_exceptions":    { "exceptions": [ ...502 entries... ] },
    "semantic_obfuscation":    { "rules":      [ ...5 entries... ] },
    "distractor_plausibility": { "distractors":[ ...470 entries... ] }
  }
}
```

Each TX entry:
```json
{
  "from":      "alkene",
  "to":        "alkyl_halide",
  "reagents":  ["HBr", "peroxides"],
  "archetype": ["I", "III"],
  "conditions":"anti-Markovnikov addition; radical mechanism...",
  "notes":     "archetype I: include in chain; archetype III: ask why peroxides invert regiochemistry",
  "meta_tags": { "question_length_scope":3, "semantic_obfuscation":2, "conceptual_fragility":4,
                 "number_of_exceptions":5, "model_solution_length":3, "distractor_plausibility":4 }
}
```

### meta_tag_norm_stats.json

**Path:** `calibration/meta_tag_norm_stats.json`

```json
{
  "global": {
    "semantic_obfuscation": { "mean": 0.187, "std": 0.063, "metric": "iupac_token_density" }
  },
  "per_archetype": {
    "I":   {
      "question_length_scope":   { "mean": 82.3,  "std": 31.4  },
      "conceptual_fragility":    { "mean": 0.653,  "std": 0.142 },
      "number_of_exceptions":    { "mean": 4.1,    "std": 2.8   },
      "model_solution_length":   { "mean": 1338,   "std": 1087  },
      "distractor_plausibility": { "mean": 0.85,   "std": 1.16  }
    },
    "II":  { ... },
    "III": { ... },
    "IV":  { ... }
  }
}
```

Sample sizes for calibration: I=34, II=18, III=29, IV=10.

### generated_questions.json

Output file appended on each accepted question:
```json
[{
  "question_id":          "GEN_20260622T143521",
  "seed_id":              "GROUNDUP_HYDRO_001",
  "generation_mode":      "ground_up",
  "chapter":              "Hydrocarbons",
  "archetype":            "Long Reaction Chains",
  "archetype_code":       "I",
  "question":             "...",
  "solution":             "...",
  "operators_applied":    ["allylic_radical_chlorination", "SN2_substitution", ...],
  "loops_run":            4,
  "strong_score":         100,
  "weak_score":           0,
  "verifier_verdict":     "PASS",
  "meta_tags": { "question_length_scope":5, "semantic_obfuscation":2, ... },
  "attempt_history":      [ ...all attempt records from blackboard... ],
  "generated_at":         "2026-06-22T14:35:21+00:00"
}]
```

---

## 7. API Configuration and Rate Limits

### OpenRouter (used by `run_groundup*.py`; fallback in `run_graph*.py`)

```
Base URL:   https://openrouter.ai/api/v1
SDK:        openai.OpenAI (drop-in compatible)
Key:        OPENROUTER_KEY (required — set in .env)
Strong:     deepseek/deepseek-chat-v3-0324

Retry wrapper:
  On 429/503/rate_limit: exponential backoff, base_wait=10s, up to 5 attempts.

Per-role temperatures:
  Generator:     0.7
  Verifier:      0.0  ← deterministic
  Strong Solver: 0.0  ← deterministic
  Weak Solver:   0.7  (Ollama, not OpenRouter)
```

### SambaNova (used by `run_graph*.py` when keys are configured)

```
Base URL:   https://api.sambanova.ai/v1
SDK:        openai.OpenAI (drop-in compatible)
Keys:       SAMBANOVA_KEY_1 through SAMBANOVA_KEY_5 (uncomment in .env)

Key rotation:
  On 429: rotate to next key, sleep 2s, retry immediately.
  If all keys exhausted: sleep base_wait × 2^(attempt // n_keys) seconds.
  base_wait = 65s. Max cycles = retries × n_keys.

Per-role temperatures:
  Generator:     0.7
  Verifier:      0.0  ← deterministic
  Strong Solver: 0.0  ← deterministic
  Weak Solver:   0.7  (Ollama, not SambaNova)
```

### Ollama (Weak Solver Only)

```
Base URL:   http://localhost:11434/v1
Model:      llama3.2  (pull with: ollama pull llama3.2)
API key:    "ollama" (literal string, required by SDK)
No rate limits. No retry handler needed.
Must be running: check with curl http://localhost:11434
```

---

## 8. Calibrated Thresholds

```
STRONG_FLOOR = 85   (strong solver mean 96.4% − 1σ 12.1% ≈ 85)
WEAK_CEILING = 60   (weak solver mean 41.7% + 0.5σ 24.6% ≈ 60, conservatively)
MAX_RETRIES  = 3    (4 total attempts per question)
```

---

## 9. Reaction Knowledge Graph — Design Reference

### Node Schema

```json
{
  "id": "alkene",
  "type": "stable",
  "can_be_start": true,
  "can_be_end": true,
  "description": "Compound class with C=C double bond"
}
```

`type: "stable"` — persistent compound class; can be question start/end.
`type: "intermediate"` — carbocation, carbanion, etc.; `can_be_start: false`, `can_be_end: false`.

### Edge Schema — conditions_variants + chemoselectivity

```json
{
  "id": "alkene_HBr_markovnikov",
  "from": "alkene",
  "to": "alkyl_halide",
  "reagents": ["HBr"],
  "conditions": "electrophilic addition; Markovnikov; via carbocation intermediate",
  "firing_condition": null,
  "chapter": "Hydrocarbons",
  "archetype": ["I", "III"],
  "chemoselectivity": {
    "requires_absent": [],
    "node_redirect": {},
    "priority_ref": null
  },
  "tx_ids": [42],
  "meta_tags": { "question_length_scope":3, ... },
  "notes": "EXCEPTION: with peroxides, anti-Markovnikov via radical mechanism"
}
```

**`conditions_variants`**: same reaction, conditions change destination. Used for:
- HBr ± peroxides (Markovnikov vs anti-Markovnikov)
- KMnO₄ cold dilute vs hot concentrated (dihydroxylation vs cleavage)
- E2 small base (Zaitsev) vs bulky base (Hofmann)

**`chemoselectivity.node_redirect`**: if the substrate has a second functional group, the traversal engine redirects to that group's product instead (e.g. LiAlH₄ reduces ketone before alkene).

### Traversal State

```json
{
  "current_node": "alkene",
  "also_present": ["carbonyl"],
  "path_so_far": [
    {
      "edge_id": "alkane_radical_bromination",
      "destination_node": "alkyl_halide"
    }
  ],
  "instantiated_as": "2-methylbut-2-ene"
}
```

---

## 10. Orders JSON

**Path:** `knowledge/reaction_orders.json`

14 ordering dimensions with tiers, exceptions, JEE traps:

```json
{
  "dimension_id": "carbocation_stability",
  "general_rule": "tertiary > secondary > primary > methyl",
  "tiers": [ { "rank":1, "compounds":["tertiary", "benzylic", "allylic secondary"], ... } ],
  "exceptions": [
    {
      "condition": "adjacent to aromatic ring",
      "modified_order": "benzylic > tertiary",
      "jee_trap": "students apply simple alkyl order and miss benzylic resonance"
    }
  ]
}
```

Dimensions covered: carbocation stability, carbanion stability, radical stability, acidity,
basicity, nucleophilicity (polar protic), nucleophilicity (polar aprotic — INVERTED, key JEE trap),
electrophilicity, leaving group ability, SN1/SN2 preference, EAS reactivity, EAS regioselectivity,
oxidizing agent selectivity, migration aptitude.

---

## 11. Molecule Constructor

**Path:** `knowledge/molecule_constructor.json`

Defines what structural features make a given starting node + first edge combination question-worthy:

```json
{
  "node": "alkene",
  "interesting_when": {
    "edge_alkene_HBr": {
      "features": ["trisubstituted", "has_second_functional_group"],
      "why": "trisubstituted forces Markovnikov regiochemistry question"
    }
  },
  "valid_combinations": ["alkene + carbonyl (tests chemoselectivity)"],
  "forbidden_combos": ["too many functional groups (>2 makes chemoselectivity underdetermined)"]
}
```

---

## 12. Coverage and Sampling

**Location:** `core/coverage.py`

Four independent inverse-frequency counters:
```python
coverage = {
    "archetype": {"I": 0, "II": 0, "III": 0, "IV": 0},
    "chapter":   {ch: 0 for ch in ALL_14_CHAPTERS},
    "edge":      {edge_id: 0 for edge_id in ALL_GRAPH_EDGES},
    "concept":   {concept_name: 0 for concept_name in ALL_605_CONCEPTS}
}
```

Weight formula: `1/(count+1)` — count=0 → weight=1.0, count=10 → weight=0.09.

Edges with zero coverage are strictly prioritized until all edges are visited once; then pure weighted sampling.

---

## 13. Pending Work

### Priority 1 — Inorganic Knowledge Graph (Phase 0)

`run_graph_final.py --subject inorganic` requires `knowledge/reaction_graph_inorg.json`, which
is not yet built. Rebuild the graph for the inorganic concept book once `tools/build_graph.py`
gains subject support:
- Add a `--subject` argument to `tools/build_graph.py` (currently always builds organic).
- Run it against `concept_book_inorg.json` to produce `reaction_graph_inorg.json`.

### Priority 2 — Archetype IV (GOC) Generation Path

Separate from graph traversal. Pick a dimension from `reaction_orders.json`, pick an exception, instantiate compounds, generate comparison question. Same 4-gate filter applies.

### Priority 3 — Expand Graph Coverage

Current: ~57% TX coverage. The 288 unmapped TXs in `knowledge/graph_unmapped.json` are recoverable:
- Additional class-level aliases in `tools/build_graph.py` (~60 TXs)
- Qualitative test outcomes → encode as notes in `knowledge/qualitative_tests.json` (~150 TXs)
- Remaining carbocation rearrangement intermediates → new nodes (~20 TXs)

### Physics / Inorganic — Already Wired

Subject support is implemented via `subject_config.py`. Pour each new subject in alongside
`organic`/`inorganic`/`physical` — only the knowledge files need to exist for a subject to run.

---

## Operational Notes

```
Python:          python (or python3 — script is platform-independent)
Weak model:      llama3.2 via Ollama, must be running (ollama pull llama3.2)
Env file:        .env — OPENROUTER_KEY required; SAMBANOVA_KEY_1..5 optional (uncomment to use)

Vision policy:
  NO OCR tools anywhere in the pipeline.
  Use Claude vision only (Read tool with pages parameter for PDFs).

IUPAC convention:
  All generated questions use IUPAC nomenclature throughout.
  Generator prompt enforces: "Use standard IUPAC nomenclature throughout."

Code transparency:
  Always show code or explain exactly what tools and APIs are being used.
```
