"""Compare coder models on a question already in the bank (a few cents in all).

Each model writes the SOLVING program for the saved question (from its text only, as in the pipeline:
qfirst.program_for, up to 3 tries, no escalation); the table shows whether it reproduced the bank's
answer, in how many tries, its errors and its cost. Nothing is saved; the step-by-step state is untouched.

    python tools/compare_coders.py
    python tools/compare_coders.py --question GEN_20261116T101250 --coders openai/gpt-6-luna qwen/qwen3.8-flash deepseek/deepseek-v4-pro
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.blackboard import Blackboard  # noqa: E402
from core.pipeline import qfirst  # noqa: E402

DEFAULT_CODERS = ["openai/gpt-6-luna", "qwen/qwen3.8-flash", "deepseek/deepseek-v4-pro"]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--question", default="GEN_20261116T101250")
    ap.add_argument("--coders", nargs="+", default=DEFAULT_CODERS)
    args = ap.parse_args()
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    from subject_config import get_subject_config
    with open(get_subject_config("physical")["output_file"], encoding="utf-8") as f:
        rec = next((r for r in json.load(f) if r.get("question_id") == args.question), None)
    if rec is None:
        sys.exit(f"✗ {args.question} is not in the bank")
    eng = rec["engine"]
    txs = list(eng.get("txs") or [])
    cand = {"txs": txs, "drawn_txs": [t for t in txs if t not in (eng.get("extra_txs") or [])], "edges": []}
    asks, unit, answer = eng.get("asks") or "the asked quantity", rec.get("unit") or "", float(rec["answer"])
    print(f"{args.question}: answer {answer:g} {unit}; formulas {txs}\n")
    rows = []
    models.CODER_STRONG = None                       # each model on its own, no hand-over
    for m in args.coders:
        models.CODER = m
        bb = Blackboard("physical")
        bb.start_chain({"txs": txs, "edges": []})
        before = models.SPEND.total_cost
        print(f"── {m}")
        try:
            code, run, why = qfirst.program_for(rec["question"], asks, unit, cand, bb)
        except Exception as e:  # noqa: BLE001
            code, run, why = None, None, f"{type(e).__name__}: {str(e)[:160]}"
        tries = sum(1 for ev in bb.current["events"] if ev["stage"] == "program")
        ok = run is not None and abs(run["answer_exact"] - answer) <= max(0.02, run["tolerance"]) * abs(answer)
        rows.append((m, ok, run["answer"] if run else None, tries, models.SPEND.total_cost - before,
                     None if ok else (why or f"answer {run['answer'] if run else '?'}")))
    print(f"\n{'model':32} {'correct':8} {'answer':>10} {'tries':>5} {'cost':>9}")
    for m, ok, ans, tries, cost, why in rows:
        print(f"{m:32} {'yes' if ok else 'NO':8} {('' if ans is None else f'{ans:g}'):>10} {tries:>5} ${cost:8.4f}"
              + (f"\n{'':32} {str(why)[:150]}" if why else ""))


if __name__ == "__main__":
    main()
