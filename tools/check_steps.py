"""
Measure a blind per-step product check (2026-11-24, approved by the author "measure first"): strong models are shown
one reaction (substrate SMILES + reagent, never the engine's product) and asked for the major organic product; code
compares with the engine. Measured on known-good steps (tests/organic_golden.json, hand-checked) and known-bad steps
(the engine's real mistakes, below). Nothing in the pipeline uses this yet.

    python tools/check_steps.py --n 10            # a few good + a few bad, prints the cost
    python tools/check_steps.py                   # everything
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


from core import models  # noqa: E402
from core.engine.organic.labels import REAGENT_LABEL  # noqa: E402
from core.pipeline import org_step_check as SC  # noqa: E402

CHECKERS = [("gemini-3.1-pro", models.DESIGNER), ("gpt-6-luna", SC.STEP_CHECKER)]
OUT = os.path.join(ROOT, "outputs", "step_check_calibration.json")

# The engine's real mistakes (input, reagent edge, what the engine gave). Live runs 6-8 and earlier rule bugs.
BAD = [
    ("run 6: PCl5 took the phenol OH, not the CHO", "phenol_to_aryl_halide_pclslowreact", "C=CCc1ccc(O)c(C=O)c1",
     "C=CCc1ccc(Cl)c(C=O)c1"),
    ("run 7: 2° benzylic alcohol + conc. H2SO4 383 K → hydrogen sulphate", "alcohol_to_sulfonate_conchso",
     "C=CCc1ccc(OC)c(C(C)O)c1", "C=CCc1ccc(OC)c(C(C)OS(=O)(=O)O)c1"),
    ("run 8: Markovnikov hydration of an enone", "alkene_to_alcohol_ho", "O=CC1=CCCCC1=O", "O=CC1(O)CCCCC1=O"),
    ("carbylamine on an amide", "amine_to_isocyanide_carbylaminetest", "CCCC(N)=O", "[C-]#[N+]C(=O)CCC"),
    ("HI 'cleaving' an epoxide to CH3I", "ether_to_alkyl_halide_conchxhihbra", "CC1CO1", "CI"),
    ("NaBH4 bug: every ketone gave propan-2-ol", "ketone_to_alcohol_nabh", "O=C1CCCCC1", "CC(C)O"),
    ("Wolff–Kishner bug: every ketone gave propane", "ketone_to_alkane_nhnh", "CCC(=O)CCC", "CCC"),
    ("isocyanide hydrolysis gave the N-methyl amine", "isocyanide_to_amine_hydrolysis", "CC[N+]#[C-]", "CCNC"),
    ("PCl5 on a phenol with a 2° alcohol present", "phenol_to_aryl_halide_pclslowreact", "CC(O)c1ccc(O)cc1",
     "CC(O)c1ccc(Cl)cc1"),
    ("HBr 1 equiv added to the alkyne of an enyne", "alkyne_to_vinyl_halide_hx1equiv", "C#CCCCCCCC=C",
     "C=CCCCCCCC(Br)=C"),
    ("SN2 on a neopentyl bromide", "alkyl_halide_to_alcohol_naoh", "CC(C)(C)CBr", "CC(C)(C)CO"),
    ("H2/Ni nitrile reduction kept a benzylic C–Br", "nitrile_to_amine_h", "N#Cc1ccc(CBr)cc1", "NCc1ccc(CBr)cc1"),
]

def ask(model: str, substrate: str, reagent: str) -> dict:
    return SC.ask(substrate, reagent, model=model)


canon_set, verdict = SC.canon_set, SC.verdict      # the pipeline's own check (core/pipeline/org_step_check.py)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="a sample: n/2 good and n/2 bad steps (0 = all)")
    ap.add_argument("--luna-only", action="store_true", help="GPT-6 Luna as the only checker (the author, 2026-11-24)")
    ap.add_argument("--reuse", help="an earlier results file: its steps are not asked again, and its rows for the "
                                    "chosen checkers are counted in the report")
    ap.add_argument("--good", type=int, default=None, help="how many new good steps (random); all bad ones not "
                                                           "measured yet are always added")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    checkers = [c for c in CHECKERS if c[0] == "gpt-6-luna"] if args.luna_only else CHECKERS
    with open(os.path.join(ROOT, "tests", "organic_golden.json"), encoding="utf-8") as f:
        golden = json.load(f)["cases"]
    good = [("golden", eid, s, p) for eid, (s, p) in sorted(golden.items())]
    bad = list(BAD)
    old_rows = []
    if args.reuse:
        with open(args.reuse, encoding="utf-8") as f:
            old_rows = [r for r in json.load(f)["rows"] if r["checker"] in {c[0] for c in checkers}]
        done = {(r["edge"], r["substrate"]) for r in old_rows}
        good = [g for g in good if (g[1], g[2]) not in done]
        bad = [b for b in bad if (b[1], b[2]) not in done]
    if args.good is not None:
        good = random.Random(1).sample(good, min(args.good, len(good)))
    elif args.n:
        rng = random.Random(0)
        good = rng.sample(good, args.n - args.n // 2)
        bad = rng.sample(bad, min(len(bad), args.n // 2))
    items = [("good", *g) for g in good] + [("bad", *b) for b in bad]
    jobs = [(it, name, slug) for it in items for name, slug in checkers]
    print(f"{len(items)} new steps ({len(good)} good, {len(bad)} bad) x {len(checkers)} checker(s)"
          + (f"; {len({(r['edge'], r['substrate']) for r in old_rows})} steps reused" if old_rows else ""))

    def run(job):
        (kind, why, eid, s, p), name, slug = job
        d = ask(slug, s, REAGENT_LABEL[eid])
        return {"kind": kind, "why": why, "edge": eid, "substrate": s, "engine": p, "checker": name,
                "reply": d, "verdict": verdict(p, d)}
    with ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(run, jobs))
    new_rows = rows
    rows = old_rows + rows

    by_step = {}
    for r in rows:
        by_step.setdefault((r["kind"], r["edge"], r["substrate"]), {})[r["checker"]] = r
    flagged = {"good": 0, "bad": 0}
    n = {"good": 0, "bad": 0}
    print()
    for (kind, eid, s), rs in by_step.items():
        n[kind] += 1
        vs = {c: rs[c]["verdict"] for c in rs}
        flag = any(v != "agree" for v in vs.values())     # the gate rule: any checker not agreeing holds the step
        flagged[kind] += flag
        mark = ("✓ caught" if flag else "✗ MISSED") if kind == "bad" else ("✗ false alarm" if flag else "✓ passed")
        print(f"{mark:14s} {kind:4s} {eid:44s} {s:28s} " + "  ".join(f"{c}={v}" for c, v in vs.items()))
        if flag:
            for c, r in rs.items():
                if r["verdict"] != "agree":
                    print(f"{'':20s}{c}: {str(r['reply'].get('product_smiles', r['reply'].get('error')))[:60]}"
                          f"  ({str(r['reply'].get('reason', ''))[:110]})")
    cost = models.SPEND.total_cost
    rate = 88
    print(f"\nbad steps caught: {flagged['bad']}/{n['bad']}; good steps flagged (false alarms): {flagged['good']}/{n['good']}")
    print(f"cost of this run: ${cost:.4f} ≈ ₹{cost * rate:.2f} at ₹{rate}/$; per new step ≈ "
          f"₹{cost * rate / max(1, len(items)):.2f}")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"checkers": checkers, "rows": rows, "new_rows": len(new_rows), "cost_usd": cost}, f,
                  ensure_ascii=False, indent=1)
    print(f"written: {os.path.relpath(args.out, ROOT)}")


if __name__ == "__main__":
    main()
