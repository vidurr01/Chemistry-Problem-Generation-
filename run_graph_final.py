"""
run_graph.py — Graph-wired ground-up generation. Supports --subject {organic,inorganic}.

Physical Chemistry has no reaction graph (see Phase 0 plan — ground-up only),
so --subject physical is rejected here; use run_groundup.py --subject physical instead.

Replaces the full concept_book TX dump in the Concept Reasoner with:
  1. get_paths() call on the reaction knowledge graph → candidate chains
  2. coverage.weight() scoring → highest-weight chain passed to the LLM
  3. coverage.on_acceptance() on success → diversity tracking persists

Everything else (generator, verifier, weak/strong solver, gates, meta_tags) unchanged
from organic — only the knowledge files, coverage/output files, and prompt wording
are now selected via --subject (see subject_config.py).
"""

import argparse
import json
import os
import re
import sys
import time
import random
from datetime import datetime, timezone
from openai import OpenAI

# Enforce UTF-8 output (Windows console default cp1252 cannot print box-drawing chars).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from core.blackboard import Blackboard
from core.graph_traversal import get_paths

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

SAMBANOVA_KEYS = [
    k for k in (
        os.environ.get("SAMBANOVA_KEY_1", ""),
        os.environ.get("SAMBANOVA_KEY_2", ""),
        os.environ.get("SAMBANOVA_KEY_3", ""),
        os.environ.get("SAMBANOVA_KEY_4", ""),
        os.environ.get("SAMBANOVA_KEY_5", ""),
    ) if k
]
_key_idx = 0

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

def samba_client():
    return OpenAI(api_key=SAMBANOVA_KEYS[_key_idx], base_url="https://api.sambanova.ai/v1")

def openrouter_client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

weak_client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")

GENERATOR_MODEL     = "DeepSeek-V3.2"
VERIFIER_MODEL      = "DeepSeek-V3.2"
STRONG_SOLVER_MODEL = "DeepSeek-V3.2"
WEAK_MODEL          = "llama3.2"

STRONG_MODEL = GENERATOR_MODEL
STRONG_FLOOR = 85
WEAK_CEILING = 60


def api_call(fn, retries=3, base_wait=65):
    """4-key rotation on 429; exponential backoff when all keys exhausted."""
    global _key_idx
    for attempt in range(retries * len(SAMBANOVA_KEYS)):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                next_idx = (_key_idx + 1) % len(SAMBANOVA_KEYS)
                if next_idx != _key_idx:
                    _key_idx = next_idx
                    print(f"    [rate limit] → rotating to key {_key_idx + 1}")
                    time.sleep(2)
                else:
                    wait = base_wait * (2 ** (attempt // len(SAMBANOVA_KEYS)))
                    print(f"    [all keys limited] waiting {wait}s...")
                    time.sleep(wait)
            else:
                raise
    raise RuntimeError("SambaNova: exhausted all keys and retries")


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


# ── Graph-based path sampling ──────────────────────────────────────────────────

def _edge_label(edge: dict) -> str:
    reagents = edge.get("reagents", [])
    r = reagents[0] if reagents else "?"
    return f"{edge['from']} →[{r}]→ {edge['to']}"


def sample_paths(coverage, config: dict, n_options: int = 6, depth: int = 3,
                  avoid_nodes: list | None = None) -> list:
    """
    Sample candidate reaction chains from the graph, scored by coverage weight.

    Returns list of dicts:
      { "idx": int, "start": str, "nodes": [str,...], "edges": [str,...],
        "weight": float, "description": str }
    Sorted by weight descending (highest = least recently used).
    """
    avoid = avoid_nodes or []
    all_paths = []
    start_nodes = config["start_nodes"]
    chapter     = config["default_chapter"]
    arch_code   = config["default_archetype_code"]

    for start in start_nodes:
        result = get_paths(start, depth=depth, avoid_nodes=avoid)
        for p in result.get("paths", []):
            if len(p["edges"]) < 2:
                continue  # need at least 2 steps for a good chain
            w = coverage.weight(arch_code, chapter, p["edges"], [])
            all_paths.append({
                "start":  start,
                "nodes":  p["nodes"],
                "edges":  p["edges"],
                "weight": w,
            })

    if not all_paths:
        return []

    all_paths.sort(key=lambda x: (-x["weight"], random.random()))

    options = []
    with open(config["graph_path"], encoding="utf-8") as f:
        graph = json.load(f)
    edge_map = {e["id"]: e for e in graph["edges"]}

    for i, p in enumerate(all_paths[:n_options]):
        steps = []
        for eid in p["edges"]:
            e = edge_map.get(eid, {})
            reagents = e.get("reagents", [])
            r_str = ", ".join(reagents[:2]) if reagents else "?"
            steps.append(f"{e.get('from','?')} → {e.get('to','?')} [{r_str}]")

        p["idx"] = i
        p["description"] = " | ".join(steps)
        options.append(p)

    return options


def edges_to_tx_format(edge_ids: list, config: dict) -> list:
    """Convert graph edge IDs to TX-format dicts for the generator prompt."""
    with open(config["graph_path"], encoding="utf-8") as f:
        graph = json.load(f)
    edge_map = {e["id"]: e for e in graph["edges"]}
    txs = []
    for eid in edge_ids:
        e = edge_map.get(eid, {})
        txs.append({
            "from":       e.get("from", "?"),
            "to":         e.get("to", "?"),
            "reagents":   e.get("reagents", []),
            "conditions": e.get("conditions", ""),
            "notes":      e.get("notes", ""),
            "chapter":    e.get("chapter", config["default_chapter"]),
        })
    return txs


# ── Pipeline functions ──────────────────────────────────────────────────────────

def concept_reasoner(blackboard: Blackboard, path_options: list, config: dict) -> dict:
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()
    chapter = config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    path_lines = []
    for p in path_options:
        path_lines.append(
            f"Path {p['idx']} (diversity_weight={p['weight']:.4f}): {p['description']}"
        )
    paths_block = "\n".join(path_lines)

    prompt = f"""You are a reasoning model designing JEE Advanced {config['display_name']} problems.

TASK: Select the BEST reaction chain from the options below to build a 3-4 step
{chapter} synthesis/transformation question (Archetype {code}: {arch}).

The question will ask a student to identify products after sequential reagent treatments,
OR identify a missing reagent, OR give a key quantity/intermediate along the chain.

Chapter: {chapter}
Archetype: {arch} ({code})
Target difficulty: Advanced (strong solver ≥85%, weak solver ≤60%)

Available chains (choose by Path number):
{paths_block}

Operators already tried in previous attempts: {tried}
Attempt history:
{context}

Selection criteria:
1. Prefer chains with NON-OBVIOUS selectivity or exception behaviour.
2. Prefer chains with MORE steps (higher depth = richer question).
3. Avoid chains containing steps that caused verifier rejection in prior attempts.
4. Higher diversity_weight = less recently used = prefer it for variety.
5. If previous strong score was too low (question broken), pick a simpler, unambiguous chain.

Return JSON:
{{
  "selected_path_idx": integer (Path number from the list above),
  "chain_description": "one sentence describing the overall transformation",
  "difficulty_rationale": "why this chain will challenge a weak solver",
  "reasoning": "brief reasoning for your choice"
}}"""

    resp = api_call(lambda: samba_client().chat.completions.create(
        model=GENERATOR_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=1.0
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

CREATE A QUESTION FROM SCRATCH using the reaction steps below.
Do NOT base this on any existing question. Build a new, original problem.

Chapter: {chapter}
Archetype: {arch} ({code})
Chain: {chain_desc}

Reaction steps to incorporate:
{tx_detail}

MANDATORY INTERNAL CHECKS — do these BEFORE writing the question:
{config['mandatory_checks_block']}

Question format:
- Present a starting compound/system (named per IUPAC/standard convention).
- Apply the reaction steps sequentially (give reagents/conditions for each step).
- Ask the student to identify the final product, OR identify a missing reagent, OR
  give a key intermediate quantity.
- The answer must be unique and unambiguous.
- Use standard nomenclature throughout. Do NOT include diagrams — text only.
- Difficulty target: a JEE Advanced student who hasn't seen this exact chain should find it tricky.

{refine_block}

Return JSON:
{{
  "problem": "full question text",
  "solution": "complete step-by-step solution with reasoning and final answer",
  "formula_trace": ["state/formula at each step"],
  "active_species_per_step": ["all reactive species/groups present after each step"],
  "difficulty_levers": ["lever: condition X → outcome A; without X → outcome B"],
  "operators_applied": ["list of reaction/transformation names used"],
  "reasoning": "brief note on what makes this hard"
}}"""

    resp = api_call(lambda: samba_client().chat.completions.create(
        model=GENERATOR_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7
    ))
    return parse_llm_json(resp.choices[0].message.content)


def verifier(problem: str, solution: str, config: dict) -> dict:
    role = config["chemist_role"]

    blind_prompt = f"""You are an expert {role} verifier.

Solve the following problem completely independently. Show full step-by-step working.
Do NOT skip steps.

Problem:
{problem}

Return JSON:
{{
  "independent_solution": "full step-by-step solution",
  "formula_trace": ["state/quantity after each step"],
  "final_answer": "name/formula/value of the final product or answer"
}}"""

    blind_resp = api_call(lambda: samba_client().chat.completions.create(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": f"You are an expert {role}. Output JSON only."},
            {"role": "user",   "content": blind_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    blind = json.loads(blind_resp.choices[0].message.content.strip())

    compare_prompt = f"""You are an expert {role} verifier. You have already solved
the problem independently (shown below). Now compare your solution to the candidate solution
and run the mandatory invariant checks.

Problem:
{problem}

YOUR INDEPENDENT SOLUTION:
{blind.get('independent_solution', '')}

Your trace: {blind.get('formula_trace', [])}
Your final answer: {blind.get('final_answer', '')}

CANDIDATE SOLUTION:
{solution}

MANDATORY CHECKS — evaluate each explicitly:

{config['verifier_checks_block']}

Return JSON:
{{
  "check1_formula": "PASS or FAIL — explanation",
  "check2_fgs": "PASS or FAIL — explanation",
  "check3_stereo": "PASS or FAIL — explanation",
  "check4_circularity": "PASS or FAIL — explanation",
  "check5_agreement": "AGREE or DISAGREE — explanation",
  "check6_levers": "note on decorative vs genuine conditions",
  "semantic_flaws": "combined list of all flaws found, or 'None found'",
  "verdict": "PASS only if checks 1-4 all pass AND check5 is AGREE; FAIL otherwise",
  "difficulty_rating": "Beginner / Intermediate / Advanced (or N/A if FAIL)",
  "feedback_for_generator": "specific actionable fix if FAIL, else empty string"
}}"""

    compare_resp = api_call(lambda: samba_client().chat.completions.create(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry verifier. Output JSON only."},
            {"role": "user",   "content": compare_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    result = json.loads(compare_resp.choices[0].message.content.strip())
    result["independent_solution"] = blind.get("independent_solution", "")
    result["blind_formula_trace"]  = blind.get("formula_trace", [])
    result["blind_final_answer"]   = blind.get("final_answer", "")
    return result


def weak_solver(problem: str, config: dict) -> dict:
    """Blind (edit 1): the weak model solves WITHOUT the reference and does NOT
    self-score. It used to be handed the answer key "for scoring only" and asked to
    grade its own attempt against it — so its score reflected self-assessment noise,
    not whether it could actually solve the problem. Scoring is now done separately by
    grade_answer()."""
    prompt = f"""You are a chemistry undergraduate student.
Solve this {config['display_name']} problem as best you can. You are NOT given an
answer key — work it out yourself.

Problem:
{problem}

Return JSON:
{{
  "attempted_solution": "your full working",
  "final_answer": "your final answer only (product name / value / reagent)"
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


def grade_answer(problem: str, reference_solution: str, candidate: dict, config: dict) -> dict:
    """Independent grader (edit 1): score a blind solver's final answer against the
    reference. The solver never saw the reference; the grader does — decoupling solving
    from scoring so the weak baseline gives an honest can-it-solve-this signal."""
    role = config["chemist_role"]
    prompt = f"""You are an expert {role} acting as an impartial grader.

A solver attempted the problem below WITHOUT seeing any answer key. Judge their FINAL
ANSWER against the reference solution.

Rules:
- Give a score 0-100 for how chemically correct/complete the solver's final answer is
  (partial credit allowed). Judge equivalence of chemistry, not wording or format.
- If the solver disagrees with the reference AND the solver is chemically correct
  (the reference key is wrong), set reference_correct=false and explain.

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
  "reasoning": "brief justification"
}}"""

    resp = api_call(lambda: samba_client().chat.completions.create(
        model=STRONG_SOLVER_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry grader. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return parse_llm_json(resp.choices[0].message.content)


def strong_solver(problem: str, solution: str, config: dict) -> dict:
    role = config["chemist_role"]

    blind_prompt = f"""You are an expert {role} solving a JEE Advanced problem.

Solve rigorously. Show full reasoning and track key quantities/species step by step.

Problem:
{problem}

Return JSON:
{{
  "attempted_solution": "full step-by-step solution with reasoning",
  "final_answer": "name/formula/value of the final product or answer",
  "formula_trace": ["state/quantity at each step"]
}}"""

    blind_resp = api_call(lambda: samba_client().chat.completions.create(
        model=STRONG_SOLVER_MODEL,
        messages=[
            {"role": "system", "content": f"You are an expert {role}. Output JSON only."},
            {"role": "user",   "content": blind_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    blind = json.loads(blind_resp.choices[0].message.content.strip())

    score_prompt = f"""You are scoring a JEE Advanced chemistry problem answer.

YOUR INDEPENDENT SOLUTION:
{blind.get('attempted_solution', '')}
Your final answer: {blind.get('final_answer', '')}

REFERENCE SOLUTION:
{solution}

Compare your independent answer to the reference.
- If your answer matches the reference: score reflects completeness/rigour of your solution (0-100).
- If your answer DISAGREES with the reference: do NOT anchor to the reference.
  Instead, determine which answer is chemically correct using first principles.
  Set reference_correct = false and explain why.

Return JSON:
{{
  "score": integer 0-100 (100 = your solution is complete and matches a correct reference),
  "reference_correct": true or false,
  "disagreement_explanation": "if reference_correct is false, explain the error in the reference",
  "reasoning": "brief explanation of the score"
}}"""

    score_resp = api_call(lambda: samba_client().chat.completions.create(
        model=STRONG_SOLVER_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry scorer. Output JSON only."},
            {"role": "user",   "content": score_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    scored = json.loads(score_resp.choices[0].message.content.strip())

    return {
        "attempted_solution":       blind.get("attempted_solution", ""),
        "blind_final_answer":       blind.get("final_answer", ""),
        "blind_formula_trace":      blind.get("formula_trace", []),
        "score":                    scored.get("score"),
        "reference_correct":        scored.get("reference_correct", True),
        "disagreement_explanation": scored.get("disagreement_explanation", ""),
        "reasoning":                scored.get("reasoning", ""),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Graph-wired JEE Advanced question generation.")
    parser.add_argument(
        "--subject", choices=["organic", "inorganic"], default="organic",
        help="Which subject's knowledge graph to use. Physical has no graph — "
             "use run_groundup.py --subject physical instead."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = get_subject_config(args.subject)

    if not SAMBANOVA_KEYS:
        print("ERROR: No SambaNova keys configured (SAMBANOVA_KEY_1..5).")
        print("  Add them to .env (uncomment the SAMBANOVA block) or use the")
        print("  OpenRouter-based entrypoint run_groundup_final.py instead.")
        return

    if config["graph_path"] is None:
        print(f"ERROR: --subject {args.subject} has no reaction graph. "
              f"Use run_groundup.py --subject {args.subject} instead.")
        return

    if not os.path.exists(config["graph_path"]):
        print(f"ERROR: {config['graph_path']} not found.")
        print(f"Run `python3 tools/build_graph.py --subject {args.subject}` first (Phase 0).")
        return

    MAX_RETRIES = 3
    OUTPUT_FILE = config["output_file"]

    coverage = load_coverage_for_subject(config)
    print(f"Coverage loaded ({args.subject}): {coverage.total_accepted()} questions accepted so far.")

    chapter = config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    topic_anchor = {
        "question_index": f"GRAPH_{config['seed_id_prefix']}",
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

    print("\n══════════════════════════════════════════════════════")
    print(f" GRAPH-WIRED GENERATION [{config['display_name']}]: {chapter} / Archetype {code}")
    print("══════════════════════════════════════════════════════\n")

    print("Sampling candidate chains from reaction graph...")
    path_options = sample_paths(coverage, config, n_options=6, depth=3)
    if not path_options:
        print("ERROR: No paths found in reaction graph. Check graph coverage for this subject.")
        return
    print(f"  {len(path_options)} candidate chains (sorted by diversity weight):")
    for p in path_options:
        print(f"    Path {p['idx']} (w={p['weight']:.4f}): {p['description']}")
    print()

    selected_path = None
    accepted = False

    for attempt in range(1, MAX_RETRIES + 2):
        print(f"── Attempt {attempt} ─────────────────────────────────")

        print("Concept reasoner (RLM)...")
        cr = concept_reasoner(blackboard, path_options, config)
        path_idx = cr.get("selected_path_idx", 0)

        if not isinstance(path_idx, int) or path_idx >= len(path_options):
            path_idx = 0

        selected_path = path_options[path_idx]
        chain_desc    = cr.get("chain_description", selected_path["description"])
        selected_txs  = edges_to_tx_format(selected_path["edges"], config)

        print(f"  Selected Path {path_idx}: {selected_path['description']}")
        print(f"  Chain: {chain_desc}")

        print("Generator...")
        gen = generator(blackboard, selected_txs, chain_desc, attempt, config)

        print("Verifier (blind pass 1 + invariant checks pass 2)...")
        ver = verifier(gen["problem"], gen["solution"], config)
        print(f"  Verdict: {ver['verdict']} | Difficulty: {ver.get('difficulty_rating','?')}")
        if ver["verdict"] == "FAIL":
            print(f"  Flaw: {ver.get('semantic_flaws','')[:120]}")
            print(f"  Fix: {ver.get('feedback_for_generator','')[:120]}")

        # Weak solver — blind (edit 1): solve WITHOUT the reference, then grade the
        # blind answer independently. Score is None if the call or grade fails (edit 2)
        # — never silently 0, which used to *pass* the weak gate for free.
        print("Weak solver (llama3.2, blind)...")
        try:
            wk_blind   = weak_solver(gen["problem"], config)
            wk_grade   = grade_answer(gen["problem"], gen["solution"], wk_blind, config)
            weak_score = wk_grade.get("score")
        except Exception as e:
            print(f"  Weak solver error: {e}")
            weak_score = None
        print(f"  Weak score: {weak_score if weak_score is not None else 'n/a (unmeasured)'}")

        print("Strong solver — blind first...")
        try:
            st           = strong_solver(gen["problem"], gen["solution"], config)
            strong_score = st.get("score")
            ref_correct  = st.get("reference_correct", True)
            strong_trace = st.get("attempted_solution", "")
        except Exception as e:
            print(f"  Strong solver error: {e}")
            st           = {}
            strong_score = None
            ref_correct  = True
            strong_trace = ""
        print(f"  Strong score: {strong_score if strong_score is not None else 'n/a (unmeasured)'}"
              f"  |  reference_correct: {ref_correct}")
        if not ref_correct:
            print(f"  !! Reference key flagged wrong: {st.get('disagreement_explanation','')[:120]}")

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
                edges     = selected_path["edges"],
                concepts  = [],
            )
            save_coverage(coverage, config)
            print(f"  Coverage updated. Total accepted: {coverage.total_accepted()}")

            record = {
                "question_id":       f"GRAPH_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                "seed_id":           f"GRAPH_{config['seed_id_prefix']}",
                "generation_mode":   "graph_wired",
                "subject":           args.subject,
                "chapter":           chapter,
                "archetype":         arch,
                "archetype_code":    code,
                "graph_path":        selected_path["nodes"],
                "graph_edges":       selected_path["edges"],
                "coverage_weight":   selected_path["weight"],
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
