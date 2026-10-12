"""
Subject adapters: what the pipeline needs from a subject's engine.

    candidates(coverage, chapter, n, exclude)  chains the engine can compute, best first
    input_spec(plan)                           the inputs whose values must be proposed
    compute(plan, values)                      answer, trace, traps (core.engine.base.ChainResult)
    refine_modes                               what a "too easy" refinement may change

Physical is implemented; inorganic and organic follow the same interface.
"""

from __future__ import annotations

import random

from core.engine.base import EngineError, plan_chain, run_chain
from core.graph_traversal import load_graph, sample_chains


class PhysicalAdapter:
    subject = "physical"
    refine_modes = ("new_inputs", "reword")

    def __init__(self, config: dict, rng=None):
        from core.engine import physical
        self.engine = physical
        self.config = config
        self.graph = load_graph(config["graph_path"])
        self.rng = rng or random.Random()

    # ── chains ──
    def candidates(self, coverage, chapter=None, n: int = 6, exclude=()) -> list:
        g, ph = self.graph, self.engine
        raw = sample_chains(g, coverage, None, chapter, n_options=max(40, n * 8), depth=3,
                            can_follow=ph.can_follow,
                            validate=lambda es: ph.chain_steps(es, self.rng) is not None)
        out = []
        for c in raw:
            if tuple(c["edges"]) in exclude:
                continue
            steps = ph.chain_steps([g.edge_map[e] for e in c["edges"]], self.rng)
            if steps is None:
                continue
            try:
                plan = plan_chain(steps)
            except EngineError:
                continue
            trap_ids = sorted({t.id for s in steps for t in s.traps})
            out.append({
                "edges": c["edges"], "nodes": c["nodes"], "chapters": c["chapters"],
                "txs": [s.tx for s in steps], "trap_ids": trap_ids,
                "weight": c["weight"] * coverage.trap_weight(trap_ids),
                "description": " → ".join(f"{s.asks} [{s.formula}]" for s in steps),
                "_steps": steps, "_plan": plan,
            })
        out.sort(key=lambda x: (-x["weight"], self.rng.random()))
        return out[:n]

    def plan(self, txs: list):
        return plan_chain([self.engine.step(t) for t in txs])

    # ── inputs ──
    @staticmethod
    def input_spec(plan) -> list:
        spec = []
        for qk, g in plan.givens.items():
            p = g.param
            spec.append({"key": qk, "desc": p.desc, "unit": p.unit, "kind": p.kind,
                         "range": [p.lo, p.hi] if p.lo is not None or p.hi is not None else None,
                         "choices": list(p.choices) if p.choices else None,
                         "step": g.steps[0]})
        return spec

    def compute(self, plan, values: dict):
        return run_chain(plan, values)

    @staticmethod
    def chain_text(plan) -> str:
        lines = []
        for i, st in enumerate(plan.steps):
            lines.append(f"Step {i + 1}: {st.asks} — {st.formula}")
        return "\n".join(lines)


ADAPTERS = {"physical": PhysicalAdapter}


def adapter_for(subject: str, config: dict, rng=None):
    if subject not in ADAPTERS:
        raise NotImplementedError(f"the {subject} engine is not wired into the pipeline yet")
    return ADAPTERS[subject](config, rng)
