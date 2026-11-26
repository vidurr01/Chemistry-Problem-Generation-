"""
audit_concept_coverage.py — sort every concept-book entry the knowledge graph does not use (knowledge/graph_unmapped*.json)
into what it is, by code only (₹0). Reviewer, 2026-11-26: the graphs use 47 % (organic), 44 % (inorganic) and 69 %
(physical) of the concept book; a reaction missing from the graph is variety the pipeline can never produce.

    reaction   a real transformation with reagents and a species product: a candidate graph edge (for approval)
    property   a property/structure fact about one species (shape, magnetism, bond order, isoelectronic ...): the
               inorganic species engine computes these itself; not a graph edge
    concept    a concept, comparison, trend, test procedure or qualitative fact: not a graph edge (fact questions
               or meta tags only)

Writes outputs/concept_coverage_audit.json (every entry with its class and reason) and
docs/concept_coverage_audit.md (counts, and the reaction candidates listed for approval). Nothing in knowledge/ changes.

    python tools/audit_concept_coverage.py
"""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KG = os.path.join(ROOT, "knowledge")
SUBJECTS = {"organic": ("concept_book.json", "graph_unmapped.json"),
            "inorganic": ("concept_book_inorg.json", "graph_unmapped_inorg.json"),
            "physical": ("concept_book_physical.json", "graph_unmapped_physical.json")}

PROPERTY = re.compile(r"\b(shape|planar|linear|tetrahedral|octahedral|pyramidal|bent|t-shaped|see-?saw|square|"
                      r"hybridi[sz]|sp\d|d\dsp|dsp|diamagnetic|paramagnetic|bond order|\bBO\s*=|isoelectronic|"
                      r"lone pair|dipole|polar|magnetic moment|unpaired|resonance|bond angle|bond length|"
                      r"oxidation state|configuration|colou?r(ed|less)?\b)", re.I)
CONCEPT = re.compile(r"\b(which|compare|comparison|order of|trend|increase|decrease|stability|stable|acidity|basicity|"
                     r"reactivity|aromatic|antiaromatic|isomer|enantiomer|racemi|optical|chiral|R/S|E/Z|D-|L-|"
                     r"rule|law|principle|definition|vs\.?|versus|test for|identification|preparation of|"
                     r"conditions|effect|factor|why|explain|difference|classification|property_list|"
                     r"yield|rate|mechanism only)\b", re.I)
FORMULA = re.compile(r"[A-Z][a-z]?[₀-₉\d]|[A-Z][a-z]?\(|[A-Z]{2}|⁺|⁻|\b(acid|alcohol|aldehyde|ketone|ester|amine|amide|"
                     r"halide|ether|alkene|alkyne|nitrile|phenol|benzene|oxide|chloride|sulph|sulf|nitrate|hydroxide|"
                     r"carbonate|salt|complex)\b", re.I)


def _book(path):
    d = json.load(open(path, encoding="utf-8"))
    for op in d.get("structural_operators", {}).values():
        if isinstance(op, dict) and op.get("valid_transformations"):
            return op["valid_transformations"]
    return []


def classify(subject, t) -> tuple:
    frm, to = str(t.get("from") or ""), str(t.get("to") or "")
    reag = t.get("reagents") or []
    reag = reag if isinstance(reag, list) else [reag]
    text = f"{frm} -> {to}"
    if subject == "physical":
        if "=" in to or re.search(r"\bformula\b", to, re.I):
            return "reaction", "looks like a formula (physical: candidate engine step)"
        return "concept", "physical qualitative entry"
    if PROPERTY.search(to) and not re.search(r"→|->", to):
        return "property", "the product side states properties of one species"
    if CONCEPT.search(text):
        return "concept", "comparison, concept or procedure wording"
    has_reagent = any(str(r).strip() and str(r).strip().lower() not in ("none", "-", "heat") for r in reag) or \
        bool(str(t.get("conditions") or "").strip())
    if has_reagent and FORMULA.search(to) and FORMULA.search(frm):
        return "reaction", "reagents plus a species on both sides"
    return "concept", "no clear species product or no reagent"


def main():
    out, md = [], ["# Concept-book coverage audit (code only, 2026-11-26)", "",
                   "Entries of the concept book the knowledge graph does not use, sorted by `tools/audit_concept_coverage.py`. "
                   "**Reaction candidates** could become graph edges (each needs the reviewer's approval; organic ones "
                   "also need an engine rule and a test). Property and concept entries are not graph material.", ""]
    for subject, (cb, un) in SUBJECTS.items():
        book = _book(os.path.join(KG, cb))
        unm = json.load(open(os.path.join(KG, un), encoding="utf-8"))
        rows = []
        for u in unm:
            i = u.get("tx_index")
            t = book[i] if isinstance(i, int) and 0 <= i < len(book) else {"from": u.get("from_raw"), "to": u.get("to_raw")}
            cls, why = classify(subject, t)
            reag = t.get("reagents") or []
            rows.append({"subject": subject, "tx_index": i, "class": cls, "why": why, "from": t.get("from"),
                         "to": t.get("to"), "reagents": reag if isinstance(reag, list) else [reag],
                         "conditions": t.get("conditions"), "chapter": t.get("source_chapter") or t.get("chapter")})
        out += rows
        n = {c: sum(r["class"] == c for r in rows) for c in ("reaction", "property", "concept")}
        md += [f"## {subject.capitalize()} — {len(rows)} unmapped of {len(book)}", "",
               f"- reaction candidates: **{n['reaction']}**", f"- species properties (engine computes): {n['property']}",
               f"- concepts / facts: {n['concept']}", "", "Reaction candidates:", ""]
        for r in rows:
            if r["class"] == "reaction":
                cond = str(r["conditions"] or "").strip()
                md.append(f"- [{r['tx_index']}] {r['from']} → {r['to']} | {', '.join(map(str, r['reagents']))}"
                          + (f" | {cond[:90]}" if cond else ""))
        md.append("")
    with open(os.path.join(ROOT, "outputs", "concept_coverage_audit.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "docs", "concept_coverage_audit.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    for subject in SUBJECTS:
        rs = [r for r in out if r["subject"] == subject]
        print(subject, len(rs), {c: sum(r["class"] == c for r in rs) for c in ("reaction", "property", "concept")})


if __name__ == "__main__":
    main()
