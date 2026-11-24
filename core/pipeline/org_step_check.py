"""
Organic only: a blind check of every reaction step of a drawn scheme (2026-11-24, approved by the author after a
measurement: tools/check_steps.py, outputs/step_check_calibration_luna*.json).

GPT-6 Luna is shown one step at a time (substrate SMILES + the reagent as the question prints it, never the
engine's product) and names the major organic product; code compares it with the engine's (canonical SMILES,
stereo ignored, small by-products such as H2O / CO2 / HCl left out). Any step it does not agree with holds the
scheme: a wrong engine step (live runs 6-8) would otherwise become a wrong key. GPT-6 Luna is not used anywhere
else in the organic pipeline, so this is an independent check. About Rs 0.03 per step.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from rdkit import Chem, RDLogger

from core import models
from core.engine.organic.labels import REAGENT_LABEL

RDLogger.DisableLog("rdApp.*")

STEP_CHECKER = "openai/gpt-6-luna"          # fixed: --coder (physical) must not change the organic checker

# by-products a checker may list that are not the organic product
SMALL = {"O", "O=C=O", "Cl", "Br", "I", "N", "[H][H]", "N#N", "O=S=O", "O=P(Cl)(Cl)Cl", "OS(=O)(=O)O"}


def canon_set(smiles: str) -> set:
    out = set()
    for part in str(smiles or "").replace(" ", "").split("."):
        m = Chem.MolFromSmiles(part)
        if m is None:
            continue
        Chem.RemoveStereochemistry(m)
        s = Chem.MolToSmiles(m)
        if s not in SMALL:
            out.add(s)
    return out


def ask(substrate: str, reagent: str, model: str = STEP_CHECKER) -> dict:
    prompt = f"""Organic reaction (JEE Advanced / NCERT chemistry, standard textbook outcome):
substrate (SMILES): {substrate}
reagent and conditions: {reagent}

What is the major organic product? Think about every functional group in the substrate: which one this reagent
attacks first, regiochemistry, rearrangements, and whether the textbook reaction applies to THIS substrate at all.
If the molecule splits, give every organic piece separated by '.'.
Return JSON: {{"product_smiles": "SMILES, or empty if no single major product / no reaction",
 "no_single_product": true or false, "reason": "one sentence"}}"""
    try:
        return models.ask_json("step_checker", model, "You are an expert organic chemist. Output JSON only.", prompt,
                               temperature=0.0, max_tokens=6000)
    except Exception as e:                        # noqa: BLE001  a failed call is a result, never a pass
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


def verdict(engine: str, d: dict) -> str:
    """agree / disagree / unparsed / error"""
    if "error" in d:
        return "error"
    if d.get("no_single_product") and not d.get("product_smiles"):
        return "disagree"
    got = canon_set(d.get("product_smiles"))
    if not got:
        return "unparsed"
    want = canon_set(engine)
    if len(want) == 1 and len(got) > 1:          # the checker names several pieces: the engine's must be the main one
        largest = max(got, key=lambda s: Chem.MolFromSmiles(s).GetNumHeavyAtoms())  # (live run 9: acetic acid
        return "agree" if largest in want else "disagree"                            #  passed as "S")
    return "agree" if want and (want <= got or got <= want) else "disagree"


def check_scheme(cand) -> list:
    """Every step the checker does not agree with: [{"label", "edge", "substrate", "reagent", "engine", "verdict",
    "checker_product", "reason"}]. [] means every step agrees."""
    comps = cand["_comps"]
    steps = [(lab, comps[comps[lab]["parent"]]["smiles"], comps[lab]["edge"]["id"], comps[lab]["smiles"])
             for lab in cand["_order"][1:]]

    def one(step):
        lab, sub, eid, prod = step
        d = ask(sub, REAGENT_LABEL[eid])
        return {"label": lab, "edge": eid, "substrate": sub, "reagent": REAGENT_LABEL[eid], "engine": prod,
                "verdict": verdict(prod, d), "checker_product": d.get("product_smiles", d.get("error")),
                "reason": d.get("reason", "")}
    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(one, steps))
    return [r for r in rows if r["verdict"] != "agree"]
