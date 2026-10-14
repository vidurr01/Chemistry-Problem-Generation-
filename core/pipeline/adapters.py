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

import math
import random

from core.engine.base import ChainResult, EngineError, plan_chain, plan_tree, role_ok, run_chain
from core.engine.forms import COMPARE_TX, plan_condition
from core.graph_traversal import load_graph, sample_chains

SINGLE_STEP_WEIGHT = 0.5      # a step that cannot join any chain is offered alone, at half weight
# Share of the question ideas that are trees (two branches merged by one step) and conditions
# (two systems compared): docs/advanced_formula_map.md.
TREE_SHARE = 0.25
CONDITION_SHARE = 0.10
SHAPE_TRIES = 40              # random attempts per shaped idea before giving up on it
BRANCH_MAX = 2                # steps in one branch of a tree or condition
NUMERIC_KINDS = {"real", "positive", "nonneg", "negative", "fraction", "open_fraction", "percent", "ph",
                 "temperature"}
# What a condition may ask for: a condition or amount the experimenter sets (see
# forms_layer.ADJUSTABLE_UNITS), not a property of a substance.
# Real conditions ask for a temperature, a time or a pressure ("at what temperature do the two
# rate constants become equal", "after how long are the two activities equal"); asking for
# "the concentration [R] at which two rate constants are equal" is algebra, not chemistry.
CONDITION_UNITS = {"K", "°C", "s", "h", "min", "years", "atm"}
# What a condition may compare: a quantity that changes with the conditions (a pressure, a rate
# constant, a pH, ΔG), not a property of the substance (molar mass, equivalent mass): "the
# mass at which the two molar masses are equal" means nothing.
COMPARE_UNITS = {"K", "atm", "mol", "mol L⁻¹", "mol kg⁻¹", "L", "mL", "g", "J", "kJ", "m s⁻¹",
                 "s", "V", "", "mm Hg", "s⁻¹", "mol L⁻¹ s⁻¹", "eV", "nm"}
# A substance's own constant is never the unknown of a condition, even in a time or pressure
# unit (a half-life, a Henry's law constant).
NOT_A_CONDITION = ("constant", "half-life", "life", "critical")


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
        self.edge_of_tx = {t: e for e in self.graph.edges for t in e.get("tx_ids", []) if t in physical.STEPS}
        self.mergers = self._mergers()

    # ── trees and conditions ─────────────────────────────────────────────────

    def _feeds(self, a, f, key) -> bool:
        """Can step a's result `key` be one input of the merging step f? Only a value a
        computes (not one it was given and hands on, like the T of K at T₂), and only within
        one topic: the two parts of a tree describe the one system the last step is about."""
        if a.tx == f.tx or a.tx in f.not_after:
            return False
        if key != (a.final[0] if a.final else a.answer):     # its result, not a value it hands on
            return False
        if a.domain and f.domain and a.domain != f.domain:
            return False
        p = next((p for p in f.needs if p.key == key), None)
        return p is not None and role_ok(p, a.roles.get(key))

    def _mergers(self) -> dict:
        """{merging step tx: {input key: [steps that compute it]}} for steps with two or more
        numeric inputs another step can compute (ΔG = ΔH − TΔS: ΔH and ΔS)."""
        steps = [s for s in self.engine.STEPS.values() if s.tx in self.edge_of_tx]
        out = {}
        for f in steps:
            sup = {}
            for p in f.needs:
                if p.kind not in NUMERIC_KINDS:
                    continue
                got = [a for a in steps if self._feeds(a, f, p.key)]
                if got:
                    sup[p.key] = got
            if len(sup) >= 2:
                out[f.tx] = sup
        return out

    def _shaped(self, coverage, shape: dict, branches: list, final_tx=None):
        """The candidate dict for a tree or a condition, or None if it does not plan."""
        try:
            plan = self.plan(None, shape)
        except EngineError:
            return None
        txs = [s.tx for b in branches for s in b] + ([final_tx] if final_tx is not None else [])
        edges = [self.edge_of_tx[t] for t in txs if t in self.edge_of_tx]
        if len(edges) != len(txs):
            return None
        ids = [e["id"] for e in edges]
        nodes = list(dict.fromkeys(n for e in edges for n in (e["from"], e["to"])))
        chapters = list(dict.fromkeys(e.get("chapter", "") for e in edges))
        trap_ids = sorted({t.id for s in plan.steps for t in s.traps})
        steps = [s for s in plan.steps if s.tx != COMPARE_TX]
        if shape["kind"] == "tree":
            desc = (" + ".join("(" + " → ".join(f"{s.asks} [{s.formula}]" for s in b) + ")" for b in branches)
                    + f" ⇒ {plan.steps[-1].asks} [{plan.steps[-1].formula}]")
        else:
            desc = ("condition: " + " vs ".join("(" + " → ".join(f"{s.asks} [{s.formula}]" for s in b) + ")"
                                               for b in branches))
        return {"edges": ids, "nodes": nodes, "chapters": chapters, "txs": txs, "trap_ids": trap_ids,
                "weight": coverage.weight(None, None, ids, []) * coverage.trap_weight(trap_ids),
                "description": desc, "_steps": steps, "_plan": plan, "_shape": shape}

    def _branch(self, pool, key=None, f=None):
        """A branch: a short walk chain from `pool` or a single step; when `key` is set, one
        whose last step computes that input of step f."""
        rng = self.rng
        if key is None:
            choices = [c["_steps"] for c in pool if len(c["_steps"]) <= BRANCH_MAX]
            singles = [[s] for s in self.engine.STEPS.values() if s.tx in self.edge_of_tx]
        else:
            choices = [c["_steps"] for c in pool if len(c["_steps"]) <= BRANCH_MAX
                       and self._feeds(c["_steps"][-1], f, key)]
            singles = [[a] for a in self.mergers[f.tx][key]]
        if choices and rng.random() < 0.4:
            return list(rng.choice(choices))
        return list(rng.choice(singles)) if singles else None

    def _tree(self, coverage, pool):
        rng = self.rng
        for _ in range(SHAPE_TRIES):
            ftx = rng.choice(sorted(self.mergers))
            f = self.engine.step(ftx)
            k1, k2 = rng.sample(sorted(self.mergers[ftx]), 2)
            b1, b2 = self._branch(pool, k1, f), self._branch(pool, k2, f)
            if not b1 or not b2 or b1[-1].tx == b2[-1].tx:
                continue                          # two parts ending in the same step: one quantity twice
            if any(s.domain and f.domain and s.domain != f.domain for s in b1 + b2):
                continue
            shape = {"kind": "tree", "branches": [[s.tx for s in b1], [s.tx for s in b2]], "final": ftx,
                     "feeds": {k1: 0, k2: 1}}
            cand = self._shaped(coverage, shape, [b1, b2], ftx)
            if cand:
                return cand
        return None

    def _condition(self, coverage, pool):
        rng = self.rng
        for _ in range(SHAPE_TRIES):
            a = self._branch(pool)
            if not a:
                continue
            last = a[-1]
            f, unit, kind = (last.final[0], last.final[1], last.final[2]) if last.final else \
                (last.answer, last.unit, last.kind)
            if callable(unit) or kind not in NUMERIC_KINDS or unit not in COMPARE_UNITS:
                continue
            if rng.random() < 0.6:
                b = list(a)                       # the same relation for two substances / processes
            else:
                same = [[s] for s in self.engine.STEPS.values() if s.tx in self.edge_of_tx and s.tx != last.tx
                        and not s.final and s.answer == f and s.unit == unit]
                if not same:
                    continue
                b = rng.choice(same)
            try:
                pa, pb = plan_chain(a), plan_chain(b)
            except EngineError:
                continue
            unknowns = [qk for qk, g in pa.givens.items() if g.param.kind in NUMERIC_KINDS
                        and g.param.lo is not None and g.param.hi is not None and g.param.unit in CONDITION_UNITS
                        and not any(w in g.param.desc.lower() for w in NOT_A_CONDITION)]
            if not unknowns:
                continue
            ua = rng.choice(unknowns)
            pk = pa.givens[ua].param
            match = [qk for qk, g in pb.givens.items() if g.param.key == pk.key and g.param.unit == pk.unit]
            ub = rng.choice(match) if match and rng.random() < 0.6 else None
            shape = {"kind": "condition", "branches": [[s.tx for s in a], [s.tx for s in b]],
                     "unknown": ua, "unknown_b": ub, "shared": ub is not None}
            cand = self._shaped(coverage, shape, [a, b])
            if cand and self._posable(cand):
                return cand
        return None

    def _posable(self, cand, tries: int = 8, need: int = 3) -> bool:
        """Before any model is paid: can this condition be posed for some realistic values?
        (Many pairs cannot: two osmotic pressures sharing T are equal at every T or at none.)
        Only conditions whose inputs are all numbers are offered, drawn from their ranges, and
        only if they can be posed for `need` of `tries` draws (one lucky draw means the
        generator's values will usually fail, after its call is paid)."""
        from core.pipeline import forms_layer
        plan, rng = cand["_plan"], self.rng
        spec = self.input_spec(plan)
        ok = 0
        for _ in range(tries):
            values = {}
            for qk, g in plan.givens.items():
                p = g.param
                if p.kind not in NUMERIC_KINDS or p.lo is None or p.hi is None:
                    return False
                lo, hi = float(p.lo), float(p.hi)
                values[qk] = (math.exp(rng.uniform(math.log(lo), math.log(hi))) if lo > 0 and hi / lo > 20
                              else rng.uniform(lo, hi))
                values[qk] = float(f"{values[qk]:.3g}")
            try:
                base = run_chain(plan, values)
                if forms_layer.apply_form(self, cand, spec, values, base, rng):
                    ok += 1
                    if ok >= need:
                        return True
            except (EngineError, ArithmeticError, ValueError, TypeError):
                continue
        return False

    def _with_shapes(self, coverage, chains: list, n: int, exclude=()) -> list:
        """Mix trees and conditions into the chain ideas at random places."""
        rng = self.rng
        k_tree, k_cond = round(n * TREE_SHARE), round(n * CONDITION_SHARE)
        shaped = []
        for maker, k in ((self._tree, k_tree), (self._condition, k_cond)):
            for _ in range(k):
                c = maker(coverage, chains)
                if c and tuple(c["edges"]) not in exclude:
                    shaped.append(c)
        out = chains[:max(0, n - len(shaped))]
        for c in shaped:
            out.insert(rng.randrange(len(out) + 1), c)
        return out[:n]

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
        return self._with_shapes(coverage, out, n, exclude)

    def plan(self, txs: list, shape: dict | None = None):
        """The plan of a chain (txs), or of a tree or condition (shape, from a candidate)."""
        st = self.engine.step
        if not shape:
            return plan_chain([st(t) for t in txs])
        branches = [[st(t) for t in b] for b in shape["branches"]]
        if shape["kind"] == "tree":
            return plan_tree(branches, st(shape["final"]), {k: int(v) for k, v in shape["feeds"].items()})
        return plan_condition(branches[0], branches[1], shape["unknown"], shape.get("unknown_b"))

    @staticmethod
    def _labels(plan) -> dict:
        """For a tree or condition, a label per given whose description another given shares:
        which system ('first system') or which branch result ('for the ΔH') it belongs to."""
        if not plan.branches:
            return {}
        cond = plan.steps[-1].tx == COMPARE_TX
        descs = [g.param.desc for g in plan.givens.values()]

        def where(j):
            for b, (lo, hi) in enumerate(plan.branches):
                if lo <= j <= hi:
                    return b
            return None

        out = {}
        for qk, g in plan.givens.items():
            if descs.count(g.param.desc) < 2:
                continue
            bs = {where(j) for j in g.steps}
            if len(bs) > 1:
                out[qk] = "the same for both systems" if cond else "used in more than one part"
            else:
                b = bs.pop()
                if b is None:
                    out[qk] = "for the last step"
                elif cond:
                    out[qk] = ("first", "second")[b] + " system"
                else:
                    end = plan.steps[plan.branches[b][1]]
                    out[qk] = f"for the {end.asks}"
        return out

    @classmethod
    def input_spec(cls, plan) -> list:
        spec = []
        labels = cls._labels(plan)
        for qk, g in plan.givens.items():
            p = g.param
            desc = f"{p.desc} ({labels[qk]})" if qk in labels else p.desc
            spec.append({"key": qk, "desc": desc, "unit": p.unit, "kind": p.kind,
                         "range": [p.lo, p.hi] if p.lo is not None or p.hi is not None else None,
                         "choices": list(p.choices) if p.choices else None,
                         "step": g.steps[0]})
        return spec

    def compute(self, plan, values: dict):
        return run_chain(plan, values)

    @staticmethod
    def answer_format(result):
        """The answer instruction the stem must end with, for a non-numeric answer, or None."""
        from core.engine.physical import ANSWER_FORMATS
        if isinstance(result.answer, (int, float)) and not isinstance(result.answer, bool):
            return None
        return ANSWER_FORMATS.get(result.trace[-1]["tx"]) if result.trace else None

    @staticmethod
    def chain_text(plan) -> str:
        """The steps, and for each later step what it takes from the one before: the
        generator chooses the substances, so it must know that 'the amount of the excess
        reagent left' goes on as 'amount of Cr2O7²⁻ reduced to Cr³⁺' (the excess reagent must
        be the dichromate) or as 'amount of the gas' (it must be a gas)."""
        lines = []
        starts = {lo: b for b, (lo, _) in enumerate(plan.branches)}
        cond = bool(plan.branches) and plan.steps[-1].tx == COMPARE_TX
        if plan.branches:
            lines.append("TWO SYSTEMS, the same kind of calculation for each (different substances or processes):"
                         if cond else "TREE: the parts below are worked out separately; the last step combines them.")
        for i, st in enumerate(plan.steps):
            if i in starts:
                lines.append(("First system:", "Second system:")[starts[i]] if cond else f"Part {starts[i] + 1}:")
            if plan.branches and i == len(plan.steps) - 1:
                if cond:
                    lines.append(f"Condition: {st.formula.removeprefix('condition: ')}")
                    continue
                lines.append("Last step (combines the parts):")
            lines.append(f"Step {i + 1}: {st.asks} — {st.formula}")
            if i == 0 or i in starts:
                continue
            params = {p.key: p for p in st.needs}
            for d in st.derive:
                for p in d.params:
                    params.setdefault(p.key, p)
            used = {}
            for key, (src, ref) in plan.wiring[i].items():
                p = params.get(key)
                if p is None or src not in ("prev", "step"):
                    continue
                j = i - 1 if src == "prev" else ref[0]
                used.setdefault(j, []).append(f"'{p.desc}'")
            for j, ds in sorted(used.items()):
                lines.append(f"   takes from step {j + 1}: " + "; ".join(ds)
                             + " (choose the substances so that this is literally true)")
        return "\n".join(lines)


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
