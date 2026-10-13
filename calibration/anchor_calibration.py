"""
anchor_calibration.py — measure real-question solve rates for a strong and a weak model.

Purpose (the "anchor" the difficulty claim rests on): run real JEE Advanced questions
through two models BLIND (no answer key shown), grade each model's answer against the
official key, and report solve-rate distributions. This tells you where real Advanced
questions sit for each model — the baseline your generated items get compared against.

Design choices (kept deliberately simple):
  * Strong model : --strong, default openai/gpt-oss-120b      (OpenRouter, reasoning-grade)
  * Weak model   : --weak,   default meta-llama/llama-3.2-3b-instruct (OpenRouter, 3B floor)
  * Subset       : the last 5 years (2021-2025), NUMERIC-answer questions only.
      MCQ/MSQ option text is NOT present in the dataset, so a blind solver cannot map
      its answer to a letter — numeric (NAT/Numerical) questions need no options and
      grade deterministically, so they are the honest subset to measure on.
  * Grading      : deterministic numeric match (tolerance below). No LLM grader, so the
      score is reproducible and carries no model bias.

Blind == the model never sees correct_answer or solution_summary. That is the whole point:
a model that is shown the answer cannot tell you whether the question was solvable.

Output: calibration/anchor_calibration_results_<strong model>.json, checkpointed after every
question. Each strong model gets its own file, so runs never overwrite each other:
    python calibration/anchor_calibration.py
    python calibration/anchor_calibration.py --strong qwen/qwen3-235b-a22b-2507
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from openai import OpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)
from core.llm import call_json, load_env, parse_json, write_json_atomic  # noqa: E402

load_env()   # repo-root .env → os.environ

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    print("ERROR: no OPENROUTER_KEY in .env"); sys.exit(1)

# Strong solver = a reasoning-grade model via OpenRouter. (SambaNova's gpt-oss-120b was
# capacity-blocked with persistent 429s, and 405B is not served on any available
# provider.) openai/gpt-oss-120b is reasoning-tuned, so a FAILURE means the question is
# genuinely hard, not that the solver isn't expert enough — which is what makes it a
# trustworthy expert-ceiling probe.
STRONG_MODEL = "openai/gpt-oss-120b"               # default; override with --strong
# Weak solver via OpenRouter, NOT local Ollama: Ollama's llama3.2 returns an empty JSON
# object ("{}") under response_format=json_object, so every answer came back None — a
# broken solver, not a genuine failure. The hosted llama-3.2-3b actually attempts it.
WEAK_MODEL   = "meta-llama/llama-3.2-3b-instruct"  # OpenRouter (3B); override with --weak

JEE_DIR    = os.path.join(_ROOT, "data", "jee_advanced")
YEARS      = range(2021, 2026)
OUT_PATH   = None   # set in main() from the strong model


COUNCIL_MODE = False   # --council: solve exactly as a council member does in generation


def results_path(strong_model: str) -> str:
    """calibration/anchor_calibration_results_<model>.json, e.g. ..._gpt_oss_120b.json
    (with --council: ..._<model>_council.json)"""
    tag = re.sub(r"[^a-z0-9]+", "_", strong_model.split("/")[-1].lower()).strip("_")
    return os.path.join(_HERE, f"anchor_calibration_results_{tag}{'_council' if COUNCIL_MODE else ''}.json")

def openrouter_client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

# ── data ──────────────────────────────────────────────────────────────────────
_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

def to_float(x):
    """Extract the last numeric token from a string/number, or None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace(",", "").replace("×10^", "e").replace("x10^", "e").replace("^", "e")
    m = _NUM_RE.findall(s)
    if not m:
        return None
    try:
        return float(m[-1])
    except ValueError:
        return None

def is_numeric_answer(ca) -> bool:
    return re.fullmatch(r"-?\d+(\.\d+)?", str(ca).strip()) is not None if ca is not None else False

# A text-only solver cannot answer a question whose content lives in a figure/scheme/plot
# not present in the text. Including them would count as failures for BOTH models and
# spuriously deflate the absolute solve rate, so we drop them (per the no-OCR policy).
_FIG_REF = re.compile(
    r"(\[(reaction scheme|image|figure|structure|diagram|graph|plot|table)[^\]]*\]|"
    r"shown below|given below|shown in the figure|in the (figure|diagram|graph|plot|scheme)|"
    r"the plot of|the following structure|structure shown|as shown in|following reaction scheme)",
    re.IGNORECASE,
)

def load_numeric_questions():
    out = []
    for y in YEARS:
        fp = os.path.join(JEE_DIR, f"{y}.json")
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        for q in data.get("questions", []):
            ca = q.get("correct_answer")
            if ca is None or "[Image" in str(ca):
                continue
            if not is_numeric_answer(ca):
                continue
            if not q.get("question_text"):
                continue
            if q.get("exclude_reason"):
                continue   # cleaned out: missing text, missing figure or disputed key
            if _FIG_REF.search(q["question_text"]):
                continue   # figure/scheme-dependent — not solvable text-only
            topic = (q.get("topic", "") or "?").split("-")[0].split("Chemistry")[0].strip() or "?"
            out.append({
                "id": q.get("id", f"{y}_{q.get('question_number','?')}"),
                "year": y,
                "topic": topic,
                "question_text": q["question_text"],
                "correct_answer": float(str(ca).strip()),
                "question_type": q.get("question_type", ""),
            })
    return out


# ── blind solve ─────────────────────────────────────────────────────────────
def blind_prompt(q, expert: bool) -> str:
    who = ("an expert chemist" if expert else "a chemistry undergraduate student")
    return f"""You are {who} solving a JEE Advanced chemistry problem with a NUMERICAL answer.

You are NOT given the answer key. Work it out yourself, showing your reasoning, then
state the final numeric value.

Question:
{q['question_text']}

Return JSON:
{{
  "reasoning": "your step-by-step working",
  "final_answer": <the final numeric value only, as a number>
}}"""

def solve_strong(q):
    if COUNCIL_MODE:
        # The generation council's own call: same prompt, token cap (16k), reasoning
        # effort and temperature, so thinking models are not cut off and candidates are
        # compared exactly as they would be used. Cost goes to models.SPEND.
        from core.pipeline import stages
        return stages._solve(STRONG_MODEL, q["question_text"] +
                             "\n\n(The answer is a single numerical value.)")
    return call_json(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[{"role": "system", "content": "You are an expert chemist. Output JSON only."},
                  {"role": "user", "content": blind_prompt(q, True)}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=2500,   # reasoning model needs room before the JSON
    ), parse_json, retries=6, base_wait=8, label="OpenRouter")

def solve_weak(q):
    return call_json(lambda: openrouter_client().chat.completions.create(
        model=WEAK_MODEL,
        messages=[{"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
                  {"role": "user", "content": blind_prompt(q, False)}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1200,
    ), parse_json, retries=6, base_wait=8, label="OpenRouter")


def graded_correct(model_ans, ref: float) -> bool:
    from core.answers import numeric_value
    a = numeric_value(model_ans)
    if a is None:
        return False
    return abs(a - ref) <= max(0.1, 0.01 * abs(ref))   # 1% relative or 0.1 absolute


class _Skip(Exception):
    pass


def regrade(path):
    """Re-score a results file with the current dataset (keys, exclusions) and grader."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    qs = {q["id"]: q for q in load_numeric_questions()}
    kept, changed = [], 0
    for r in data["records"]:
        q = qs.get(r["id"])
        if q is None:
            continue                                   # excluded or no longer numeric
        before = (r["strong_correct"], r.get("weak_correct"))
        r["correct_answer"] = q["correct_answer"]
        if r.get("strong_answer") is not None:
            r["strong_correct"] = graded_correct(r["strong_answer"], q["correct_answer"])
        if r.get("weak_answer") is not None:
            r["weak_correct"] = graded_correct(r["weak_answer"], q["correct_answer"])
        changed += before != (r["strong_correct"], r.get("weak_correct"))
        kept.append(r)
    data.update(records=kept, n=len(kept), summary=summarize(kept),
                regraded_at=datetime.now(timezone.utc).isoformat())
    write_json_atomic(path, data, indent=2, ensure_ascii=False)
    s = data["summary"]["overall"]["strong"]
    print(f"{os.path.basename(path)}: {len(data['records'])} questions kept, {changed} grades changed; "
          f"strong {s[0]}/{s[1]} = {s[2]:.1f}%")


def _spend():
    if not COUNCIL_MODE:
        return None
    from core import models
    return models.SPEND.summary()


# ── run ───────────────────────────────────────────────────────────────────────
def summarize(records):
    def rate(key, subset=None):
        rows = [r for r in records if (subset is None or subset(r))]
        rows = [r for r in rows if r[key] is not None]
        if not rows:
            return (0, 0, 0.0)
        c = sum(1 for r in rows if r[key])
        return (c, len(rows), 100.0 * c / len(rows))
    out = {"overall": {"strong": rate("strong_correct"), "weak": rate("weak_correct")}}
    out["by_year"] = {
        y: {"strong": rate("strong_correct", lambda r, y=y: r["year"] == y),
            "weak":   rate("weak_correct",   lambda r, y=y: r["year"] == y)}
        for y in sorted({r["year"] for r in records})
    }
    out["by_topic"] = {
        t: {"strong": rate("strong_correct", lambda r, t=t: r["topic"] == t),
            "weak":   rate("weak_correct",   lambda r, t=t: r["topic"] == t)}
        for t in sorted({r["topic"] for r in records})
    }
    return out

def main():
    global STRONG_MODEL, WEAK_MODEL, OUT_PATH
    ap = argparse.ArgumentParser(description="Blind solve-rate of two models on real JEE Advanced numeric questions.")
    ap.add_argument("--strong", default=STRONG_MODEL, help="OpenRouter slug of the strong model")
    ap.add_argument("--weak", default=WEAK_MODEL, help="OpenRouter slug of the weak model")
    ap.add_argument("--council", action="store_true",
                    help="solve with the generation council's settings (16k tokens, reasoning effort) "
                         "and report cost; use this to compare council candidates")
    ap.add_argument("--skip-weak", action="store_true", help="do not run the weak model")
    ap.add_argument("--workers", type=int, default=1, help="questions solved in parallel (default 1)")
    ap.add_argument("--regrade", action="store_true",
                    help="re-score the saved answers in this model's results file with the current "
                         "answer keys and grader (no API calls); excluded questions are dropped")
    args = ap.parse_args()
    global COUNCIL_MODE
    COUNCIL_MODE = args.council
    STRONG_MODEL, WEAK_MODEL = args.strong, args.weak
    OUT_PATH = results_path(STRONG_MODEL)
    if args.regrade:
        return regrade(OUT_PATH)
    qs = load_numeric_questions()
    print(f"Loaded {len(qs)} numeric Advanced questions (2021-2025).")
    print(f"Strong: {STRONG_MODEL} (OpenRouter)  |  Weak: {WEAK_MODEL} (OpenRouter)\n")

    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()
    records = []

    def one(i, q):
        rec = {"id": q["id"], "year": q["year"], "topic": q["topic"],
               "question_type": q["question_type"], "correct_answer": q["correct_answer"],
               "strong_answer": None, "weak_answer": None,
               "strong_correct": None, "weak_correct": None}
        try:
            s = solve_strong(q)
            rec["strong_answer"] = s.get("final_answer")
            rec["strong_correct"] = graded_correct(s.get("final_answer"), q["correct_answer"])
        except Exception as e:
            print(f"    strong error: {e}")
        try:
            if args.skip_weak:
                raise _Skip()
            w = solve_weak(q)
            rec["weak_answer"] = w.get("final_answer")
            rec["weak_correct"] = graded_correct(w.get("final_answer"), q["correct_answer"])
        except _Skip:
            pass
        except Exception as e:
            print(f"    weak error: {e}")
        with lock:
            print(f"[{i}/{len(qs)}] {q['id']} | {q['topic']} | ans={q['correct_answer']}"
                  f"   strong={rec['strong_answer']} {'✓' if rec['strong_correct'] else '✗'}"
                  f"   weak={rec['weak_answer']} {'✓' if rec['weak_correct'] else '✗'}")
            records.append(rec)
            # checkpoint after every question
            write_json_atomic(OUT_PATH, {"generated_at": datetime.now(timezone.utc).isoformat(),
                           "strong_model": STRONG_MODEL, "weak_model": None if args.skip_weak else WEAK_MODEL,
                           "council_settings": COUNCIL_MODE, "spend": _spend(),
                           "n": len(records), "records": records,
                           "summary": summarize(records)}, indent=2, ensure_ascii=False)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        list(ex.map(lambda iq: one(*iq), enumerate(qs, 1)))
    order = {q["id"]: n for n, q in enumerate(qs)}
    records.sort(key=lambda r: order[r["id"]])

    s = summarize(records)
    sp_ = _spend()
    if sp_:
        print(f"\nSpend: ${sp_['total_cost_usd']:.4f}  "
              f"(${sp_['total_cost_usd'] / max(1, len(records)):.5f} per question)")
    print("\n" + "=" * 60)
    print("SOLVE RATES (numeric Advanced, 2021-2025, blind)")
    print("=" * 60)
    sc, sn, sp = s["overall"]["strong"]; wc, wn, wp = s["overall"]["weak"]
    print(f"  STRONG ({STRONG_MODEL}): {sc}/{sn} = {sp:.1f}%")
    print(f"  WEAK   ({WEAK_MODEL}): {wc}/{wn} = {wp:.1f}%")
    print("\n  by year:")
    for y, v in s["by_year"].items():
        print(f"    {y}: strong {v['strong'][2]:.0f}% ({v['strong'][0]}/{v['strong'][1]})   "
              f"weak {v['weak'][2]:.0f}% ({v['weak'][0]}/{v['weak'][1]})")
    print("\n  by topic:")
    for t, v in s["by_topic"].items():
        print(f"    {t:10s}: strong {v['strong'][2]:.0f}% ({v['strong'][0]}/{v['strong'][1]})   "
              f"weak {v['weak'][2]:.0f}% ({v['weak'][0]}/{v['weak'][1]})")
    print(f"\nSaved: {OUT_PATH}")

if __name__ == "__main__":
    main()
