"""Calibrate the formula-fit threshold on real JEE Advanced questions (about half a cent).

Jev scores (qfirst.FIT_QUESTION) the formula sets of the real JEE Advanced physical questions that use
two or more formulas (docs/advanced_formula_map.py: sets known to make good questions) and as many
random draws as the pipeline makes (adapters.random_formulas). The threshold is the score that
PERCENTILE % of the real sets reach; how many random draws reach it is reported too. Written to
knowledge/fit_calibration_physical.json, which qfirst reads (FIT_FLOOR).

    python tools/calibrate_fit.py
"""
import importlib.util
import json
import os
import random
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.engine import physical as ph  # noqa: E402
from core.pipeline import qfirst  # noqa: E402

OUT = os.path.join(ROOT, "knowledge", "fit_calibration_physical.json")
PERCENTILE = 20          # the threshold: 80 % of real JEE sets score at least this
RANDOM_SETS = 60


def real_sets() -> list:
    spec = importlib.util.spec_from_file_location("fmap", os.path.join(ROOT, "docs", "advanced_formula_map.py"))
    fmap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmap)
    out = []
    for qid, (steps, mod, note) in fmap.MAP.items():
        txs = list(dict.fromkeys(s for s in steps if isinstance(s, int) and s in ph.STEPS))
        if len(txs) >= 2:
            out.append({"id": qid, "txs": txs})
    return out


def random_sets(n: int) -> list:
    from core.pipeline.adapters import adapter_for
    from subject_config import get_subject_config
    ad = adapter_for("physical", {**get_subject_config("physical"), "question_first": True}, random.Random(7))
    out, seen = [], set()
    while len(out) < n:
        c = ad.random_formulas(None)
        key = tuple(sorted(c["txs"]))
        if key not in seen:
            seen.add(key)
            out.append({"id": "random", "txs": c["txs"]})
    return out


def score(sets: list) -> list:
    def one(s):
        return qfirst.formulas_fit([ph.step(t) for t in s["txs"]], quiet=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, sets))


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    real, rand = real_sets(), random_sets(RANDOM_SETS)
    print(f"Scoring {len(real)} real JEE Advanced formula sets and {len(rand)} random draws with Jev ...")
    rs, xs = score(real), score(rand)
    real_ok = [(s, x) for s, x in zip(real, rs) if x is not None]
    rand_ok = [x for x in xs if x is not None]
    if len(real_ok) < 10 or len(rand_ok) < 10:
        sys.exit(f"✗ Jev answered too few ({len(real_ok)} real, {len(rand_ok)} random); nothing written")
    r = [x for _, x in real_ok]
    big = [x for s, x in real_ok if len(s["txs"]) >= 3]
    thr = round(pct(r, PERCENTILE), 3)
    passing = sum(x >= thr for x in rand_ok) / len(rand_ok)
    print(f"\nreal JEE sets ({len(r)}): median {statistics.median(r):.0%}, "
          f"{PERCENTILE}th percentile {thr:.0%}, range {min(r):.0%}–{max(r):.0%}")
    if big:
        print(f"  of them with 3+ formulas ({len(big)}): median {statistics.median(big):.0%}")
    print(f"random draws ({len(rand_ok)}): median {statistics.median(rand_ok):.0%}, "
          f"range {min(rand_ok):.0%}–{max(rand_ok):.0%}")
    print(f"\nthreshold {thr:.0%}: {100 - PERCENTILE}% of real JEE sets pass it, {passing:.0%} of random draws do")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"threshold": thr, "percentile": PERCENTILE, "random_pass_rate": round(passing, 3),
                   "jev_model": models.JEV_MODEL, "real": [{**s, "p": x} for s, x in real_ok],
                   "random": [{**s, "p": x} for s, x in zip(rand, xs) if x is not None]},
                  f, ensure_ascii=False, indent=1)
    print(f"written: {os.path.relpath(OUT, ROOT)}  (cost ${models.SPEND.total_cost:.4f})")


if __name__ == "__main__":
    main()
