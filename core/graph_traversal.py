"""
graph_traversal.py — knowledge-graph queries, shared by every subject.

Each subject has one graph file with the same schema (nodes + edges), built by
tools/build_graph.py:
    organic    knowledge/reaction_graph.json          functional-group classes
    inorganic  knowledge/reaction_graph_inorg.json    chemical species
    physical   knowledge/reaction_graph_physical.json physical quantities

The same traversal runs on all three: load_graph(path) returns a KnowledgeGraph, and
sample_chains() picks coverage-weighted multi-step chains from it for the generator.

The module-level functions (get_edges_from, get_paths, get_node, get_coverage,
get_ordering) and GRAPH_TOOLS / dispatch_tool keep working for LLM tool calls; they
query the organic graph.
"""

from __future__ import annotations

import json
import os
import random
from collections import deque

_KG           = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge")
_DEFAULT_PATH = os.path.join(_KG, "reaction_graph.json")
_ORDERS_PATH  = os.path.join(_KG, "reaction_orders.json")
_LABELS_PATH  = os.path.join(_KG, "node_labels.json")


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class KnowledgeGraph:
    """One subject's graph. Nodes are functional groups, species or quantities; an
    edge is one transformation step backed by concept-book TXs (edge["tx_ids"])."""

    def __init__(self, path: str):
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        self.path = path
        self.nodes = {n["id"]: n for n in g["nodes"]}
        self.edges = g["edges"]
        self.edge_map = {e["id"]: e for e in self.edges}
        self.edges_from: dict = {}
        for e in self.edges:
            self.edges_from.setdefault(e["from"], []).append(e)

    def display(self, node_id: str) -> str:
        return self.nodes.get(node_id, {}).get("display", node_id)

    def get_edges_from(self, node_id: str, molecular_state: dict | None = None) -> dict:
        """
        Return all edges leaving node_id, optionally filtered by molecular_state.

        molecular_state keys:
          also_present (list[str])  — other FGs present in the molecule
          must_absent  (list[str])  — FGs that must NOT be present

        Applies chemoselectivity.node_redirect: if a node in also_present matches
        a redirect key, the returned edge `to` is overridden to the redirect target.
        """
        if node_id not in self.nodes:
            return {"error": f"Unknown node: {node_id}", "edges": []}

        molecular_state = molecular_state or {}
        also_present = set(molecular_state.get("also_present", []))
        must_absent  = set(molecular_state.get("must_absent",  []))

        result = []
        for e in self.edges_from.get(node_id, []):
            chemo = e.get("chemoselectivity", {})
            if set(chemo.get("requires_absent", [])) & also_present:
                continue   # a required-absent FG is present — edge suppressed
            if must_absent & also_present:
                continue
            effective_to = e["to"]
            for fg, redirect_node in chemo.get("node_redirect", {}).items():
                if fg in also_present:
                    effective_to = redirect_node
                    break
            result.append({
                "id":                  e["id"],
                "to":                  effective_to,
                "reagents":            e.get("reagents", []),
                "conditions":          e.get("conditions", ""),
                "archetype":           e.get("archetype", []),
                "chapter":             e.get("chapter", ""),
                "conditions_variants": e.get("conditions_variants", {}),
                "notes":               e.get("notes", ""),
            })
        return {"node_id": node_id, "edges": result}

    def get_paths(
        self,
        start_node: str,
        depth: int = 3,
        archetype: str | None = None,
        chapter: str | None = None,
        avoid_nodes: list[str] | None = None,
        chapter_scope: str = "all",
        can_follow=None,
    ) -> dict:
        """
        BFS from start_node up to `depth` steps. Returns all reachable paths.

        Filters:
          archetype     — only edges whose archetype list contains this value
          chapter       — edges whose chapter matches (case-insensitive substring)
          chapter_scope — "all": every edge must match the chapter;
                          "start": only the first edge must (the chain starts in the
                          chapter and may continue into neighbouring chapters)
          avoid_nodes   — never traverse through these node ids
          can_follow    — can_follow(prev_edge, edge): only extend a path with an edge
                          that can follow the path's last edge (the physical engine uses
                          this so every chain is computable)

        A self-loop edge (from == to, e.g. a dilution: molarity -> molarity) may be taken
        once per path; otherwise no node is visited twice.

        Returns { "start": str, "paths": [ { "nodes": [...], "edges": [...] } ] },
        longest first, at most 50.
        """
        if start_node not in self.nodes:
            return {"error": f"Unknown node: {start_node}", "paths": []}

        avoid = set(avoid_nodes or [])
        max_depth = max(1, min(depth, 6))  # cap at 6 to avoid explosion
        chap = chapter.lower() if chapter else None

        paths = []
        queue = deque([(start_node, [start_node], [])])
        while queue:
            node, path_nodes, path_edges = queue.popleft()
            if len(path_edges) >= max_depth:
                paths.append({"nodes": path_nodes, "edges": path_edges})
                continue

            expanded = False
            for e in self.edges_from.get(node, []):
                if archetype and archetype not in e.get("archetype", []):
                    continue
                if chap and (chapter_scope == "all" or not path_edges) \
                        and chap not in e.get("chapter", "").lower():
                    continue
                next_node = e["to"]
                if next_node == node:
                    if e["id"] in path_edges:
                        continue   # a self-loop at most once
                elif next_node in path_nodes or next_node in avoid:
                    continue   # no cycles, no banned nodes
                if can_follow is not None and path_edges \
                        and not can_follow(self.edge_map[path_edges[-1]], e):
                    continue
                expanded = True
                queue.append((next_node, path_nodes + [next_node], path_edges + [e["id"]]))

            if not expanded and path_edges:
                paths.append({"nodes": path_nodes, "edges": path_edges})

        seen, unique = set(), []
        for p in sorted(paths, key=lambda x: -len(x["edges"])):
            key = "→".join(p["edges"])
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return {"start": start_node, "paths": unique[:50]}

    def get_node(self, node_id: str) -> dict:
        """Full metadata for one node, merged with node_labels.json when present."""
        if node_id not in self.nodes:
            return {"error": f"Unknown node: {node_id}"}
        n = dict(self.nodes[node_id])
        n["out_degree"] = len(self.edges_from.get(node_id, []))
        label = _LABELS.get(node_id, {})
        if label:
            n["display_name"]   = label.get("display", node_id)
            n["iupac_class"]    = label.get("iupac_class", "")
            n["common_names"]   = label.get("common_names", [])
            n["example_iupac"]  = label.get("example_iupac", "")
            n["example_common"] = label.get("example_common", "")
        return n

    def get_coverage(self, coverage_state: dict | None = None) -> dict:
        """Graph size statistics, merged with coverage_state when provided."""
        result = {
            "total_nodes":        len(self.nodes),
            "total_edges":        len(self.edges),
            "stable_nodes":       sum(1 for n in self.nodes.values() if n.get("type") == "stable"),
            "intermediate_nodes": sum(1 for n in self.nodes.values() if n.get("type") == "intermediate"),
            "node_out_degrees":   {nid: len(es) for nid, es in self.edges_from.items()},
        }
        if coverage_state:
            result["coverage_state"] = coverage_state
        return result

    def start_nodes(self) -> list[str]:
        return [nid for nid, n in self.nodes.items() if n.get("can_be_start", True)]

    def chapters(self, archetype: str | None = None) -> list[str]:
        return sorted({e.get("chapter", "") for e in self.edges
                       if not archetype or archetype in e.get("archetype", [])} - {""})


_GRAPHS: dict = {}


def chain_chapters(graph: KnowledgeGraph, edge_ids: list) -> list:
    """The chapters a chain's edges belong to, in chain order, without repeats."""
    out = []
    for eid in edge_ids:
        ch = graph.edge_map[eid].get("chapter", "")
        if ch and ch not in out:
            out.append(ch)
    return out


def load_graph(path: str | None = None) -> KnowledgeGraph:
    """Load (once) and return the graph at `path`; defaults to the organic graph."""
    path = os.path.abspath(path or _DEFAULT_PATH)
    if path not in _GRAPHS:
        _GRAPHS[path] = KnowledgeGraph(path)
    return _GRAPHS[path]


def sample_chains(graph: KnowledgeGraph, coverage, archetype: str, chapter: str | None = None,
                  start_nodes: list | None = None, n_options: int = 6, depth: int = 3,
                  min_steps: int = 2, avoid_nodes: list | None = None, can_follow=None,
                  validate=None) -> list:
    """
    Candidate chains for one question, highest coverage weight first (ties shuffled).

    chapter=None (the default): chains come from the WHOLE graph. BFS from every start
    node follows edges in order — a step can follow another only if they share a node —
    whatever chapter each edge belongs to. Same procedure for every subject.

    chapter given (--chapter): chains whose every step lies in that chapter; if there are
    fewer than `n_options`, it tops up with chains that START in the chapter and continue
    into neighbouring chapters (in-chapter chains win ties).

    can_follow(prev_edge, edge) prunes the walk (see KnowledgeGraph.get_paths), and
    validate(edges) -> bool drops whole chains a subject's engine cannot compute.

    Returns [ { "idx", "start", "nodes", "edges", "chapters", "weight", "scope", "description" } ].
    """
    starts = start_nodes or graph.start_nodes()
    found, seen = [], set()
    scopes = ("all", "start") if chapter else ("graph",)
    for rank, scope in enumerate(scopes):
        for start in starts:
            result = graph.get_paths(start, depth=depth, archetype=archetype, chapter=chapter,
                                     avoid_nodes=avoid_nodes,
                                     chapter_scope=scope if chapter else "all",
                                     can_follow=can_follow)
            for p in result.get("paths", []):
                key = tuple(p["edges"])
                if len(p["edges"]) < min_steps or key in seen:
                    continue
                if validate is not None and not validate([graph.edge_map[e] for e in p["edges"]]):
                    continue
                seen.add(key)
                found.append({
                    "start":    start,
                    "nodes":    p["nodes"],
                    "edges":    p["edges"],
                    "chapters": chain_chapters(graph, p["edges"]),
                    # chapter=None → the chapter term is the same for every chain; the edge
                    # term (least-used edges first) decides
                    "weight":   coverage.weight(archetype, chapter, p["edges"], []),
                    "scope":    scope,
                    "_rank":    rank,
                })
        if len(found) >= n_options:
            break
    if not found:
        return []

    found.sort(key=lambda x: (-x["weight"], x.pop("_rank"), random.random()))
    options = []
    for i, p in enumerate(found[:n_options]):
        steps = []
        for eid in p["edges"]:
            e = graph.edge_map[eid]
            reagents = e.get("reagents", [])
            r_str = ", ".join(reagents[:2]) if reagents else "?"
            steps.append(f"{graph.display(e['from'])} → {graph.display(e['to'])} [{r_str}]")
        p["idx"] = i
        p["description"] = " | ".join(steps)
        options.append(p)
    return options


_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "01234567890123456789+-")


def compound_key(text: str) -> str:
    """The principal compound of one side of a TX, as a comparable key:
    "2-allylphenol (Claisen rearrangement) + H2O" -> "2-allylphenol";
    "4Ag + 8KCN + O₂" -> "ag". Used to join consecutive steps on the same compound."""
    s = str(text or "").translate(_SUBSCRIPTS)
    s = s.split(" + ")[0].split(" (")[0].split(" —")[0].split(" ->")[0]
    s = s.strip().lower()
    if s[:1].isdigit() and len(s) > 1 and not s[1].isdigit() and s[1] not in ",-":
        s = s.lstrip("0123456789")      # stoichiometric coefficient: 4ag -> ag (keeps 2-allyl...)
    return " ".join(s.split())


def chain_txs(graph: KnowledgeGraph, edge_ids: list, concept_book_txs: list) -> list:
    """The concept-book TX behind each edge of a chain, so the generator sees the full
    entry: reagents, conditions, mechanism, notes.

    An edge usually has several TXs (edge["tx_ids"]). Among them, pick the sequence in
    which the most consecutive steps join on the SAME compound (step N's product is
    step N+1's substrate); ties go to each edge's primary TX. Edges are connected by
    node, which for organic is a functional-group class, so without this the entries
    can describe unrelated example compounds of the same class."""
    options = []
    for eid in edge_ids:
        e = graph.edge_map[eid]
        ids = [i for i in (e.get("tx_ids") or []) if 0 <= i < len(concept_book_txs)]
        if ids:
            opts = [dict(concept_book_txs[i], tx_id=i) for i in ids]
        else:
            opts = [{"from": e["from"], "to": e["to"], "reagents": e.get("reagents", []),
                     "conditions": e.get("conditions", ""), "notes": e.get("notes", "")}]
        options.append(opts)

    # best[j] = (joins, -sum of option ranks, choice list) for chains ending in option j
    best = [(0, -j, [j]) for j in range(len(options[0]))] if options else []
    for k in range(1, len(options)):
        nxt = []
        for j, opt in enumerate(options[k]):
            key = compound_key(opt["from"])
            cand = []
            for i, (joins, rank, choice) in enumerate(best):
                prev = options[k - 1][choice[-1]]
                cand.append((joins + (compound_key(prev["to"]) == key and key != ""),
                             rank - j, choice + [j]))
            nxt.append(max(cand))
        best = nxt
    choice = max(best)[2] if best else []

    out = []
    for k, (eid, j) in enumerate(zip(edge_ids, choice)):
        tx = dict(options[k][j])
        tx["graph_edge"] = eid
        tx["step"] = k + 1
        if k:
            tx["joins_previous_compound"] = compound_key(options[k - 1][choice[k - 1]]["to"]) == compound_key(tx["from"])
        out.append(tx)
    return out


# ── Organic-graph helpers for LLM tool calls ─────────────────────────────────

_ORDERS = _load_json(_ORDERS_PATH, {})
_LABELS = {k: v for k, v in _load_json(_LABELS_PATH, {}).items() if not k.startswith("_")}


def get_edges_from(node_id: str, molecular_state: dict | None = None) -> dict:
    return load_graph().get_edges_from(node_id, molecular_state)


def get_paths(start_node: str, depth: int = 3, archetype: str | None = None,
              chapter: str | None = None, avoid_nodes: list[str] | None = None) -> dict:
    return load_graph().get_paths(start_node, depth, archetype, chapter, avoid_nodes)


def get_node(node_id: str) -> dict:
    return load_graph().get_node(node_id)


def get_coverage(coverage_state: dict | None = None) -> dict:
    return load_graph().get_coverage(coverage_state)


def get_ordering(dimension_id: str) -> dict:
    """
    Return ordering tiers for a GOC dimension from reaction_orders.json.

    dimension_id examples: "carbocation_stability", "acidity", "basicity",
      "nucleophilicity_protic", "nucleophilicity_aprotic", "radical_stability",
      "leaving_group_ability", "sn1_vs_sn2"
    """
    if not _ORDERS:
        return {"error": "reaction_orders.json not found — build it first"}
    if dimension_id not in _ORDERS:
        return {"error": f"Unknown dimension: {dimension_id}", "available": list(_ORDERS.keys())}
    return {"dimension_id": dimension_id, **_ORDERS[dimension_id]}


# ── Tool dispatcher ───────────────────────────────────────────────────────────

_TOOL_FNS = {
    "get_edges_from": get_edges_from,
    "get_paths":      get_paths,
    "get_node":       get_node,
    "get_coverage":   get_coverage,
    "get_ordering":   get_ordering,
}

def dispatch_tool(name: str, args: dict) -> str:
    """Call the named graph tool with args dict, return JSON string result."""
    fn = _TOOL_FNS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(**args)
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result, ensure_ascii=False)


# ── OpenAI tool schemas ────────────────────────────────────────────────────────

GRAPH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_edges_from",
            "description": (
                "Return all reaction edges (transformations) leaving a given functional-group node. "
                "Pass molecular_state to apply chemoselectivity filtering and node_redirect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "Canonical node ID (e.g. 'alkene', 'alcohol', 'ketone')",
                    },
                    "molecular_state": {
                        "type": "object",
                        "description": "Optional. Keys: also_present (list of other FG node_ids in the molecule), must_absent (list of FG node_ids that must not be present).",
                        "properties": {
                            "also_present": {"type": "array", "items": {"type": "string"}},
                            "must_absent":  {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_paths",
            "description": (
                "BFS from start_node up to `depth` steps. Returns all reachable reaction chains. "
                "Use for planning multi-step synthesis questions (Archetype I). "
                "Filter by archetype or chapter to stay on topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node": {
                        "type": "string",
                        "description": "Starting node ID (must be type=stable, can_be_start=true)",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Maximum number of reaction steps (1–6). Default 3.",
                        "default": 3,
                    },
                    "archetype": {
                        "type": "string",
                        "description": "Optional. Filter edges to those tagged with this archetype.",
                    },
                    "chapter": {
                        "type": "string",
                        "description": "Optional. Filter edges to those in this chapter (substring match).",
                    },
                    "avoid_nodes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional. Node IDs to exclude from paths (avoids recently used nodes).",
                    },
                },
                "required": ["start_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node",
            "description": "Return full metadata for a single functional-group node.",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "Node ID to look up"},
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_coverage",
            "description": (
                "Return graph coverage statistics: node count, edge count, out-degrees. "
                "Pass coverage_state from coverage.py to see which nodes/edges are overused."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "coverage_state": {
                        "type": "object",
                        "description": "Optional. Coverage counters from coverage.py.to_dict()",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_ordering",
            "description": (
                "Return ordering tiers for a GOC/Archetype IV dimension from reaction_orders.json. "
                "Use for comparative ranking questions (acidity, basicity, stability, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dimension_id": {
                        "type": "string",
                        "description": (
                            "Dimension key, e.g.: 'carbocation_stability', 'acidity', 'basicity', "
                            "'nucleophilicity_protic', 'nucleophilicity_aprotic', 'radical_stability', "
                            "'leaving_group_ability', 'sn1_vs_sn2', 'eas_reactivity', 'alkene_stability'"
                        ),
                    },
                },
                "required": ["dimension_id"],
            },
        },
    },
]
