"""Choose the coder on real JEE Advanced questions (the paper's coder table).

Each coder writes the SOLVING program (qfirst.program_for, as in the pipeline: up to 3 tries, no hand-over
to another model) for real JEE Advanced physical questions: numeric answer, every formula of the solution
an engine step (docs/advanced_formula_map.py), no figure or graph to read. The program's answer is checked
against the OFFICIAL answer: within 2 %, or the official answer rounded to its stated decimals.

Two rates per coder:
  right     some try reached the official answer      (can it solve real Advanced questions?)
  accepted  the pipeline accepted that program         (also passed our checks)

Every try is saved (its program, answer and what our checks said about it), so the checks can be rerun on
the saved programs offline, at no API cost (--recheck).

    python tools/calibrate_coder.py --coders openai/gpt-6-luna qwen/qwen3.8-flash          # 8 questions
    python tools/calibrate_coder.py --coders openai/gpt-6-luna --ids 2012P1_Q36 2015P2_Q28  # only these
    python tools/calibrate_coder.py --recheck                  # rerun our checks on the saved programs (free)
"""
import argparse
import contextlib
import glob
import importlib.util
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.blackboard import Blackboard  # noqa: E402
from core.engine import physical as ph  # noqa: E402
from core.pipeline import qfirst  # noqa: E402

OUT = os.path.join(ROOT, "knowledge", "coder_calibration_physical.json")
OUT_IDS = os.path.join(ROOT, "knowledge", "coder_calibration_tries.json")    # runs with --ids
DEFAULT_CODERS = ["openai/gpt-6-luna", "qwen/qwen3.8-flash", "deepseek/deepseek-v4-pro"]
NUMERIC = {"NAT", "Numerical", "NNI", "PNV", "Integer", "SDI"}
FIGURE = re.compile(r"figure|graph|plot|diagram|shown below|shown above|curve", re.I)
ASKS = "the value the question asks for (the blank to fill in), in the unit the question asks for"
PARALLEL = 4


def real_questions() -> list:
    spec = importlib.util.spec_from_file_location("fmap", os.path.join(ROOT, "docs", "advanced_formula_map.py"))
    fmap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmap)
    qs = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "jee_advanced", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            for q in json.load(fh)["questions"]:
                qs[q["id"].replace("_Chem", "")] = q
    out = []
    for qid, (steps, mod, _note) in fmap.MAP.items():
        q = qs.get(qid)
        if not q or q.get("question_type") not in NUMERIC or mod == "graph":
            continue
        if not all(isinstance(s, int) and s in ph.STEPS for s in steps):
            continue
        text = " ".join(str(q["question_text"]).split())
        ans = str(q.get("correct_answer", "")).strip()
        if FIGURE.search(text) or not re.fullmatch(r"-?\d+(\.\d+)?", ans):
            continue
        out.append({"id": qid, "text": text, "answer": ans, "txs": list(dict.fromkeys(steps)), "use": mod})
    return out


def spread(items: list, n: int) -> list:
    """n questions spread over the years (every k-th), the same for every coder."""
    if n <= 0 or n >= len(items):
        return items
    return [items[round(i * (len(items) - 1) / (n - 1))] for i in range(n)] if n > 1 else items[:1]


def matches(x, official: str) -> bool:
    if x is None:
        return False
    a = float(official)
    decimals = len(official.split(".")[1]) if "." in official else 0
    return abs(x - a) <= max(0.02 * abs(a), 0.5 * 10 ** -decimals + 1e-12)


def _try_record(ev: dict) -> dict:
    """One try as the pipeline noted it: its program, answer, and what was wrong (checks, error, cannot)."""
    return {"attempt": ev.get("attempt"), "answer": ev.get("answer"), "accepted": bool(ev.get("ok")),
            "problems": ev.get("problems") or ([ev["error"]] if ev.get("error") else []),
            "cannot": ev.get("cannot"), "code": ev.get("code")}


def one(q: dict) -> dict:
    cand = {"txs": q["txs"], "drawn_txs": q["txs"], "edges": []}
    bb = Blackboard("physical")
    bb.start_chain({"txs": q["txs"], "edges": []})
    try:
        _code, run, why = qfirst.program_for(q["text"], ASKS, "", cand, bb)
    except Exception as e:  # noqa: BLE001
        run, why = None, f"{type(e).__name__}: {str(e)[:160]}"
    tries = [_try_record(ev) for ev in bb.current["events"] if ev["stage"] == "program"]
    right = any(matches(t["answer"], q["answer"]) for t in tries)
    accepted = run is not None and matches(run["answer_exact"], q["answer"])
    return {"id": q["id"], "use": q["use"], "txs": q["txs"], "official": q["answer"], "tries": tries,
            "right": right, "accepted": accepted, "why": None if accepted else (why or "")[:300]}


def show(r: dict) -> None:
    got = ", ".join("—" if t["answer"] is None else f"{t['answer']:g}" for t in r["tries"]) or "—"
    print(f"   {'✓' if r['right'] else '✗'} {r['id']:12} official {r['official']:>9}  got {got}"
          f"{'' if r['accepted'] else '   (not accepted)'}")
    for t in r["tries"]:
        if not t["accepted"]:
            said = t["cannot"] and f"cannot: {t['cannot']}" or "; ".join(t["problems"]) or "?"
            print(f"       try {t['attempt']}: {said[:220]}")


def run_coder(model: str, qs: list, cap: float) -> dict:
    models.CODER, models.CODER_STRONG = model, None        # each model on its own, no hand-over
    start = models.SPEND.total_cost
    rows = []
    for i in range(0, len(qs), PARALLEL):
        if models.SPEND.total_cost - start > cap:
            print(f"   stopped: spend cap ${cap:.2f} reached after {len(rows)} questions")
            break
        with contextlib.redirect_stdout(io.StringIO()), ThreadPoolExecutor(PARALLEL) as ex:
            batch = list(ex.map(one, qs[i:i + PARALLEL]))
        for r in batch:
            show(r)
        rows.extend(batch)
    cost = models.SPEND.total_cost - start
    return {"model": model, "questions": len(rows), "right": sum(r["right"] for r in rows),
            "accepted": sum(r["accepted"] for r in rows), "tries": sum(len(r["tries"]) for r in rows),
            "cost_usd": round(cost, 4), "rows": rows}


def recheck(path: str) -> None:
    """Rerun the sandbox and our checks on every saved program (no API calls)."""
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    texts = {q["id"]: q["text"] for q in real_questions()}
    for res in saved["results"]:
        print(f"── {res['model']}")
        for r in res["rows"]:
            for t in r["tries"]:
                if not t.get("code"):
                    continue
                run = qfirst.sandbox.evaluate(t["code"], r["txs"], any_step=True)
                probs = [run["error"]] if not run.get("ok") else \
                    qfirst.program_problems(texts[r["id"]], run, r["txs"], may_drop=True)
                ans = run.get("answer")
                print(f"   {r['id']:12} try {t['attempt']}: answer {ans} (official {r['official']}) -> "
                      f"{'accepted' if not probs else '; '.join(probs)[:300]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coders", nargs="+", default=DEFAULT_CODERS)
    ap.add_argument("--limit", type=int, default=8, help="questions per coder (0 = all)")
    ap.add_argument("--ids", nargs="+", help="only these questions (e.g. 2012P1_Q36)")
    ap.add_argument("--max-spend", type=float, default=0.05, help="stop a coder once it has spent this ($)")
    ap.add_argument("--recheck", nargs="?", const="", metavar="FILE",
                    help="rerun our checks on the saved programs, offline (default: the --ids file, else the main one)")
    args = ap.parse_args()
    if args.recheck is not None:
        path = args.recheck or (OUT_IDS if os.path.exists(OUT_IDS) else OUT)
        print(f"rechecking the programs saved in {os.path.relpath(path, ROOT)} (no API calls)\n")
        return recheck(path)
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    allq = real_questions()
    if args.ids:
        qs = [q for q in allq if q["id"] in set(args.ids)]
        missing = set(args.ids) - {q["id"] for q in qs}
        if missing:
            sys.exit(f"✗ not among the usable questions: {', '.join(sorted(missing))}")
    else:
        qs = spread(allq, args.limit)
    print(f"{len(qs)} of {len(allq)} usable real JEE Advanced questions, same set for every coder\n")
    results = []
    for m in args.coders:
        print(f"── {m}")
        results.append(run_coder(m, qs, args.max_spend))
    print(f"\n{'coder':32} {'right':>9} {'accepted':>9} {'tries/q':>8} {'cost':>9} {'cost/q':>8}")
    for r in results:
        n = max(r["questions"], 1)
        print(f"{r['model']:32} {r['right']:>3}/{r['questions']:<3} {r['accepted']:>5}/{r['questions']:<3}"
              f" {r['tries'] / n:>8.2f} ${r['cost_usd']:>8.4f} ${r['cost_usd'] / n:>7.4f}")
    out = OUT_IDS if args.ids else OUT        # a debug run never overwrites the paper's table
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"questions": [q["id"] for q in qs], "results": results}, f, indent=1, ensure_ascii=False)
    print(f"\nwritten to {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
