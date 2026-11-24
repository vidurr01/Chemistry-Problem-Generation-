"""
Review of the 134 exception notes of the inorganic concept book (2026-11-24, asked by the author before they are
used as traps): GPT-6 Luna judges each note's claim (standard case, exception, reason, example) against JEE
Advanced / NCERT chemistry; every note it does not call correct goes to the author with the problem and a fix.

The notes are knowledge/concept_book_inorg.json -> interpretive_operators -> number_of_exceptions -> exceptions.
Nothing in the question pipeline reads them yet.

    python tools/audit_inorg_exceptions.py      -> outputs/inorg_exception_audit.json / .log
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models                              # noqa: E402

BOOK = os.path.join(ROOT, "knowledge", "concept_book_inorg.json")
OUT = os.path.join(ROOT, "outputs", "inorg_exception_audit.json")
CHECKER = "openai/gpt-6-luna"


def IP_plain(text) -> str:
    return "".join(str(text or "").lower().split())
BATCH = 3
FIELDS = ("standard_case", "exception", "why_exception", "trap", "exam_relevance")


def notes():
    with open(BOOK, encoding="utf-8") as f:
        book = json.load(f)
    ex = book["interpretive_operators"]["number_of_exceptions"]["exceptions"]
    return [dict(n, n=i + 1) for i, n in enumerate(ex)]


def ask(batch):
    body = "\n\n".join(f"NOTE {n['n']} ({n.get('source_chapter')}):\n" + "\n".join(f"  {k}: {n.get(k)}" for k in FIELDS)
                       for n in batch)
    prompt = f"""You are checking notes of a JEE Advanced inorganic chemistry book. FORMAT: "standard_case" is the
naive rule a student believes; it is EXPECTED to be false or too broad (that is the point of the note), so never
fault it for being false. Judge only what the note asserts as TRUE: the exception, why_exception and exam_relevance.
Is every chemical fact there true (numbers, products, colours, structures, which species belong to the list), and
does the exception really break the naive rule? Be strict about facts, not wording.

{body}

Return JSON: {{"notes": [{{"n": 1, "exception_starts": "the first six words of THIS note's exception, copied",
  "verdict": "correct" | "minor" | "wrong",
  "problem": "empty if correct; else the exact false or misleading statement in the exception / why / exam_relevance",
  "fix": "empty if correct; else the corrected statement"}}]}}
"minor": true chemistry but a misleading example or reason; "wrong": a false chemical statement."""
    try:
        out = models.ask_json("exception_audit", CHECKER, "You are an expert inorganic chemist. Output JSON only.",
                              prompt, temperature=0.0, max_tokens=14000)
        by_n = {n["n"]: n for n in batch}
        got = {}
        for r in out.get("notes") or []:
            if not isinstance(r, dict) or int(r.get("n", -1)) not in by_n:
                continue
            head = IP_plain(r.get("exception_starts"))[:12]
            if head and head not in IP_plain(by_n[int(r["n"])].get("exception")):
                continue                            # the reply mixed up two notes: ask again
            got[int(r["n"])] = r
        return got
    except Exception as e:                       # noqa: BLE001
        return {n["n"]: {"verdict": "error", "problem": f"call failed: {str(e)[:80]}", "fix": ""} for n in batch}


def main():
    ns = notes()
    batches = [ns[i:i + BATCH] for i in range(0, len(ns), BATCH)]
    print(f"{len(ns)} notes in {len(batches)} calls")
    got = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for d in ex.map(ask, batches):
            got.update(d)
        for _ in range(2):                          # replies cut off at the cap: again, in smaller batches
            left = [n for n in ns if n["n"] not in got or got[n["n"]].get("verdict") == "error"]
            if not left:
                break
            print(f"retrying {len(left)} notes")
            for d in ex.map(ask, [left[i:i + 3] for i in range(0, len(left), 3)]):
                got.update(d)
    rows = []
    for n in ns:
        r = got.get(n["n"]) or {"verdict": "missing", "problem": "", "fix": ""}
        rows.append({"n": n["n"], "chapter": n.get("source_chapter"), **{k: n.get(k) for k in FIELDS},
                     "verdict": r.get("verdict"), "problem": r.get("problem", ""), "fix": r.get("fix", ""),
                     "book_audit_note": n.get("audit_note"), "book_unverified": n.get("unverified")})
    from collections import Counter
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"n": len(rows), "spend": models.SPEND.summary(), "notes": rows}, f, ensure_ascii=False, indent=1)
    print(Counter(r["verdict"] for r in rows))
    for r in rows:
        if r["verdict"] != "correct":
            print(f"\n[{r['n']}] {r['verdict'].upper()} ({r['chapter']})\n  rule: {r['standard_case']}\n"
                  f"  exception: {r['exception']}\n  problem: {r['problem']}\n  fix: {r['fix']}")
    print("\nspend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
