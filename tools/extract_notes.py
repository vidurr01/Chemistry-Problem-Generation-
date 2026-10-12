"""
extract_notes.py — turn a chapter's notes (OCR text) into concept-book entries and
merge them into knowledge/concept_book.json (organic).

    python tools/extract_notes.py --notes data/notes/amines_lec1.txt --topic Amines --dry-run
    python tools/extract_notes.py --notes data/notes/amines_lec1.txt --topic Amines

HOW IT WORKS:
1. Read the notes text from --notes (plain text, e.g. OCR of handwritten notes)
2. Send it to DeepSeek-V3.2 (SambaNova) with a structured extraction prompt
3. The model returns JSON with new transformations, fragile concepts, exceptions, distractors
4. Merge them into concept_book.json, skipping duplicates and malformed entries
   (--dry-run shows what would be added and writes nothing)

After adding transformations, rebuild the organic graph only if you mean to replace the
curated knowledge/reaction_graph.json (see tools/build_graph.py).

Needs SAMBANOVA_KEY_1 in .env.
"""

import argparse
import json
import os
import sys

from openai import OpenAI

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core.llm import call_json, load_env, parse_json as _parse_json, write_json_atomic  # noqa: E402

# ── Client setup ──────────────────────────────────────────────────────────────
load_env()

MODEL = "DeepSeek-V3.2"
_CB_PATH = os.path.join(_ROOT, "knowledge", "concept_book.json")


def _client():
    return OpenAI(api_key=os.environ.get("SAMBANOVA_KEY_1", ""), base_url="https://api.sambanova.ai/v1")


# ── Extraction prompt ─────────────────────────────────────────────────────────
# We tell the LLM exactly what format we want back ("structured output prompting":
# the JSON schema is described in the prompt itself). {topic} and {notes} are filled in.
EXTRACTION_PROMPT = """
You are an expert organic chemistry knowledge engineer.

Below is OCR-extracted text from handwritten JEE Advanced organic chemistry notes on {topic}.
Your job is to extract structured entries for a concept book used in a problem generation pipeline.

The concept book has this structure:
{{
  "new_transformations": [
    {{"from": "source functional group", "to": "product", "reagents": ["list"], "archetype": ["I","II","III","IV"]}}
  ],
  "new_fragile_concepts": [
    {{"name": "concept name", "explanation": "clear explanation", "fragile_in": ["III","IV"], "routine_in": ["I"]}}
  ],
  "new_exceptions": [
    {{"standard_case": "what students expect", "exception": "what actually happens", "trap": "why students get it wrong"}}
  ],
  "new_distractors": [
    {{"type": "distractor type", "examples": ["example1"], "mechanism_trap": "what wrong reasoning leads here"}}
  ]
}}

Archetypes:
I = Long Reaction Chains (synthesis routes)
II = Counting/Enumeration (how many compounds satisfy X)
III = Deep Mechanistic Reasoning (short but insight-dependent)
IV = Comparative Ranking/GOC (rank by property)

Raw notes:
{notes}

Extract ALL chemically meaningful entries. Be precise with reagents and conditions.
For fragile concepts, identify ones that commonly trip up JEE students.
Return ONLY valid JSON, no explanation outside the JSON.
"""


def extract_from_notes(notes_text: str, topic: str) -> dict:
    """
    Sends the notes to the LLM and gets back structured concept book entries.

    Returns a dict with keys: new_transformations, new_fragile_concepts,
    new_exceptions, new_distractors
    """
    print(f"Extracting from {topic} notes ({len(notes_text)} characters)...")
    prompt = EXTRACTION_PROMPT.format(topic=topic, notes=notes_text)
    return call_json(lambda: _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "You are a chemistry knowledge engineer. Output valid JSON only."},
            {"role": "user",   "content": prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.3   # Low temperature = more deterministic, less creative
    ), _parse_json, label="SambaNova")


def merge_into_concept_book(extracted: dict, concept_book_path: str = _CB_PATH, dry_run: bool = False):
    """
    Merges extracted entries into concept_book.json, skipping duplicates and entries
    missing their key field:
    - new_transformations  → structural_operators.add_reaction_step.valid_transformations  (key: from+to)
    - new_fragile_concepts → interpretive_operators.conceptual_fragility.concepts           (key: name)
    - new_exceptions       → interpretive_operators.number_of_exceptions.exceptions          (key: standard_case)
    - new_distractors      → interpretive_operators.distractor_plausibility.distractors      (key: type)
    Returns {"added": {...}, "skipped_malformed": {...}}. Writes nothing if dry_run.
    """
    with open(concept_book_path, encoding="utf-8") as f:
        concept_book = json.load(f)

    targets = {
        "transformations": (extracted.get("new_transformations", []),
                            concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"],
                            lambda e: (e.get("from"), e.get("to")) if e.get("from") and e.get("to") else None),
        "fragile_concepts": (extracted.get("new_fragile_concepts", []),
                             concept_book["interpretive_operators"]["conceptual_fragility"]["concepts"],
                             lambda e: e.get("name") or None),
        "exceptions": (extracted.get("new_exceptions", []),
                       concept_book["interpretive_operators"]["number_of_exceptions"]["exceptions"],
                       lambda e: e.get("standard_case") or None),
        "distractors": (extracted.get("new_distractors", []),
                        concept_book["interpretive_operators"]["distractor_plausibility"]["distractors"],
                        lambda e: e.get("type") or None),
    }
    added, malformed = {}, {}
    for name, (new_items, existing, key) in targets.items():
        seen = {key(e) for e in existing if isinstance(e, dict)}
        added[name] = malformed[name] = 0
        for item in new_items or []:
            k = key(item) if isinstance(item, dict) else None
            if k is None:
                malformed[name] += 1
                continue
            if k not in seen:
                existing.append(item)
                seen.add(k)
                added[name] += 1

    if not dry_run:
        # Atomic write, same format as the committed file (ASCII-escaped, indent 2).
        write_json_atomic(concept_book_path, concept_book)
    return {"added": added, "skipped_malformed": malformed}


def main():
    ap = argparse.ArgumentParser(description="Extract concept-book entries from chapter notes.")
    ap.add_argument("--notes", required=True, help="text file with the notes, e.g. data/notes/amines_lec1.txt")
    ap.add_argument("--topic", required=True, help="chapter/topic name used in the prompt, e.g. Amines")
    ap.add_argument("--concept-book", default=_CB_PATH, help="concept book to merge into (organic)")
    ap.add_argument("--dry-run", action="store_true", help="show what would be added; write nothing")
    args = ap.parse_args()

    if not os.environ.get("SAMBANOVA_KEY_1"):
        print("ERROR: SAMBANOVA_KEY_1 is not set in .env.")
        return 1
    with open(args.notes, encoding="utf-8") as f:
        notes = f.read()

    extracted = extract_from_notes(notes, args.topic)
    print("\n--- Extracted entries ---")
    for k in ("new_transformations", "new_fragile_concepts", "new_exceptions", "new_distractors"):
        print(f"  {k:22s}: {len(extracted.get(k, []) or [])}")

    result = merge_into_concept_book(extracted, args.concept_book, dry_run=args.dry_run)
    print(f"\n--- {'Would add (dry run, nothing written)' if args.dry_run else 'Added to ' + args.concept_book} ---")
    for k, n in result["added"].items():
        bad = result["skipped_malformed"][k]
        print(f"  {k:18s}: {n}" + (f"   ({bad} malformed entries skipped)" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
