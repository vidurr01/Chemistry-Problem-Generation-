"""
audit_inorg_products.py — run the blind product check (inorg_products.check, GPT-6 Luna) over EVERY reaction the
hidden-products kind can draw, once, offline (live review 2026-11-26, item 2: graph audit).

Live runs kept losing draws to reactions whose product depends on an unstated condition (SO2 vs H2SO3, NO2 vs HNO2,
H2O vs O2, P4 + NaOH). This finds them all at once instead of one paid draw at a time. Writes
outputs/audit_inorg_products.json (every row: graph product, checker's answer, agreed or not) and prints the
disagreements for the author to decide (pin the condition, split into condition variants, or block the reaction).
Nothing in knowledge/ is changed.

    python tools/audit_inorg_products.py [--cap 10]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import run_groundup_final as entry  # noqa: E402
from core import models  # noqa: E402
from core.pipeline import adapters, inorg_products as P, inorg_qfirst as IQ  # noqa: E402
from tools.spend_cap import RS_PER_USD, SpendCap  # noqa: E402

BATCH = 8
OUT = os.path.join(ROOT, "outputs", "audit_inorg_products.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, default=10.0, help="hard spend cap in rupees")
    args = ap.parse_args()
    cap = SpendCap(args.cap)
    ad = adapters.InorganicAdapter(entry.get_subject_config("inorganic"), random.Random(1))
    g = IQ._graph(ad)
    edges = P.with_naive(list(g["edges"].values())) + P.variant_edges()
    pool = P._pool(edges)
    report = []
    for fam, rows in sorted(pool.items()):
        for i in range(0, len(rows), BATCH):
            cap.check(f"{fam} batch {i // BATCH + 1}")
            chunk = rows[i:i + BATCH]
            bad = P.check({"_products": {"rows": chunk, "family": fam}})
            badmap = {b["edge"]: b for b in bad}
            for r in chunk:
                b = badmap.get(r["edge"]["id"])
                report.append({"family": fam, "edge": r["edge"]["id"], "reaction": r["text"], "element": r["element"],
                               "graph": r["edge"]["to"], "agree": b is None,
                               "checker": b["checker"] if b else None, "reason": b["reason"] if b else None})
            print(f"  {fam}: {min(i + BATCH, len(rows))}/{len(rows)} checked, {len(bad)} disagree in this batch")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    dis = {}
    for row in report:
        if not row["agree"]:
            dis.setdefault(row["edge"], row)
    print(f"\n{len(report)} rows, {len({r['edge'] for r in report})} reactions; {len(dis)} reactions disagree:")
    for e, row in sorted(dis.items()):
        print(f"- {e} | {row['reaction']} -> {row['graph']} | checker {row['checker']}")
    spent = float(models.SPEND.summary()["total_cost_usd"])
    print(f"\nspend ${spent:.4f} (₹{spent * RS_PER_USD:.2f} at ₹{RS_PER_USD:.0f}/$); report {OUT}")


if __name__ == "__main__":
    main()
