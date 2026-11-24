"""
One-time blind audit of every inorganic property a count question can ask (2026-11-24, approved by the author).

GPT-6 Luna is shown each species (with the atom to look at) and asked the property as JEE / NCERT teaches it,
never the code's value; code compares. Every difference goes to the author, who rules: engine bug, a convention
to encode (like PH3 "unhybridised"), or a species to leave out. Live run 4 (PbCl2 "sp2") is why: conventions were
being found one paid run at a time.

Covers the species-list rows (core/pipeline/inorg_list.py ROWS) and the hidden-products pool
(core/pipeline/inorg_products.py). Writes outputs/inorg_prop_audit.json.

    python tools/audit_inorg_props.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models                              # noqa: E402
from core.engine.inorganic import properties as P    # noqa: E402
from core.pipeline import inorg_list as IL           # noqa: E402
from core.pipeline import inorg_products as IP       # noqa: E402
from subject_config import get_subject_config         # noqa: E402

OUT = os.path.join(ROOT, "outputs", "inorg_prop_audit.json")
BATCH = 15
SHAPES = ["linear", "bent", "trigonal planar", "trigonal pyramidal", "T-shaped", "tetrahedral", "square planar",
          "see-saw", "trigonal bipyramidal", "square pyramidal", "octahedral", "pentagonal bipyramidal",
          "distorted octahedral"]
HYBRIDS = ["sp", "sp2", "sp3", "dsp2", "sp3d", "sp3d2", "d2sp3", "sp3d3", "unhybridised"]
ASK = {"geometry": ("geometry around the named atom", SHAPES),
       "hybridisation": ("hybridisation of the named atom", HYBRIDS),
       "magnetism": ("magnetic behaviour of the species", ["paramagnetic", "diamagnetic"]),
       "polarity": ("polarity of the molecule", ["polar", "non-polar"])}


def _norm(v) -> str:
    s = IP._plain(str(v)).lower().replace("-", "").replace(" ", "")
    return {"seesaw": "seesaw", "vshaped": "bent", "angular": "bent", "nonpolar": "nonpolar"}.get(s, s)


def items():
    """[{"id", "source", "species", "element", "family", "code"}], one per (species, property)."""
    out, seen = [], set()
    fam_of = {"shape": "geometry", "hybridisation": "hybridisation", "magnetism": "magnetism", "polarity": "polarity"}
    for sid, row in IL.ROWS.items():
        for prop, fam in fam_of.items():
            if row.get(prop) is None:
                continue
            if row["class"] == "complex":
                el = next(e for e in re.findall(r"[A-Z][a-z]?", sid) if P.is_transition(e))
            elif row["class"] == "molecule":
                el = IL.CENTRAL.get(sid) or P.vsepr(sid, IL.CENTRAL.get(sid))["central"]
            else:
                el = None
            key = (IL.pretty(sid), fam)
            if key not in seen:
                seen.add(key)
                out.append({"source": "list", "species": IL.pretty(sid), "graph_id": sid, "element": el,
                            "family": fam, "code": row[prop]})
    with open(get_subject_config("inorganic")["graph_path"], encoding="utf-8") as f:
        edges = json.load(f)["edges"]
    for fam, rows in IP._pool(edges).items():
        for r in rows:
            key = (IP.pretty(r["edge"]["to"]), fam)
            if key not in seen:
                seen.add(key)
                out.append({"source": f"products ({r['key']})", "species": IP.pretty(r["edge"]["to"]),
                            "graph_id": r["edge"]["to"], "element": r["element"], "family": fam,
                            "code": r["value"]})
    for i, it in enumerate(out, 1):
        it["id"] = i
    return out


def ask(batch):
    lines = []
    for it in batch:
        what, choices = ASK[it["family"]]
        atom = f" (named atom: {it['element']})" if it["element"] and it["family"] in ("geometry", "hybridisation") else ""
        lines.append(f"{it['id']}. {it['species']}{atom}: {what}; choose from {', '.join(choices)}")
    prompt = f"""For each species, give the answer a JEE Advanced / NCERT answer key would give (the species as it is
taught: a salt or solid by its usual textbook description). If textbooks genuinely differ or JEE would not ask it
of this species, say so in "doubt".
{chr(10).join(lines)}
Return JSON: {{"answers": [{{"id": 1, "value": "one of the choices", "doubt": "empty, or why books differ / not asked"}}]}}"""
    try:
        out = models.ask_json("prop_audit", IP.CHECKER, "You are an expert inorganic chemist. Output JSON only.",
                              prompt, temperature=0.0, max_tokens=12000)
        return {int(a["id"]): a for a in out.get("answers") or [] if isinstance(a, dict) and "id" in a}
    except Exception as e:                       # noqa: BLE001
        return {it["id"]: {"value": None, "doubt": f"call failed: {str(e)[:80]}"} for it in batch}


def main():
    its = items()
    batches = [its[i:i + BATCH] for i in range(0, len(its), BATCH)]
    print(f"{len(its)} properties in {len(batches)} calls")
    with ThreadPoolExecutor(max_workers=6) as ex:
        got = {}
        for d in ex.map(ask, batches):
            got.update(d)
    for it in its:
        a = got.get(it["id"]) or {}
        it["checker"], it["doubt"] = a.get("value"), str(a.get("doubt") or "").strip()
        it["agree"] = it["checker"] is not None and _norm(it["checker"]) == _norm(it["code"])
    diff = [it for it in its if not it["agree"] or it["doubt"]]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"n": len(its), "n_disagree": sum(not it["agree"] for it in its),
                   "n_doubt_only": sum(it["agree"] and bool(it["doubt"]) for it in its),
                   "spend": models.SPEND.summary(), "flagged": diff, "all": its}, f, ensure_ascii=False, indent=1)
    print(f"disagree {sum(not it['agree'] for it in its)}; agree but doubted {sum(it['agree'] and bool(it['doubt']) for it in its)}")
    for it in diff:
        mark = "DIFF " if not it["agree"] else "doubt"
        print(f"{mark} {it['family']:13s} {it['species']:18s} [{it['element'] or ''}] code={it['code']} "
              f"luna={it['checker']}  {it['doubt'][:90]}")
    print("spend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
