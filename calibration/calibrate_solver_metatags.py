"""
Run strong solver on all 153 organic seeds to calibrate:
  - model_solution_length  (trace word count, per-archetype)
  - distractor_plausibility (rejected-path count, per-archetype)

Saves incremental progress to solver_traces.json so restarts are safe.
Writes calibrated stats into meta_tag_norm_stats.json when done.
"""

import json
import math
import os
import re
import time
from collections import defaultdict
from openai import OpenAI

_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
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
    ) if k
]
_key_index = 0

def get_client():
    return OpenAI(api_key=SAMBANOVA_KEYS[_key_index], base_url="https://api.sambanova.ai/v1")

MODEL = "DeepSeek-V3.2"

_HERE         = os.path.dirname(os.path.abspath(__file__))
TRACES_FILE   = os.path.join(_HERE, "solver_traces.json")
SEEDS_FILE    = os.path.join(_HERE, "..", "data", "seeds", "jeeadv_organic_seeds.json")
NORM_FILE     = os.path.join(_HERE, "meta_tag_norm_stats.json")

ARCH_CODE_MAP = {
    "Long Reaction Chains": "I",
    "Counting/Enumeration": "II",
    "Deep Mechanistic Reasoning": "III",
    "Comparative Ranking (GOC)": "IV",
    "I": "I", "II": "II", "III": "III", "IV": "IV",
}

# ── reject pattern (same as meta_tags.py) ─────────────────────────────────
_REJECT = re.compile(
    r'(ruled out|not correct|incorrect because|wrong because|'
    r'eliminated|discarded|rejected|cannot be|would not work|'
    r'not applicable here|this is not)',
    re.IGNORECASE
)


def sambanova_call(fn, retries=2, base_wait=65):
    global _key_index
    for attempt in range(retries * len(SAMBANOVA_KEYS)):
        try:
            return fn()
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                # Try rotating to next key first
                next_idx = (_key_index + 1) % len(SAMBANOVA_KEYS)
                if next_idx != _key_index:
                    _key_index = next_idx
                    print(f"    [rate limit] rotating to key {_key_index + 1}/{len(SAMBANOVA_KEYS)}")
                    time.sleep(2)
                else:
                    wait = base_wait * (2 ** (attempt // len(SAMBANOVA_KEYS)))
                    print(f"    [all keys limited] waiting {wait}s...")
                    time.sleep(wait)
            else:
                raise
    raise RuntimeError("SambaNova: max retries exceeded on all keys")


def run_solver(question_text: str, archetype: str) -> dict:
    prompt = f"""You are an expert organic chemist. Solve this problem rigorously, showing full mechanistic reasoning step by step.
Explicitly note any alternative approaches you consider and why you reject them.

Problem:
{question_text}

Archetype: {archetype}

Return JSON with:
- "attempted_solution": your full step-by-step solution (be thorough)
- "confidence": integer 0-100
- "reasoning": brief note on key decision points
"""
    resp = sambanova_call(lambda: get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    ))
    return json.loads(resp.choices[0].message.content.strip())


def compute_stats(values):
    n = len(values)
    if n == 0:
        return 0.0, 1.0
    mean = sum(values) / n
    var  = sum((x - mean)**2 for x in values) / max(n - 1, 1)
    return mean, math.sqrt(var) if var > 0 else 1.0


def main():
    with open(SEEDS_FILE, encoding="utf-8") as f:
        seeds = json.load(f)
    with open(NORM_FILE, encoding="utf-8") as f:
        norm_stats = json.load(f)

    # Load existing traces (resume support)
    if os.path.exists(TRACES_FILE):
        with open(TRACES_FILE, encoding="utf-8") as f:
            traces = json.load(f)
        print(f"Resuming — {len(traces)} traces already saved.")
    else:
        traces = {}

    total = len(seeds)
    for i, seed in enumerate(seeds):
        qid = seed["question_index"]
        if qid in traces:
            continue  # already done

        arch = seed.get("archetype", "III")
        qtxt = seed.get("question_text", "")
        if not qtxt.strip():
            print(f"[{i+1}/{total}] {qid} — SKIP (no question text)")
            traces[qid] = {"skipped": True, "trace_words": 0, "distractor_count": 0}
            continue

        print(f"[{i+1}/{total}] {qid} ({arch[:25]})", end="", flush=True)
        try:
            result = run_solver(qtxt, arch)  # uses get_client() → rotates keys
            trace  = result.get("attempted_solution", "")
            tw     = len(trace.split())
            dc     = len(_REJECT.findall(trace))
            traces[qid] = {
                "arch_code":       ARCH_CODE_MAP.get(arch, "III"),
                "trace_words":     tw,
                "distractor_count": dc,
                "confidence":      result.get("confidence", 0),
            }
            print(f"  → {tw} words, {dc} distractors")
        except Exception as e:
            print(f"  ERROR: {e}")
            traces[qid] = {"error": str(e), "trace_words": 0, "distractor_count": 0}

        # Save after every question
        with open(TRACES_FILE, "w", encoding="utf-8") as f:
            json.dump(traces, f, indent=2)

        # ~7 req/min — stays under SambaNova free-tier RPM
        time.sleep(8)

    print(f"\nAll {total} seeds processed. Computing calibration stats...")

    # ── Per-archetype stats ────────────────────────────────────────────────
    arch_trace_words    = defaultdict(list)
    arch_distractor_cnt = defaultdict(list)

    for qid, t in traces.items():
        if t.get("skipped") or t.get("error"):
            continue
        code = t.get("arch_code", "III")
        arch_trace_words[code].append(t["trace_words"])
        arch_distractor_cnt[code].append(t["distractor_count"])

    for code in ["I", "II", "III", "IV"]:
        tws = arch_trace_words.get(code, [0])
        dcs = arch_distractor_cnt.get(code, [0])
        tw_mean, tw_std = compute_stats(tws)
        dc_mean, dc_std = compute_stats(dcs)

        print(f"  Arch {code}: trace_words={tw_mean:.0f}±{tw_std:.0f}  distractors={dc_mean:.2f}±{dc_std:.2f}  (n={len(tws)})")

        pa = norm_stats["per_archetype"].setdefault(code, {})
        pa["model_solution_length"] = {
            "mean": tw_mean, "std": tw_std,
            "metric": "word_count_of_strong_solver_trace"
        }
        pa["distractor_plausibility"] = {
            "mean": dc_mean, "std": dc_std,
            "metric": "rejected_path_count_in_strong_solver_trace"
        }

    norm_stats["pending_calibration"] = []  # cleared

    with open(NORM_FILE, "w", encoding="utf-8") as f:
        json.dump(norm_stats, f, indent=2)
    print(f"Updated {NORM_FILE}")

    # ── Back-fill seeds with the two new meta-tags ─────────────────────────
    def zscore_to_15(z):
        return max(1, min(5, round(z * 1.5 + 3)))

    updated = 0
    for seed in seeds:
        qid  = seed["question_index"]
        t    = traces.get(qid, {})
        code = ARCH_CODE_MAP.get(seed.get("archetype", "III"), "III")
        pa   = norm_stats["per_archetype"].get(code, {})

        tw_mean = pa.get("model_solution_length", {}).get("mean", 0)
        tw_std  = pa.get("model_solution_length", {}).get("std", 1)
        dc_mean = pa.get("distractor_plausibility", {}).get("mean", 0)
        dc_std  = pa.get("distractor_plausibility", {}).get("std", 1)

        tw = t.get("trace_words", 0)
        dc = t.get("distractor_count", 0)

        if "meta_tags" not in seed:
            seed["meta_tags"] = {}
        seed["meta_tags"]["model_solution_length"]   = zscore_to_15((tw - tw_mean) / max(tw_std, 1))
        seed["meta_tags"]["distractor_plausibility"] = zscore_to_15((dc - dc_mean) / max(dc_std, 1))
        updated += 1

    with open(SEEDS_FILE, "w", encoding="utf-8") as f:
        json.dump(seeds, f, indent=2)
    print(f"Back-filled meta_tags on {updated} seeds → {SEEDS_FILE}")
    print("Calibration complete.")


if __name__ == "__main__":
    main()
