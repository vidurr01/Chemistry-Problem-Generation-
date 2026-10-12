"""
Review queues — one file per reason, for the questions code cannot settle.

    engine_unknown         the engine could not compute an input set it was handed
    gate_unreadable        the gate could not read the facts back out of a stem
    engine_wrong           the mismatch verifier judged the engine's answer or the question wrong
    objection_unresolved   a council objection neither the gate nor the verifier could settle

Each file is outputs/queue_<reason>_<subject>.json: a list of items, newest last.
`python tools/results.py queue ...` lists, clears or dismisses them.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from core.llm import write_json_atomic

REASONS = ("engine_unknown", "gate_unreadable", "engine_wrong", "objection_unresolved")
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "outputs")


def path(reason: str, subject: str) -> str:
    if reason not in REASONS:
        raise ValueError(f"unknown queue {reason!r}")
    return os.path.abspath(os.path.join(_OUT, f"queue_{reason}_{subject}.json"))


def load(reason: str, subject: str) -> list:
    p = path(reason, subject)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def add(reason: str, subject: str, item: dict) -> str:
    """Append an item; returns its id."""
    items = load(reason, subject)
    qid = f"{reason[:3].upper()}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{len(items) + 1}"
    items.append({"id": qid, "reason": reason, "queued_at": datetime.now(timezone.utc).isoformat(), **item})
    write_json_atomic(path(reason, subject), items, ensure_ascii=False)
    return qid


def remove(reason: str, subject: str, item_id: str) -> bool:
    items = load(reason, subject)
    kept = [x for x in items if x.get("id") != item_id]
    if len(kept) == len(items):
        return False
    write_json_atomic(path(reason, subject), kept, ensure_ascii=False)
    return True
