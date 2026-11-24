"""
Blind audit of every reaction edge of the inorganic graph (2026-11-24, asked by the author): GPT-6 Luna reads
each reaction as a student would (start, reagents, conditions; never the graph's product) and names the product
containing the named element; code compares with the graph. Differences go to the author.

Same check as the live hidden-products check (core/pipeline/inorg_products.py), run once over the whole graph so
bad edges are fixed in the graph instead of being dropped (and paid for) run after run.

    python tools/audit_inorg_graph.py          -> outputs/inorg_graph_audit.json / .log
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models                              # noqa: E402
from core.engine.base import EngineError             # noqa: E402
from core.engine.chem import parse_formula           # noqa: E402
from core.engine.inorganic import species as S       # noqa: E402
from core.pipeline import inorg_products as IP       # noqa: E402
from subject_config import get_subject_config         # noqa: E402

OUT = os.path.join(ROOT, "outputs", "inorg_graph_audit.json")
BATCH = 15


def _element(e):
    """The element to name: one the start and product share (not O, H), the rarer in the product first."""
    try:
        to = parse_formula(S.to_formula_charge(e["to"])[0].split("·")[0])[0]
    except (EngineError, ValueError, IndexError):
        return None
    try:
        fr = parse_formula(S.to_formula_charge(e["from"])[0].split("·")[0])[0]
    except (EngineError, ValueError, IndexError):
        fr = {}
    shared = [x for x in to if x not in ("O", "H") and x in fr] or [x for x in to if x not in ("O", "H")] or list(to)
    return min(shared, key=lambda x: to[x]) if shared else None


def _text(e):
    src = IP._plain(e["from"])
    reagents = [r for r in (e.get("reagents") or []) if IP._plain(r) != src]
    cond = str(e.get("conditions") or "").strip().rstrip(".")
    return ", ".join([IP.pretty(e["from"])] + reagents + ([cond] if cond else []))


def ask(batch):
    lines = "\n".join(f"{i}. {t}  ->  the product containing {el}" for i, (_e, t, el) in batch)
    prompt = f"""Inorganic reactions (JEE Advanced / NCERT, standard textbook outcome). For each, name the product that
contains the named element (the main one if several contain it). Write the species actually formed (a salt as the
neutral salt, an ion in solution as the ion with its charge). If the outcome depends on conditions not given, or
the textbook gives no clear single product, say so in "doubt".
{lines}
Return JSON: {{"products": [{{"n": 1, "formula": "...", "charge": 0, "doubt": "empty, or why"}}]}}"""
    try:
        out = models.ask_json("graph_audit", IP.CHECKER, "You are an expert inorganic chemist. Output JSON only.",
                              prompt, temperature=0.0, max_tokens=12000)
        return {int(p["n"]): p for p in out.get("products") or [] if isinstance(p, dict) and "n" in p}
    except Exception as ex:                      # noqa: BLE001
        return {i: {"formula": None, "doubt": f"call failed: {str(ex)[:80]}"} for i, _ in batch}


def main():
    with open(get_subject_config("inorganic")["graph_path"], encoding="utf-8") as f:
        edges = [e for e in json.load(f)["edges"] if not e.get("synthetic")]
    rows = []
    for e in edges:
        el = _element(e)
        if el:
            rows.append((len(rows) + 1, (e, _text(e), el)))
    batches = [[(i, (r[0], r[1], r[2])) for i, r in rows[k:k + BATCH]] for k in range(0, len(rows), BATCH)]
    print(f"{len(rows)} edges ({len(edges) - len(rows)} without a nameable element) in {len(batches)} calls")
    got = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for d in ex.map(ask, batches):
            got.update(d)
    out = []
    for i, (e, text, el) in rows:
        p = got.get(i) or {}
        exact = IP.same_species(e["to"], p.get("formula"), p.get("charge"))
        form = not exact and IP.same_answer({"edge": e, "element": el, "family": "magnetism"},
                                            p.get("formula"), p.get("charge"))
        out.append({"edge": e["id"], "chapter": e.get("chapter"), "reaction": text, "element": el,
                    "graph": e["to"], "checker": p.get("formula"), "charge": p.get("charge"),
                    "doubt": str(p.get("doubt") or "").strip(),
                    "verdict": "agree" if exact else ("same_form" if form else "differs"),
                    "variants": bool(e.get("conditions_variants"))})
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"n": len(out), "spend": models.SPEND.summary(), "edges": out}, f, ensure_ascii=False, indent=1)
    from collections import Counter
    print(Counter(r["verdict"] for r in out), "doubted:", sum(bool(r["doubt"]) for r in out))
    for r in out:
        if r["verdict"] != "agree" or r["doubt"]:
            print(f"{r['verdict']:9s} {r['edge']:40s} graph={r['graph']:18s} luna={r['checker']} ({r['charge']})"
                  f"  | {r['reaction'][:80]} | {r['doubt'][:100]}")
    print("spend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
