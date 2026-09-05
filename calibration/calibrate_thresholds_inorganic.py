"""
Calibrate STRONG_SCORE_FLOOR and WEAK_SCORE_CEILING by running real JEE Advanced
INORGANIC chemistry questions through both solvers.

Subject-specific changes vs. organic's calibrate_thresholds.py:
  - 6 archetypes (I-VI) instead of 4 (I-IV)
  - topic filter matches "Inorganic Chemistry" instead of organic/carbon
  - archetype resolution tries, in order: explicit archetype_code field,
    archetype_analysis.primary_archetype slug, full archetype name match
    (raw jee_advanced schema for non-organic subjects isn't finalized yet,
    so all three paths are supported defensively)

Meta-tag definitions, scoring protocol, and z-score math are UNCHANGED from
organic — only the archetype set and subject filter differ.

Strong solver : DeepSeek-V3.2 via SambaNova
Weak solver   : llama3.2 via Ollama (local)

Output: calibration_results_inorganic.json + printed statistics
"""

import json, glob, time, random, re, statistics, os

from openai import OpenAI

_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

SAMBANOVA_KEY = os.environ.get("SAMBANOVA_KEY_1", "")
STRONG_MODEL  = "DeepSeek-V3.2"
WEAK_MODEL    = "llama3.2"

strong_client = OpenAI(api_key=SAMBANOVA_KEY, base_url="https://api.sambanova.ai/v1")
weak_client   = OpenAI(api_key="ollama",       base_url="http://localhost:11434/v1")

_HERE    = os.path.dirname(os.path.abspath(__file__))
JEE_DIR  = os.path.join(_HERE, "..", "data", "jee_advanced")
OUT_PATH = os.path.join(_HERE, "calibration_results_inorganic.json")

SUBJECT_TOPIC_MATCH = "inorgan"   # matches "Inorganic Chemistry" topic field

# ── 6 inorganic archetypes (labels match what the questions actually do) ──────
# Raw jee_advanced data re-uses the organic 4-taxonomy (long_reaction_chains,
# counting_enumeration, deep_mechanistic_reasoning, comparative_ranking). The
# fallback below maps those onto the nearest inorganic bucket so a re-run can
# still stratify a sample.
INORGANIC_ARCHETYPES = [
    ("I",   "Reaction Chemistry & Transformation Analysis"),
    ("II",  "Property & Trend Ordering / Exception Reasoning"),
    ("III", "Mechanism, Redox & Structural Reasoning"),
    ("IV",  "Enumeration, Nomenclature & Numerical Deduction"),
    ("V",   "Qualitative Identification (Observation-Based Deduction)"),
    ("VI",  "Applied / Real-World Conceptual Reasoning"),
]

RAW_ARCHETYPE_FALLBACK = {
    "long_reaction_chains":       "I",
    "comparative_ranking":        "II",
    "deep_mechanistic_reasoning": "III",
    "counting_enumeration":       "IV",
}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return re.sub(r"_+", "_", s)


ARCHETYPE_MAP = {code: f"{name} ({code})" for code, name in INORGANIC_ARCHETYPES}
# accepts: direct code, slugged full name, or exact full name as the "key"
CODE_LOOKUP = {}
for code, name in INORGANIC_ARCHETYPES:
    CODE_LOOKUP[code] = code
    CODE_LOOKUP[_slug(name)] = code
    CODE_LOOKUP[name] = code

SAMPLES_PER_ARCH = 3   # 3 x 6 archetypes = 18 questions total

random.seed(42)


def sambanova_call(fn, retries=5, base_wait=15):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                wait = base_wait * (2 ** attempt)
                print(f"    [rate limit] retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("SambaNova: max retries exceeded")


def _resolve_archetype_code(q):
    """Defensive resolution across possible raw-data schemas."""
    if q.get("archetype_code") in CODE_LOOKUP.values():
        return q["archetype_code"]
    aa = q.get("archetype_analysis", {}) or {}
    primary = aa.get("primary_archetype", "")
    if primary in CODE_LOOKUP:
        return CODE_LOOKUP[primary]
    if _slug(primary) in CODE_LOOKUP:
        return CODE_LOOKUP[_slug(primary)]
    arch_field = q.get("archetype", "")
    if arch_field in CODE_LOOKUP:
        return CODE_LOOKUP[arch_field]
    if _slug(arch_field) in CODE_LOOKUP:
        return CODE_LOOKUP[_slug(arch_field)]
    if primary in RAW_ARCHETYPE_FALLBACK:
        return RAW_ARCHETYPE_FALLBACK[primary]
    return None


def load_inorganic_questions():
    qs = []
    for fpath in sorted(glob.glob(os.path.join(JEE_DIR, "*.json"))):
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for q in data.get("questions", []):
            topic = (q.get("topic", "") + q.get("sub_topic", "")).lower()
            if SUBJECT_TOPIC_MATCH not in topic:
                continue
            if not q.get("solution_summary") or not q.get("question_text"):
                continue
            code = _resolve_archetype_code(q)
            if code is None:
                continue
            q["_arch_code"] = code
            qs.append(q)
    return qs


def stratified_sample(qs):
    by_arch = {code: [] for code, _ in INORGANIC_ARCHETYPES}
    for q in qs:
        by_arch[q["_arch_code"]].append(q)
    sample = []
    for code, pool in by_arch.items():
        picked = random.sample(pool, min(SAMPLES_PER_ARCH, len(pool)))
        sample.extend(picked)
        if len(pool) < SAMPLES_PER_ARCH:
            print(f"  [warn] archetype {code} ({ARCHETYPE_MAP[code]}): only {len(pool)} eligible questions found")
    return sample


def strong_prompt(q):
    return f"""You are an expert inorganic chemist solving a JEE Advanced question.
Work through the problem step by step using rigorous structural/periodic/reaction reasoning
before committing to a final answer.

Question:
{q['question_text']}

Topic: {q.get('topic','')} — {q.get('sub_topic','')}
Question type: {q.get('question_type','')}

After solving, compare your answer to the reference below and score yourself 0-100:
  100 = completely correct answer and reasoning
  0   = completely wrong

Reference answer: {q['correct_answer']}
Reference solution: {q['solution_summary']}

Return JSON:
  "attempted_solution": string — your full step-by-step answer
  "score": integer 0-100
  "reasoning": string — where you were right or wrong"""


def weak_prompt(q):
    return f"""You are a chemistry undergraduate student attempting a JEE Advanced question.

Question:
{q['question_text']}

Topic: {q.get('topic','')} — {q.get('sub_topic','')}

Step 1 — Write your answer.
Step 2 — Compare to the reference below and give yourself a score from 0 to 100.
  (100 = perfectly correct, 0 = completely wrong)

Reference answer: {q['correct_answer']}
Reference solution: {q['solution_summary']}

Respond with ONLY the following JSON, no other text:
{{
  "attempted_solution": "<your answer>",
  "score": <integer 0-100>,
  "reasoning": "<why you gave that score>"
}}"""


def run_question(q, idx, total):
    qid  = q.get("id", f"Q{idx}")
    arch = ARCHETYPE_MAP[q["_arch_code"]]
    stem = q["question_text"][:80].replace("\n", " ")
    print(f"\n[{idx}/{total}] {qid} | {arch}")
    print(f"  Q: {stem}...")

    print("  → Strong solver (DeepSeek-V3.2 / SambaNova)...")
    try:
        resp = sambanova_call(lambda: strong_client.chat.completions.create(
            model=STRONG_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert inorganic chemist. Output JSON only."},
                {"role": "user",   "content": strong_prompt(q)},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        ))
        strong_raw   = json.loads(resp.choices[0].message.content.strip())
        strong_score = int(strong_raw.get("score", 0))
        strong_sol   = strong_raw.get("attempted_solution", "")[:200]
    except Exception as e:
        print(f"    ERROR: {e}")
        strong_score, strong_sol = None, str(e)

    print(f"  Strong score: {strong_score}")

    print("  → Weak solver (llama3.2 / Ollama)...")
    try:
        resp = weak_client.chat.completions.create(
            model=WEAK_MODEL,
            messages=[
                {"role": "system", "content": "You are a chemistry undergraduate. Respond with valid JSON only."},
                {"role": "user",   "content": weak_prompt(q)},
            ],
            temperature=0.7,
        )
        raw_text = resp.choices[0].message.content.strip()
        try:
            weak_raw   = json.loads(raw_text)
            weak_score = int(weak_raw.get("score", 0))
            weak_sol   = str(weak_raw.get("attempted_solution", ""))[:200]
        except Exception:
            m = re.search(r'"score"\s*:\s*(\d+)', raw_text)
            weak_score = int(m.group(1)) if m else None
            weak_sol   = raw_text[:200]
    except Exception as e:
        print(f"    ERROR: {e}")
        weak_score, weak_sol = None, str(e)

    print(f"  Weak score:   {weak_score}")

    return {
        "id":           qid,
        "archetype":    arch,
        "archetype_code": q["_arch_code"],
        "topic":        q.get("topic", ""),
        "question":     q["question_text"][:300],
        "correct":      q["correct_answer"],
        "solution":     q["solution_summary"][:300],
        "strong_score": strong_score,
        "weak_score":   weak_score,
        "strong_sol":   strong_sol,
        "weak_sol":     weak_sol,
    }


def stats(scores, label):
    valid = [s for s in scores if s is not None]
    if len(valid) < 2:
        print(f"  {label}: not enough data ({len(valid)} points)")
        return {}
    mean_v   = statistics.mean(valid)
    median_v = statistics.median(valid)
    std_v    = statistics.stdev(valid)
    print(f"\n  {label} (n={len(valid)}):")
    print(f"    Mean   : {mean_v:.1f}")
    print(f"    Median : {median_v:.1f}")
    print(f"    Std dev: {std_v:.1f}")
    print(f"    Min    : {min(valid):.0f}   Max: {max(valid):.0f}")
    print(f"    Raw    : {sorted(valid)}")
    return {"n": len(valid), "mean": round(mean_v, 1), "median": round(median_v, 1),
             "std": round(std_v, 1), "min": min(valid), "max": max(valid)}


def recommend(strong_stats, weak_stats):
    """
    Floor   = strong mean - 1 std  (catch genuinely broken problems)
    Ceiling = weak mean + 0.5 std  (reject only clearly-too-easy problems)
    Both rounded to nearest 5. Same formula as organic.
    """
    if not strong_stats or not weak_stats:
        return None, None
    floor   = strong_stats["mean"] - strong_stats["std"]
    ceiling = weak_stats["mean"]   + 0.5 * weak_stats["std"]
    return int(round(floor / 5) * 5), int(round(ceiling / 5) * 5)


def main():
    print("=" * 65)
    print("  JEEGen Threshold Calibration — INORGANIC CHEMISTRY")
    print("  Archetypes: 6 (I-VI)")
    print("  Strong: DeepSeek-V3.2 (SambaNova)")
    print("  Weak  : llama3.2 (Ollama)")
    print("=" * 65)

    print("\nLoading JEE Advanced inorganic questions...")
    all_qs = load_inorganic_questions()
    print(f"Found {len(all_qs)} eligible questions across all archetypes.")

    sample = stratified_sample(all_qs)
    print(f"Stratified sample: {len(sample)} questions (target {SAMPLES_PER_ARCH} per archetype)\n")

    results = []
    for idx, q in enumerate(sample, 1):
        r = run_question(q, idx, len(sample))
        results.append(r)
        time.sleep(2)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nRaw results saved → {OUT_PATH}")

    strong_scores = [r["strong_score"] for r in results]
    weak_scores   = [r["weak_score"]   for r in results]

    print("\n" + "=" * 65)
    print("  CALIBRATION RESULTS")
    print("=" * 65)

    ss = stats(strong_scores, "STRONG SOLVER (DeepSeek-V3.2)")
    ws = stats(weak_scores,   "WEAK SOLVER   (llama3.2)")

    print("\n  Per-archetype breakdown:")
    for code, name in INORGANIC_ARCHETYPES:
        sub = [r for r in results if r["archetype_code"] == code]
        sv = [r["strong_score"] for r in sub if r["strong_score"] is not None]
        wv = [r["weak_score"]   for r in sub if r["weak_score"]   is not None]
        if sv and wv:
            print(f"    {code} {name[:36]:36s}  strong={statistics.mean(sv):.0f}  weak={statistics.mean(wv):.0f}")
        else:
            print(f"    {code} {name[:36]:36s}  insufficient data (n={len(sub)})")

    floor, ceiling = recommend(ss, ws)
    if floor and ceiling:
        print(f"\n  ── Recommended thresholds ──────────────────────────────")
        print(f"    STRONG_SCORE_FLOOR  = {floor}%")
        print(f"    WEAK_SCORE_CEILING  = {ceiling}%")
        print(f"    (floor  = strong mean − 1σ, rounded to nearest 5)")
        print(f"    (ceiling = weak mean + 0.5σ, rounded to nearest 5)")

    print("\n" + "=" * 65)
    return {"strong": ss, "weak": ws, "floor": floor, "ceiling": ceiling}


if __name__ == "__main__":
    main()
