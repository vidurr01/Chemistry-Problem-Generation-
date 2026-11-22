"""
Offline check of the organic start picker (core/pipeline/org_start.py) against the JEE yardstick. Paid: it calls models.

    python tools/start_batch.py --yardstick     # once: the starting compound of each real JEE Advanced organic
                                                #   scheme question -> SMILES -> features (data/jee_organic_start_features.json)
    python tools/start_batch.py --n 30          # n picks (each up to PICK_TRIES tries), then the comparison

JEE text goes ONLY to the yardstick extraction, to measure; the picker never sees it (novelty rule).
Writes outputs/start_batch.jsonl (one line per pick) and prints picks vs JEE starts vs today's pool.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics as st
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402
from core.engine.organic import pool  # noqa: E402
from core.pipeline import org_start as S  # noqa: E402
from subject_config import get_subject_config  # noqa: E402

JEE = os.path.join(ROOT, "data", "jee_advanced_organic_full.json")
YARD = os.path.join(ROOT, "data", "jee_organic_start_features.json")
OUT = os.path.join(ROOT, "outputs", "start_batch.jsonl")
INR = 88.0


def yardstick():
    qs = [q for q in json.load(open(JEE, encoding="utf-8"))["questions"] if not q.get("structures_approximate")]
    done = json.load(open(YARD, encoding="utf-8")) if os.path.exists(YARD) else {}
    for q in qs:
        if q["id"] in done:
            continue
        try:
            d = models.ask_json("yardstick", models.EXTRACTOR, "You read chemistry exam questions. Output JSON only.",
                                "If this question gives a reaction sequence or scheme, give the SMILES of its FIRST "
                                "starting compound (the organic substrate, not a reagent). Otherwise smiles is null.\n\n"
                                f"{q['text'][:3000]}\n\nReturn JSON: {{\"smiles\": \"...\" or null}}",
                                temperature=0.0, max_tokens=3000)   # 800 was cut off (it reasons first)
        except Exception as e:  # noqa: BLE001
            print(q["id"], "error", str(e)[:80])
            continue
        smi = d.get("smiles")
        rec = {"smiles": smi}
        if smi:
            try:
                rec["features"] = S.features(smi)
            except Exception:  # noqa: BLE001
                rec = {"smiles": smi, "bad": True}
        done[q["id"]] = rec
        with open(YARD + ".tmp", "w", encoding="utf-8") as f:   # saved after every answer: a stopped run
            json.dump(done, f, indent=1)                          # keeps everything it paid for
        os.replace(YARD + ".tmp", YARD)
        spent = models.SPEND.total_cost
        print(f"[{len(done)}/{len(qs)}] {q['id']} {smi}  (spent ₹{spent * INR:.2f})")
    print(f"yardstick: {sum(1 for v in done.values() if v.get('features'))} starts with features")


def _summary(name, feats):
    if not feats:
        return f"{name:10} (none)"
    n = len(feats)
    med = lambda k: st.median(f[k] for f in feats)  # noqa: E731
    share = lambda c: f"{100 * sum(1 for f in feats if c(f)) / n:3.0f}%"  # noqa: E731
    return (f"{name:10} n={n:3}  heavy {med('heavy'):5}  ≥2 groups {share(lambda f: len(f['groups']) >= 2)}  "
            f"ring {share(lambda f: f['rings'] >= 1)}  aromatic {share(lambda f: f['aromatic'])}  "
            f"stereocentre {share(lambda f: f['stereocentres'] >= 1)}")


def batch(n: int, seed: int):
    adapter = SimpleNamespace(config=dict(get_subject_config("organic"), display_name="Organic Chemistry"),
                              subject="organic")
    rng = random.Random(seed)
    picks, used = [], []
    with open(OUT, "a", encoding="utf-8") as f:
        def log(rec):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
        for i in range(n):
            p = S.pick_start(adapter, rng, avoid=used, log=log)
            print(f"[pick {i + 1}/{n}] {'accepted: ' + p['name'] if p else 'no molecule accepted'}  "
                  f"(spent ₹{models.SPEND.total_cost * INR:.2f})")
            if p:
                used.append(p["name"])
                picks.append(p)
    yard = json.load(open(YARD, encoding="utf-8")) if os.path.exists(YARD) else {}
    jee = [v["features"] for v in yard.values() if v.get("features")]
    pl = [S.features(s) for v in pool.POOL.values() for _, s in v if "." not in s]
    print("\n== starting molecules ==")
    print(_summary("picks", [p["stats"] for p in picks]))
    print(_summary("JEE", jee))
    print(_summary("pool", pl))
    print(f"\naccepted {len(picks)} of {n} picks; tries per accepted pick "
          f"{st.mean(p['tries'] for p in picks):.1f}" if picks else f"\naccepted 0 of {n}")
    sel = [p["stats"].get("selectivity_steps", 0) for p in picks]
    if sel:
        print(f"selectivity steps in the first scheme found: median {st.median(sel)}")
    for p in picks:
        print(f"  {p['name']}  {p['smiles']}  groups {p['stats'].get('groups_reacting')}")


if __name__ == "__main__":
    sys.stdout.reconfigure(line_buffering=True)     # progress shows in a redirected log as it happens
    ap = argparse.ArgumentParser()
    ap.add_argument("--yardstick", action="store_true")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.yardstick:
        yardstick()
    if a.n:
        batch(a.n, a.seed)
    s = models.SPEND.summary()
    print(f"\nSpend: ${s['total_cost_usd']:.4f} ≈ ₹{s['total_cost_usd'] * INR:.2f} (₹{INR:.0f}/$)  {json.dumps(s['by_role'])}")
