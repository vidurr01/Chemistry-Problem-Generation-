"""
anchor_calibration.py — measure real-question solve rates for a strong and a weak model.

Purpose (the "anchor" the difficulty claim rests on): run real JEE Advanced questions
through two models BLIND (no answer key shown), grade each model's answer against the
official key, and report solve-rate distributions. This tells you where real Advanced
questions sit for each model — the baseline your generated items get compared against.

Design choices for this run (kept deliberately simple for the deadline):
  * Strong model : openai/gpt-oss-120b             (OpenRouter, reasoning-grade)
  * Weak model   : meta-llama/llama-3.2-3b-instruct (OpenRouter, genuine 3B floor)
  * Subset       : the last 5 years (2021-2025), NUMERIC-answer questions only.
      MCQ/MSQ option text is NOT present in the dataset, so a blind solver cannot map
      its answer to a letter — numeric (NAT/Numerical) questions need no options and
      grade deterministically, so they are the honest subset to measure on.
  * Grading      : deterministic numeric match (tolerance below). No LLM grader, so the
      score is reproducible and carries no model bias.

Blind == the model never sees correct_answer or solution_summary. That is the whole point:
a model that is shown the answer cannot tell you whether the question was solvable.

Output: calibration/anchor_calibration_results.json  (checkpointed after every question).
"""

import json
import glob
import os
import re
import sys
import time
from datetime import datetime, timezone
from openai import OpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# ── env ─────────────────────────────────────────────────────────────────────
_env_path = os.path.join(_ROOT, ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    print("ERROR: no OPENROUTER_KEY in .env"); sys.exit(1)

# Strong solver = a reasoning-grade model via OpenRouter. (SambaNova's gpt-oss-120b was
# capacity-blocked with persistent 429s, and 405B is not served on any available
# provider.) openai/gpt-oss-120b is reasoning-tuned, so a FAILURE means the question is
# genuinely hard, not that the solver isn't expert enough — which is what makes it a
# trustworthy expert-ceiling probe.
STRONG_MODEL = "qwen/qwen3-235b-a22b-2507"        # OpenRouter — matches the generation strong solver
# Weak solver via OpenRouter, NOT local Ollama: Ollama's llama3.2 returns an empty JSON
# object ("{}") under response_format=json_object, so every answer came back None — a
# broken solver, not a genuine failure. The hosted llama-3.2-3b actually attempts it.
WEAK_MODEL   = "meta-llama/llama-3.2-3b-instruct"  # OpenRouter (3B)

JEE_DIR    = "/Users/admin/Downloads/data/jee_advanced"
YEARS      = range(2021, 2026)
OUT_PATH   = os.path.join(_HERE, "anchor_calibration_results.json")

def openrouter_client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

def strong_call(fn, retries=6, base_wait=8):
    """Exponential backoff on 429/503 for OpenRouter."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate" in msg.lower() or "503" in msg:
                wait = base_wait * (2 ** attempt)
                print(f"      [rate limit] waiting {wait}s ({attempt+1}/{retries})...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("OpenRouter: max retries exceeded")


def parse_json(content: str) -> dict:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s, e = text.find("{"), text.rfind("}")
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    return {}


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
        data = json.load(open(fp, encoding="utf-8"))
        for q in data.get("questions", []):
            ca = q.get("correct_answer")
            if ca is None or "[Image" in str(ca):
                continue
            if not is_numeric_answer(ca):
                continue
            if not q.get("question_text"):
                continue
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
    resp = strong_call(lambda: openrouter_client().chat.completions.create(
        model=STRONG_MODEL,
        messages=[{"role": "system", "content": "You are an expert chemist. Output JSON only."},
                  {"role": "user", "content": blind_prompt(q, True)}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=2500,   # reasoning model needs room before the JSON
    ))
    return parse_json(resp.choices[0].message.content)

def solve_weak(q):
    resp = strong_call(lambda: openrouter_client().chat.completions.create(
        model=WEAK_MODEL,
        messages=[{"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
                  {"role": "user", "content": blind_prompt(q, False)}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=1200,
    ))
    return parse_json(resp.choices[0].message.content)


def graded_correct(model_ans, ref: float) -> bool:
    a = to_float(model_ans)
    if a is None:
        return False
    return abs(a - ref) <= max(0.1, 0.01 * abs(ref))   # 1% relative or 0.1 absolute


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
    qs = load_numeric_questions()
    print(f"Loaded {len(qs)} numeric Advanced questions (2021-2025).")
    print(f"Strong: {STRONG_MODEL} (OpenRouter)  |  Weak: {WEAK_MODEL} (OpenRouter)\n")

    records = []
    for i, q in enumerate(qs, 1):
        print(f"[{i}/{len(qs)}] {q['id']} | {q['topic']} | ans={q['correct_answer']}")
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
            w = solve_weak(q)
            rec["weak_answer"] = w.get("final_answer")
            rec["weak_correct"] = graded_correct(w.get("final_answer"), q["correct_answer"])
        except Exception as e:
            print(f"    weak error: {e}")
        print(f"    strong={rec['strong_answer']} {'✓' if rec['strong_correct'] else '✗'}"
              f"   weak={rec['weak_answer']} {'✓' if rec['weak_correct'] else '✗'}")
        records.append(rec)

        # checkpoint after every question
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "strong_model": STRONG_MODEL, "weak_model": WEAK_MODEL,
                       "n": len(records), "records": records,
                       "summary": summarize(records)}, f, indent=2, ensure_ascii=False)

    s = summarize(records)
    print("\n" + "=" * 60)
    print("SOLVE RATES (numeric Advanced, 2021-2025, blind)")
    print("=" * 60)
    sc, sn, sp = s["overall"]["strong"]; wc, wn, wp = s["overall"]["weak"]
    print(f"  STRONG (405B): {sc}/{sn} = {sp:.1f}%")
    print(f"  WEAK (llama3.2): {wc}/{wn} = {wp:.1f}%")
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
