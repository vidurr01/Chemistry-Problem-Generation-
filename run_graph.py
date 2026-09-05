"""
run_graph.py — Graph-wired ground-up generation.

Replaces the full concept_book TX dump in the Concept Reasoner with:
  1. get_paths() call on the reaction knowledge graph → candidate chains
  2. coverage.weight() scoring → highest-weight chain passed to the LLM
  3. coverage.on_acceptance() on success → diversity tracking persists

Everything else (generator, verifier, weak/strong solver, 3-gate, meta_tags) unchanged.
"""

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
from core.meta_tags import compute_meta_tags
from core.graph_traversal import get_paths
from core.coverage import Coverage

# ── API clients ───────────────────────────────────────────────────────────────
# Load .env if present (no external deps required)
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

# ── Model assignments — deliberately different families per role ───────────────
# Generator:     DeepSeek-V3.2                — best at creative instruction-following
# Verifier:      DeepSeek-R1                  — reasoning model; independent blind-solver
# Strong solver: Meta-Llama-3.1-405B-Instruct — different family (Meta dense 405B vs
#                                               DeepSeek MoE); genuinely 400B+ active params
# Weak solver:   llama3.2 (Ollama local)      — free, stays local
GENERATOR_MODEL     = "DeepSeek-V3.2"
VERIFIER_MODEL      = "DeepSeek-V3.2"
STRONG_SOLVER_MODEL = "DeepSeek-V3.2"
WEAK_MODEL          = "llama3.2"

# Keep STRONG_MODEL alias for meta_tags / blackboard calls that still use it
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


# ── Graph-based path sampling ─────────────────────────────────────────────────

# Hydrocarbon-chapter start nodes — nodes with enough outgoing edges for synthesis chains
HYDRO_START_NODES = [
    "alkane", "alkene", "alkyne", "diene_conjugated",
    "cycloalkane", "cycloalkene",
]

def _edge_label(edge: dict) -> str:
    reagents = edge.get("reagents", [])
    r = reagents[0] if reagents else "?"
    return f"{edge['from']} →[{r}]→ {edge['to']}"


def sample_paths(coverage: Coverage, n_options: int = 6, depth: int = 3,
                 avoid_nodes: list[str] | None = None) -> list[dict]:
    """
    Sample candidate reaction chains from the graph, scored by coverage weight.

    Returns list of dicts:
      { "idx": int, "start": str, "nodes": [str,...], "edges": [str,...],
        "weight": float, "description": str }
    Sorted by weight descending (highest = least recently used).
    """
    avoid = avoid_nodes or []
    all_paths = []

    for start in HYDRO_START_NODES:
        result = get_paths(start, depth=depth, avoid_nodes=avoid)
        for p in result.get("paths", []):
            if len(p["edges"]) < 2:
                continue  # need at least 2 steps for a good chain
            w = coverage.weight("I", "Hydrocarbons", p["edges"], [])
            all_paths.append({
                "start":  start,
                "nodes":  p["nodes"],
                "edges":  p["edges"],
                "weight": w,
            })

    if not all_paths:
        return []

    # Sort by weight desc, break ties randomly
    all_paths.sort(key=lambda x: (-x["weight"], random.random()))

    # Format descriptions and return top n_options
    options = []
    for i, p in enumerate(all_paths[:n_options]):
        # Look up edge reagents for the description
        steps = []
        with open(os.path.join(os.path.dirname(__file__), "knowledge", "reaction_graph.json"), encoding="utf-8") as f:
            graph = json.load(f)
        edge_map = {e["id"]: e for e in graph["edges"]}
        for eid in p["edges"]:
            e = edge_map.get(eid, {})
            reagents = e.get("reagents", [])
            r_str = ", ".join(reagents[:2]) if reagents else "?"
            steps.append(f"{e.get('from','?')} → {e.get('to','?')} [{r_str}]")

        p["idx"] = i
        p["description"] = " | ".join(steps)
        options.append(p)

    return options


def edges_to_tx_format(edge_ids: list[str]) -> list[dict]:
    """Convert graph edge IDs to TX-format dicts for the generator prompt."""
    with open(os.path.join(os.path.dirname(__file__), "knowledge", "reaction_graph.json"), encoding="utf-8") as f:
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
            "chapter":    e.get("chapter", "Hydrocarbons"),
        })
    return txs


# ── Pipeline functions ────────────────────────────────────────────────────────

def concept_reasoner(blackboard: Blackboard, path_options: list[dict]) -> dict:
    """
    Concept Reasoner: receives scored graph paths, picks the best one.
    Returns: { selected_path_idx, chain_description, difficulty_rationale, reasoning }
    """
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()

    # Format paths for the LLM
    path_lines = []
    for p in path_options:
        path_lines.append(
            f"Path {p['idx']} (diversity_weight={p['weight']:.4f}): {p['description']}"
        )
    paths_block = "\n".join(path_lines)

    prompt = f"""You are a reasoning model designing JEE Advanced organic chemistry problems.

TASK: Select the BEST reaction chain from the options below to build a 3-4 step
Hydrocarbon synthesis/transformation question (Archetype I: Long Reaction Chains).

The question will ask a student to identify products after sequential reagent treatments,
OR identify a missing reagent, OR give the molecular formula of an intermediate.

Chapter: Hydrocarbons
Archetype: Long Reaction Chains (I)
Target difficulty: Advanced (strong solver ≥85%, weak solver ≤60%)

Available chains (choose by Path number):
{paths_block}

Operators already tried in previous attempts: {tried}
Attempt history:
{context}

Selection criteria:
1. Prefer chains with NON-OBVIOUS selectivity — Markovnikov/anti-Markovnikov,
   stereochemical outcome (syn/anti), or reagent specificity.
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

MANDATORY INTERNAL CHECKS — do these BEFORE writing the question:
1. MOLECULAR FORMULA TRACKING: Write the molecular formula of the starting compound,
   then propagate it step by step, accounting for every atom added or removed by each
   reagent. The degree of unsaturation (DoU = (2C + 2 + N - H - X) / 2) must change
   by the correct amount at each step. Write out: Start: CₙHₘ → Step 1 (+HBr): → Step 2
   (-NaBr, +NaOH, net: -Br +OH): → etc. If the arithmetic does not balance, redesign.
2. ALL FUNCTIONAL GROUPS PRESENT: After each step, list ALL active functional groups
   in the molecule — not just the one being transformed. If the molecule carries a C=C
   AND an OH, subsequent reagents will act on whichever FG is more reactive under those
   conditions. Do not lose track of FGs that survive a step.
3. NON-CIRCULARITY: The final product must be chemically distinct from the starting
   material. If the chain routes back to the same compound, redesign.
4. STEREODESCRIPTOR VALIDITY: Any E/Z label requires two distinct groups on each
   sp2 carbon. Any R/S label requires four distinct substituents. Do not apply E/Z to
   terminal alkenes (=CH₂ ends) — they have no isomerism. Remove any descriptor that
   has no stereogenic element.
5. DIFFICULTY LEVER TEST: If you include a condition as a difficulty lever (e.g., low
   temperature for kinetic control, specific solvent for SN2 vs E2 selectivity), verify
   that CHANGING that condition would give a DIFFERENT final product. If both branches
   converge to the same answer, the condition is decorative — remove it or pick a step
   where the condition genuinely discriminates.

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
  "formula_trace": ["CₙHₘ (start)", "CₙHₘ+₁Br (after step 1)", "..."],
  "active_fgs_per_step": ["alkene (start)", "allylic bromide + alkene (after step 1)", "..."],
  "difficulty_levers": ["lever: condition X → product A; without X → product B"],
  "operators_applied": ["list of reaction names used"],
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


def verifier(problem: str, solution: str) -> dict:
    # Pass 1: solve completely blind — no candidate solution in context yet
    blind_prompt = f"""You are an expert organic chemistry verifier.

Solve the following problem completely independently. Show full step-by-step working.
Do NOT skip steps. Track the molecular formula at EVERY step.

Problem:
{problem}

Return JSON:
{{
  "independent_solution": "full step-by-step solution",
  "formula_trace": ["molecular formula after each step, e.g. C4H8 → C4H9Br → C4H10O → ..."],
  "final_answer": "IUPAC name or formula of the final product"
}}"""

    blind_resp = api_call(lambda: samba_client().chat.completions.create(
        model=VERIFIER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert organic chemist. Output JSON only."},
            {"role": "user",   "content": blind_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    blind = json.loads(blind_resp.choices[0].message.content.strip())

    # Pass 2: compare blind solution to candidate, run mechanical invariant checks
    compare_prompt = f"""You are an expert organic chemistry verifier. You have already solved
the problem independently (shown below). Now compare your solution to the candidate solution
and run the mandatory invariant checks.

Problem:
{problem}

YOUR INDEPENDENT SOLUTION:
{blind.get('independent_solution', '')}

Your formula trace: {blind.get('formula_trace', [])}
Your final answer: {blind.get('final_answer', '')}

CANDIDATE SOLUTION:
{solution}

MANDATORY CHECKS — evaluate each explicitly:

CHECK 1 — FORMULA CONSERVATION: Write out the molecular formula at every step of the
CANDIDATE solution. Verify that atoms balance (e.g., adding HBr to C4H6 gives C4H7Br,
not C4H8Br). Compute degree of unsaturation (DoU = (2C+2+N-H-X)/2) before and after each
step. Dehydration must increase DoU by 1; hydrogenation decreases by 1; substitution keeps
DoU constant. Flag any step where the arithmetic does not balance.

CHECK 2 — ALL FUNCTIONAL GROUPS TRACKED: After each step of the CANDIDATE solution, list
every active functional group in the molecule. If a C=C survives a step (e.g., only one of
two double bonds reacted), it must appear in subsequent steps. Flag if the candidate solution
silently loses a functional group between steps.

CHECK 3 — STEREODESCRIPTOR VALIDITY: For every E/Z or R/S label in the CANDIDATE, verify
a genuine stereogenic element exists. E/Z requires two distinct groups on each sp2 carbon —
terminal alkenes (=CH₂) cannot have E/Z. Flag any hallucinated descriptor.

CHECK 4 — NON-CIRCULARITY: Is the final product of the CANDIDATE chemically distinct from
the starting material? If yes, acceptable. If no (same compound), FAIL.

CHECK 5 — ANSWER AGREEMENT: Does the candidate's final answer match YOUR independent answer?
If they disagree, trust your independent solution unless you can identify a clear error in
your own reasoning.

CHECK 6 — DIFFICULTY LEVER VALIDITY: For any condition presented as a difficulty lever
(temperature, solvent, concentration), would changing it give a different final product?
If not, note it as a decorative condition (not a FAIL trigger, but note it).

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
    # Carry through the blind solution for the record
    result["independent_solution"] = blind.get("independent_solution", "")
    result["blind_formula_trace"]  = blind.get("formula_trace", [])
    result["blind_final_answer"]   = blind.get("final_answer", "")
    return result


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
    # Step 1: solve blind — do not show reference solution yet
    blind_prompt = f"""You are an expert organic chemist solving a JEE Advanced problem.

Solve rigorously. Show full mechanism and track molecular formulas step by step.

Problem:
{problem}

Return JSON:
{{
  "attempted_solution": "full step-by-step solution with mechanism",
  "final_answer": "IUPAC name or formula of the final product/answer",
  "formula_trace": ["molecular formula at each step"]
}}"""

    blind_resp = api_call(lambda: samba_client().chat.completions.create(
        model=STRONG_SOLVER_MODEL,
        messages=[
            {"role": "system", "content": "You are an expert organic chemist. Output JSON only."},
            {"role": "user",   "content": blind_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    blind = json.loads(blind_resp.choices[0].message.content.strip())

    # Step 2: compare to reference, produce a score AND flag if reference is wrong
    score_prompt = f"""You are scoring a JEE Advanced chemistry problem answer.

YOUR INDEPENDENT SOLUTION:
{blind.get('attempted_solution', '')}
Your final answer: {blind.get('final_answer', '')}

REFERENCE SOLUTION:
{solution}

Compare your independent answer to the reference.
- If your answer matches the reference: score reflects completeness/rigour of your solution (0-100).
- If your answer DISAGREES with the reference: do NOT anchor to the reference.
  Instead, determine which answer is chemically correct using formula arithmetic and mechanism.
  Set reference_correct = false and explain why.

Return JSON:
{{
  "score": integer 0-100 (100 = your solution is complete and matches a correct reference),
  "reference_correct": true or false,
  "disagreement_explanation": "if reference_correct is false, explain the chemical error in the reference",
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
        "score":                    scored.get("score", 0),
        "reference_correct":        scored.get("reference_correct", True),
        "disagreement_explanation": scored.get("disagreement_explanation", ""),
        "reasoning":                scored.get("reasoning", ""),
    }


def _strong_solver_original(problem: str, solution: str) -> dict:
    """Kept for reference — single-pass anchored scorer (old behaviour)."""
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

    resp = api_call(lambda: samba_client().chat.completions.create(
        model=GENERATOR_MODEL,
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
    if not SAMBANOVA_KEYS:
        print("ERROR: No SambaNova keys configured (SAMBANOVA_KEY_1..5).")
        print("  Add them to .env (uncomment the SAMBANOVA block) or use the")
        print("  OpenRouter-based entrypoint run_groundup.py instead.")
        return

    MAX_RETRIES = 3
    OUTPUT_FILE = "generated_questions.json"

    # Load coverage state (resumes from prior runs)
    coverage = Coverage.load()
    print(f"Coverage loaded: {coverage.total_accepted()} questions accepted so far.")

    topic_anchor = {
        "question_index": "GRAPH_HYDRO",
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

    print("\n══════════════════════════════════════════════════════")
    print(" GRAPH-WIRED GENERATION: Hydrocarbons / Archetype I")
    print("══════════════════════════════════════════════════════\n")

    # Sample paths from graph (scored by coverage)
    print("Sampling candidate chains from reaction graph...")
    path_options = sample_paths(coverage, n_options=6, depth=3)
    if not path_options:
        print("ERROR: No paths found in reaction graph. Run build_graph.py first.")
        return
    print(f"  {len(path_options)} candidate chains (sorted by diversity weight):")
    for p in path_options:
        print(f"    Path {p['idx']} (w={p['weight']:.4f}): {p['description']}")
    print()

    selected_path = None  # will be set on first accepted concept_reasoner response
    accepted = False

    for attempt in range(1, MAX_RETRIES + 2):
        print(f"── Attempt {attempt} ─────────────────────────────────")

        print("Concept reasoner (RLM)...")
        cr = concept_reasoner(blackboard, path_options)
        path_idx = cr.get("selected_path_idx", 0)

        # Guard against out-of-range idx
        if not isinstance(path_idx, int) or path_idx >= len(path_options):
            path_idx = 0

        selected_path = path_options[path_idx]
        chain_desc    = cr.get("chain_description", selected_path["description"])
        selected_txs  = edges_to_tx_format(selected_path["edges"])

        print(f"  Selected Path {path_idx}: {selected_path['description']}")
        print(f"  Chain: {chain_desc}")

        print("Generator...")
        gen = generator(blackboard, selected_txs, chain_desc, attempt)

        print("Verifier (blind pass 1 + invariant checks pass 2)...")
        ver = verifier(gen["problem"], gen["solution"])
        print(f"  Verdict: {ver['verdict']} | Difficulty: {ver.get('difficulty_rating','?')}")
        print(f"  Check1 formula: {ver.get('check1_formula','?')[:60]}")
        print(f"  Check2 FGs:     {ver.get('check2_fgs','?')[:60]}")
        print(f"  Check3 stereo:  {ver.get('check3_stereo','?')[:60]}")
        print(f"  Check4 circular:{ver.get('check4_circularity','?')[:60]}")
        print(f"  Check5 agree:   {ver.get('check5_agreement','?')[:60]}")
        if ver.get("check6_levers"):
            print(f"  Check6 levers:  {ver['check6_levers'][:80]}")
        if ver["verdict"] == "FAIL":
            print(f"  Flaw: {ver.get('semantic_flaws','')[:120]}")
            print(f"  Fix: {ver.get('feedback_for_generator','')[:120]}")

        print("Weak solver (llama3.2)...")
        try:
            wk = weak_solver(gen["problem"], gen["solution"])
            weak_score = wk.get("score", 0)
        except Exception as e:
            print(f"  Weak solver error: {e}")
            weak_score = 0
        print(f"  Weak score: {weak_score}%")

        print("Strong solver (DeepSeek-V3.2) — blind first...")
        st = strong_solver(gen["problem"], gen["solution"])
        strong_score = st.get("score", 0)
        ref_correct  = st.get("reference_correct", True)
        print(f"  Strong score: {strong_score}%  |  reference_correct: {ref_correct}")
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

        # Gate: verifier PASS + strong ≥85% + weak ≤60% + reference key not flagged wrong
        gate_verifier = ver["verdict"] == "PASS"
        gate_strong   = strong_score >= STRONG_FLOOR
        gate_weak     = weak_score   <= WEAK_CEILING
        gate_ref_ok   = ref_correct  # fail if strong solver flagged the reference key as wrong

        print(f"  Gates: verifier={'✓' if gate_verifier else '✗'}  "
              f"strong={'✓' if gate_strong else '✗'} ({strong_score}% vs ≥{STRONG_FLOOR})  "
              f"weak={'✓' if gate_weak else '✗'} ({weak_score}% vs ≤{WEAK_CEILING})  "
              f"ref_ok={'✓' if gate_ref_ok else '✗'}")

        if gate_verifier and gate_strong and gate_weak and gate_ref_ok:
            accepted = True

            meta = compute_meta_tags(
                question_text    = gen["problem"],
                archetype_code   = "I",
                solver_trace     = st.get("attempted_solution", ""),
                fragility_weight = None,
            )

            # Update coverage — this path is now used
            coverage.on_acceptance(
                archetype = "I",
                chapter   = "Hydrocarbons",
                edges     = selected_path["edges"],
                concepts  = [],
            )
            coverage.save()
            print(f"  Coverage updated. Total accepted: {coverage.total_accepted()}")

            record = {
                "question_id":       f"GRAPH_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                "seed_id":           "GRAPH_HYDRO",
                "generation_mode":   "graph_wired",
                "chapter":           "Hydrocarbons",
                "archetype":         "Long Reaction Chains",
                "archetype_code":    "I",
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
