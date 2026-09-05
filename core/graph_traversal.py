"""
graph_traversal.py — Knowledge graph query interface for the Concept Reasoner.

Loads reaction_graph.json once at import time and exposes five query functions.
Each function has a matching OpenAI tool schema in GRAPH_TOOLS (see bottom).

Usage in LLM call:
    from graph_traversal import GRAPH_TOOLS, dispatch_tool
    response = client.chat.completions.create(..., tools=GRAPH_TOOLS)
    for call in response.choices[0].message.tool_calls:
        result = dispatch_tool(call.function.name, json.loads(call.function.arguments))
"""

import json
import os
from collections import deque

# ── Load graph at import time ─────────────────────────────────────────────────

_KG          = os.path.join(os.path.dirname(__file__), "..", "knowledge")
_GRAPH_PATH  = os.path.join(_KG, "reaction_graph.json")
_ORDERS_PATH = os.path.join(_KG, "reaction_orders.json")
_LABELS_PATH = os.path.join(_KG, "node_labels.json")

def _load_graph():
    with open(_GRAPH_PATH, encoding="utf-8") as f:
        g = json.load(f)
    nodes = {n["id"]: n for n in g["nodes"]}
    # Index edges by from-node for fast lookup
    edges_from = {}
    for e in g["edges"]:
        edges_from.setdefault(e["from"], []).append(e)
    return nodes, edges_from, g["edges"]

NODES, _EDGES_FROM, _ALL_EDGES = _load_graph()


def _load_orders():
    if not os.path.exists(_ORDERS_PATH):
        return {}
    with open(_ORDERS_PATH, encoding="utf-8") as f:
        return json.load(f)

def _load_labels():
    if not os.path.exists(_LABELS_PATH):
        return {}
    with open(_LABELS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    # Strip _meta key
    return {k: v for k, v in data.items() if not k.startswith("_")}

_ORDERS = _load_orders()
_LABELS = _load_labels()


# ── Tool functions ─────────────────────────────────────────────────────────────

def get_edges_from(node_id: str, molecular_state: dict | None = None) -> dict:
    """
    Return all edges leaving node_id, optionally filtered by molecular_state.

    molecular_state keys:
      also_present (list[str])  — other FGs present in the molecule
      must_absent  (list[str])  — FGs that must NOT be present

    Applies chemoselectivity.node_redirect: if a node in also_present matches
    a redirect key, the returned edge `to` is overridden to the redirect target.

    Returns:
      { "node_id": str,
        "edges": [ { "id", "to", "reagents", "conditions",
                      "archetype", "chapter", "conditions_variants" } ] }
    """
    if node_id not in NODES:
        return {"error": f"Unknown node: {node_id}", "edges": []}

    raw_edges = _EDGES_FROM.get(node_id, [])
    if not raw_edges:
        return {"node_id": node_id, "edges": []}

    molecular_state = molecular_state or {}
    also_present = set(molecular_state.get("also_present", []))
    must_absent  = set(molecular_state.get("must_absent",  []))

    result = []
    for e in raw_edges:
        chemo = e.get("chemoselectivity", {})

        # Filter: requires_absent
        req_absent = set(chemo.get("requires_absent", []))
        if req_absent & also_present:
            # A required-absent FG is present — this edge is suppressed
            continue

        # Filter: must_absent constraint from caller
        if must_absent & also_present:
            continue

        # Apply node_redirect (chemoselectivity override)
        effective_to = e["to"]
        node_redirect = chemo.get("node_redirect", {})
        for fg, redirect_node in node_redirect.items():
            if fg in also_present:
                effective_to = redirect_node
                break

        result.append({
            "id":                 e["id"],
            "to":                 effective_to,
            "reagents":           e.get("reagents", []),
            "conditions":         e.get("conditions", ""),
            "archetype":          e.get("archetype", []),
            "chapter":            e.get("chapter", ""),
            "conditions_variants": e.get("conditions_variants", {}),
            "notes":              e.get("notes", ""),
        })

    return {"node_id": node_id, "edges": result}


def get_paths(
    start_node: str,
    depth: int = 3,
    archetype: str | None = None,
    chapter: str | None = None,
    avoid_nodes: list[str] | None = None,
) -> dict:
    """
    BFS from start_node up to `depth` steps. Returns all reachable paths.

    Filters:
      archetype  — only include edges whose archetype list contains this value
      chapter    — only include edges whose chapter matches (substring match)
      avoid_nodes — do not traverse through these node IDs

    Intermediate nodes (type="intermediate") are included in paths but not
    counted as terminal endpoints.

    Returns:
      { "start": str,
        "paths": [ { "nodes": [str, ...], "edges": [str, ...] } ] }
      where each path is a sequence of alternating node/edge IDs.
    """
    if start_node not in NODES:
        return {"error": f"Unknown node: {start_node}", "paths": []}

    avoid = set(avoid_nodes or [])
    max_depth = max(1, min(depth, 6))  # cap at 6 to avoid explosion

    paths = []
    # BFS queue: (current_node, path_nodes, path_edges)
    queue = deque([(start_node, [start_node], [])])

    while queue:
        node, path_nodes, path_edges = queue.popleft()

        if len(path_edges) >= max_depth:
            if len(path_edges) > 0:
                paths.append({"nodes": path_nodes, "edges": path_edges})
            continue

        outgoing = _EDGES_FROM.get(node, [])
        expanded = False

        for e in outgoing:
            # Archetype filter
            if archetype and archetype not in e.get("archetype", []):
                continue
            # Chapter filter (substring)
            if chapter and chapter.lower() not in e.get("chapter", "").lower():
                continue
            # Avoid cycles and banned nodes
            next_node = e["to"]
            if next_node in path_nodes or next_node in avoid:
                continue

            expanded = True
            queue.append((
                next_node,
                path_nodes + [next_node],
                path_edges + [e["id"]],
            ))

        if not expanded and len(path_edges) > 0:
            paths.append({"nodes": path_nodes, "edges": path_edges})

    # Deduplicate and sort by length (longest first — more useful for generation)
    seen = set()
    unique = []
    for p in sorted(paths, key=lambda x: -len(x["edges"])):
        key = "→".join(p["nodes"])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    return {"start": start_node, "paths": unique[:50]}  # cap at 50 paths


def get_node(node_id: str) -> dict:
    """
    Return full metadata for a single node, including IUPAC class name,
    common names, and a concrete example molecule.

    Returns: node dict with graph fields + label fields from node_labels.json.
    Returns {"error": ...} if node_id unknown.
    """
    if node_id not in NODES:
        return {"error": f"Unknown node: {node_id}"}
    n = dict(NODES[node_id])
    n["out_degree"] = len(_EDGES_FROM.get(node_id, []))
    # Merge label metadata
    label = _LABELS.get(node_id, {})
    if label:
        n["display_name"]   = label.get("display", node_id)
        n["iupac_class"]    = label.get("iupac_class", "")
        n["common_names"]   = label.get("common_names", [])
        n["example_iupac"]  = label.get("example_iupac", "")
        n["example_common"] = label.get("example_common", "")
    return n


def get_coverage(coverage_state: dict | None = None) -> dict:
    """
    Return graph coverage statistics.

    If coverage_state is provided (from coverage.py), merges hit counts.
    Otherwise returns raw graph statistics.

    Returns:
      { "total_nodes": int, "total_edges": int,
        "stable_nodes": int, "intermediate_nodes": int,
        "node_out_degrees": { node_id: int },
        "coverage_state": { ... } if provided }
    """
    stable = sum(1 for n in NODES.values() if n.get("type") == "stable")
    inter  = sum(1 for n in NODES.values() if n.get("type") == "intermediate")

    out_degrees = {nid: len(edges) for nid, edges in _EDGES_FROM.items()}

    result = {
        "total_nodes":       len(NODES),
        "total_edges":       len(_ALL_EDGES),
        "stable_nodes":      stable,
        "intermediate_nodes": inter,
        "node_out_degrees":  out_degrees,
    }
    if coverage_state:
        result["coverage_state"] = coverage_state

    return result


def get_ordering(dimension_id: str) -> dict:
    """
    Return ordering tiers for a GOC dimension from reaction_orders.json.

    dimension_id examples: "carbocation_stability", "acidity", "basicity",
      "nucleophilicity_protic", "nucleophilicity_aprotic", "radical_stability",
      "leaving_group_ability", "sn1_vs_sn2"

    Returns:
      { "dimension_id": str, "tiers": [...], "jee_traps": [...],
        "exceptions": [...] }
    Returns {"error": ...} if dimension_id unknown or orders file missing.
    """
    if not _ORDERS:
        return {"error": "reaction_orders.json not found — build it first"}
    if dimension_id not in _ORDERS:
        available = list(_ORDERS.keys())
        return {"error": f"Unknown dimension: {dimension_id}", "available": available}
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
