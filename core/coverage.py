"""
coverage.py — 4-counter inverse-frequency tracker for AutoData diversity.

Each accepted question increments four independent counters:
  archetype : Archetype code (I, II, III, IV)
  chapter   : Chapter name (e.g. "Hydrocarbons", "Alcohols, Phenols & Ethers")
  edge      : Edge ID(s) used in the question's reaction chain
  concept   : Concept ID(s) from concept_book.json (tx_ids)

Sampling weight for each candidate = product of 1/(count+1) across all 4 counters.
Higher weight = less previously seen = should be prioritised.

Usage:
    cov = Coverage()                    # fresh session
    cov = Coverage.from_dict(d)         # resume from saved state
    w = cov.weight(archetype, chapter, edges, concepts)
    cov.on_acceptance(archetype, chapter, edges, concepts)
    d = cov.to_dict()                   # persist to disk
"""

import json
import math
from collections import defaultdict
from pathlib import Path

_SAVE_PATH = Path(__file__).parent.parent / "coverage_state.json"


class Coverage:
    def __init__(self):
        self._archetype: dict[str, int] = defaultdict(int)
        self._chapter:   dict[str, int] = defaultdict(int)
        self._edge:      dict[str, int] = defaultdict(int)
        self._concept:   dict[str, int] = defaultdict(int)

    # ── Weight ─────────────────────────────────────────────────────────────────

    def weight(
        self,
        archetype: str,
        chapter: str,
        edges: list[str],
        concepts: list[str],
    ) -> float:
        """
        Inverse-frequency weight for this candidate.
        w = prod(1/(count+1)) across the 4 dimensions.
        Range: (0, 1]. Equals 1.0 only if none of the 4 have been seen before.
        """
        w_arch    = 1.0 / (self._archetype[archetype] + 1)
        w_chapter = 1.0 / (self._chapter[chapter] + 1)

        # For multi-edge/multi-concept, use the minimum weight (most-seen controls)
        if edges:
            w_edge = min(1.0 / (self._edge[e] + 1) for e in edges)
        else:
            w_edge = 1.0

        if concepts:
            w_concept = min(1.0 / (self._concept[c] + 1) for c in concepts)
        else:
            w_concept = 1.0

        return w_arch * w_chapter * w_edge * w_concept

    def log_weight(
        self,
        archetype: str,
        chapter: str,
        edges: list[str],
        concepts: list[str],
    ) -> float:
        """Log-scale weight (more numerically stable for many dimensions)."""
        w = self.weight(archetype, chapter, edges, concepts)
        return math.log(w) if w > 0 else -math.inf

    # ── Update ─────────────────────────────────────────────────────────────────

    def on_acceptance(
        self,
        archetype: str,
        chapter: str,
        edges: list[str],
        concepts: list[str],
    ) -> None:
        """Increment all 4 counters. Call after a question passes 3-gate."""
        self._archetype[archetype] += 1
        self._chapter[chapter]     += 1
        for e in edges:
            self._edge[e] += 1
        for c in concepts:
            self._concept[c] += 1

    # ── Introspection ──────────────────────────────────────────────────────────

    def top_saturated(self, n: int = 10) -> dict:
        """Return the n most-seen items in each counter (for monitoring)."""
        def top(d, k):
            return sorted(d.items(), key=lambda x: -x[1])[:k]
        return {
            "archetype": top(self._archetype, n),
            "chapter":   top(self._chapter,   n),
            "edge":      top(self._edge,       n),
            "concept":   top(self._concept,    n),
        }

    def total_accepted(self) -> int:
        """Total questions accepted so far (sum of archetype counter)."""
        return sum(self._archetype.values())

    # ── Persistence ────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "archetype": dict(self._archetype),
            "chapter":   dict(self._chapter),
            "edge":      dict(self._edge),
            "concept":   dict(self._concept),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Coverage":
        cov = cls()
        cov._archetype.update(d.get("archetype", {}))
        cov._chapter.update(d.get("chapter", {}))
        cov._edge.update(d.get("edge", {}))
        cov._concept.update(d.get("concept", {}))
        return cov

    def save(self, path: Path | str = _SAVE_PATH) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: Path | str = _SAVE_PATH) -> "Coverage":
        p = Path(path)
        if not p.exists():
            return cls()
        with open(p, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))
