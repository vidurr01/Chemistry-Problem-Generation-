"""
enrich_inorg_reagents.py: propose other reagents for the inorganic graph's conversions, check them blind, and
keep only what a hand review passes (the author, 2026-11-25: enrich the graph before reagent-choice questions).

Why: the graph records ONE way to do most conversions (5 of 286 start -> product pairs have two), so a
"which reagent(s) convert A to B" question could only be single-correct, and a reagent missing from the graph is no
proof it fails, so a distractor could secretly be right.

For each sampled conversion A -> B (already in the graph):
    1. propose  models.DESIGNER lists up to 3 OTHER standard reagent/condition sets giving B from A, and up to 2
                that react with A but give a DIFFERENT main product C (named): honest distractors and new edges
    2. check    GPT-6 Luna (another model family) names the main product of "A + reagents, conditions" blind,
                without the proposal; a proposal survives only if it names the proposer's product
                (same formula and charge, or the same complex as salt or ion)
    3. review   every survivor is read by hand (and shown to the author) before anything enters the graph;
                accepted ones go to knowledge/inorg_graph_additions.json, never into reaction_graph_inorg.json
                (a rebuild would overwrite them)

    python tools/enrich_inorg_reagents.py --dry-run --n 40          # the sampled conversions and the prompt
    python tools/enrich_inorg_reagents.py --n 40                    # paid pilot
Output: outputs/inorg_reagent_proposals.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import models                                   # noqa: E402
from core.llm import write_json_atomic                    # noqa: E402
from core.pipeline import inorg_products as IP            # noqa: E402
from core.pipeline import inorg_qfirst as IQ              # noqa: E402
from core.pipeline import inorg_system as SY              # noqa: E402
from tools.spend_cap import SpendCap, SpendCapReached  # noqa: E402

OUT = os.path.join(ROOT, "outputs", "inorg_reagent_proposals.json")
BATCH = 8
PROPOSER = models.DESIGNER
CHECKER = IP.CHECKER


class _Adapter:
    config = {"graph_path": os.path.join(ROOT, "knowledge", "reaction_graph_inorg.json")}


def conversions(n, seed=20261125):
    """n graph conversions A -> B (usable, not under doubt), one per start, spread over chapters."""
    g = IQ._graph(_Adapter())
    bad = set(SY.load_memory()["unconfirmed_edges"])
    es = [e for x in g["out"].values() for e in x if SY._usable(e) and e["id"] not in bad]
    rng = random.Random(seed)
    rng.shuffle(es)
    out, starts = [], set()
    for e in es:
        if e["from"] in starts:
            continue
        starts.add(e["from"])
        out.append(e)
        if len(out) == n:
            break
    return out, g


def _line(e):
    cond = IP._conditions(e.get("conditions"))
    return f"{IP.pretty(e['from'])} + {', '.join(SY._reagents(e)) or '(heat only)'}{', ' + cond if cond else ''} -> {IP.pretty(e['to'])}"


def propose(batch):
    listing = "\n".join(f"{i + 1}. {_line(e)}" for i, e in enumerate(batch))
    prompt = f"""You are an expert in inorganic chemistry at the level of NCERT and JEE Advanced.
For each conversion below (start -> main product, with the reagent we already have), give:
  "same":  up to 3 OTHER standard reagent/condition sets that convert the SAME start mainly into the SAME product
           (only textbook-established ones; omit if unsure; never repeat the given reagent)
  "other": up to 2 reagent/condition sets that react with the SAME start but give a DIFFERENT main product, with that
           product's formula (well-known contrasts, e.g. dilute vs concentrated acid, limited vs excess reagent)
Write formulas, not names (KOH, not potassium hydroxide). Conditions short ("heat", "conc.", "excess", "573 K").
{listing}
Return JSON: {{"items": [{{"n": 1, "same": [{{"reagents": ["..."], "conditions": "..."}}],
  "other": [{{"reagents": ["..."], "conditions": "...", "product": "formula", "charge": 0}}]}}]}}"""
    return models.ask_json("designer", PROPOSER, "You are a careful inorganic chemist. Output JSON only.", prompt,
                           temperature=0.2, max_tokens=6000)


def check(rows):
    """Luna names the main product of each 'start + reagents, conditions', blind."""
    listing = "\n".join(f"{i + 1}. {r['start_pretty']} + {', '.join(r['reagents'])}"
                        f"{', ' + r['conditions'] if r['conditions'] else ''}" for i, r in enumerate(rows))
    prompt = f"""Inorganic reactions (NCERT / JEE Advanced, standard textbook outcome). For each, name the MAIN product
that contains the start's key element (a salt as the neutral salt, an ion in solution as the ion with its charge).
If the reaction does not normally occur, write "none".
{listing}
Return JSON: {{"products": [{{"n": 1, "formula": "...", "charge": 0}}]}}"""
    out = models.ask_json("step_checker", CHECKER, "You are an expert inorganic chemist. Output JSON only.", prompt,
                          temperature=0.0, max_tokens=6000)
    return {int(p.get("n")): p for p in out.get("products") or [] if isinstance(p, dict) and str(p.get("n")).isdigit()}


def agrees(expected, got):
    if not got or str(got.get("formula") or "").strip().lower() in ("", "none"):
        return False
    return IP.same_species(expected, got.get("formula"), got.get("charge")) or \
        SY.same_entity(expected, got.get("formula"), got.get("charge"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-rs", type=float, default=10.0, help="hard spend cap in rupees")
    args = ap.parse_args()
    cap = SpendCap(args.max_rs)
    convs, g = conversions(args.n)
    print(f"{len(convs)} conversions sampled; chapters: "
          + ", ".join(f"{c}:{n}" for c, n in sorted({e.get('chapter', ''): 0 for e in convs}.items())))
    if args.dry_run:
        for e in convs:
            print("  " + _line(e))
        return
    rows = []
    for i in range(0, len(convs), BATCH):
        batch = convs[i:i + BATCH]
        try:
            cap.check(f"proposal batch {i // BATCH + 1}")
        except SpendCapReached as e:
            print(e)
            break
        try:
            items = {int(x["n"]): x for x in (propose(batch).get("items") or []) if str(x.get("n")).isdigit()}
        except Exception as e:                       # noqa: BLE001
            print("proposal call failed:", str(e)[:120])
            continue
        for k, e in enumerate(batch, 1):
            have = {frozenset(SY._reagents(o)) for o in g["out"].get(e["from"], [])}
            for kind in ("same", "other"):
                for p in (items.get(k) or {}).get(kind) or []:
                    reagents = [str(r).strip() for r in p.get("reagents") or [] if str(r).strip()]
                    if not reagents or frozenset(reagents) in have:
                        continue
                    expected = e["to"] if kind == "same" else IP._graph_id(str(p.get("product") or ""),
                                                                           p.get("charge"))
                    rows.append({"edge": e["id"], "start": e["from"], "start_pretty": IP.pretty(e["from"]),
                                 "graph_product": e["to"], "kind": kind, "reagents": reagents,
                                 "conditions": str(p.get("conditions") or "").strip(), "expected": expected})
        print(f"  proposals so far: {len(rows)}", flush=True)
    for i in range(0, len(rows), 12):
        part = rows[i:i + 12]
        try:
            cap.check(f"check batch {i // 12 + 1}")
            got = check(part)
        except SpendCapReached as e:
            print(e)
            break
        except Exception as e:                       # noqa: BLE001
            got = {}
            print("check call failed:", str(e)[:120])
        for k, r in enumerate(part, 1):
            r["checker"] = {x: (got.get(k) or {}).get(x) for x in ("formula", "charge")}
            r["confirmed"] = agrees(r["expected"], got.get(k))
            if r["kind"] == "other" and r["expected"] == r["graph_product"]:
                r["confirmed"] = False               # an "other" product that is the same product is no contrast
    write_json_atomic(OUT, {"proposer": PROPOSER, "checker": CHECKER, "rows": rows,
                            "spend": models.SPEND.summary()}, ensure_ascii=False)
    n_ok = sum(r["confirmed"] for r in rows)
    print(f"proposals {len(rows)} | confirmed blind {n_ok} "
          f"(same product {sum(r['confirmed'] for r in rows if r['kind'] == 'same')}, "
          f"other product {sum(r['confirmed'] for r in rows if r['kind'] == 'other')})")
    print("spend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
