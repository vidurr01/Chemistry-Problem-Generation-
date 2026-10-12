"""
blackboard.py — the shared notebook for one question.

Created right after the graph walk picks a chain. Every stage writes what it did to it
(the inputs chosen, the engine's answer and traps, each stem, the gate result, every
council attempt, the verifier's diagnoses, hint results, the round and retry counters),
and the generator reads it whenever it has to retry or refine. Its history is saved
with every attempt and every accepted question, so each decision can be traced.
"""

from __future__ import annotations

from datetime import datetime, timezone


class Blackboard:
    def __init__(self, subject: str):
        self.subject = subject
        self.chains: list = []          # one entry per chain tried in this run
        self.current: dict | None = None

    # ── chains ──
    def start_chain(self, candidate: dict) -> dict:
        self.current = {
            "chain": {k: v for k, v in candidate.items() if not k.startswith("_")},
            "rounds": 0,               # refinements used (too easy, or reworded for clarity)
            "events": [],
        }
        self.chains.append(self.current)
        return self.current

    def note(self, stage: str, **data) -> dict:
        """Record what a stage did on the current chain."""
        if self.current is None:
            raise RuntimeError("no chain started")
        ev = {"stage": stage, "at": datetime.now(timezone.utc).isoformat(), **data}
        self.current["events"].append(ev)
        return ev

    def last(self, stage: str) -> dict | None:
        if not self.current:
            return None
        for ev in reversed(self.current["events"]):
            if ev["stage"] == stage:
                return ev
        return None

    def tried_edges(self) -> set:
        return {tuple(c["chain"]["edges"]) for c in self.chains}

    def history(self) -> list:
        return self.chains
