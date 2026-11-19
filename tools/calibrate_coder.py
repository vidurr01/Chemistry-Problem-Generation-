"""Choose the coder on real JEE Advanced questions (the paper's coder table).

Each coder writes the SOLVING program (qfirst.program_for, as in the pipeline: up to 3 tries, no hand-over
to another model) for real JEE Advanced physical questions: numeric answer, every formula of the solution
an engine step (docs/advanced_formula_map.py), no figure or graph to read. The program's answer is checked
against the OFFICIAL answer: within 2 %, or the official answer rounded to its stated decimals.

Two rates per coder:
  right     some try reached the official answer      (can it solve real Advanced questions?)
  accepted  the program the pipeline kept is right     (its last try that ran)

Every try is saved (its program, answer and any error), so the saved programs can be rerun offline, at
no API cost (--recheck).

    python tools/calibrate_coder.py --coders openai/gpt-6-luna qwen/qwen3.8-flash          # the table's 8 (PAPER_SET)
    python tools/calibrate_coder.py --coders openai/gpt-6-luna --limit 0                     # every usable question

The test set leaves out questions whose stored text is incomplete or does not give its stored answer
(EXCLUDED), and restates the ones that use a rounded constant with the engine's (ADAPTED).
    python tools/calibrate_coder.py --coders openai/gpt-6-luna --ids 2012P1_Q36 2015P2_Q28  # only these
    python tools/calibrate_coder.py --recheck                  # rerun the saved programs offline (free)
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
VERBOSE = False                 # --verbose: the pipeline's own messages (retries, timeouts) are shown

# The test set's own faults, found in the 49-question run of 2026-11-18 (data/jee_advanced/ is left as the
# papers have it: eight other tools read it). Questions no program can be judged on are left out:
EXCLUDED = {
    "2018P1_Q9": "the compartments' pressures, volumes and temperatures are in a figure missing from the text",
    "2020P1_Q13": "the five NaOH titre volumes are in a table missing from the text",
    "2024P1_Q9": "the mechanism is in a scheme missing from the text",
    "2017P1_Q26": "the stored text (cell constant 1000 m⁻¹, α = 0.01) gives Λ°m = 0.0333 S m² mol⁻¹, not the stored 6, "
                  "which belongs to the paper's version (electrodes 120 cm apart, pH 4, Z × 10² S cm² mol⁻¹)",
    "2017P1_Q27": "the stored text (1 mol each of A and B in 10 L, 0.1 mol D) gives Kc = 0.1736, not the stored 0.014",
}
# Questions that state their own rounded constant, restated with the engine's (the engine always uses its own,
# which moved the answer 2-3 %, past the 2 % match): [(text, replaced by)], the answer recomputed.
ADAPTED = {
    "2018P2_Q10": ([("R = 8 J K−1 mol−1", "R = 8.314 J K−1 mol−1")], "-14.23"),   # ln 0.01 − 100000/(8.314 × 1250)
    "2023P1_Q9": ([("R = 8×10⁻² L atm K⁻¹ mol⁻¹", "R = 0.0821 L atm K⁻¹ mol⁻¹")], "102.6"),  # x/y = 1250 R
}


# The 8 questions of the coder table (Luna, Qwen3 Coder, Codestral; knowledge/coder_calibration_physical.json):
# the default set, pinned. Spreading 8 over the set picked another 8 once EXCLUDED shortened it, and a run on
# other questions drops every coder's saved entry from the table.
PAPER_SET = ["2012P1_Q36", "2015P2_Q28", "2018P1_Q10", "2019P1_Q16", "2020P1_Q17", "2021P2_Q11", "2022P2_Q3",
             "2024P2_Q11"]


def _adapt(qid: str, text: str, answer: str):
    """(text, answer) as the test uses them: restated with the engine's constants for ADAPTED questions."""
    if qid not in ADAPTED:
        return text, answer
    swaps, new_answer = ADAPTED[qid]
    for old, new in swaps:
        if old not in text:                     # never a silent no-op if the source text changes
            raise ValueError(f"{qid}: {old!r} is not in the question text")
        text = text.replace(old, new)
    return text, new_answer


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
        if FIGURE.search(text) or not re.fullmatch(r"-?\d+(\.\d+)?", ans) or qid in EXCLUDED:
            continue
        text, ans = _adapt(qid, text, ans)
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
        batch = []
        quiet = contextlib.nullcontext() if VERBOSE else contextlib.redirect_stdout(io.StringIO())
        with quiet, ThreadPoolExecutor(PARALLEL) as ex:
            for fut in as_completed([ex.submit(one, q) for q in qs[i:i + PARALLEL]]):
                r = fut.result()
                with contextlib.redirect_stdout(sys.__stdout__):
                    show(r)                     # each question as soon as it is done (2026-11-17: 5 silent minutes)
                    sys.__stdout__.flush()
                batch.append(r)
        rows.extend(sorted(batch, key=lambda r: [q["id"] for q in qs].index(r["id"])))
    cost = models.SPEND.total_cost - start
    return {"model": model, "questions": len(rows), "right": sum(r["right"] for r in rows),
            "accepted": sum(r["accepted"] for r in rows), "tries": sum(len(r["tries"]) for r in rows),
            "cost_usd": round(cost, 4), "rows": rows}


def recheck(path: str) -> None:
    """Rerun every saved program in the sandbox and compare with the official answer (no API calls)."""
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    for res in saved["results"]:
        print(f"── {res['model']}")
        for r in res["rows"]:
            for t in r["tries"]:
                if not t.get("code"):
                    continue
                run = qfirst.sandbox.evaluate(t["code"], r["txs"], any_step=True)
                if not run.get("ok"):
                    verdict = f"error: {run['error'][:250]}"
                else:
                    verdict = "right" if matches(run["answer_exact"], r["official"]) else "WRONG answer"
                print(f"   {r['id']:12} try {t['attempt']}: answer {run.get('answer')} "
                      f"(official {r['official']}) -> {verdict}")


def main():
    global VERBOSE, PARALLEL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coders", nargs="+", default=DEFAULT_CODERS)
    ap.add_argument("--limit", type=int, default=8, help="questions per coder (0 = all)")
    ap.add_argument("--ids", nargs="+", help="only these questions (e.g. 2012P1_Q36)")
    ap.add_argument("--max-spend", type=float, default=0.05, help="stop a coder once it has spent this ($)")
    ap.add_argument("--no-thinking", action="store_true", help="ask the coders not to think (models.THINKING_OFF)")
    ap.add_argument("--parallel", type=int, default=PARALLEL, help="questions at once (1 for a router that drops "
                                                                   "connections)")
    ap.add_argument("--verbose", action="store_true", help="show the pipeline's messages (retries, timeouts)")
    ap.add_argument("--thinking", type=int, help="the coders' thinking budget in tokens (models.THINKING_BUDGET)")
    ap.add_argument("--recheck", nargs="?", const="", metavar="FILE",
                    help="rerun the saved programs offline (default: the --ids file, else the main one)")
    args = ap.parse_args()
    if args.recheck is not None:
        path = args.recheck or (OUT_IDS if os.path.exists(OUT_IDS) else OUT)
        print(f"rechecking the programs saved in {os.path.relpath(path, ROOT)} (no API calls)\n")
        return recheck(path)
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    VERBOSE, PARALLEL = args.verbose, max(1, args.parallel)
    if args.no_thinking:
        models.THINKING_OFF.update(args.coders)
    if args.thinking:
        models.THINKING_BUDGET.update({m: args.thinking for m in args.coders})
    allq = real_questions()
    if args.ids:
        qs = [q for q in allq if q["id"] in set(args.ids)]
        missing = set(args.ids) - {q["id"] for q in qs}
        if missing:
            sys.exit(f"✗ not among the usable questions: {', '.join(sorted(missing))}")
    elif args.limit == len(PAPER_SET):         # the default: the table's own questions
        qs = [q for qid in PAPER_SET for q in allq if q["id"] == qid]
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
    # each coder's result is kept beside the others' (2026-11-17: a failed Mistral Large 4 run replaced
    # Devstral's 8 programs); a coder run again on the same questions replaces only its own entry
    old = {}
    try:
        with open(out, encoding="utf-8") as f:
            prev = json.load(f)
        if prev.get("questions") == [q["id"] for q in qs]:
            old = {r["model"]: r for r in prev.get("results", [])}
    except (OSError, ValueError):
        pass
    old.update({r["model"]: r for r in results if r["questions"]})
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"questions": [q["id"] for q in qs], "results": list(old.values())}, f, indent=1,
                  ensure_ascii=False)
    print(f"\nwritten to {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
