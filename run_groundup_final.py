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
from core.verifier import verify_problem  # two-tier: deterministic dedup + blind-solve LLM judge

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
GRADER_MODEL        = "openai/gpt-4o"                     # GPT-4o  — grades solvers' answers (≠ solvers, ≠ generator)

# ── Council of solvers ──────────────────────────────────────────────────────
# Three DIFFERENT families, all ~Mains-capable / not Advanced (non-reasoning instruct).
# The count of how many solve a question IS the difficulty signal:
#   3 or 2 solved → too easy (still within Mains reach) → refine, add reasoning complexity
#   0 or 1 solved → hard enough (above the council's Mains ceiling) → accept (if verifier PASS)
# Distinct from generator (DeepSeek) and verifier (Qwen2.5) → no model grades its own output.
# NOTE: the "Mains-capable / not-Advanced" profile must be confirmed empirically with
# calibration/council_eval.py before trusting the count; slugs verified present on OpenRouter.
COUNCIL = [
    ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct"),   # Meta
    ("mistral-large", "mistralai/mistral-large-2407"),         # Mistral
    ("gemma-2-27b",   "google/gemma-2-27b-it"),                # Google
]
COUNCIL_TOO_EASY_IF_SOLVED_GE = 2   # ≥2 of 3 solve ⇒ too easy

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

def concept_reasoner(blackboard: Blackboard, txs: list, config: dict, chapter: str = None) -> dict:
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()
    chapter = chapter or config["default_chapter"]
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
2. NON-CIRCULARITY (hard rule): the final product MUST be a different compound class than
   the starting material. Do NOT pick a step that undoes a previous one — e.g. elimination
   then hydrogenation back to the same alkane, or oxidation then reduction to the original.
   Trace the class through every step and confirm start-class ≠ end-class before returning.
3. FUNCTIONAL-GROUP PROGRESSION: each step should install or transform a group that carries
   forward; avoid a step whose product has no valid next step in the list (dead ends waste
   the chain).
4. Prefer steps with non-obvious selectivity or exception behaviour (this is where difficulty
   comes from — chemoselectivity, regio-/stereochemistry — NOT from obscurity).
5. Avoid steps tried in previous attempts if they caused verifier rejection.
6. If weak score was too high (problem too easy), pick steps with more subtle reasoning.
7. If strong score was too low (problem broken), simplify — ensure each step is unambiguous.

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
              attempt_num: int, config: dict, chapter: str = None) -> dict:
    last = blackboard.last_attempt()
    chapter = chapter or config["default_chapter"]
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


def build_knowledge_sheet(txs: list, config: dict) -> str:
    """Format the chapter's allowed knowledge from the concept book into a closed-book
    sheet. Each subject stores its rules the same way (valid_transformations): organic
    reactions, inorganic structure/reactivity facts, physical formulas (e.g. the reagents
    field carries formulas like 'mole = mass/GAM'). The solver may use ONLY these."""
    lines = []
    for i, t in enumerate(txs):
        frm = t.get("from", ""); to = t.get("to", "")
        rg = ", ".join(t.get("reagents", [])) if t.get("reagents") else ""
        cond = (t.get("conditions", "") or "").strip().replace("\n", " ")[:160]
        entry = f"[{i}] {frm} → {to}"
        if rg:   entry += f"  | reagents/formula: {rg}"
        if cond: entry += f"  | {cond}"
        lines.append(entry)
    return "\n".join(lines)


def blind_solve(problem: str, config: dict, model: str, knowledge_sheet: str = None,
                temperature: float = 0.0) -> dict:
    """Solve the problem WITHOUT seeing the reference solution, on the given `model`.

    The solver works cold and only reports its own answer; scoring is done separately
    by grade_answer(). If knowledge_sheet is given, the solver runs CLOSED-BOOK: it may
    use ONLY the reactions/formulas/facts on the sheet, not its pretrained knowledge —
    testing application/reasoning rather than memorised recall.
    """
    role = config["chemist_role"]
    system = f"You are an expert {role}. Output JSON only."
    instruction = (f"You are an expert {role}. Solve this {config['display_name']} "
                   f"problem rigorously, showing full step-by-step reasoning.")

    closed_book = ""
    if knowledge_sheet:
        closed_book = f"""
CLOSED-BOOK CONSTRAINT — you may use ONLY the reactions/formulas/facts listed below.
Do NOT rely on any reaction, formula, or fact from your own memory that is not on this
list. Cite the [index] of each item you use. If solving requires knowledge that is not
on the list, state exactly what is missing and stop — do not guess from memory.

ALLOWED KNOWLEDGE (concept book, this chapter):
{knowledge_sheet}
"""

    prompt = f"""{instruction}

You are NOT given an answer key. Work the answer out yourself.
{closed_book}
Problem:
{problem}

Return JSON:
{{
  "attempted_solution": "your full step-by-step working",
  "final_answer": "your final answer only (product name / value / reagent)"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=4000,
    ))
    return parse_llm_json(resp.choices[0].message.content)


def council_solve(problem: str, reference_solution: str, config: dict,
                  knowledge_sheet: str = None, construction: list = None) -> dict:
    """Run the 3-model council. Each member blind-solves (closed-book) and is graded
    independently; `solved` = the grader judged its final answer correct. The COUNT of
    solvers that solved is the difficulty signal.

    Returns:
      { "members": [ {model, name, final_answer, working, grade, solved, error} ],
        "n_solved": int, "n_measured": int,
        "reference_correct": bool  (False if any member's grade flags the key wrong) }
    """
    members = []
    n_solved = 0
    n_measured = 0
    reference_correct = True
    for name, slug in COUNCIL:
        rec = {"name": name, "model": slug, "final_answer": None, "working": None,
               "grade": None, "solved": None, "error": None}
        try:
            blind = blind_solve(problem, config, model=slug, knowledge_sheet=knowledge_sheet)
            grade = grade_answer(problem, reference_solution, blind, config, construction=construction)
            rec["final_answer"] = blind.get("final_answer")
            rec["working"]      = blind.get("attempted_solution")
            rec["grade"]        = grade
            rec["solved"]       = bool(grade.get("final_answer_correct"))
            if not grade.get("reference_correct", True):
                reference_correct = False
            n_measured += 1
            if rec["solved"]:
                n_solved += 1
        except Exception as e:
            rec["error"] = str(e)[:160]
        members.append(rec)
        tag = "n/a" if rec["solved"] is None else ("solved" if rec["solved"] else "failed")
        print(f"    [{name}] {tag}"
              + (f" — {rec['error']}" if rec["error"] else ""))
    return {"members": members, "n_solved": n_solved, "n_measured": n_measured,
            "reference_correct": reference_correct}


def _score_from_rubric(g: dict) -> "int | None":
    """Derive the 0-100 score in CODE from the grader's discrete TRUE/FALSE judgments,
    so the number is deterministic and auditable instead of a hallucinated magnitude.
    reference_correct == false ⇒ the item's own key is wrong ⇒ None (quarantine, don't score)."""
    if not g.get("reference_correct", True):
        return None
    ans   = bool(g.get("final_answer_correct"))
    steps = bool(g.get("all_construction_steps_used_correctly"))
    route = bool(g.get("method_sound"))
    if ans and steps:
        return 100          # right answer AND used the intended construction chemistry correctly
    if ans:
        return 85           # right answer, but a construction step was slipped/skipped
    if route:
        return 50           # right route, wrong answer (arithmetic/regio/stereo slip)
    return 0                # wrong route and wrong answer


def grade_answer(problem: str, reference_solution: str, candidate: dict, config: dict,
                 construction: list = None) -> dict:
    """Combined rubric + construction-comparison grader.

    GROUND TRUTH = the construction knowledge (the concept-book transformations/formulas
    the question was actually BUILT from), passed in as `construction`. The grader does
    NOT invent a magnitude; it makes discrete TRUE/FALSE calls (which LLMs do reliably),
    and _score_from_rubric() computes the number in code. It also audits, per construction
    step, whether the solver used that exact chemistry — giving a `took_shortcut` signal
    (the solver reached the answer without the intended steps ⇒ the item is easier than built)."""
    role = config["chemist_role"]

    construction = construction or []
    constr_block = json.dumps(
        [{"id": i, "from": t.get("from"), "to": t.get("to"),
          "reagents": t.get("reagents", []), "conditions": (t.get("conditions", "") or "")[:160]}
         for i, t in enumerate(construction)],
        indent=2, ensure_ascii=False,
    )

    prompt = f"""You are an expert {role} auditing a solver who worked WITHOUT any answer key.
Do NOT invent a numeric score. Make only the discrete TRUE/FALSE judgments below, and for
each cite the exact step in the solver's working that justifies it.

GROUND TRUTH — the transformations/formulas this problem was CONSTRUCTED from. Correct
solving should use these, applied correctly:
{constr_block}

Reference solution (secondary check; the construction steps above are primary ground truth):
{reference_solution}

Problem:
{problem}

Solver's final answer:
{candidate.get('final_answer', '')}

Solver's full working:
{candidate.get('attempted_solution', '')}

For EACH construction step, decide whether the solver used it and used it correctly.
Then make the overall judgments.

Return JSON:
{{
  "per_step": [{{"id": 0, "used": true/false, "used_correctly": true/false, "note": "..."}}, ...],
  "coverage": 0.0-1.0,                              // fraction of construction steps used
  "took_shortcut": true/false,                      // reached the answer WITHOUT the intended steps
  "final_answer_correct": true/false,               // chemically equivalent to the reference answer
  "method_sound": true/false,                       // overall route valid even if a number is off
  "all_construction_steps_used_correctly": true/false,
  "reference_correct": true/false,                  // false ONLY if the solver is right and the KEY is wrong
  "justification": "cite the exact step(s) behind each judgment"
}}"""

    resp = api_call(lambda: openrouter_client().chat.completions.create(
        model=GRADER_MODEL,
        messages=[
            {"role": "system", "content": "You are a rigorous chemistry grader. Output JSON only."},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1500,
    ))
    g = parse_llm_json(resp.choices[0].message.content)
    g["score"] = _score_from_rubric(g)   # deterministic number from the discrete judgments
    return g


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

    # Closed-book solving: solvers may use ONLY this chapter's concept-book knowledge,
    # not their pretrained memory. Same sheet given to strong and weak so the comparison
    # is apples-to-apples.
    knowledge_sheet = build_knowledge_sheet(txs, config)
    print(f"Closed-book knowledge sheet: {len(txs)} allowed items injected into solvers")

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

    # ── Control parameters for the verifier-first + council state machine ──────
    MAX_LINEAGES     = 4    # fresh question ideas to try before giving up
    MAX_ITERS        = 8    # hard cap on total generate→check iterations (anti-loop)
    VERIFIER_FAIL_MAX = 2   # consecutive verifier FAILs on a lineage → abandon it

    # Full run log — EVERY attempt (accepted, failed, or discarded), for traceability.
    run_log = []
    def log_attempt(rec):
        run_log.append(rec)
        log_path = OUTPUT_FILE.replace(".json", "_attempts.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    accepted = False
    iters = 0
    lineage = 0

    while not accepted and lineage < MAX_LINEAGES and iters < MAX_ITERS:
        lineage += 1
        print(f"\n╔═══ LINEAGE {lineage} (new question idea) ═══╗")
        # Fresh idea for this lineage.
        try:
            cr = concept_reasoner(blackboard, txs, config, chapter=chapter)
            selected_ids = cr.get("selected_tx_ids", [])
            chain_desc   = cr.get("chain_description", "")
            try:
                selected_ids = [int(i) for i in selected_ids]
            except (TypeError, ValueError):
                selected_ids = []
            selected_txs = [txs[i] for i in selected_ids if 0 <= i < len(txs)]
            print(f"  Selected {len(selected_txs)} steps: {[t['from']+' → '+t['to'] for t in selected_txs]}")
            gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chapter)
        except Exception as e:
            print(f"  lineage {lineage} setup error: {e}")
            continue

        verifier_fails = 0

        # Inner loop: refine within this lineage until accept / abandon / cap.
        while iters < MAX_ITERS:
            iters += 1
            print(f"── iter {iters} (lineage {lineage}) ─────────────────────")

            try:
                # 1) VERIFIER FIRST — validity gate.
                print("Verifier (Tier1 dedup + Tier2 blind judge)...")
                ver = verify_problem(
                    gen["problem"], gen["solution"], arch, args.subject,
                    formula_signature="|".join(gen.get("operators_applied", [])),
                )
                print(f"  Verdict: {ver['verdict']} | Difficulty: {ver.get('difficulty_rating','?')}")

                if ver["verdict"] == "FAIL":
                    verifier_fails += 1
                    print(f"  Flaw: {ver.get('semantic_flaws','')[:160]}")
                    print(f"  Fix: {ver.get('feedback_for_generator','')[:160]}")
                    log_attempt({
                        "lineage": lineage, "iter": iters, "outcome": "verifier_fail",
                        "verifier_fails": verifier_fails,
                        "question": gen["problem"], "solution": gen["solution"],
                        "construction": {"selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                        "verifier": ver, "council": None,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    if verifier_fails >= VERIFIER_FAIL_MAX:
                        # Verifier bounced this lineage twice → abandon, make a NEW question.
                        print(f"  ✗ verifier failed {verifier_fails}× → abandoning lineage, new question.")
                        break
                    # Otherwise flag once and refine, telling the generator exactly where.
                    blackboard.record_attempt(
                        problem=gen["problem"], solution=gen["solution"],
                        operators_used=gen.get("operators_applied", []),
                        verifier_result=ver, weak_score=None, strong_score=None,
                    )
                    print("  → refining to fix the flagged issue...")
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chapter)
                    continue

                # 2) verifier PASS → COUNCIL of solvers decides difficulty.
                verifier_fails = 0
                print(f"Council solve ({len(COUNCIL)} models, blind, closed-book)...")
                council = council_solve(gen["problem"], gen["solution"], config,
                                        knowledge_sheet=knowledge_sheet, construction=selected_txs)
                n_solved = council["n_solved"]
                ref_ok   = council["reference_correct"]
                print(f"  Council: {n_solved}/{len(COUNCIL)} solved | reference_correct={ref_ok}")

                blackboard.record_attempt(
                    problem=gen["problem"], solution=gen["solution"],
                    operators_used=gen.get("operators_applied", []),
                    verifier_result=ver,
                    weak_score=None, strong_score=n_solved,   # store council count in strong slot
                )

                if not ref_ok:
                    # A council member judged the generator's own key wrong → refine.
                    print("  ⚠ reference flagged wrong by a solver → refining.")
                    log_attempt({
                        "lineage": lineage, "iter": iters, "outcome": "reference_wrong",
                        "question": gen["problem"], "solution": gen["solution"],
                        "construction": {"selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                        "verifier": ver, "council": council,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chapter)
                    continue

                if n_solved >= COUNCIL_TOO_EASY_IF_SOLVED_GE:
                    # Too easy — within the Mains-level council's reach. Refine for
                    # REASONING complexity (a decision/trap/constraint), NOT more steps.
                    print(f"  Too easy ({n_solved}/{len(COUNCIL)} solved) → refine, add reasoning complexity.")
                    log_attempt({
                        "lineage": lineage, "iter": iters, "outcome": "too_easy",
                        "n_solved": n_solved,
                        "question": gen["problem"], "solution": gen["solution"],
                        "construction": {"selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                        "verifier": ver, "council": council,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    # Inject a difficulty directive via the blackboard feedback channel.
                    blackboard.attempts[-1]["verifier_feedback"] = (
                        f"TOO EASY: {n_solved}/{len(COUNCIL)} Mains-level models solved it. Increase "
                        f"REASONING difficulty — add a chemoselectivity decision, an exception/trap where "
                        f"the naive rule fails, or a constraint to resolve. Do NOT just add more steps or jargon."
                    )
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chapter)
                    continue

                # 3) verifier PASS + ≤1 of 3 solved → ACCEPT.
                accepted = True
                meta = compute_meta_tags_for_subject(
                    config, question_text=gen["problem"], archetype_code=code,
                    solver_trace=next((m["working"] for m in council["members"] if m.get("working")), ""),
                    fragility_weight=None,
                )
                coverage.on_acceptance(archetype=code, chapter=chapter, edges=[],
                                       concepts=gen.get("operators_applied", []))
                save_coverage(coverage, config)

                record = {
                    "question_id":       f"GEN_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
                    "seed_id":           f"GROUNDUP_{config['seed_id_prefix']}_001",
                    "generation_mode":   "ground_up_council",
                    "subject":           args.subject,
                    "chapter":           chapter,
                    "archetype":         arch,
                    "archetype_code":    code,
                    "question":          gen["problem"],
                    "solution":          gen["solution"],
                    "operators_applied": gen.get("operators_applied", []),
                    "chain_description": chain_desc,
                    "lineage":           lineage,
                    "iters_run":         iters,
                    "council_n_solved":  n_solved,
                    "council_size":      len(COUNCIL),
                    "reference_correct": ref_ok,
                    "verifier_verdict":  ver["verdict"],
                    "verifier_difficulty": ver.get("difficulty_rating", "?"),
                    "meta_tags":         meta,
                    # ── Full traceability (#1) ──
                    "models": {
                        "concept_reasoner": CONCEPT_MODEL, "generator": GENERATOR_MODEL,
                        "verifier": VERIFIER_MODEL, "grader": GRADER_MODEL,
                        "council": [slug for _, slug in COUNCIL],
                    },
                    "construction": {"selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                    "verifier_detail": {
                        "verdict": ver.get("verdict"),
                        "independent_solution": ver.get("independent_solution", ""),
                        "flaws": ver.get("semantic_flaws", ""),
                    },
                    "council_detail": council,   # per-member blind answer + grade
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
                log_attempt({**{k: record[k] for k in ("question_id","lineage","iters_run","council_n_solved")},
                             "outcome": "accepted", "question": gen["problem"],
                             "ts": record["generated_at"]})

                print(f"\n✓ ACCEPTED (lineage {lineage}, iter {iters}) — {n_solved}/{len(COUNCIL)} council solved")
                print(f"  Meta-tags: {meta}")
                print("="*60); print("QUESTION:\n"+gen["problem"])
                print("="*60); print(f"Saved to {OUTPUT_FILE}")
                break

            except Exception as e:
                print(f"  iter {iters} error: {e}")
                # treat as a soft failure; refine and continue within cap
                try:
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chapter)
                except Exception:
                    break

    if not accepted:
        print(f"\n✗ No question accepted ({lineage} lineages, {iters} iters). "
              f"Full attempt log: {OUTPUT_FILE.replace('.json','_attempts.jsonl')}")


if __name__ == "__main__":
    main()
