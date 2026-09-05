"""
Ground-up question generation — no seed question.
Target: Hydrocarbon, Archetype I (Long Reaction Chains).

Pipeline: concept_reasoner (RLM) → generator → verifier → weak → strong → 3-gate → meta_tags
Uses OpenRouter for all API roles. Weak solver via Ollama (llama3.2, local).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from openai import OpenAI

# Enforce UTF-8 output (Windows console default cp1252 cannot print box-drawing chars).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from core.blackboard import Blackboard
from core.meta_tags import compute_meta_tags

# ── API clients ───────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

def openrouter_client():
    return OpenAI(
        api_key=OPENROUTER_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

weak_client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")

STRONG_MODEL = "deepseek/deepseek-chat-v3-0324"
WEAK_MODEL   = "llama3.2"
STRONG_FLOOR = 85
WEAK_CEILING = 60


def api_call(fn, retries=5, base_wait=10):
    """Retry wrapper for OpenRouter calls. Backs off on 429/503."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower() or "503" in msg:
                wait = base_wait * (2 ** attempt)
                print(f"    [rate limit] waiting {wait}s (attempt {attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("OpenRouter: max retries exceeded")


def parse_llm_json(content: str) -> dict:
    """Robustly parse a JSON object from LLM output (handles ``` fences,
    stray markdown, and leading/trailing text). Raises on failure."""
    if isinstance(content, str):
        text = content.strip()
    else:
        text = str(content).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from model output: {text[:200]!r}")


# ── Filter concept book to Hydrocarbon + Archetype I TXs ─────────────────────
HYDRO_TERMS = re.compile(
    r'\b(alkan|alken|alkyn|alkane|alkene|alkyne|cycloalk|cyclopent|cyclohex|cyclohept|'
    r'methane|ethane|propane|butane|pentane|hexane|heptane|octane|'
    r'methyl|ethyl|propyl|butyl|vinyl|allyl|propargyl|'
    r'hydrocarbon|radical halogen|ozonolysis|birch|lindlar|'
    r'hydrogenation|dehydrogen|dehydrat|markovnikov|hydroboration)\b',
    re.IGNORECASE
)

def filter_hydrocarbon_txs(concept_book):
    txs = concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"]
    filtered = []
    for tx in txs:
        if "I" not in tx.get("archetype", []):
            continue
        combined = f"{tx.get('from','')} {tx.get('to','')} {' '.join(tx.get('reagents',[]))}"
        if HYDRO_TERMS.search(combined):
            filtered.append(tx)
    return filtered


# ── Pipeline functions ────────────────────────────────────────────────────────

def concept_reasoner(blackboard: Blackboard, hydro_txs: list) -> dict:
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()

    # Summarize TXs concisely — just from/to/reagents/conditions (drop meta_tags)
    tx_summary = [
        {
            "id": i,
            "from": t["from"],
            "to": t["to"],
            "reagents": t["reagents"],
            "conditions": t.get("conditions", "")[:200],
        }
        for i, t in enumerate(hydro_txs)
    ]

    prompt = f"""You are a reasoning model designing JEE Advanced organic chemistry problems.

TASK: Select 3-4 reaction steps from the list below to build a coherent multi-step
Hydrocarbon synthesis/transformation chain (Archetype I: Long Reaction Chains).

The final question will be created FROM SCRATCH — there is no seed question.
The question will ask a student to identify the product after a series of reagent treatments,
OR identify the reagents needed for a specific transformation.

Chapter: Hydrocarbons
Archetype: Long Reaction Chains (I)
Target difficulty: Advanced (strong solver ≥85%, weak solver ≤60%)

Available transformations (choose by id):
{json.dumps(tx_summary, indent=2)}

Operators already tried in previous attempts: {tried}
Attempt history:
{context}

Reasoning instructions:
1. Pick 3-4 steps that form a CHEMICALLY COHERENT chain (product of step N is substrate of step N+1).
2. Prefer steps with non-obvious selectivity, stereochemistry, or exception behaviour.
3. Avoid steps tried in previous attempts if they caused verifier rejection.
4. If weak score was too high (problem too easy), pick steps with more subtle selectivity.
5. If strong score was too low (problem broken), simplify — ensure each step is unambiguous.

Return JSON:
{{
  "selected_tx_ids": [list of integer ids from the table above],
  "chain_description": "brief description of the overall transformation chain",
  "difficulty_rationale": "why this chain will be hard for a weak solver but solvable for a strong one",
  "reasoning": "step-by-step reasoning about why you picked these"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=1.0
    ))
    return parse_llm_json(resp.choices[0].message.content)


def generator(blackboard: Blackboard, selected_txs: list, chain_desc: str, attempt_num: int) -> dict:
    last = blackboard.last_attempt()

    if last:
        refine_block = f"""
--- REFINE IN PLACE (Attempt {attempt_num}) ---
Do NOT start over. Take the problem below and fix ONLY what was flagged.

Previous Problem:
{last['problem']}

Previous Solution:
{last['solution']}

Verifier Feedback: {last['verifier_feedback']}
Weak Solver Score: {last['weak_score']}%  (target ≤{WEAK_CEILING}%)
Strong Solver Score: {last['strong_score']}%  (target ≥{STRONG_FLOOR}%)

Fix the specific issue flagged. Keep all other elements identical.
"""
    else:
        refine_block = ""

    tx_detail = json.dumps(selected_txs, indent=2)

    prompt = f"""You are an expert JEE Advanced organic chemistry problem designer.

CREATE A QUESTION FROM SCRATCH using the reaction steps below.
Do NOT base this on any existing question. Build a new, original problem.

Chapter: Hydrocarbons
Archetype: Long Reaction Chains (I)
Chain: {chain_desc}

Reaction steps to incorporate:
{tx_detail}

Question format:
- Present a starting hydrocarbon compound (named in IUPAC).
- Apply the reaction steps sequentially (give reagents/conditions for each step).
- Ask the student to identify the final product, OR identify a missing reagent, OR
  give the molecular formula of a specific intermediate.
- The answer must be unique and unambiguous.
- Use IUPAC nomenclature throughout. Represent structures as IUPAC names or condensed formulas.
- Do NOT include diagrams — text only.
- Difficulty target: a JEE Advanced student who hasn't seen this exact chain should find it tricky.

{refine_block}

Return JSON:
{{
  "problem": "full question text",
  "solution": "complete step-by-step solution with mechanism and final answer",
  "operators_applied": ["list of reaction names used"],
  "reasoning": "brief note on what makes this hard"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    ))
    return parse_llm_json(resp.choices[0].message.content)


def verifier(problem: str, solution: str) -> dict:
    prompt = f"""You are an expert organic chemistry verifier (Blind Solver).

Protocol:
1. Read the problem. Do NOT read the candidate solution yet.
2. Solve independently, step by step.
3. Compare your solution to the candidate solution.
4. Check: functional group feasibility, mechanism correctness, reagent validity,
   stereochemical assignments, unambiguity of final answer.
5. Rate difficulty for a JEE Advanced student (Beginner / Intermediate / Advanced).

Problem:
{problem}

Candidate Solution:
{solution}

Return JSON:
{{
  "independent_solution": "your full solution",
  "semantic_flaws": "specific flaws, or 'None found'",
  "verdict": "PASS or FAIL",
  "difficulty_rating": "Beginner / Intermediate / Advanced (or N/A if FAIL)",
  "feedback_for_generator": "specific actionable fix if FAIL, else empty string"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry verifier. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return parse_llm_json(resp.choices[0].message.content)


def weak_solver(problem: str, solution: str) -> dict:
    prompt = f"""You are a chemistry undergraduate student.
Solve this organic chemistry problem as best you can, then score yourself 0-100 against the reference.

Problem:
{problem}

Reference Solution (for scoring only):
{solution}

Return JSON:
{{
  "attempted_solution": "your answer",
  "score": integer 0-100,
  "reasoning": "where you lost points"
}}"""

    resp = weak_client.chat.completions.create(
        model=WEAK_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    )
    return parse_llm_json(resp.choices[0].message.content)


def strong_solver(problem: str, solution: str) -> dict:
    prompt = f"""You are an expert organic chemist. Solve rigorously with full mechanism, then score 0-100.

Problem:
{problem}

Reference Solution (for scoring only):
{solution}

Return JSON:
{{
  "attempted_solution": "full step-by-step solution",
  "score": integer 0-100,
  "reasoning": "explanation of score and any discrepancies"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return parse_llm_json(resp.choices[0].message.content)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not OPENROUTER_KEY or "your-openrouter-key-here" in OPENROUTER_KEY:
        print("ERROR: OPENROUTER_KEY is not set to a real key.")
        print("  Add your key to .env (see .env.example) before running.")
        return

    MAX_RETRIES = 3
    OUTPUT_FILE = "generated_questions.json"

    print("Loading concept book...")
    with open(os.path.join(os.path.dirname(__file__), "knowledge", "concept_book.json"), encoding="utf-8") as f:
        concept_book = json.load(f)

    hydro_txs = filter_hydrocarbon_txs(concept_book)
    print(f"Filtered to {len(hydro_txs)} Hydrocarbon + Archetype I TXs")

    # Synthetic topic anchor — no seed question
    topic_anchor = {
        "question_index": "GROUNDUP_HYDRO_001",
        "question":  None,
        "answer":    None,
        "archetype": "Long Reaction Chains",
        "archetype_code": "I",
        "chapter":   "Hydrocarbons",
        "sub_topic": "Hydrocarbons",
    }

    target_profile = {
        "structural":   {"question_length_scope": "Advanced", "model_solution_length": "Advanced"},
        "interpretive": {"conceptual_fragility": "Advanced", "number_of_exceptions": "Intermediate",
                         "semantic_obfuscation": "Advanced", "distractor_plausibility": "Advanced"}
    }

    blackboard = Blackboard(topic_anchor, "Long Reaction Chains", target_profile)

    print("\n══════════════════════════════════════════════════")
    print(" GROUND-UP GENERATION: Hydrocarbons / Archetype I")
    print("══════════════════════════════════════════════════\n")

    accepted = False
    for attempt in range(1, MAX_RETRIES + 2):
        print(f"── Attempt {attempt} ─────────────────────────────────")

        print("Concept reasoner (RLM)...")
        cr = concept_reasoner(blackboard, hydro_txs)
        selected_ids  = cr.get("selected_tx_ids", [])
        chain_desc    = cr.get("chain_description", "")
        try:
            selected_ids = [int(i) for i in selected_ids]
        except (TypeError, ValueError):
            selected_ids = []
        selected_txs  = [hydro_txs[i] for i in selected_ids if 0 <= i < len(hydro_txs)]
        print(f"  Selected {len(selected_txs)} steps: {[t['from']+' → '+t['to'] for t in selected_txs]}")
        print(f"  Chain: {chain_desc}")

        print("Generator...")
        gen = generator(blackboard, selected_txs, chain_desc, attempt)

        print("Verifier...")
        ver = verifier(gen["problem"], gen["solution"])
        print(f"  Verdict: {ver['verdict']} | Difficulty: {ver.get('difficulty_rating','?')}")
        if ver["verdict"] == "FAIL":
            print(f"  Flaw: {ver['semantic_flaws']}")
            print(f"  Fix needed: {ver['feedback_for_generator']}")

        print("Weak solver (llama3.2)...")
        try:
            wk = weak_solver(gen["problem"], gen["solution"])
            weak_score = wk.get("score", 0)
        except Exception as e:
            print(f"  Weak solver error: {e}")
            weak_score = 0

        print(f"  Weak score: {weak_score}%")

        print("Strong solver (DeepSeek-V3.2)...")
        st = strong_solver(gen["problem"], gen["solution"])
        strong_score = st.get("score", 0)
        print(f"  Strong score: {strong_score}%")

        blackboard.record_attempt(
            problem          = gen["problem"],
            solution         = gen["solution"],
            operators_used   = gen.get("operators_applied", [t["from"]+"→"+t["to"] for t in selected_txs]),
            verifier_result  = ver,
            weak_score       = weak_score,
            strong_score     = strong_score,
        )

        gate_verifier = ver["verdict"] == "PASS"
        gate_strong   = strong_score >= STRONG_FLOOR
        gate_weak     = weak_score   <= WEAK_CEILING

        print(f"  Gates: verifier={'✓' if gate_verifier else '✗'}  "
              f"strong={'✓' if gate_strong else '✗'} ({strong_score}% vs ≥{STRONG_FLOOR})  "
              f"weak={'✓' if gate_weak else '✗'} ({weak_score}% vs ≤{WEAK_CEILING})")

        if gate_verifier and gate_strong and gate_weak:
            accepted = True

            meta = compute_meta_tags(
                question_text    = gen["problem"],
                archetype_code   = "I",
                solver_trace     = st.get("attempted_solution", ""),
                fragility_weight = None,
            )

            record = {
                "question_id":       f"GEN_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                "seed_id":           "GROUNDUP_HYDRO_001",
                "generation_mode":   "ground_up",
                "chapter":           "Hydrocarbons",
                "archetype":         "Long Reaction Chains",
                "archetype_code":    "I",
                "question":          gen["problem"],
                "solution":          gen["solution"],
                "operators_applied": gen.get("operators_applied", []),
                "chain_description": chain_desc,
                "loops_run":         attempt,
                "strong_score":      strong_score,
                "weak_score":        weak_score,
                "verifier_verdict":  ver["verdict"],
                "verifier_difficulty": ver.get("difficulty_rating", "?"),
                "meta_tags":         meta,
                "attempt_history":   blackboard.history(),
                "generated_at":      datetime.now(timezone.utc).isoformat(),
            }

            existing = []
            if os.path.exists(OUTPUT_FILE):
                with open(OUTPUT_FILE) as f:
                    existing = json.load(f)
            existing.append(record)
            with open(OUTPUT_FILE, "w") as f:
                json.dump(existing, f, indent=2)

            print(f"\n✓ ACCEPTED on attempt {attempt}")
            print(f"  Meta-tags: {meta}")
            print(f"\n{'='*60}")
            print("QUESTION:")
            print('='*60)
            print(gen["problem"])
            print(f"\n{'='*60}")
            print("SOLUTION:")
            print('='*60)
            print(gen["solution"])
            print(f"\nVerifier difficulty: {ver.get('difficulty_rating','?')}")
            print(f"Strong: {strong_score}% | Weak: {weak_score}%")
            print(f"Saved to {OUTPUT_FILE}")
            break

        if attempt > MAX_RETRIES:
            print(f"\n✗ Max retries ({MAX_RETRIES}) reached without acceptance.")
            break

        print("  → Refining...\n")

    if not accepted:
        last = blackboard.last_attempt()
        print("\nBest attempt (not accepted):")
        if last:
            print(last["problem"])


if __name__ == "__main__":
    main()
