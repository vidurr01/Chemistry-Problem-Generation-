"""
Extraction agent: reads notes from Google Drive folders,
uses an LLM to structure them into concept book operator format,
and merges the result into concept_book.json.

HOW IT WORKS:
1. We hardcode the raw OCR text (fetched via MCP tool in the session)
2. We send it to DeepSeek with a structured extraction prompt
3. DeepSeek returns JSON with new operators, transformations, fragile concepts, exceptions
4. We merge these into the existing concept_book.json

PYTHON CONCEPTS USED:
- json.load / json.dump  : reading and writing JSON files
- dict.setdefault()      : safely add to a dict key without overwriting
- list.append()          : add items to a list
- f-strings              : string formatting with {}
- OpenAI SDK             : same client we use everywhere else
"""

import json
import os
from openai import OpenAI

# ── Client setup ──────────────────────────────────────────────────────────────
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

client = OpenAI(
    api_key=os.environ.get("SAMBANOVA_KEY_1", ""),
    base_url="https://api.sambanova.ai/v1"
)

# ── Raw OCR text from Drive ───────────────────────────────────────────────────
# This came directly from read_file_content(fileId="1seDv_oDZ2LlfpflQPNK50KSPEbgzccNG")
# In the full agent, this would be fetched dynamically per file.
AMINES_OCR = """
G.M.P. Amines
1 From Amide: R-C-NH2 + LAH → R-CH-NH2 (1°) / R-CH-NH-R (2°) / R-CH-N-R (3°)
2 Hoffman degradation: R-CONH2 + KOH/Br2 → R-NH2 (only 1° amine)
3 From reduction of NO2: R-NO2 → R-NH2 [Fe/HCl (best), Zn/HCl, Sn/HCl, H2/Pt, LAH]
   Selective reduction: neutral (Fe/NH4Cl) → phenylhydroxylamine
   Highly basic (2mol NaOH) → azobenzene
   Excess NaOH → azoxybenzene
4 From reduction of cyanide: R-CN + H2/Pt,Pd,Ni or LAH → R-CH2-NH2 (1° amine)
   Isocyanide (R-NC) + LAH → R-NH-CH3 (2° amine)
5 From Aldehyde & ketone (reductive amination):
   R-CHO + NH3 + H2/Pt or NaBHCN → 1° amine
   R-CHO + R-NH2 + H2/Pt → 2° amine (via imine intermediate)
   R-CHO + R2NH + H2/Pt → 3° amine
6 Hofmann exhaustive methylation: R-NH2 + excess CH3X → quaternary ammonium salt
7 From alcohol: R-OH + NH3 + Al2O3 at 450°C → R-NH2 / R-NHR / R-NR2 (mixture)
8 Ritter Reaction: alkene + HCN + H2O → amide → amine
9 Mannich Reaction: aldehyde + ketone (with alpha-H) + NH2 → beta-amino carbonyl
10 Schmidt Reaction: ketone + HN3 → amine (rearrangement, loss of CO)
11 Lossen Rearrangement: hydroxamic acid → isocyanate → amine (via rearrangement)
12 Curtius Reaction: acid chloride + NaN3 → isocyanate → amine (heat)
13 Gabriel Phthalimide Synthesis: phthalimide + RX → N-alkylphthalimide → R-NH2 (hydrolysis)
    NOTE: Only gives pure 1° amines. Cannot make 2° or 3°. Cannot use ArX.

TESTS:
Carbylamine Test: R-NH2 + CHCl3 + 3KOH → R-NC (isocyanide, foul smell) — ONLY for 1° amines
Mustard Oil Test: R-NH2 + CS2 + HgCl2 → R-N=C=S (alkyl isothiocyanate, smells like mustard) — ONLY 1°
NaNO2/HCl test:
    1° aliphatic amine → ROH + N2 (unstable diazonium)
    1° aromatic amine + NaNO2 + 2HCl at 0-5°C → ArN2+Cl- (stable diazonium salt)
    2° amine → yellow oily N-nitroso compound
    3° amine → no reaction (in acid) / rearrangement products
Azo Dye Test: diazonium salt + beta-naphthol → azo dye (orange-red) — confirms aromatic 1° amine
Hinsberg Test: amine + PhSO2Cl →
    1° amine → sulphonamide soluble in base (N-H present)
    2° amine → sulphonamide insoluble in base (no N-H)
    3° amine → no reaction

BASICITY ORDER:
Aliphatic: 2° > 1° > 3° > NH3 (in gas phase due to steric + inductive)
Aliphatic in water: 2° > 1° > 3° > NH3 (solvation matters)
Aromatic: NH3 > 1° aromatic > 2° aromatic > 3° aromatic (lone pair delocalisation into ring)

REARRANGEMENTS:
Benzidine Rearrangement: hydrazobenzene + H+ → 4,4'-diaminobiphenyl (benzidine) [major product]
Hofmann-Martius Rearrangement: N-alkylaniline salt + heat (200°C) → ortho/para alkylaniline
Fischer-Hepp Rearrangement: N-nitroso secondary amine → para-nitroso primary amine

OXIDATION:
1° amine + KMnO4 → nitroso → nitro → carboxylic acid (over-oxidation)
2° amine + KMnO4 → R-C=N-R (imine/ketimine)
3° amine + KMnO4 → no reaction
Aniline + KMnO4 → complex products (ring oxidation)
Amine + per-acid (H2O2, mCPBA) → amine oxide (3° → N-oxide)
"""


# ── Extraction prompt ─────────────────────────────────────────────────────────
# We tell the LLM exactly what format we want back.
# This is called "structured output prompting" — you describe the JSON schema
# you want in the prompt itself.

EXTRACTION_PROMPT = f"""
You are an expert organic chemistry knowledge engineer.

Below is OCR-extracted text from handwritten JEE Advanced organic chemistry notes on Amines.
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
{AMINES_OCR}

Extract ALL chemically meaningful entries. Be precise with reagents and conditions.
For fragile concepts, identify ones that commonly trip up JEE students.
Return ONLY valid JSON, no explanation outside the JSON.
"""


def extract_from_notes(ocr_text: str, chapter_name: str) -> dict:
    """
    Sends OCR text to the LLM and gets back structured concept book entries.

    Parameters:
        ocr_text    : the raw text from Google Drive OCR
        chapter_name: used for logging only

    Returns:
        A dict with keys: new_transformations, new_fragile_concepts,
        new_exceptions, new_distractors
    """
    print(f"Extracting from {chapter_name}...")

    # This is the same pattern as everywhere else in the pipeline:
    # client.chat.completions.create() sends a message to the model
    # and returns a response object. We then parse the text content as JSON.
    response = client.chat.completions.create(
        model="DeepSeek-V3.2",
        messages=[
            {"role": "system", "content": "You are a chemistry knowledge engineer. Output valid JSON only."},
            {"role": "user",   "content": EXTRACTION_PROMPT}
        ],
        response_format={"type": "json_object"},
        temperature=0.3   # Low temperature = more deterministic, less creative
    )

    # response.choices[0].message.content is a string containing JSON
    # json.loads() converts that string into a Python dictionary
    return json.loads(response.choices[0].message.content.strip())


_CB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge", "concept_book.json")


def merge_into_concept_book(extracted: dict, concept_book_path: str = _CB_PATH):
    """
    Merges extracted entries into the existing concept_book.json.

    HOW MERGING WORKS:
    - new_transformations → appended to structural_operators.add_reaction_step.valid_transformations
    - new_fragile_concepts → appended to interpretive_operators.conceptual_fragility.concepts
    - new_exceptions → appended to interpretive_operators.number_of_exceptions.exceptions
    - new_distractors → appended to interpretive_operators.distractor_plausibility.distractors
    """
    # json.load() reads a JSON file and converts it to a Python dict
    with open(concept_book_path, "r", encoding="utf-8") as f:
        concept_book = json.load(f)

    # Count what we're adding so we can report it
    added = {"transformations": 0, "fragile_concepts": 0, "exceptions": 0, "distractors": 0}

    # --- Merge transformations ---
    existing_txs = concept_book["structural_operators"]["add_reaction_step"]["valid_transformations"]
    # Build a set of (from, to) pairs already in the book to avoid duplicates
    existing_pairs = {(t["from"], t["to"]) for t in existing_txs}

    for tx in extracted.get("new_transformations", []):
        if (tx["from"], tx["to"]) not in existing_pairs:
            existing_txs.append(tx)
            existing_pairs.add((tx["from"], tx["to"]))
            added["transformations"] += 1

    # --- Merge fragile concepts ---
    existing_concepts = concept_book["interpretive_operators"]["conceptual_fragility"]["concepts"]
    existing_names = {c["name"] for c in existing_concepts}

    for concept in extracted.get("new_fragile_concepts", []):
        if concept["name"] not in existing_names:
            existing_concepts.append(concept)
            existing_names.add(concept["name"])
            added["fragile_concepts"] += 1

    # --- Merge exceptions ---
    existing_exceptions = concept_book["interpretive_operators"]["number_of_exceptions"]["exceptions"]
    existing_exc_cases = {e["standard_case"] for e in existing_exceptions}

    for exc in extracted.get("new_exceptions", []):
        if exc["standard_case"] not in existing_exc_cases:
            existing_exceptions.append(exc)
            existing_exc_cases.add(exc["standard_case"])
            added["exceptions"] += 1

    # --- Merge distractors ---
    existing_distractors = concept_book["interpretive_operators"]["distractor_plausibility"]["distractors"]
    existing_dist_types = {d["type"] for d in existing_distractors}

    for dist in extracted.get("new_distractors", []):
        if dist["type"] not in existing_dist_types:
            existing_distractors.append(dist)
            existing_dist_types.add(dist["type"])
            added["distractors"] += 1

    # json.dump() converts the Python dict back to JSON and writes it to the file
    # indent=2 makes it human-readable (pretty-printed)
    with open(concept_book_path, "w", encoding="utf-8") as f:
        json.dump(concept_book, f, indent=2)

    return added


def main():
    # Step 1: Extract structured entries from the Amines OCR
    extracted = extract_from_notes(AMINES_OCR, "Amines Lec1")

    # Show what was extracted before merging
    print("\n--- Extracted entries ---")
    print(f"  New transformations:   {len(extracted.get('new_transformations', []))}")
    print(f"  New fragile concepts:  {len(extracted.get('new_fragile_concepts', []))}")
    print(f"  New exceptions:        {len(extracted.get('new_exceptions', []))}")
    print(f"  New distractors:       {len(extracted.get('new_distractors', []))}")

    # Step 2: Merge into concept_book.json
    added = merge_into_concept_book(extracted)

    print("\n--- Merged into concept_book.json ---")
    print(f"  Added transformations:   {added['transformations']}")
    print(f"  Added fragile concepts:  {added['fragile_concepts']}")
    print(f"  Added exceptions:        {added['exceptions']}")
    print(f"  Added distractors:       {added['distractors']}")

    # Step 3: Verify final counts
    with open(_CB_PATH, encoding="utf-8") as f:
        cb = json.load(f)

    txs   = cb["structural_operators"]["add_reaction_step"]["valid_transformations"]
    frags = cb["interpretive_operators"]["conceptual_fragility"]["concepts"]
    excs  = cb["interpretive_operators"]["number_of_exceptions"]["exceptions"]
    dists = cb["interpretive_operators"]["distractor_plausibility"]["distractors"]

    print(f"\n--- concept_book.json final state ---")
    print(f"  Total transformations:  {len(txs)}")
    print(f"  Total fragile concepts: {len(frags)}")
    print(f"  Total exceptions:       {len(excs)}")
    print(f"  Total distractors:      {len(dists)}")


if __name__ == "__main__":
    main()
