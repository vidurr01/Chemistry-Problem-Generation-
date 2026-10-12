"""
run_groundup_final.py — no-seed-question generation from the subject's knowledge graph.
Supports --subject {organic,inorganic,physical}.

Pipeline: pending recheck → graph traversal (core/graph_traversal.py, same for every
subject) → concept_reasoner picks one chain → generator → verifier (core/verifier.py) →
council of 3 blind solvers + grader → gate → save. Uses OpenRouter for all API roles.
Per-subject files and prompt wording come from subject_config.py.

Exit codes: 0 done (accepted, or nothing accepted this run), 2 configuration problem
(key, concept book, graph or chapter), 3 a council member failed (question parked),
4 an accepted question could not be saved (question parked).
"""

import argparse
import json
import os
import sys
import queue
import threading
from datetime import datetime, timezone
from openai import OpenAI

# Enforce UTF-8 output (Windows console default cp1252 cannot print box-drawing chars).
# line_buffering=True flushes every print on its newline, so progress stays visible
# when stdout is a pipe or file (for example a batch driver or `... > run.log`).
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except (AttributeError, ValueError):
    pass

from core.blackboard import Blackboard
from core.llm import as_bool, call_with_retry, call_json, load_env, parse_json, write_json_atomic
from core.graph_traversal import load_graph, sample_chains, chain_txs
from core.verifier import verify_problem, record_accepted_inputs, VERIFIER_MODEL  # two-tier verifier

from subject_config import (
    get_subject_config,
    load_coverage_for_subject,
    save_coverage,
    compute_meta_tags_for_subject,
)

# ── API clients ───────────────────────────────────────────────────────────────
load_env()   # repo-root .env → os.environ

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")

def openrouter_client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

# Per-role models, diversified across families so no single model both produces a claim
# and certifies it (the "no producer certifies itself" commitment). The verifier's model,
# VERIFIER_MODEL (Gemini 3 Flash), is defined in core/verifier.py and imported above.
CONCEPT_MODEL       = "deepseek/deepseek-chat-v3-0324"   # DeepSeek — selects the graph chain
GENERATOR_MODEL     = "google/gemini-2.5-flash"          # Gemini 2.5 Flash — writes question + reference solution (cheaper than the verifier)
GRADER_MODEL        = "openai/gpt-4o"                     # GPT-4o  — grades solvers' answers (≠ solvers, ≠ generator)

# ── Council of solvers ──────────────────────────────────────────────────────
# Three DIFFERENT families, all ~Mains-capable / not Advanced (non-reasoning instruct).
# The count of how many solve a question IS the difficulty signal:
#   3 or 2 solved → too easy (still within Mains reach) → refine, add reasoning complexity
#   0 or 1 solved → hard enough (above the council's Mains ceiling) → accept (if verifier PASS)
# Distinct from the generator (Gemini 2.5 Flash), verifier (Gemini 3 Flash) and grader
# (GPT-4o) → no model grades its own output. (Gemma shares Google with the generator and
# verifier, but is a different model.)
# NOTE: the "Mains-capable / not-Advanced" profile must be confirmed empirically with
# calibration/council_eval.py before trusting the count; slugs verified present on OpenRouter.
COUNCIL = [
    ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct"),   # Meta
    ("mistral-large", "mistralai/mistral-large-2407"),         # Mistral
    ("gemma-3-27b",   "google/gemma-3-27b-it"),                # Google — gemma-2-27b-it 400s on OpenRouter
]
COUNCIL_TOO_EASY_IF_SOLVED_GE = 2   # ≥2 of 3 solve ⇒ too easy
REFERENCE_WRONG_IF_FLAGGED_GE = 2   # ≥2 of 3 graders flag the answer key ⇒ key wrong, refine


EXIT_CONFIG_ERROR   = 2   # process exit code for a setup problem (key, files, chapter)
EXIT_COUNCIL_FAILED = 3   # process exit code when the run stops on a council failure
EXIT_SAVE_FAILED    = 4   # process exit code when an accepted question could not be saved


class CouncilMemberFailed(RuntimeError):
    """A council member's solve or grade call failed. Every member must be measured,
    so the run stops; the question is parked in the subject's pending file (neither
    accepted nor rejected) and rechecked first on the next run."""



def api_call(fn, retries=5, base_wait=10):
    """Retry wrapper for OpenRouter calls: backs off on any transient error (429, 5xx,
    timeouts, dropped connections); raises at once on 400/401/403/404."""
    return call_with_retry(fn, retries=retries, base_wait=base_wait, label="OpenRouter")


def ask_json(create):
    """One OpenRouter chat call that must return JSON: transient errors are retried,
    and an empty or unparseable reply is asked for again (twice) before failing."""
    return call_json(create, parse_llm_json, label="OpenRouter")


# Robust JSON from model output (fences, prose around the object): core/llm.parse_json.
parse_llm_json = parse_json


# ── Pipeline functions ──────────────────────────────────────────────────────────

def concept_reasoner(blackboard: Blackboard, path_options: list, config: dict,
                     chapter: str = None) -> dict:
    """Pick the best chain among the coverage-weighted graph chains (sample_chains)."""
    context = blackboard.context_summary()
    tried   = blackboard.operators_tried()
    chapter = chapter or config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    paths_block = "\n".join(
        f"Path {p['idx']} (diversity_weight={p['weight']:.4f}): {p['description']}"
        for p in path_options
    )

    prompt = f"""You are a reasoning model designing JEE Advanced {config['display_name']} problems.

TASK: Select the BEST chain from the options below to build a multi-step
{chapter} question (Archetype {code}: {arch}). Each chain is a path through the
subject's knowledge graph; every step is a transformation from the concept book.

The question will be created FROM SCRATCH — there is no seed question. It will ask a
student to identify the final product/answer after the steps, OR identify a missing
reagent/condition/formula, OR give a key intermediate quantity.

Available chains (choose by Path number):
{paths_block}

Operators already tried in previous attempts: {tried}
Attempt history:
{context}

Selection criteria:
1. The chain must be COHERENT: the output of step N is the input of step N+1, and every
   step can be posed with a concrete starting compound/system and concrete data.
2. NON-CIRCULARITY: the final answer must differ from the starting point.
3. Prefer chains with non-obvious selectivity, an exception, or a trap — difficulty should
   come from reasoning, not from obscurity.
4. Higher diversity_weight = less used before = prefer it for variety.
5. Avoid chains whose steps caused verifier rejection in previous attempts.

Return JSON:
{{
  "selected_path_idx": integer (Path number from the list above),
  "chain_description": "brief description of the overall chain",
  "difficulty_rationale": "why this chain makes a hard question",
  "reasoning": "brief reasoning for your choice"
}}"""

    return ask_json(lambda: openrouter_client().chat.completions.create(
        model=CONCEPT_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=1.0,
        max_tokens=1500,
    ))


def generator(blackboard: Blackboard, selected_txs: list, chain_desc: str,
              attempt_num: int, config: dict, chapter: str = None) -> dict:
    last = blackboard.last_attempt()
    chapter = chapter or config["default_chapter"]
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    if last:
        council_line = ""
        if last.get("council_solved") is not None:
            council_line = (f"Council result: {last['council_solved']}/{last.get('council_size')} "
                            f"Mains-level solvers solved it (target: at most "
                            f"{COUNCIL_TOO_EASY_IF_SOLVED_GE - 1}).\n")
        refine_block = f"""
--- REFINE IN PLACE (Attempt {attempt_num}) ---
Do NOT start over. Take the problem below and fix ONLY what was flagged.

Previous Problem:
{last['problem']}

Previous Solution:
{last['solution']}

Verifier Feedback: {last['verifier_feedback']}
{council_line}
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

HOW TO USE THESE STEPS — they form ONE chain, in order (field "step"):
- Each step is a general transformation from the concept book. Its from/to may name a
  class or an example compound; the example is an illustration, not a requirement.
- Carry the compound forward: apply step N+1 to the ACTUAL product of step N, not to the
  example compound written in step N+1's entry. ("joins_previous_compound": true means the
  entries already name the same compound; false means you must make them join.)
- If a step cannot apply to the actual product of the step before it, choose a different
  starting compound/system so that every step applies. Never silently skip a step.

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

    return ask_json(lambda: openrouter_client().chat.completions.create(
        model=GENERATOR_MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=8000,   # gemini-2.5-flash truncated verbose reference solutions at 4000, breaking the JSON
    ))


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

    return ask_json(lambda: openrouter_client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=4000,
    ))


def council_solve(problem: str, reference_solution: str, config: dict,
                  knowledge_sheet: str = None, construction: list = None) -> dict:
    """Run the 3-model council. Each member blind-solves (closed-book) and is graded
    independently; `solved` = the grader judged its final answer correct. The COUNT of
    solvers that solved is the difficulty signal.

    All three members must be measured. The first member whose solve or grade call
    fails raises CouncilMemberFailed straight away, without waiting for the others.

    Returns:
      { "members": [ {model, name, final_answer, working, grade, solved, error} ],
        "n_solved": int, "n_measured": int,
        "n_reference_flags": int  (graders that judged the generator's key wrong),
        "reference_correct": bool  (False if at least REFERENCE_WRONG_IF_FLAGGED_GE of them did) }
    """
    def solve_member(name, slug):
        """Blind-solve then grade one council member. Its two API calls stay
        sequential (the grade needs the answer); members run concurrently."""
        rec = {"name": name, "model": slug, "final_answer": None, "working": None,
               "grade": None, "solved": None, "error": None}
        try:
            blind = blind_solve(problem, config, model=slug, knowledge_sheet=knowledge_sheet)
            grade = grade_answer(problem, reference_solution, blind, config, construction=construction)
            rec["final_answer"] = blind.get("final_answer")
            rec["working"]      = blind.get("attempted_solution")
            rec["grade"]        = grade
            rec["solved"]       = as_bool(grade.get("final_answer_correct"))
        except Exception as e:
            rec["error"] = str(e)[:160]
        return rec

    # Run all council members in parallel — the work is API I/O, so threads are
    # enough. Daemon threads, so a failure can end the run without waiting for the
    # other members' calls. Results are put back in COUNCIL order for a stable log.
    done = queue.Queue()
    for i, (name, slug) in enumerate(COUNCIL):
        threading.Thread(target=lambda i=i, name=name, slug=slug: done.put((i, solve_member(name, slug))),
                         daemon=True).start()
    members = [None] * len(COUNCIL)
    for _ in COUNCIL:
        i, rec = done.get()
        if rec["error"]:
            raise CouncilMemberFailed(f"{rec['name']} ({rec['model']}): {rec['error']}")
        members[i] = rec

    n_solved = 0
    n_measured = 0
    n_reference_flags = 0
    for rec in members:
        if rec["grade"] is not None:
            n_measured += 1
            if not as_bool(rec["grade"].get("reference_correct"), default=True):
                n_reference_flags += 1
        if rec["solved"]:
            n_solved += 1
        tag = "n/a" if rec["solved"] is None else ("solved" if rec["solved"] else "failed")
        print(f"    [{rec['name']}] {tag}"
              + (f" — {rec['error']}" if rec["error"] else ""))
    # A majority, not a single grader, decides that the generator's key is wrong: one
    # grader's slip should not force a rewrite the other two disagree with.
    return {"members": members, "n_solved": n_solved, "n_measured": n_measured,
            "n_reference_flags": n_reference_flags,
            "reference_correct": n_reference_flags < REFERENCE_WRONG_IF_FLAGGED_GE}


def _score_from_rubric(g: dict) -> "int | None":
    """Derive the 0-100 score in CODE from the grader's discrete TRUE/FALSE judgments,
    so the number is deterministic and auditable instead of a hallucinated magnitude.
    reference_correct == false ⇒ the item's own key is wrong ⇒ None (quarantine, don't score)."""
    if not as_bool(g.get("reference_correct"), default=True):
        return None
    ans   = as_bool(g.get("final_answer_correct"))
    steps = as_bool(g.get("all_construction_steps_used_correctly"))
    route = as_bool(g.get("method_sound"))
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

    g = ask_json(lambda: openrouter_client().chat.completions.create(
        model=GRADER_MODEL,
        messages=[
            {"role": "system", "content": "You are a rigorous chemistry grader. Output JSON only."},
            {"role": "user",   "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1500,
    ))
    g["score"] = _score_from_rubric(g)   # deterministic number from the discrete judgments
    return g


# ── Pending queue and acceptance ─────────────────────────────────────────────

def _read_json_list(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    """Write via a temp file so an interrupted write never corrupts the file."""
    write_json_atomic(path, data, ensure_ascii=False)


def unique_id(prefix, taken):
    """f"{prefix}_<UTC timestamp to the second>", with _2, _3, ... appended if that id is
    already taken (two acceptances in the same second used to share an id, and
    results/ then silently skipped the second question)."""
    base = f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    qid, n = base, 2
    while qid in taken:
        qid, n = f"{base}_{n}", n + 1
    return qid


def _taken_question_ids(config, subject):
    """Every question id already used for this subject: output file, results/, rejected."""
    taken = {r.get("question_id") for r in _read_json_list(config["output_file"])}
    try:
        from tools.results import results_path, REJECTED_FILE
        taken |= {r.get("question_id") for r in _read_json_list(results_path(subject))}
        if os.path.exists(REJECTED_FILE):
            with open(REJECTED_FILE, encoding="utf-8") as f:
                taken |= set(json.load(f))
    except Exception:
        pass
    return taken


def park_pending(config, item):
    """Save a verifier-passed question whose council check failed, for the next run."""
    pending = _read_json_list(config["pending_file"])
    pending.append(item)
    _write_json(config["pending_file"], pending)


def save_accepted(*, config, subject, chapter, arch, code, gen, chain_desc, selected_path,
                  selected_ids, selected_txs, lineage, iters, council, ver, history,
                  coverage, log_attempt, extra=None):
    """Everything that happens on acceptance, in an order that cannot half-complete:

      1. build the record (meta-tags are labels: if they fail, the record carries
         meta_tags=None and the error instead of losing the question);
      2. write it to the output file — the ONLY step whose failure means "not
         accepted"; it is atomic and nothing else has changed yet, so on failure
         this raises and no state is left behind;
      3. then coverage, the Tier 1 dedup store, the copy into results/ and the
         attempt log. Each is repairable, so a failure there only warns.

    Returns the record."""
    n_solved = council["n_solved"]
    try:
        meta, meta_error = compute_meta_tags_for_subject(
            config, question_text=gen["problem"], archetype_code=code,
            solver_trace=next((m["working"] for m in council["members"] if m.get("working")), ""),
            fragility_weight=None,
        ), None
    except Exception as e:
        meta, meta_error = None, f"{type(e).__name__}: {e}"
        print(f"  [warn] meta-tags failed ({meta_error}); saving the question without them.")

    construction = {"graph_path": selected_path["nodes"], "graph_edges": selected_path["edges"],
                    "selected_tx_ids": selected_ids, "knowledge_used": selected_txs}
    record = {
        "question_id":       unique_id("GEN", _taken_question_ids(config, subject)),
        "seed_id":           f"GROUNDUP_{config['seed_id_prefix']}_001",
        "generation_mode":   "graph_council",
        "subject":           subject,
        "chapter":           chapter,
        "chapters":          selected_path.get("chapters", []),
        "archetype":         arch,
        "archetype_code":    code,
        "question":          gen["problem"],
        "solution":          gen["solution"],
        "operators_applied": gen.get("operators_applied", []),
        "chain_description": chain_desc,
        "graph_path":        selected_path["nodes"],
        "graph_edges":       selected_path["edges"],
        "lineage":           lineage,
        "iters_run":         iters,
        "council_n_solved":  n_solved,
        "council_size":      len(COUNCIL),
        "reference_correct": council["reference_correct"],
        "verifier_verdict":  ver["verdict"],
        "verifier_difficulty": ver.get("difficulty_rating", "?"),
        "meta_tags":         meta,
        **({"meta_tags_error": meta_error} if meta_error else {}),
        # ── Full traceability ──
        "models": {
            "concept_reasoner": CONCEPT_MODEL, "generator": GENERATOR_MODEL,
            "verifier": VERIFIER_MODEL, "grader": GRADER_MODEL,
            "council": [slug for _, slug in COUNCIL],
        },
        "construction": construction,
        "verifier_detail": {
            "verdict": ver.get("verdict"),
            "independent_solution": ver.get("independent_solution", ""),
            "flaws": ver.get("semantic_flaws", ""),
        },
        "council_detail":    council,   # per-member blind answer + grade
        "attempt_history":   history,
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        **(extra or {}),
    }
    # 2) The acceptance itself. Raises on failure, before anything else has changed.
    existing = _read_json_list(config["output_file"])
    existing.append(record)
    _write_json(config["output_file"], existing)

    # 3) Secondary state. The question is accepted now; each of these can be repaired.
    def after_save(what, fix, fn):
        try:
            fn()
        except Exception as e:
            print(f"  [warn] question saved, but updating {what} failed: {type(e).__name__}: {e}  ({fix})")

    def update_coverage():
        coverage.on_acceptance(archetype=code, chapter=chapter, edges=selected_path["edges"],
                               concepts=gen.get("operators_applied", []))
        save_coverage(coverage, config)

    def copy_to_results():
        from tools.results import promote
        promote((subject,), quiet=True)

    after_save("coverage", "its weights only steer chain choice; it catches up on the next acceptance",
               update_coverage)
    # Tier 1 dedup remembers ACCEPTED questions with a numeric answer (same signature
    # verify_problem used; the answer is the one its extraction call read).
    after_save("the Tier 1 dedup store", "this question will not be checked against later duplicates",
               lambda: record_accepted_inputs(gen["problem"], ver.get("candidate_final_answer", ""),
                                              "|".join(gen.get("operators_applied", [])),
                                              record["question_id"], archetype=arch))
    after_save("results/", "run `python tools/results.py promote`", copy_to_results)
    after_save("the attempt log", "the record in the output file is complete",
               lambda: log_attempt({**{k: record[k] for k in ("question_id", "lineage", "iters_run", "council_n_solved")},
                                    "outcome": "accepted", "question": gen["problem"], "ts": record["generated_at"],
                                    **({"pending_id": extra["pending_id"]} if extra and "pending_id" in extra else {})}))

    print(f"\n✓ ACCEPTED (lineage {lineage}, iter {iters}) — {n_solved}/{len(COUNCIL)} council solved")
    print(f"  Meta-tags: {meta}")
    print("=" * 60); print("QUESTION:\n" + gen["problem"])
    print("=" * 60); print(f"Saved to {config['output_file']}")
    return record


def recheck_pending(config, subject, coverage, log_attempt):
    """Recheck parked questions (oldest first) before generating anything new.

    A question parked because its SAVE failed already has a complete council result
    (item["council_result"]); only the save is retried, with no new API calls.

    Returns "accepted" (this run's question is done), "failed" (a council member
    failed again; the question stays parked), "save_failed" (saving failed again;
    it stays parked), or "empty" (nothing left to recheck)."""
    pending = _read_json_list(config["pending_file"])
    while pending:
        item = pending[0]
        gen = item["gen"]
        saved_council = item.get("council_result")
        print(f"\n╔═══ PENDING {item['pending_id']} ({item['chapter']}) — "
              f"{'retrying the save' if saved_council else 'rechecking council'} ═══╗")
        print(f"  {len(pending)} pending question(s) for {subject}; the verifier already passed this one.")
        try:
            council = saved_council or council_solve(gen["problem"], gen["solution"], config,
                                                     knowledge_sheet=item["knowledge_sheet"],
                                                     construction=item["selected_txs"])
        except CouncilMemberFailed as e:
            item["council_error"] = str(e)
            item["recheck_failures"] = item.get("recheck_failures", 0) + 1
            item["last_failed_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(config["pending_file"], pending)
            print(f"  ✗ council member failed again: {e}")
            print(f"  Still pending in {config['pending_file']}.")
            return "failed"

        n_solved, ref_ok = council["n_solved"], council["reference_correct"]
        print(f"  Council: {n_solved}/{len(COUNCIL)} solved | reference_correct={ref_ok}")
        if ref_ok and n_solved < COUNCIL_TOO_EASY_IF_SOLVED_GE:
            try:
                save_accepted(config=config, subject=subject, chapter=item["chapter"], arch=item["arch"],
                              code=item["code"], gen=gen, chain_desc=item["chain_desc"],
                              selected_path=item["selected_path"], selected_ids=item["selected_ids"],
                              selected_txs=item["selected_txs"], lineage=item["lineage"],
                              iters=item["iters"], council=council, ver=item["verifier"],
                              history=item["attempt_history"], coverage=coverage,
                              log_attempt=log_attempt,
                              extra={"pending_id": item["pending_id"], "rechecked_from_pending": True})
            except Exception as e:
                item["council_result"] = council          # keep it: the next retry needs no API calls
                item["save_error"] = f"{type(e).__name__}: {e}"
                item["last_failed_at"] = datetime.now(timezone.utc).isoformat()
                _write_json(config["pending_file"], pending)
                print(f"  ✗ saving failed again: {item['save_error']}")
                print(f"  Still pending in {config['pending_file']}.")
                return "save_failed"
            pending.pop(0)
            _write_json(config["pending_file"], pending)
            return "accepted"

        # A real result, just not an acceptance: drop it from the queue and move on.
        outcome = "pending_reference_wrong" if not ref_ok else "pending_too_easy"
        print(f"  {'Reference flagged wrong' if not ref_ok else 'Too easy'} → removed from pending.")
        log_attempt({"pending_id": item["pending_id"], "lineage": item["lineage"], "iter": item["iters"],
                     "outcome": outcome, "n_solved": n_solved,
                     "question": gen["problem"], "solution": gen["solution"],
                     "verifier": item["verifier"], "council": council,
                     "ts": datetime.now(timezone.utc).isoformat()})
        pending.pop(0)
        _write_json(config["pending_file"], pending)
    return "empty"


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(description="Ground-up JEE Advanced question generation.")
    parser.add_argument(
        "--subject", choices=["organic", "inorganic", "physical"], default="organic",
        help="Which subject's concept book to use."
    )
    parser.add_argument(
        "--chapter", default=None,
        help="Restrict chains to one chapter (must match a chapter on the subject's "
             "knowledge-graph edges; a wrong value prints the valid ones). Default: chains "
             "from the whole graph, following node connections across chapters."
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not OPENROUTER_KEY or "your-openrouter-key-here" in OPENROUTER_KEY:
        print("ERROR: OPENROUTER_KEY is not set to a real key.")
        print("  Add your key to .env (see .env.example) before running.")
        return EXIT_CONFIG_ERROR

    config = get_subject_config(args.subject)
    chapter = args.chapter          # None → chains from the whole graph, any chapter
    arch    = config["default_archetype"]
    code    = config["default_archetype_code"]

    if not os.path.exists(config["concept_book_path"]):
        print(f"ERROR: {config['concept_book_path']} not found.")
        print(f"Complete Phase 0 for --subject {args.subject} first (build the concept book).")
        return EXIT_CONFIG_ERROR
    if not os.path.exists(config["graph_path"]):
        print(f"ERROR: {config['graph_path']} not found.")
        print(f"Build it first:  python tools/build_graph.py --subject {args.subject}")
        return EXIT_CONFIG_ERROR

    OUTPUT_FILE = config["output_file"]

    # Full run log — EVERY attempt (accepted, failed, or discarded), for traceability.
    def log_attempt(rec):
        log_path = os.path.splitext(OUTPUT_FILE)[0] + "_attempts.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Loading concept book ({config['display_name']})...")
    with open(config["concept_book_path"], encoding="utf-8") as f:
        concept_book = json.load(f)

    book_txs = concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"]
    graph = load_graph(config["graph_path"])
    print(f"Knowledge graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges ({config['graph_path']})")

    coverage = load_coverage_for_subject(config)
    print(f"Coverage loaded ({args.subject}): {coverage.total_accepted()} questions accepted so far.")

    # Questions parked by an earlier council failure are checked before making new ones.
    status = recheck_pending(config, args.subject, coverage, log_attempt)
    if status == "accepted":
        return None
    if status == "failed":
        print("\n✗ Run stopped: a council member failed (check OpenRouter / the API key).")
        return EXIT_COUNCIL_FAILED
    if status == "save_failed":
        print(f"\n✗ Run stopped: a pending question could not be saved (check {OUTPUT_FILE}).")
        return EXIT_SAVE_FAILED

    if not sample_chains(graph, coverage, code, chapter, config["start_nodes"]):
        where = f"chapter {chapter!r}" if chapter else "the graph"
        print(f"ERROR: the knowledge graph has no {code}-archetype chains in {where}.")
        print(f"  Chapters with chains: {graph.chapters(code)}")
        return EXIT_CONFIG_ERROR

    def chapter_tx_ids(chapters):
        """Concept-book TXs behind every graph edge in these chapters (the closed-book sheet)."""
        wanted = [c.lower() for c in chapters]
        return sorted({i for e in graph.edges
                       if any(w in e.get("chapter", "").lower() for w in wanted)
                       for i in e.get("tx_ids", []) if 0 <= i < len(book_txs)})

    scope_label = chapter or "all chapters (chains follow graph connections)"
    print(f"Chains from: {scope_label}")

    topic_anchor = {
        "question_index": f"GROUNDUP_{config['seed_id_prefix']}_001",
        "question":  None,
        "answer":    None,
        "archetype": arch,
        "archetype_code": code,
        "chapter":   scope_label,
        "sub_topic": scope_label,
    }

    target_profile = {
        "structural":   {"question_length_scope": "Advanced", "model_solution_length": "Advanced"},
        "interpretive": {"conceptual_fragility": "Advanced", "number_of_exceptions": "Intermediate",
                         "semantic_obfuscation": "Advanced", "distractor_plausibility": "Advanced"}
    }

    blackboard = Blackboard(topic_anchor, arch, target_profile)

    print("\n══════════════════════════════════════════════════")
    print(f" GRAPH GENERATION [{config['display_name']}]: {scope_label} / Archetype {code}")
    print("══════════════════════════════════════════════════\n")

    # ── Control parameters for the verifier-first + council state machine ──────
    MAX_LINEAGES     = 3    # fresh question ideas to try before giving up
    MAX_ITERS        = 4    # hard cap on total generate→check iterations (anti-loop)
    VERIFIER_FAIL_MAX = 2   # consecutive verifier FAILs on a lineage → abandon it
                            # (2 ⇒ the generator gets one refine pass against verifier feedback)

    accepted = False
    iters = 0
    lineage = 0
    tried_chains = set()   # graph chains already used by an earlier lineage of this run
    council_failed = False # a council member failed: the question is parked, run ends
    save_failed    = False # an accepted question could not be saved: parked, run ends

    def pending_item(**reason):
        """Everything needed to finish the current question in a later run."""
        return {
            "pending_id": unique_id("PENDING", {x.get("pending_id")
                                                for x in _read_json_list(config["pending_file"])}),
            "subject": args.subject, "chapter": chain_label, "arch": arch, "code": code,
            "gen": gen, "chain_desc": chain_desc,
            "selected_path": {k: selected_path[k] for k in ("nodes", "edges", "chapters", "scope", "description")},
            "selected_ids": selected_ids, "selected_txs": selected_txs,
            "knowledge_sheet": knowledge_sheet, "verifier": ver,
            "lineage": lineage, "iters": iters,
            "attempt_history": blackboard.history(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
            **reason,
        }

    while not accepted and not council_failed and not save_failed \
            and lineage < MAX_LINEAGES and iters < MAX_ITERS:
        lineage += 1
        print(f"\n╔═══ LINEAGE {lineage} (new question idea) ═══╗")
        # Fresh idea for this lineage.
        try:
            print("  [1/5] graph traversal + concept-reasoner: selecting a chain...")
            path_options = [p for p in sample_chains(graph, coverage, code, chapter,
                                                     config["start_nodes"], n_options=12)
                            if tuple(p["edges"]) not in tried_chains][:6]
            if not path_options:
                print("  No untried chains left.")
                break
            for i, p in enumerate(path_options):
                p["idx"] = i
            cr = concept_reasoner(blackboard, path_options, config, chapter=scope_label)
            try:
                path_idx = int(cr.get("selected_path_idx", 0))
            except (TypeError, ValueError):
                path_idx = 0
            if not 0 <= path_idx < len(path_options):
                path_idx = 0
            selected_path = path_options[path_idx]
            tried_chains.add(tuple(selected_path["edges"]))
            chain_desc   = cr.get("chain_description") or selected_path["description"]
            selected_txs = chain_txs(graph, selected_path["edges"], book_txs)
            selected_ids = [t["tx_id"] for t in selected_txs if "tx_id" in t]
            # The question's "chapter" is wherever its chain runs: the chapters of its edges.
            chain_label = " → ".join(selected_path["chapters"]) or scope_label
            # Closed-book sheet: everything behind the chain's chapters, plus its own steps.
            base_ids = chapter_tx_ids([chapter] if chapter else selected_path["chapters"])
            sheet_ids = base_ids + [i for i in selected_ids if i not in base_ids]
            # Steps with no concept-book entry (synthetic salt -> ion links) go on the sheet too.
            knowledge_sheet = build_knowledge_sheet(
                [book_txs[i] for i in sheet_ids] + [t for t in selected_txs if "tx_id" not in t], config)
            print(f"  Selected path {path_idx}: "
                  f"{' → '.join(graph.display(n) for n in selected_path['nodes'])}  [{chain_label}]")
            print(f"  Closed-book knowledge: {len(sheet_ids)} concept-book items")
            print("  [2/5] generator: writing question + reference solution...")
            gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chain_label)
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
                print("  [3/5] verifier: Tier1 dedup + Tier2 blind judge (solving blind)...")
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
                        "construction": {"graph_path": selected_path["nodes"], "graph_edges": selected_path["edges"],
                                         "selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
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
                        verifier_result=ver,
                    )
                    print("  → refining to fix the flagged issue...")
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chain_label)
                    continue

                # 2) verifier PASS → COUNCIL of solvers decides difficulty.
                verifier_fails = 0
                print(f"  [4/5] council: {len(COUNCIL)} models solving blind, closed-book "
                      f"({', '.join(name for name, _ in COUNCIL)})...")
                try:
                    council = council_solve(gen["problem"], gen["solution"], config,
                                            knowledge_sheet=knowledge_sheet, construction=selected_txs)
                except CouncilMemberFailed as e:
                    # Not the question's fault and not a difficulty result: park the question
                    # (neither accepted nor rejected) for a recheck next run, and stop.
                    print(f"  ✗ council member failed: {e}")
                    park_pending(config, pending_item(council_error=str(e)))
                    print(f"  Question saved for a recheck next run: {config['pending_file']}")
                    print("  Stopping this run.")
                    council_failed = True
                    break
                n_solved = council["n_solved"]
                ref_ok   = council["reference_correct"]
                print(f"  Council: {n_solved}/{len(COUNCIL)} solved | reference_correct={ref_ok}")

                blackboard.record_attempt(
                    problem=gen["problem"], solution=gen["solution"],
                    operators_used=gen.get("operators_applied", []),
                    verifier_result=ver,
                    council_solved=n_solved, council_size=len(COUNCIL),
                )

                if not ref_ok:
                    # A majority of graders judged the generator's own key wrong → refine.
                    print(f"  ⚠ reference flagged wrong by {council['n_reference_flags']}/{len(COUNCIL)} "
                          f"graders → refining.")
                    log_attempt({
                        "lineage": lineage, "iter": iters, "outcome": "reference_wrong",
                        "question": gen["problem"], "solution": gen["solution"],
                        "construction": {"graph_path": selected_path["nodes"], "graph_edges": selected_path["edges"],
                                         "selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                        "verifier": ver, "council": council,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    # Tell the generator WHY: the graders' own reasons go into the feedback
                    # its refine prompt reads (the verifier's feedback here is empty — it passed).
                    reasons = [str(m["grade"].get("justification", "")).strip()[:400]
                               for m in council["members"]
                               if m.get("grade") and not as_bool(m["grade"].get("reference_correct"), default=True)]
                    blackboard.attempts[-1]["verifier_feedback"] = (
                        f"ANSWER KEY JUDGED WRONG by {council['n_reference_flags']}/{len(COUNCIL)} graders. "
                        + " | ".join(r for r in reasons if r)
                        + " Re-derive the final answer from the steps and correct the reference solution."
                    )
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chain_label)
                    continue

                if n_solved >= COUNCIL_TOO_EASY_IF_SOLVED_GE:
                    # Too easy — within the Mains-level council's reach. Refine for
                    # REASONING complexity (a decision/trap/constraint), NOT more steps.
                    print(f"  Too easy ({n_solved}/{len(COUNCIL)} solved) → refine, add reasoning complexity.")
                    log_attempt({
                        "lineage": lineage, "iter": iters, "outcome": "too_easy",
                        "n_solved": n_solved,
                        "question": gen["problem"], "solution": gen["solution"],
                        "construction": {"graph_path": selected_path["nodes"], "graph_edges": selected_path["edges"],
                                         "selected_tx_ids": selected_ids, "knowledge_used": selected_txs},
                        "verifier": ver, "council": council,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    })
                    # Inject a difficulty directive via the blackboard feedback channel.
                    blackboard.attempts[-1]["verifier_feedback"] = (
                        f"TOO EASY: {n_solved}/{len(COUNCIL)} Mains-level models solved it. Increase "
                        f"REASONING difficulty — add a chemoselectivity decision, an exception/trap where "
                        f"the naive rule fails, or a constraint to resolve. Do NOT just add more steps or jargon."
                    )
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chain_label)
                    continue

                # 3) verifier PASS + all 3 council members measured + ≤1 solved → ACCEPT.
                #    `accepted` is set only once the record is really saved. A save failure
                #    is not the question's fault: park it (with its council result) instead
                #    of regenerating, and stop.
                print("  [5/5] accepted: computing difficulty meta-tags and saving...")
                try:
                    save_accepted(config=config, subject=args.subject, chapter=chain_label, arch=arch, code=code,
                                  gen=gen, chain_desc=chain_desc, selected_path=selected_path,
                                  selected_ids=selected_ids, selected_txs=selected_txs,
                                  lineage=lineage, iters=iters, council=council, ver=ver,
                                  history=blackboard.history(), coverage=coverage, log_attempt=log_attempt)
                except Exception as e:
                    err = f"{type(e).__name__}: {e}"
                    print(f"  ✗ could not save the accepted question: {err}")
                    try:
                        park_pending(config, pending_item(save_error=err, council_result=council))
                        print(f"  Question parked for a save retry next run: {config['pending_file']}")
                    except Exception as e2:
                        print(f"  ✗ could not park it either ({type(e2).__name__}: {e2}). The question was:")
                        print(gen["problem"])
                    save_failed = True
                    break
                accepted = True
                break

            except Exception as e:
                print(f"  iter {iters} error: {e}")
                # treat as a soft failure; refine and continue within cap
                try:
                    gen = generator(blackboard, selected_txs, chain_desc, iters + 1, config, chapter=chain_label)
                except Exception:
                    break

    if council_failed:
        print("\n✗ Run stopped: a council member failed (check OpenRouter / the API key).")
        return EXIT_COUNCIL_FAILED
    if save_failed:
        print(f"\n✗ Run stopped: the accepted question could not be saved (check {OUTPUT_FILE}).")
        return EXIT_SAVE_FAILED
    if not accepted:
        print(f"\n✗ No question accepted ({lineage} lineages, {iters} iters). "
              f"Full attempt log: {os.path.splitext(OUTPUT_FILE)[0] + '_attempts.jsonl'}")


if __name__ == "__main__":
    sys.exit(main())
