"""
fit_ab.py — does Jev's formula-fit check help or hurt? Two arms, draws interleaved:

    off   the first random formula set (adapter.random_formulas), as drawn
    on    Jev picks, as the pipeline does (qf_draw.best_draw, calibrated floor)

Each draw goes through the question-first stages up to a finished question (design, writer, coder,
numbers, code checks, Jev coherence) and STOPS there: no ladder, nothing saved to outputs/. The outcome
is "built" or the stage it died at. The off arm's sets are also scored by Jev (a fraction of a rupee)
to see whether the score predicts the outcome.

    python tools/fit_ab.py --per-arm 5            # live: costs ~₹5-6 per draw at ₹88/$
    python tools/fit_ab.py --per-arm 0            # wiring check, no model call

Results: outputs/fit_ab/<timestamp>.json (per draw: arm, formulas, Jev score, twist, outcome, cost)
and the Blackboard of every draw.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

USD_TO_INR = 88.0


def outcome_of(chain: dict, made) -> tuple[str, str]:
    """('built' | 'impossible_design' | 'impossible_writer' | 'failed', the last reason)."""
    from core.pipeline import qfirst
    evs = chain["events"]
    last = lambda stage: next((e for e in reversed(evs) if e["stage"] == stage), None)  # noqa: E731
    if made is not None and made != qfirst.IMPOSSIBLE:
        return "built", ""
    if made == qfirst.IMPOSSIBLE:
        imp = last("impossible")
        if imp is None:
            dr = last("design_rejected")
            return "impossible_design", str(dr.get("problem") if dr else "")[:300]
        where = "impossible_design" if imp.get("at") == "design" else "impossible_writer"
        return where, str(imp.get("reason"))[:300]
    rej = last("question_rejected")
    return "failed", str(rej.get("problems") if rej else "")[:300]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-arm", type=int, default=5)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    from core import models
    from core.blackboard import Blackboard
    from core.llm import write_json_atomic
    from core.pipeline import qf_draw, qfirst
    from core.pipeline.adapters import adapter_for
    from subject_config import get_subject_config

    seed = args.seed if args.seed is not None else random.randrange(1 << 30)
    rng = random.Random(seed)
    cfg = get_subject_config("physical")
    ad = adapter_for("physical", {**cfg, "question_first": True, "max_run_spend": None}, random.Random(seed))
    boards = {"off": Blackboard("physical"), "on": Blackboard("physical")}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "fit_ab")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{stamp}.json")
    rows = []

    def save():
        write_json_atomic(path, {"seed": seed, "per_arm": args.per_arm, "rows": rows,
                                 "spend": models.SPEND.summary(),
                                 "boards": {k: b.chains for k, b in boards.items()}})

    print(f"fit A/B: {args.per_arm} draws per arm, interleaved, seed {seed}; results {path}")
    for i in range(args.per_arm):
        for arm in ("off", "on"):
            bb = boards[arm]
            before = models.SPEND.total_cost
            if arm == "on":
                cand = qf_draw.best_draw(ad, None, bb, lambda rec: None)
                fit = None if cand is None else cand.get("_fit")
            else:
                cand = ad.random_formulas(None, exclude=bb.tried_edges())
                fit = None if cand is None else qf_draw.formulas_fit(cand["_steps"])
            if cand is None:
                print(f"  [{arm} {i + 1}] no formula set could be drawn")
                continue
            twist = rng.choice(sorted(qfirst.TWISTS))
            print(f"\n=== [{arm} {i + 1}/{args.per_arm}] formulas {cand['txs']} ({', '.join(cand['chapters'])}); "
                  f"twist {twist}; Jev fit {'?' if fit is None else f'{fit:.0%}'} ===")
            bb.start_chain({**cand, "twist": twist})
            bb.note("formula_fit", p=fit, arm=arm)
            try:
                made = qfirst.write_and_solve(ad, cand, twist, bb, rng)
            except Exception as e:                       # noqa: BLE001 - one broken draw must not end the test
                if getattr(e, "status_code", None) == 402:
                    raise
                bb.note("crashed", error=f"{type(e).__name__}: {str(e)[:300]}")
                made = None
            kind, why = outcome_of(bb.current, made)
            cost = models.SPEND.total_cost - before
            rows.append({"arm": arm, "draw": i + 1, "txs": cand["txs"], "chapters": cand["chapters"], "fit": fit,
                         "twist": twist, "outcome": kind, "why": why, "cost_usd": round(cost, 5)})
            print(f"  → {kind}{(': ' + why[:160]) if why else ''}  (₹{cost * USD_TO_INR:.2f})")
            save()

    print("\n=== summary (₹ at ₹%.0f/$) ===" % USD_TO_INR)
    for arm in ("off", "on"):
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        built = sum(r["outcome"] == "built" for r in rs)
        cost = sum(r["cost_usd"] for r in rs) * USD_TO_INR
        kinds = {}
        for r in rs:
            kinds[r["outcome"]] = kinds.get(r["outcome"], 0) + 1
        fits = [f"{r['fit']:.0%}{'✓' if r['outcome'] == 'built' else '✗'}" for r in rs if r["fit"] is not None]
        print(f"  {arm:3}: built {built}/{len(rs)}; {kinds}; ₹{cost:.1f} total, "
              f"₹{cost / built:.1f} per built question" if built else
              f"  {arm:3}: built 0/{len(rs)}; {kinds}; ₹{cost:.1f} total")
        print(f"       Jev scores (✓ built, ✗ not): {', '.join(fits)}")
    print(f"  total spend ₹{models.SPEND.total_cost * USD_TO_INR:.1f}; results {path}")
    save()


if __name__ == "__main__":
    main()
