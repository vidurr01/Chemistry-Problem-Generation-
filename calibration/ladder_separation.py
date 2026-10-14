"""
Does a model's failure rate track difficulty? (offline: reads saved calibration results)

    python calibration/ladder_separation.py llama_3_3_70b_instruct phi_4 granite_4_2_8b ...

Easy/medium Mains = the bottom two thirds of the calibrated Mains items by
calculated_difficulty; hard Mains (top third) count as Advanced-level, with the real
Advanced items. A good bottom ladder step fails Advanced-level far more often than easy
Mains (Llama 3.3 70B: 29 % vs 66 %).
"""

import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _find(x):
    if isinstance(x, dict):
        if "calculated_difficulty" in x:
            return x["calculated_difficulty"]
        x = list(x.values())
    if isinstance(x, list):
        for v in x:
            r = _find(v)
            if r is not None:
                return r
    return None


def difficulties():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "data", "jee_mains", "*.json")):
        for q in json.load(open(f, encoding="utf-8"))["questions"]:
            out[q["id"]] = _find(q)
    return out


def load(tag):
    with open(os.path.join(HERE, f"anchor_calibration_results_{tag}.json"), encoding="utf-8") as f:
        return json.load(f)


def row(tag, diff, cut):
    mains, adv = load(tag + "_mains_council"), load(tag + "_council")
    m, a = mains["records"], adv["records"]
    easy = [r for r in m if diff.get(r["id"]) is not None and diff[r["id"]] < cut]
    hard = [r for r in m if diff.get(r["id"]) is not None and diff[r["id"]] >= cut]
    fail = lambda rs: 100 * sum(1 for r in rs if not r["strong_correct"]) / max(1, len(rs))
    cost = lambda d: (d.get("spend") or {}).get("total_cost_usd", 0) / max(1, len(d["records"]))
    errors = sum(1 for r in m + a if r.get("strong_answer") is None)
    return {"model": tag, "easy": fail(easy), "hard_mains": fail(hard), "advanced": fail(a),
            "advanced_level": fail(hard + a), "gap": fail(hard + a) - fail(easy),
            "cost_per_q": (cost(mains) * len(m) + cost(adv) * len(a)) / (len(m) + len(a)),
            "no_answer": errors, "n": (len(easy), len(hard), len(a))}


def main(tags):
    diff = difficulties()
    ids = [r["id"] for r in load(tags[0] + "_mains_council")["records"]]
    ds = sorted(diff[i] for i in ids if diff.get(i) is not None)
    cut = ds[int(len(ds) * 2 / 3)]
    print(f"hard Mains: calculated_difficulty >= {cut}")
    print(f"{'model':26s} {'easy':>6s} {'hardM':>6s} {'adv':>6s} {'advLvl':>7s} {'gap':>6s} {'$/q':>8s} {'noAns':>5s}")
    for t in tags:
        r = row(t, diff, cut)
        print(f"{r['model']:26s} {r['easy']:5.1f}% {r['hard_mains']:5.1f}% {r['advanced']:5.1f}% "
              f"{r['advanced_level']:6.1f}% {r['gap']:5.1f} ${r['cost_per_q']:.5f} {r['no_answer']:5d}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["llama_3_3_70b_instruct", "llama_4_maverick", "glm_5_3_flash", "gpt_6_luna"])
