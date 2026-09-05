"""
Calibrate STRONG_SCORE_FLOOR and WEAK_SCORE_CEILING by running real JEE Advanced
organic chemistry questions through both solvers.

Strong solver : DeepSeek-V3.2 via SambaNova
Weak solver   : llama3.2 via Ollama (local)

Output: calibration_results.json + printed statistics (mean, median, std)
"""

import json, glob, time, random, math, statistics, os, re

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
OUT_PATH = os.path.join(_HERE, "calibration_results.json")

ARCHETYPE_MAP = {
    "long_reaction_chains":     "Long Reaction Chains (I)",
    "counting_enumeration":     "Counting / Enumeration (II)",
    "deep_mechanistic_reasoning": "Deep Mechanistic Reasoning (III)",
    "comparative_ranking":      "Comparative Ranking / GOC (IV)",
}

SAMPLES_PER_ARCH = 3   # 3 × 4 archetypes = 12 questions total

random.seed(42)

# ── SambaNova retry wrapper ────────────────────────────────────────────────────
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

# ── Load JEE Advanced organic questions ───────────────────────────────────────
def load_organic_questions():
    qs = []
    for fpath in sorted(glob.glob(os.path.join(JEE_DIR, "*.json"))):
        try:
            with open(fpath, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        for q in data.get("questions", []):
            topic = (q.get("topic", "") + q.get("sub_topic", "")).lower()
            if "organ" not in topic and "carbon" not in topic:
                continue
            if not q.get("solution_summary") or not q.get("question_text"):
                continue
            arch = q.get("archetype_analysis", {}).get("primary_archetype", "")
            if arch not in ARCHETYPE_MAP:
                continue
            q["_arch_key"] = arch
            qs.append(q)
    return qs

def stratified_sample(qs):
    by_arch = {k: [] for k in ARCHETYPE_MAP}
    for q in qs:
        by_arch[q["_arch_key"]].append(q)
    sample = []
    for arch, pool in by_arch.items():
        picked = random.sample(pool, min(SAMPLES_PER_ARCH, len(pool)))
        sample.extend(picked)
    return sample

# ── Solver prompts ─────────────────────────────────────────────────────────────
def strong_prompt(q):
    return f"""You are an expert organic chemist solving a JEE Advanced question.
Work through the problem step by step using full mechanistic reasoning before committing
to a final answer.

Question:
{q['question_text']}

Topic: {q.get('topic','')} — {q.get('sub_topic','')}
Question type: {q.get('question_type','')}

After solving, compare your answer to the reference below and score yourself 0-100:
  100 = completely correct product, mechanism, and reasoning
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

# ── Run one question through both solvers ─────────────────────────────────────
def run_question(q, idx, total):
    qid   = q.get("id", f"Q{idx}")
    arch  = ARCHETYPE_MAP[q["_arch_key"]]
    stem  = q["question_text"][:80].replace("\n", " ")
    print(f"\n[{idx}/{total}] {qid} | {arch}")
    print(f"  Q: {stem}...")

    # Strong solver
    print("  → Strong solver (DeepSeek-V3.2 / SambaNova)...")
    try:
        resp = sambanova_call(lambda: strong_client.chat.completions.create(
            model=STRONG_MODEL,
            messages=[
                {"role": "system",  "content": "You are an expert chemist. Output JSON only."},
                {"role": "user",    "content": strong_prompt(q)},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        ))
        strong_raw = json.loads(resp.choices[0].message.content.strip())
        strong_score = int(strong_raw.get("score", 0))
        strong_sol   = strong_raw.get("attempted_solution", "")[:200]
    except Exception as e:
        print(f"    ERROR: {e}")
        strong_score, strong_sol = None, str(e)

    print(f"  Strong score: {strong_score}")

    # Weak solver — no response_format; llama3.2 ignores schema, parse manually
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
        # Try JSON parse first; fallback to regex extraction of score
        try:
            weak_raw   = json.loads(raw_text)
            weak_score = int(weak_raw.get("score", 0))
            weak_sol   = str(weak_raw.get("attempted_solution", ""))[:200]
        except Exception:
            # Extract first integer after "score" in raw text
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
        "topic":        q.get("topic", ""),
        "question":     q["question_text"][:300],
        "correct":      q["correct_answer"],
        "solution":     q["solution_summary"][:300],
        "strong_score": strong_score,
        "weak_score":   weak_score,
        "strong_sol":   strong_sol,
        "weak_sol":     weak_sol,
    }

# ── Statistics ─────────────────────────────────────────────────────────────────
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
    return {"n": len(valid), "mean": round(mean_v,1), "median": round(median_v,1),
            "std": round(std_v,1), "min": min(valid), "max": max(valid)}

def recommend(strong_stats, weak_stats):
    """
    Floor  = strong mean - 1 std  (catch genuinely broken problems)
    Ceiling = weak mean + 0.5 std  (reject only clearly-too-easy problems)
    Both rounded to nearest 5.
    """
    if not strong_stats or not weak_stats:
        return None, None
    floor   = strong_stats["mean"] - strong_stats["std"]
    ceiling = weak_stats["mean"]   + 0.5 * weak_stats["std"]
    floor_r   = round(floor   / 5) * 5
    ceiling_r = round(ceiling / 5) * 5
    return int(floor_r), int(ceiling_r)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 65)
    print("  JEEGen Threshold Calibration")
    print("  Using: JEE Advanced organic chemistry questions")
    print("  Strong: DeepSeek-V3.2 (SambaNova)")
    print("  Weak  : llama3.2 (Ollama)")
    print("=" * 65)

    print("\nLoading JEE Advanced organic questions...")
    all_qs = load_organic_questions()
    print(f"Found {len(all_qs)} eligible questions across all archetypes.")

    sample = stratified_sample(all_qs)
    print(f"Stratified sample: {len(sample)} questions ({SAMPLES_PER_ARCH} per archetype)\n")

    results = []
    for idx, q in enumerate(sample, 1):
        r = run_question(q, idx, len(sample))
        results.append(r)
        time.sleep(2)   # light spacing between calls

    # Save raw results
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n\nRaw results saved → {OUT_PATH}")

    # ── Statistics ──────────────────────────────────────────────────────────
    strong_scores = [r["strong_score"] for r in results]
    weak_scores   = [r["weak_score"]   for r in results]

    print("\n" + "=" * 65)
    print("  CALIBRATION RESULTS")
    print("=" * 65)

    ss = stats(strong_scores, "STRONG SOLVER (DeepSeek-V3.2)")
    ws = stats(weak_scores,   "WEAK SOLVER   (llama3.2)")

    # Per-archetype breakdown
    print("\n  Per-archetype breakdown:")
    arch_keys = list(ARCHETYPE_MAP.values())
    for arch in arch_keys:
        sub = [r for r in results if r["archetype"] == arch]
        sv = [r["strong_score"] for r in sub if r["strong_score"] is not None]
        wv = [r["weak_score"]   for r in sub if r["weak_score"]   is not None]
        if sv and wv:
            print(f"    {arch[:38]:38s}  strong={statistics.mean(sv):.0f}  weak={statistics.mean(wv):.0f}")

    # Recommendation
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
