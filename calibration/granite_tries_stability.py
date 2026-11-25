"""
granite_tries_stability.py: how often the inorganic Granite verdict flips between identical runs, and how well it
separates real medium/hard Advanced questions from easier ones, for "3 tries, solved if >= 2" against
"up to 7 tries, solved if >= 4 (stop once decided)". Offline: reads the 7-try measurement made by

    python calibration/ladder_vs_students_inorganic.py --models granite-4.2-8b --tries 7 --out calibration/granite7_advanced.json
    python calibration/ladder_vs_students_inorganic.py --set mains --versions altered --models granite-4.2-8b --tries 7 --out calibration/granite7_mains.json

Each question's 7 answers give its Granite solve rate p; a rule's chance of saying "solved" is computed from p
(binomial), and two identical runs disagree with chance 2q(1-q). Student buckets as in the 2026-11-25 measurement:
hard < 10 % full marks, medium 10-30 %, easier >= 30 %.
"""

import json
import os
import sys
from math import comb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRANITE = "granite-4.2-8b"


def p_solved(p: float, n: int, need: int) -> float:
    """Chance that at least `need` of `n` independent tries are right."""
    return sum(comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(need, n + 1))


def calls_sequential(p: float, n: int = 7, need: int = 4) -> float:
    """Expected tries when asking stops as soon as `need` right or `n - need + 1` wrong."""
    stop_wrong = n - need + 1
    exp, states = 0.0, {(0, 0): 1.0}
    while states:
        nxt = {}
        for (r, w), pr in states.items():
            if r == need or w == stop_wrong:
                exp += pr * (r + w)
                continue
            for (dr, dw), q in (((1, 0), p), ((0, 1), 1 - p)):
                key = (r + dr, w + dw)
                nxt[key] = nxt.get(key, 0.0) + pr * q
        states = nxt
    return exp


def bucket(pct):
    if pct is None:
        return "mains"
    return "hard" if pct < 10 else "medium" if pct < 30 else "easier"


def main():
    rows = []
    for name in ("granite7_advanced.json", "granite7_mains.json"):
        path = os.path.join(ROOT, "calibration", name)
        if not os.path.exists(path):
            print(f"missing {path}")
            continue
        for r in json.load(open(path, encoding="utf-8"))["records"]:
            for v, x in r["versions"].items():
                tries = x["tries"].get(GRANITE) or []
                if len(tries) < 7:
                    continue
                p = sum(t["solved"] for t in tries) / len(tries)
                rows.append({"id": r["id"], "v": v, "b": bucket(r.get("pct_full")), "p": p})
    if not rows:
        sys.exit("no 7-try records")
    rules = {"3 tries, >=2": (3, 2), "7 tries, >=4": (7, 4)}
    print(f"{len(rows)} question versions with 7 Granite tries\n")
    print(f"{'rule':16} {'flip between identical runs':>28} {'Granite FAILS (= accepted), expected share':>45}")
    for label, (n, need) in rules.items():
        flips = [2 * q * (1 - q) for q in (p_solved(r["p"], n, need) for r in rows)]
        by = {}
        for r in rows:
            by.setdefault(r["b"], []).append(1 - p_solved(r["p"], n, need))
        share = "  ".join(f"{b} {sum(v) / len(v):.0%} (n={len(v)})" for b, v in sorted(by.items()))
        print(f"{label:16} {sum(flips) / len(flips):>27.0%}  {share}")
    exp = sum(calls_sequential(r["p"]) for r in rows) / len(rows)
    print(f"\nexpected Granite calls per question: 3 tries = 3.00, up to 7 stopping once decided = {exp:.2f}")
    print("\nper question (p = share of the 7 tries right):")
    for r in sorted(rows, key=lambda r: (r["b"], r["p"])):
        print(f"  {r['b']:7} {r['id']:34} {r['v']:9} p={r['p']:.2f}  "
              f"P(flip) 3-try {2 * p_solved(r['p'], 3, 2) * (1 - p_solved(r['p'], 3, 2)):.2f}  "
              f"7-try {2 * p_solved(r['p'], 7, 4) * (1 - p_solved(r['p'], 7, 4)):.2f}")


if __name__ == "__main__":
    main()
