"""
Replay every step the blind step check disagreed with (outputs/queue_step_disagreement_organic.json) through the
CURRENT graph scope: a step the scope now refuses is fixed (the engine would not draw it again); a step it still
lets through is listed for reading by hand. Free (no model calls).

    python tools/replay_step_holds.py            # summary + the steps still allowed
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.engine.base import EngineError  # noqa: E402
from core.engine.organic import scope  # noqa: E402

QUEUE = os.path.join(ROOT, "outputs", "queue_step_disagreement_organic.json")
GRAPH = os.path.join(ROOT, "knowledge", "reaction_graph.json")


def main() -> int:
    with open(GRAPH, encoding="utf-8") as f:
        edges = {e["id"]: e for e in json.load(f)["edges"]}
    with open(QUEUE, encoding="utf-8") as f:
        held = json.load(f)
    seen, blocked, allowed = set(), [], []
    for item in held:
        for st in item.get("steps", []):
            key = (st.get("edge"), st.get("substrate"))
            if key in seen or not key[0] or not key[1]:
                continue
            seen.add(key)
            e = edges.get(key[0])
            if e is None:
                blocked.append((item["id"], st, "edge gone"))
                continue
            if not scope.trusted(e):
                blocked.append((item["id"], st, "edge left out"))
                continue
            try:
                scope.check(e, key[1])
            except EngineError as ex:
                blocked.append((item["id"], st, str(ex)))
                continue
            allowed.append((item["id"], st))
    print(f"{len(seen)} distinct held steps: {len(blocked)} now refused by scope, {len(allowed)} still allowed\n")
    for hid, st in allowed:
        print(f"[{hid}] {st['edge']}  ({st.get('reagent')})")
        print(f"    substrate {st['substrate']}")
        print(f"    engine    {st.get('engine')}")
        print(f"    checker   {st.get('checker_product') or '(no single product)'}: {st.get('reason', '')[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
