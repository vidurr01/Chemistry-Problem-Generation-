"""
Offline audit of the organic engine: every edge of knowledge/reaction_graph.json is a rule, a concept or a
suspect; every rule is run on every pool molecule of its start node; the product must be in the edge's end node.

    python tools/audit_organic.py            # summary + every problem
    python tools/audit_organic.py --all      # also every product
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.engine.base import EngineError  # noqa: E402
from core.engine.organic import edges, mol, pool, rules  # noqa: E402


def audit(verbose=False) -> dict:
    with open(os.path.join(ROOT, "knowledge", "reaction_graph.json"), encoding="utf-8") as f:
        g = json.load(f)
    report = {"rules": 0, "concept": 0, "suspect": 0, "missing": [], "no_molecule": [], "wrong_class": [],
              "crashed": [], "products": 0, "skipped_class": 0}
    for e in g["edges"]:
        eid = e["id"]
        if eid in edges.CONCEPT:
            report["concept"] += 1
            continue
        if eid in edges.SUSPECT:
            report["suspect"] += 1
            continue
        fn = rules.RULES.get(eid)
        if fn is None:
            report["missing"].append(eid)
            continue
        report["rules"] += 1
        worked = 0
        for name, smi in pool.POOL.get(e["from"], []):
            try:
                r = rules.apply(e, smi)
            except EngineError as ex:
                if "which is not a" in str(ex):
                    report["skipped_class"] += 1
                continue
            except Exception as ex:  # noqa: BLE001
                report["crashed"].append((eid, name, f"{type(ex).__name__}: {ex}"))
                continue
            worked += 1
            report["products"] += 1
            got = mol.classes(r.product)
            if e["to"] not in got:
                report["wrong_class"].append((eid, name, r.product, sorted(got)))
            elif verbose:
                print(f"  {eid}: {name} → {r.product}" + (f"  traps {r.traps}" if r.traps else ""))
        if not worked:
            report["no_molecule"].append(eid)
    return report


if __name__ == "__main__":
    rep = audit("--all" in sys.argv)
    print(f"rules {rep['rules']}, concept {rep['concept']}, suspect {rep['suspect']}, "
          f"products checked {rep['products']}, molecules skipped (product outside the end node) {rep['skipped_class']}")
    for k in ("missing", "no_molecule", "wrong_class", "crashed"):
        print(f"\n== {k}: {len(rep[k])}")
        for x in rep[k]:
            print("  ", x)
