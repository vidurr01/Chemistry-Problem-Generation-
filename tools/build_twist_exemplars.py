"""
Build knowledge/jee_adv_twist_exemplars_physical.json: real JEE Advanced physical questions
grouped by how they use their formulas (the "twist" of docs/advanced_formula_map.py), with
their text from data/jee_advanced/<year>.json. The question-first writer
(core/pipeline/qfirst.py) is shown two of these for its twist, for difficulty and style only.

    python tools/build_twist_exemplars.py
"""

import glob
import importlib.util
import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "knowledge", "jee_adv_twist_exemplars_physical.json")
TWISTS = {"inverse": "inverse", "two-state ratio": "two_state_ratio",
          "two-state difference": "two_state_difference", "simultaneous": "simultaneous",
          "condition": "condition"}


def _bank():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "jee_advanced", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            for q in json.load(fh)["questions"]:
                out[q["id"]] = q
    return out


def _resolve(qid, bank):
    year, rest = qid.split("_", 1)
    for cand in (f"{year}_Chem_{rest}" if "P" in year else None, qid.replace("_", "_Chem_", 1),
                 qid, f"{year}P1_{rest}"):
        if cand and cand in bank:
            return bank[cand]
    return None


def main():
    spec = importlib.util.spec_from_file_location("fmap", os.path.join(ROOT, "docs", "advanced_formula_map.py"))
    fmap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fmap)
    bank = _bank()
    out = {t: [] for t in TWISTS.values()}
    for qid, (steps, mod, note) in fmap.MAP.items():
        if mod not in TWISTS:
            continue
        q = _resolve(qid, bank)
        if q is None:
            print("not found:", qid)
            continue
        out[TWISTS[mod]].append({"id": q["id"], "text": re.sub(r"\s+", " ", q["question_text"]).strip(),
                                 "txs": [s for s in steps if isinstance(s, int)], "note": note})
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print({k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
