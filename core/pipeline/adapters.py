"""
Subject adapters: what the pipeline needs from a subject's engine.

    kind                                       "chains" (computed) or "facts" (MCQ/MSQ)
    candidates(coverage, chapter, n, exclude)  question ideas, best first
    input_spec(plan)                           the inputs whose values must be proposed
    compute(plan, values)                      answer, trace, traps (core.engine.base.ChainResult)
    refine_modes                               what a "too easy" refinement may change

Physical chains and physical facts are implemented; inorganic and organic follow the
same interface.
"""

from __future__ import annotations

import random

from core.engine.base import ChainResult, EngineError, plan_chain, run_chain
from core.graph_traversal import load_graph, sample_chains

SINGLE_STEP_WEIGHT = 0.5      # a step that cannot join any chain is offered alone, at half weight


class PhysicalAdapter:
    subject = "physical"
    kind = "chains"
    refine_modes = ("new_inputs", "reword")

    def __init__(self, config: dict, rng=None):
        from core.engine import physical
        self.engine = physical
        self.config = config
        self.graph = load_graph(config["graph_path"])
        self.rng = rng or random.Random()
        self.isolated = self._isolated_edges()

    def _isolated_edges(self) -> list:
        """Edges no other edge can follow or precede: complete single-concept questions."""
        g, ph = self.graph, self.engine
        into = {}
        for e in g.edges:
            into.setdefault(e["to"], []).append(e)
        out = []
        for e in g.edges:
            nxt = any(ph.can_follow(e, e2) for e2 in g.edges_from.get(e["to"], []) if e2 is not e)
            prv = any(ph.can_follow(e1, e) for e1 in into.get(e["from"], []) if e1 is not e)
            if not nxt and not prv:
                out.append(e)
        return out

    def _candidate(self, coverage, edges: list, nodes: list, chapters: list, weight: float):
        steps = self.engine.chain_steps(edges, self.rng)
        if steps is None:
            return None
        try:
            plan = plan_chain(steps)
        except EngineError:
            return None
        trap_ids = sorted({t.id for s in steps for t in s.traps})
        return {"edges": [e["id"] for e in edges], "nodes": nodes, "chapters": chapters,
                "txs": [s.tx for s in steps], "trap_ids": trap_ids,
                "weight": weight * coverage.trap_weight(trap_ids),
                "description": " → ".join(f"{s.asks} [{s.formula}]" for s in steps),
                "_steps": steps, "_plan": plan}

    def candidates(self, coverage, chapter=None, n: int = 6, exclude=()) -> list:
        g, ph = self.graph, self.engine
        raw = sample_chains(g, coverage, None, chapter, n_options=max(40, n * 8), depth=3,
                            can_follow=ph.can_follow,
                            validate=lambda es: ph.chain_steps(es, self.rng) is not None)
        out = []
        for c in raw:
            if tuple(c["edges"]) in exclude:
                continue
            cand = self._candidate(coverage, [g.edge_map[e] for e in c["edges"]], c["nodes"], c["chapters"], c["weight"])
            if cand:
                out.append(cand)
        for e in self.isolated:
            if (e["id"],) in exclude or (chapter and chapter.lower() not in e.get("chapter", "").lower()):
                continue
            w = coverage.weight(None, None, [e["id"]], []) * SINGLE_STEP_WEIGHT
            cand = self._candidate(coverage, [e], [e["from"], e["to"]], [e.get("chapter", "")], w)
            if cand:
                out.append(cand)
        out.sort(key=lambda x: (-x["weight"], self.rng.random()))
        return out[:n]

    def plan(self, txs: list):
        return plan_chain([self.engine.step(t) for t in txs])

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
        return "\n".join(f"Step {i + 1}: {st.asks} — {st.formula}" for i, st in enumerate(plan.steps))


class PhysicalFactsAdapter:
    """MCQ/MSQ questions built by code from core/engine/physical/facts_data.py."""
    subject = "physical"
    kind = "facts"
    refine_modes = ("new_inputs", "reword")

    def __init__(self, config: dict, rng=None):
        from core.engine.physical.facts_data import BY_ID, FACTS
        self.facts, self.by_id = FACTS, BY_ID
        self.config = config
        self.graph = load_graph(config["graph_path"])       # for --chapter validation only
        self.rng = rng or random.Random()

    def candidates(self, coverage, chapter=None, n: int = 6, exclude=()) -> list:
        from core.engine.facts import MODES, build
        out = []
        for src in self.facts:
            if chapter and chapter.lower() not in src.topic.lower():
                continue
            mode = self.rng.choice(MODES)
            key = (f"fact:{src.id}",)
            if key in exclude:
                continue
            try:
                fq = build(src, mode, self.rng)
            except EngineError:
                continue
            w = coverage.weight(None, src.topic, [key[0]], [str(t) for t in src.tx])
            out.append({"edges": [key[0]], "nodes": [src.id], "chapters": [src.topic], "txs": list(src.tx),
                        "trap_ids": [], "weight": w, "description": src.title, "_fact": fq})
        out.sort(key=lambda x: (-x["weight"], self.rng.random()))
        return out[:n]

    def rebuild(self, cand: dict) -> dict:
        """Same source, fresh statements (avoiding the previous ones), for a 'new inputs' refinement."""
        from core.engine.facts import MODES, build
        src = self.by_id[cand["nodes"][0]]
        prev = set(cand["_fact"].options)
        cand = dict(cand)
        cand["_fact"] = build(src, self.rng.choice(MODES), self.rng, avoid=prev)
        return cand

    @staticmethod
    def result(fq) -> ChainResult:
        verdicts = {f"({chr(65 + i)})": ("TRUE" if t else "FALSE") for i, t in enumerate(fq.truth)}
        trace = [{"tx": list(fq.tx), "src": fq.source, "dst": "answer",
                  "formula": "each statement checked against the fact table",
                  "inputs": {"question": fq.lead, "options": fq.option_lines},
                  "outputs": {"statement truth": verdicts, "answer": fq.answer}}]
        return ChainResult(answer=fq.answer, unit="", kind="letters", asks=fq.lead, trace=trace,
                           traps=list(fq.traps), constants=[])


ADAPTERS = {"physical": PhysicalAdapter}
FACT_ADAPTERS = {"physical": PhysicalFactsAdapter}


def adapter_for(subject: str, config: dict, rng=None, kind: str = "chains"):
    table = FACT_ADAPTERS if kind == "facts" else ADAPTERS
    if subject not in table:
        raise NotImplementedError(f"the {subject} engine ({kind}) is not wired into the pipeline yet")
    return table[subject](config, rng)
