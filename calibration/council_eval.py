"""
council_eval.py — measure a 3-model council's consensus on REAL exam questions.

Runs three different-family, ~Mains-capable models (Llama-3.3-70B, Mistral-Large,
Gemma-2-27B) BLIND (no answer key) over a question set, grades each answer by
deterministic numeric key-match, and reports the consensus histogram:

    how many questions did ALL THREE solve?
    ... EXACTLY TWO?
    ... EXACTLY ONE?
    ... NONE?

Purpose: pick / validate the council. The count of solvers that solve a question is
the difficulty signal used inside generation (run_groundup_final.py). For that count to
mean "above Mains", the council must SOLVE Mains but FAIL Advanced — this script measures
exactly that profile.

Sets:
  --set advanced   JEE Advanced 2021-2025 numeric (the 54; the difficulty target)
  --set mains      JEE Mains numeric, recent years only (2024-2025 by default) — the
                   "can the council even do Mains?" sanity check. Recent years reduce the
                   chance the questions are memorised from pretraining.

Grading is deterministic (numeric match, same tolerance as anchor_calibration.py); no LLM
grader, so results carry no grader bias. Checkpointed after every question.

Run:  python calibration/council_eval.py --set advanced
      python calibration/council_eval.py --set mains --mains-years 2024,2025
"""

import argparse
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
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

OPENROUTER_KEY = os.environ.get("OPENROUTER_KEY", "")
if not OPENROUTER_KEY:
    print("ERROR: OPENROUTER_KEY not in .env"); sys.exit(1)

# Same council as run_groundup_final.py — keep in sync.
COUNCIL = [
    ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct"),
    ("mistral-large", "mistralai/mistral-large-2407"),
    ("gemma-2-27b",   "google/gemma-2-27b-it"),
]

ADV_DIR   = "/Users/admin/Downloads/data/jee_advanced"
MAINS_FILE = "/Users/admin/Downloads/data/jee_mains/chemistry.json"


def client():
    return OpenAI(api_key=OPENROUTER_KEY, base_url="https://openrouter.ai/api/v1")

def call_with_retry(fn, retries=6, base_wait=8):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            m = str(e)
            if "429" in m or "rate" in m.lower() or "503" in m:
                time.sleep(base_wait * (2 ** attempt))
            else:
                raise
    raise RuntimeError("OpenRouter: max retries exceeded")

def parse_json(content):
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e > s:
            return json.loads(text[s:e + 1])
        return {}

# ── numeric grading (deterministic, same as anchor) ──────────────────────────
_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
def to_float(x):
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    s = str(x).replace(",", "").replace("×10^", "e").replace("x10^", "e").replace("^", "e")
    m = _NUM.findall(s)
    try: return float(m[-1]) if m else None
    except ValueError: return None

def is_numeric(ca):
    return ca is not None and re.fullmatch(r"-?\d+(\.\d+)?", str(ca).strip()) is not None

def graded_correct(ans, key):
    a = to_float(ans)
    if a is None: return False
    return abs(a - key) <= max(0.1, 0.01 * abs(key))

_FIG = re.compile(
    r"(\[(reaction scheme|image|figure|structure|diagram|graph|plot|table)[^\]]*\]|"
    r"shown below|given below|the plot of|as shown in|following reaction scheme)", re.IGNORECASE)

# ── loaders ───────────────────────────────────────────────────────────────────
def load_advanced(years):
    out = []
    for y in years:
        fp = os.path.join(ADV_DIR, f"{y}.json")
        if not os.path.exists(fp): continue
        for q in json.load(open(fp, encoding="utf-8")).get("questions", []):
            ca = q.get("correct_answer")
            if not is_numeric(ca) or "[Image" in str(ca): continue
            if _FIG.search(q.get("question_text", "")): continue
            out.append({"id": q.get("id"), "year": y,
                        "topic": (q.get("topic","") or "?").split("-")[0].strip(),
                        "question_text": q["question_text"], "answer": float(str(ca).strip())})
    return out

def load_mains(years):
    out = []
    data = json.load(open(MAINS_FILE, encoding="utf-8"))
    for q in data.get("questions", []):
        if q.get("question_type") != "numerical": continue
        na = q.get("numerical_answer")
        if na is None or not is_numeric(na): continue
        # keep only requested years if the id encodes a year (e.g. CH-24-*, CH-25-*)
        qid = str(q.get("id", ""))
        if years and not any(f"-{str(y)[-2:]}-" in qid or str(y) in qid for y in years):
            continue
        out.append({"id": qid, "year": None, "topic": q.get("topic", "?"),
                    "question_text": q["question_text"], "answer": float(str(na).strip())})
    return out

# ── blind solve on one model ──────────────────────────────────────────────────
def blind_solve(problem, slug):
    prompt = f"""You are an expert chemist solving a JEE chemistry problem with a NUMERICAL answer.
You are NOT given the answer key. Work it out, then state the final numeric value.

Question:
{problem}

Return JSON:
{{"reasoning": "your working", "final_answer": <the final numeric value only, as a number>}}"""
    resp = call_with_retry(lambda: client().chat.completions.create(
        model=slug,
        messages=[{"role": "system", "content": "You are an expert chemist. Output JSON only."},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0.0, max_tokens=2500,
    ))
    return parse_json(resp.choices[0].message.content)

# ── run ───────────────────────────────────────────────────────────────────────
def summarize(records, n_models):
    hist = {k: 0 for k in range(n_models + 1)}   # 0..n solved
    per_model = {name: [0, 0] for name, _ in COUNCIL}   # [correct, measured]
    for r in records:
        hist[r["n_solved"]] += 1
        for name, _ in COUNCIL:
            c = r["per_model"].get(name)
            if c is not None:
                per_model[name][1] += 1
                per_model[name][0] += int(c)
    return {"histogram_by_solvers": hist, "per_model": per_model, "n_questions": len(records)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["advanced", "mains"], default="advanced")
    ap.add_argument("--adv-years", default="2021,2022,2023,2024,2025")
    ap.add_argument("--mains-years", default="2024,2025",
                    help="recent years reduce pretraining-memorisation; '' = all")
    args = ap.parse_args()

    if args.set == "advanced":
        years = [int(y) for y in args.adv_years.split(",") if y.strip()]
        qs = load_advanced(years); label = f"Advanced {years}"
    else:
        years = [int(y) for y in args.mains_years.split(",") if y.strip()]
        qs = load_mains(years); label = f"Mains {years or 'all'}"

    out_path = os.path.join(_HERE, f"council_eval_{args.set}.json")
    print(f"Council eval [{label}] — {len(qs)} numeric questions")
    for name, slug in COUNCIL:
        print(f"  • {name}: {slug}")
    print()

    records = []
    for i, q in enumerate(qs, 1):
        print(f"[{i}/{len(qs)}] {q['id']} | {q['topic']} | ans={q['answer']}")
        per_model, answers = {}, {}
        n_solved = 0
        for name, slug in COUNCIL:
            try:
                out = blind_solve(q["question_text"], slug)
                ok = graded_correct(out.get("final_answer"), q["answer"])
                per_model[name] = ok
                answers[name] = out.get("final_answer")
                n_solved += int(ok)
                print(f"    [{name}] {'OK' if ok else 'x'}  ans={out.get('final_answer')}")
            except Exception as e:
                per_model[name] = None
                answers[name] = None
                print(f"    [{name}] ERROR {str(e)[:70]}")
        records.append({"id": q["id"], "year": q["year"], "topic": q["topic"],
                        "answer": q["answer"], "n_solved": n_solved,
                        "per_model": per_model, "model_answers": answers})
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                       "set": label, "council": [s for _, s in COUNCIL],
                       "n": len(records), "records": records,
                       "summary": summarize(records, len(COUNCIL))}, f, indent=2, ensure_ascii=False)

    s = summarize(records, len(COUNCIL))
    print("\n" + "=" * 60)
    print(f"CONSENSUS HISTOGRAM — {label}  (n={s['n_questions']})")
    print("=" * 60)
    h = s["histogram_by_solvers"]
    print(f"  all 3 solved : {h[3]}")
    print(f"  exactly 2    : {h[2]}")
    print(f"  exactly 1    : {h[1]}")
    print(f"  none solved  : {h[0]}")
    print("\n  per-model solve rate:")
    for name, (c, m) in s["per_model"].items():
        print(f"    {name:14s}: {c}/{m} = {100*c/m:.1f}%" if m else f"    {name}: n/a")
    print(f"\nSaved: {out_path}")

if __name__ == "__main__":
    main()
