"""
run_groundup.py — no-graph, no-seed-question generation. Supports
--subject {organic,inorganic,physical}.

Pipeline: concept_reasoner (RLM) → generator → verifier → weak → strong → gate → meta_tags.
Uses OpenRouter for all API roles. Weak solver via Ollama (llama3.2, local).

Everything except knowledge-file loading, TX filtering, coverage/output files,
and prompt wording is unchanged from organic — those now come from --subject
(see subject_config.py).
"""

import argparse
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

from subject_config import (
    get_subject_config,
    load_coverage_for_subject,
    save_coverage,
    compute_meta_tags_for_subject,
)

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
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

weak_client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")

# Per-role models, diversified across families so no single model both produces a claim
# and certifies it (the "no producer certifies itself" commitment). NOTE: the README is
# stale — these are the live assignments, verified against this code.
CONCEPT_MODEL       = "deepseek/deepseek-chat-v3-0324"   # DeepSeek — selects reaction steps
GENERATOR_MODEL     = "deepseek/deepseek-chat-v3-0324"   # DeepSeek — writes question + reference solution
VERIFIER_MODEL      = "qwen/qwen-2.5-72b-instruct"       # Qwen2.5-72B — blind-checks the item (≠ generator)
STRONG_SOLVER_MODEL = "openai/gpt-oss-120b"              # gpt-oss — blind expert solver (≠ generator)
GRADER_MODEL        = "openai/gpt-4o"                     # GPT-4o  — grades solvers' answers (≠ solvers, ≠ generator)
WEAK_MODEL          = "meta-llama/llama-3.2-3b-instruct"  # Llama 3B — blind weak floor (OpenRouter, not Ollama)
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


# ── TX filtering — organic uses regex over from/to/reagents; inorganic/physical
#    filter on the explicit source_chapter field carried by their concept books ──

def filter_txs_for_subject(concept_book: dict, config: dict, chapter: str) -> list:
    txs = concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"]
    code = config["default_archetype_code"]
    mode = config["tx_filter_mode"]

    if mode == "regex":
        pattern = re.compile(config["tx_filter_regex"], re.IGNORECASE)
        filtered = []
        for tx in txs:
            if code not in tx.get("archetype", []):
                continue
            combined = f"{tx.get('from','')} {tx.get('to','')} {' '.join(tx.get('reagents',[]))}"
            if pattern.search(combined):
                filtered.append(tx)
        return filtered

    if mode == "chapter_field":
        field = config.get("chapter_field_key", "source_chapter")
        filtered = [
            tx for tx in txs
            if tx.get(field) == chapter
            and (not tx.get("archetype") or code in tx.get("archetype", []))
        ]
        return filtered

    raise ValueError(f"Unknown tx_filter_mode: {mode}")


# ── Pipeline functions ──────────────────────────────────────────────────────────

def concept_reasoner(blackboard: Blackboard, txs: list, config: dict) -> dict:
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()
    chapter = config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    tx_summary = [
        {
            "id": i,
            "from": t["from"],
            "to": t["to"],
            "reagents": t.get("reagents", []),
            "conditions": t.get("conditions", "")[:200],
        }
        for i, t in enumerate(txs)
    ]

    prompt = f"""You are a reasoning model designing JEE Advanced {config['display_name']} problems.

TASK: Select 3-4 reaction steps from the list below to build a coherent multi-step
{chapter} transformation chain (Archetype {code}: {arch}).

The final question will be created FROM SCRATCH — there is no seed question.
The question will ask a student to identify the product after a series of steps,
OR identify the reagents/conditions needed for a specific transformation.

Chapter: {chapter}
Archetype: {arch} ({code})
Target difficulty: Advanced (strong solver ≥85%, weak solver ≤60%)

Available transformations (choose by id):
{json.dumps(tx_summary, indent=2)}

Operators already tried in previous attempts: {tried}
Attempt history:
{context}

Reasoning instructions:
1. Pick 3-4 steps that form a CHEMICALLY COHERENT chain (product of step N is substrate of step N+1).
2. Prefer steps with non-obvious selectivity or exception behaviour.
3. Avoid steps tried in previous attempts if they caused verifier rejection.
4. If weak score was too high (problem too easy), pick steps with more subtle reasoning.
5. If strong score was too low (problem broken), simplify — ensure each step is unambiguous.

Return JSON:
{{
  "selected_tx_ids": [list of integer ids from the table above],
  "chain_description": "brief description of the overall transformation chain",
  "difficulty_rationale": "why this chain will be hard for a weak solver but solvable for a strong one",
  "reasoning": "step-by-step reasoning about why you picked these"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=CONCEPT_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=1.0,
        max_tokens=1500,
    ))
    return parse_llm_json(resp.choices[0].message.content)


def generator(blackboard: Blackboard, selected_txs: list, chain_desc: str,
              attempt_num: int, config: dict) -> dict:
    last = blackboard.last_attempt()
    chapter = config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

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

    prompt = f"""You are an expert JEE Advanced {config['display_name']} problem designer.

CREATE A QUESTION FROM SCRATCH using the reaction/transformation steps below.
Do NOT base this on any existing question. Build a new, original problem.

Chapter: {chapter}
Archetype: {arch} ({code})
Chain: {chain_desc}

Steps to incorporate:
{tx_detail}

MANDATORY INTERNAL CHECKS — do these BEFORE writing the question:
{config['mandatory_checks_block']}

Question format:
- Present a starting compound/system (named per IUPAC/standard convention).
- Apply the steps sequentially (give reagents/conditions for each step).
- Ask the student to identify the final product/answer, OR identify a missing
  reagent/condition, OR give a key intermediate quantity.
- The answer must be unique and unambiguous.
- Use standard nomenclature throughout. Do NOT include diagrams — text only.
- Difficulty target: a JEE Advanced student who hasn't seen this exact chain should find it tricky.

{refine_block}

Return JSON:
{{
  "problem": "full question text",
  "solution": "complete step-by-step solution with reasoning and final answer",
  "operators_applied": ["list of reaction/transformation names used"],
  "reasoning": "brief note on what makes this hard"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=GENERATOR_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=4000,
    ))
    return parse_llm_json(resp.choices[0].message.content)


def verifier(problem: str, solution: str, config: dict) -> dict:
    role = config["chemist_role"]

    prompt = f"""You are an expert {role} verifier (Blind Solver).

Protocol:
1. Read the problem. Do NOT read the candidate solution yet.
2. Solve independently, step by step.
3. Compare your solution to the candidate solution.
4. Check the mandatory items below.
5. Rate difficulty for a JEE Advanced student (Beginner / Intermediate / Advanced).

Mandatory checks:
{config['verifier_checks_block']}

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
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry verifier. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=3000,
    ))
    return parse_llm_json(resp.choices[0].message.content)


def blind_solve(problem: str, config: dict, expert: bool) -> dict:
    """Solve the problem WITHOUT seeing the reference solution (edit 1: blind solving).

    The solver used to be handed the reference "for scoring only" and asked to
    self-score against it — which let a capable model confirm the answer it was
    shown (pinning the strong score at 100) and gave the weak model no honest task.
    Here the solver works cold and only reports its own answer; scoring is done
    separately by grade_answer().

    expert=True → strong model (OpenRouter); expert=False → weak model (Ollama).
    """
    if expert:
        role = config["chemist_role"]
        system = f"You are an expert {role}. Output JSON only."
        instruction = (f"You are an expert {role}. Solve this {config['display_name']} "
                       f"problem rigorously, showing full step-by-step reasoning.")
    else:
        system = "You are a chemistry undergraduate. Output JSON only."
        instruction = (f"You are a chemistry undergraduate student. Solve this "
                       f"{config['display_name']} problem as best you can.")

    prompt = f"""{instruction}

You are NOT given an answer key. Work the answer out yourself.

Problem:
{problem}

Return JSON:
{{
  "attempted_solution": "your full step-by-step working",
  "final_answer": "your final answer only (product name / value / reagent)"
}}"""

    if expert:
        resp = api_call(lambda: openrouter_client().chat.completions.create(
            model=STRONG_SOLVER_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=4000,
        ))
    else:
        resp = api_call(lambda: openrouter_client().chat.completions.create(
            model=WEAK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
            max_tokens=4000,
        ))
    return parse_llm_json(resp.choices[0].message.content)


def grade_answer(problem: str, reference_solution: str, candidate: dict, config: dict) -> dict:
    """Independent grader (edit 1): judge a blind solver's final answer against the
    reference. The solver never saw the reference; the grader does — grading needs a
    key, but the thing being graded was produced cold, so a solver can no longer
    certify itself by copying the answer it was shown."""
    role = config["chemist_role"]
    prompt = f"""You are an expert {role} acting as an impartial grader.

A solver attempted the problem below WITHOUT seeing any answer key. Judge their FINAL
ANSWER against the reference solution.

Rules:
- Give a score 0-100 for how chemically correct and complete the solver's final answer
  is (partial credit allowed). Judge equivalence of chemistry, not wording or format.
- If the solver's answer disagrees with the reference AND the solver is the one who is
  chemically correct (i.e. the reference key is wrong), set reference_correct=false and
  explain the error in the reference.

Problem:
{problem}

Reference solution:
{reference_solution}

Solver's final answer:
{candidate.get('final_answer', '')}

Solver's full working:
{candidate.get('attempted_solution', '')}

Return JSON:
{{
  "score": integer 0-100,
  "reference_correct": true or false,
  "reasoning": "brief justification of the score"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=GRADER_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry grader. Output JSON only."},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=800,
    ))
    return parse_llm_json(resp.choices[0].message.content)


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Ground-up JEE Advanced question generation.")
    parser.add_argument(
        "--subject", choices=["organic", "inorganic", "physical"], default="organic",
        help="Which subject's concept book to use."
    )
    parser.add_argument(
        "--chapter", default=None,
        help="Override the default chapter/sub_topic for this subject (must match a "
             "source_chapter value in the subject's concept book for inorganic/physical)."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not OPENROUTER_KEY or "your-openrouter-key-here" in OPENROUTER_KEY:
        print("ERROR: OPENROUTER_KEY is not set to a real key.")
        print("  Add your key to .env (see .env.example) before running.")
        return

    config = get_subject_config(args.subject)
    chapter = args.chapter or config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    if not os.path.exists(config["concept_book_path"]):
        print(f"ERROR: {config['concept_book_path']} not found.")
        print(f"Complete Phase 0 for --subject {args.subject} first (build the concept book).")
        return

    MAX_RETRIES = 3
    OUTPUT_FILE = config["output_file"]

    print(f"Loading concept book ({config['display_name']})...")
    with open(config["concept_book_path"], encoding="utf-8") as f:
        concept_book = json.load(f)

    txs = filter_txs_for_subject(concept_book, config, chapter)
    print(f"Filtered to {len(txs)} {chapter} + Archetype {code} TXs")
    if not txs:
        print("ERROR: No matching transformations found. Check --chapter / concept book contents.")
        return

    coverage = load_coverage_for_subject(config)
    print(f"Coverage loaded ({args.subject}): {coverage.total_accepted()} questions accepted so far.")

    topic_anchor = {
        "question_index": f"GROUNDUP_{config['seed_id_prefix']}_001",
        "question":  None,
        "answer":    None,
        "archetype": arch,
        "archetype_code": code,
        "chapter":   chapter,
        "sub_topic": chapter,
    }

    target_profile = {
        "structural":   {"question_length_scope": "Advanced", "model_solution_length": "Advanced"},
        "interpretive": {"conceptual_fragility": "Advanced", "number_of_exceptions": "Intermediate",
                         "semantic_obfuscation": "Advanced", "distractor_plausibility": "Advanced"}
    }

    blackboard = Blackboard(topic_anchor, arch, target_profile)

    print("\n══════════════════════════════════════════════════")
    print(f" GROUND-UP GENERATION [{config['display_name']}]: {chapter} / Archetype {code}")
    print("══════════════════════════════════════════════════\n")

    accepted = False
    for attempt in range(1, MAX_RETRIES + 2):
        print(f"── Attempt {attempt} ─────────────────────────────────")

        try:
            print("Concept reasoner (RLM)...")
            cr = concept_reasoner(blackboard, txs, config)
            selected_ids  = cr.get("selected_tx_ids", [])
            chain_desc    = cr.get("chain_description", "")
            try:
                selected_ids = [int(i) for i in selected_ids]
            except (TypeError, ValueError):
                selected_ids = []
            selected_txs  = [txs[i] for i in selected_ids if 0 <= i < len(txs)]
            print(f"  Selected {len(selected_txs)} steps: {[t['from']+' → '+t['to'] for t in selected_txs]}")
            print(f"  Chain: {chain_desc}")

            print("Generator...")
            gen = generator(blackboard, selected_txs, chain_desc, attempt, config)

            print("Verifier...")
            ver = verifier(gen["problem"], gen["solution"], config)
            print(f"  Verdict: {ver['verdict']} | Difficulty: {ver.get('difficulty_rating','?')}")
            if ver["verdict"] == "FAIL":
                print(f"  Flaw: {ver['semantic_flaws']}")
                print(f"  Fix needed: {ver['feedback_for_generator']}")

            # Weak solver — blind (edit 1): solve WITHOUT the reference, then grade the
            # blind answer with an independent grader. Score is None if the call or grade
            # fails (edit 2) — never silently 0, which used to *pass* the weak gate.
            print("Weak solver (llama3.2, blind)...")
            try:
                wk_blind   = blind_solve(gen["problem"], config, expert=False)
                wk_grade   = grade_answer(gen["problem"], gen["solution"], wk_blind, config)
                weak_score = wk_grade.get("score")
            except Exception as e:
                print(f"  Weak solver error: {e}")
                weak_score = None
            print(f"  Weak score: {weak_score if weak_score is not None else 'n/a (unmeasured)'}")

            # Strong solver — blind (edit 1): same protocol with the expert model.
            print("Strong solver (blind)...")
            try:
                st_blind     = blind_solve(gen["problem"], config, expert=True)
                st_grade     = grade_answer(gen["problem"], gen["solution"], st_blind, config)
                strong_score = st_grade.get("score")
                ref_correct  = st_grade.get("reference_correct", True)
                strong_trace = st_blind.get("attempted_solution", "")
            except Exception as e:
                print(f"  Strong solver error: {e}")
                strong_score = None
                ref_correct  = True
                strong_trace = ""
            print(f"  Strong score: {strong_score if strong_score is not None else 'n/a (unmeasured)'}"
                  f"  |  reference_correct: {ref_correct}")

            blackboard.record_attempt(
                problem          = gen["problem"],
                solution         = gen["solution"],
                operators_used   = gen.get("operators_applied", [t["from"]+"→"+t["to"] for t in selected_txs]),
                verifier_result  = ver,
                weak_score       = weak_score,
                strong_score     = strong_score,
            )

            # Gates (edit 2): an unmeasured score (None) can never satisfy a gate, so a
            # failed solver call quarantines the item instead of silently passing it.
            gate_verifier = ver["verdict"] == "PASS"
            gate_strong   = strong_score is not None and strong_score >= STRONG_FLOOR
            gate_weak     = weak_score   is not None and weak_score   <= WEAK_CEILING
            gate_ref_ok   = ref_correct

            print(f"  Gates: verifier={'✓' if gate_verifier else '✗'}  "
                  f"strong={'✓' if gate_strong else '✗'} ({strong_score} vs ≥{STRONG_FLOOR})  "
                  f"weak={'✓' if gate_weak else '✗'} ({weak_score} vs ≤{WEAK_CEILING})  "
                  f"ref_ok={'✓' if gate_ref_ok else '✗'}")

            if gate_verifier and gate_strong and gate_weak and gate_ref_ok:
                accepted = True

                meta = compute_meta_tags_for_subject(
                    config,
                    question_text    = gen["problem"],
                    archetype_code   = code,
                    solver_trace     = strong_trace,
                    fragility_weight = None,
                )

                coverage.on_acceptance(
                    archetype = code,
                    chapter   = chapter,
                    edges     = [],
                    concepts  = gen.get("operators_applied", []),
                )
                save_coverage(coverage, config)
                print(f"  Coverage updated. Total accepted: {coverage.total_accepted()}")

                record = {
                    "question_id":       f"GEN_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                    "seed_id":           f"GROUNDUP_{config['seed_id_prefix']}_001",
                    "generation_mode":   "ground_up",
                    "subject":           args.subject,
                    "chapter":           chapter,
                    "archetype":         arch,
                    "archetype_code":    code,
                    "question":          gen["problem"],
                    "solution":          gen["solution"],
                    "operators_applied": gen.get("operators_applied", []),
                    "chain_description": chain_desc,
                    "loops_run":         attempt,
                    "strong_score":      strong_score,
                    "weak_score":        weak_score,
                    "reference_correct": ref_correct,
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

        except Exception as e:
            print(f"  Attempt {attempt} error: {e}")

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
