"""
calibrate_solver_metatags.py — run a strong solver on every JEE Advanced seed question of
one subject to calibrate two meta-tags, per archetype:
  - model_solution_length   (word count of the solver's worked solution)
  - distractor_plausibility (alternative paths it explicitly rejects)

    python calibration/calibrate_solver_metatags.py --subject organic     # 153 seeds
    python calibration/calibrate_solver_metatags.py --subject inorganic   # 143 seeds
    python calibration/calibrate_solver_metatags.py --subject physical    # 178 seeds

Writes the stats into the subject's norm-stats file and back-fills the two tags on the
seeds. Progress is saved after every question, so a restart resumes; seeds whose call
failed are retried. Stats are written only for archetypes with MIN_SAMPLES successful
traces — the rest stay pending, never filled with placeholder numbers — and a run stops,
writing nothing, after MAX_CONSECUTIVE_ERRORS failures in a row.

Needs SAMBANOVA_KEY_1..4 in .env (rotated on rate limits).
"""

import argparse
import math
import os
import re
import sys
import time
from collections import defaultdict

from openai import OpenAI

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core.llm import (call_json, is_rate_limit, is_transient, load_env,  # noqa: E402
                      parse_json, write_json_atomic)

load_env()

SAMBANOVA_KEYS = [k for k in (os.environ.get(f"SAMBANOVA_KEY_{i}", "") for i in range(1, 5)) if k]
_key_index = 0

MODEL = "DeepSeek-V3.2"
MIN_SAMPLES = 2             # successful traces an archetype needs before it gets stats
MAX_CONSECUTIVE_ERRORS = 5  # stop the run (writing nothing) when the API keeps failing

_SEEDS = os.path.join(_ROOT, "data", "seeds")

# Per-subject settings — the only thing that differs between subjects.
SUBJECTS = {
    "organic": {
        "seeds": os.path.join(_SEEDS, "jeeadv_organic_seeds.json"),
        "traces": os.path.join(_HERE, "solver_traces.json"),
        "norm": os.path.join(_HERE, "meta_tag_norm_stats.json"),
        "codes": ["I", "II", "III", "IV"],
        "default_code": "III",
        "names": {
            "Long Reaction Chains": "I",
            "Counting/Enumeration": "II",
            "Deep Mechanistic Reasoning": "III",
            "Comparative Ranking (GOC)": "IV",
        },
        "reasoning": "mechanistic reasoning",
    },
    "inorganic": {
        "seeds": os.path.join(_SEEDS, "jeeadv_inorganic_seeds.json"),
        "traces": os.path.join(_HERE, "solver_traces_inorganic.json"),
        "norm": os.path.join(_SEEDS, "meta_tag_norm_stats_inorganic.json"),
        "codes": ["I", "II", "III", "IV", "V", "VI"],
        "default_code": "III",   # largest bucket (Structure/Bonding/Electronic Config), 50/143
        "names": {
            "Reaction & Transformation Chains": "I",
            "Property / Trend Ordering & Exception Reasoning": "II",
            "Structure, Bonding & Electronic Configuration Reasoning": "III",
            "Numerical / Computational": "IV",
            "Qualitative Identification (Observation-Based Deduction)": "V",
            "Applied / Real-World Conceptual Reasoning": "VI",
        },
        "reasoning": "structural/periodic-trend/reaction reasoning",
    },
    "physical": {
        "seeds": os.path.join(_SEEDS, "jeeadv_physical_seeds.json"),
        "traces": os.path.join(_HERE, "solver_traces_physical.json"),
        "norm": os.path.join(_SEEDS, "meta_tag_norm_stats_physical.json"),
        "codes": ["I", "II", "III", "IV", "V", "VI"],
        "default_code": "I",     # largest bucket (Multi-Formulae), 80/178
        "names": {
            "Multi-Formulae": "I",
            "Multi-Chapter Integration": "II",
            "Graphical Interpretation": "III",
            "Property/Trend Ordering": "IV",
            "Conceptual/Postulate-Based": "V",
            "Applied/Real-World": "VI",
        },
        "reasoning": "quantitative/derivational reasoning (formulae, units, graphical trends as needed)",
    },
}

# ── reject pattern (same as core/meta_tags.py) ─────────────────────────────────
_REJECT = re.compile(
    r'(ruled out|not correct|incorrect because|wrong because|'
    r'eliminated|discarded|rejected|cannot be|would not work|'
    r'not applicable here|this is not)',
    re.IGNORECASE
)


def get_client():
    return OpenAI(api_key=SAMBANOVA_KEYS[_key_index], base_url="https://api.sambanova.ai/v1")


def sambanova_call(fn, retries=2, base_wait=65):
    """Rotate keys on rate limits; back off on other transient errors."""
    global _key_index
    for attempt in range(retries * len(SAMBANOVA_KEYS)):
        try:
            return fn()
        except Exception as e:
            if is_rate_limit(e):
                next_idx = (_key_index + 1) % len(SAMBANOVA_KEYS)
                if next_idx != _key_index:
                    _key_index = next_idx
                    print(f"    [rate limit] rotating to key {_key_index + 1}/{len(SAMBANOVA_KEYS)}")
                    time.sleep(2)
                else:
                    wait = base_wait * (2 ** (attempt // len(SAMBANOVA_KEYS)))
                    print(f"    [all keys limited] waiting {wait}s...")
                    time.sleep(wait)
            elif is_transient(e):
                wait = 10 * (2 ** min(attempt, 4))
                print(f"    [{type(e).__name__}] retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("SambaNova: max retries exceeded on all keys")


def run_solver(question_text: str, archetype: str, subject: str) -> dict:
    prompt = f"""You are an expert {subject} chemist. Solve this problem rigorously, showing full
{SUBJECTS[subject]['reasoning']} step by step.
Explicitly note any alternative approaches you consider and why you reject them.

Problem:
{question_text}

Archetype: {archetype}

Return JSON with:
- "attempted_solution": your full step-by-step solution (be thorough)
- "confidence": integer 0-100
- "reasoning": brief note on key decision points
"""
    return call_json(lambda: sambanova_call(lambda: get_client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )), parse_json, retries=1, label="SambaNova")


def compute_stats(values):
    n = len(values)
    if n == 0:
        return 0.0, 1.0
    mean = sum(values) / n
    var  = sum((x - mean)**2 for x in values) / max(n - 1, 1)
    return mean, math.sqrt(var) if var > 0 else 1.0


def resolve_arch_code(seed, cfg):
    """The seed's archetype_code if valid, else its archetype name mapped, else the default."""
    code = seed.get("archetype_code")
    if code in cfg["codes"]:
        return code
    name = seed.get("archetype", "")
    if name in cfg["codes"]:
        return name
    return cfg["names"].get(name, cfg["default_code"])


def _load(path, default=None):
    import json
    if default is not None and not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def calibrate(subject: str) -> int:
    cfg = SUBJECTS[subject]
    if not SAMBANOVA_KEYS:
        print("ERROR: no SambaNova keys (SAMBANOVA_KEY_1..4) in .env; nothing to calibrate with.")
        return 1
    seeds = _load(cfg["seeds"])
    norm_stats = _load(cfg["norm"])
    traces = _load(cfg["traces"], {})
    if traces:
        print(f"Resuming — {len(traces)} traces already saved.")

    total = len(seeds)
    consecutive_errors = 0
    for i, seed in enumerate(seeds):
        qid = seed["question_index"]
        if qid in traces and not traces[qid].get("error"):
            continue  # finished (or skipped) earlier; errored seeds are retried

        arch_code = resolve_arch_code(seed, cfg)
        arch_name = seed.get("archetype", arch_code)
        qtxt = seed.get("question_text", "")
        if not qtxt.strip():
            print(f"[{i+1}/{total}] {qid} — SKIP (no question text)")
            traces[qid] = {"skipped": True, "trace_words": 0, "distractor_count": 0}
            continue

        print(f"[{i+1}/{total}] {qid} ({arch_name[:25]})", end="", flush=True)
        try:
            result = run_solver(qtxt, arch_name, subject)
            trace  = result.get("attempted_solution", "")
            if not isinstance(trace, str):
                trace = str(trace)
            tw     = len(trace.split())
            dc     = len(_REJECT.findall(trace))
            traces[qid] = {
                "arch_code":        arch_code,
                "trace_words":      tw,
                "distractor_count": dc,
                "confidence":       result.get("confidence", 0),
            }
            print(f"  → {tw} words, {dc} distractors")
        except Exception as e:
            print(f"  ERROR: {e}")
            traces[qid] = {"error": str(e), "trace_words": 0, "distractor_count": 0}
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                write_json_atomic(cfg["traces"], traces)
                print(f"\nERROR: {consecutive_errors} calls in a row failed; stopping without writing "
                      f"stats. Fix the API problem and rerun — errored seeds are retried.")
                return 1
        else:
            consecutive_errors = 0

        write_json_atomic(cfg["traces"], traces)   # save after every question
        time.sleep(8)   # ~7 req/min — stays under SambaNova free-tier RPM

    errored = [q for q, t in traces.items() if t.get("error")]
    print(f"\nProcessed {total} seeds ({len(errored)} still errored). Computing calibration stats...")

    arch_trace_words    = defaultdict(list)
    arch_distractor_cnt = defaultdict(list)
    for qid, t in traces.items():
        if t.get("skipped") or t.get("error"):
            continue
        code = t.get("arch_code", cfg["default_code"])
        arch_trace_words[code].append(t["trace_words"])
        arch_distractor_cnt[code].append(t["distractor_count"])

    # An archetype gets stats only from real traces. Fewer than MIN_SAMPLES successful
    # traces → its entry is left exactly as it was (still pending), never filled with
    # placeholder numbers.
    calibrated, missing = [], []
    for code in cfg["codes"]:
        tws = arch_trace_words.get(code, [])
        dcs = arch_distractor_cnt.get(code, [])
        n = len(tws)
        if n < MIN_SAMPLES:
            missing.append(code)
            print(f"  Arch {code}: {n} successful trace(s) — NOT calibrated, left pending")
            continue
        tw_mean, tw_std = compute_stats(tws)
        dc_mean, dc_std = compute_stats(dcs)
        flag = "  [LOW SAMPLE — verify manually]" if n < 5 else ""
        print(f"  Arch {code}: trace_words={tw_mean:.0f}±{tw_std:.0f}  distractors={dc_mean:.2f}±{dc_std:.2f}  (n={n}){flag}")

        pa = norm_stats["per_archetype"].setdefault(code, {})
        pa["model_solution_length"] = {
            "mean": tw_mean, "std": tw_std, "n": n,
            "metric": "word_count_of_strong_solver_trace"
        }
        pa["distractor_plausibility"] = {
            "mean": dc_mean, "std": dc_std, "n": n,
            "metric": "rejected_path_count_in_strong_solver_trace"
        }
        # number_of_exceptions is NOT computed here, so its status is left alone.
        calibrated.append(code)

    if not calibrated:
        print(f"ERROR: no archetype has {MIN_SAMPLES}+ successful traces; nothing written. "
              f"Fix the API errors and rerun — errored seeds are retried.")
        return 1

    norm_stats["pending_calibration"] = [f"{c}.{m}" for c in missing
                                         for m in ("model_solution_length", "distractor_plausibility")]
    write_json_atomic(cfg["norm"], norm_stats)
    print(f"Updated {cfg['norm']} (calibrated: {calibrated}; still pending: {missing or 'none'})")

    # ── Back-fill seeds with the two meta-tags, from successful traces only ─────
    def zscore_to_15(z):
        return max(1, min(5, round(z * 1.5 + 3)))

    updated = 0
    for seed in seeds:
        t    = traces.get(seed["question_index"], {})
        code = resolve_arch_code(seed, cfg)
        mt   = seed.setdefault("meta_tags", {})
        if not t or t.get("error") or t.get("skipped") or code not in calibrated:
            # no real measurement: remove any value an earlier run wrote from placeholders
            mt.pop("model_solution_length", None)
            mt.pop("distractor_plausibility", None)
            continue
        pa = norm_stats["per_archetype"][code]
        tw_mean, tw_std = pa["model_solution_length"]["mean"], pa["model_solution_length"]["std"]
        dc_mean, dc_std = pa["distractor_plausibility"]["mean"], pa["distractor_plausibility"]["std"]
        mt["model_solution_length"]   = zscore_to_15((t["trace_words"] - tw_mean) / max(tw_std, 1))
        mt["distractor_plausibility"] = zscore_to_15((t["distractor_count"] - dc_mean) / max(dc_std, 1))
        updated += 1

    write_json_atomic(cfg["seeds"], seeds)
    print(f"Back-filled meta_tags on {updated} seeds → {cfg['seeds']}")
    if errored:
        print(f"Calibration INCOMPLETE: {len(errored)} errored seeds, archetypes pending: {missing}. "
              f"Rerun to retry them.")
    elif missing:
        print(f"Calibration complete. Archetypes with fewer than {MIN_SAMPLES} seed questions "
              f"cannot be calibrated and stay pending: {missing}")
    else:
        print("Calibration complete.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Calibrate solver-based meta-tags for one subject.")
    ap.add_argument("--subject", choices=list(SUBJECTS), required=True)
    return calibrate(ap.parse_args().subject)


if __name__ == "__main__":
    sys.exit(main())
