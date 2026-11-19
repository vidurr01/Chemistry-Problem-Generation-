"""Calibrate Jev's coherence check (qfirst.COHERENCE_QUESTIONS) on labelled questions (about one cent).

GOOD: the real JEE Advanced physical-chemistry numerical questions (data/jee_advanced): real papers do not
invent relations, glue parts or link them by arbitrary conditions. BAD: questions with exactly one of these
faults: the two such questions our pipeline once accepted, and hand-written examples (BAD_EXAMPLES, labelled
by fault). For each fault the cut-off is the PERCENTILE-th percentile of the real questions' scores (so at
most 100 - PERCENTILE % of real questions are flagged for it); the share of bad questions caught is
reported. Written to knowledge/coherence_calibration_physical.json, which qfirst reads.

    python tools/calibrate_coherence.py
"""
import glob
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.pipeline import qfirst, refine  # noqa: E402

OUT = os.path.join(ROOT, "knowledge", "coherence_calibration_physical.json")
PERCENTILE = 95
NUMERIC = {"NAT", "Numerical", "NNI", "PNV", "Integer", "SDI"}
OWN_BAD = {"GEN_20261115T221723": "invented_relation", "GEN_20261115T223406": "arbitrary_condition"}

BAD_EXAMPLES = [
    ("invented_relation", "A 0.250 M solution of acetic acid has pH 2.68. The rate constant (in min⁻¹) of the first-order "
     "hydrolysis of methyl acetate in this solution is numerically equal to one tenth of its pH. Find the half-life (min) "
     "of the hydrolysis."),
    ("invented_relation", "Iron(III) chloride dissolves in water. The osmotic pressure (in atm) of a solution of it is equal to "
     "the number of unpaired electrons in Fe³⁺ multiplied by its molality. Find the osmotic pressure of a 0.150 m solution."),
    ("invented_relation", "In a galvanic cell the EMF (in V) equals 0.250 times the bond order of the O₂ molecule. Find the "
     "Gibbs energy change (kJ mol⁻¹) when 2 electrons are transferred. (F = 96500 C mol⁻¹)"),
    ("invented_relation", "A metal crystallises in a cubic lattice whose packing fraction equals the mole fraction of the solute "
     "in a solution of 10.0 g of glucose in 90.0 g of water. Identify the edge length if the atomic radius is 128 pm."),
    ("glued_parts", "4.40 g of CO₂ is collected at STP. Separately, the pH of a 0.010 M HCl solution is measured. Report "
     "the sum of the number of moles of CO₂ and the pH."),
    ("glued_parts", "A sample of N₂ occupies 2.24 L at 273 K and 1 atm. A first-order reaction has a half-life of 10.0 min. "
     "Find the product of the moles of N₂ and the rate constant (min⁻¹) of the reaction."),
    ("glued_parts", "The work function of sodium is 2.28 eV. Separately, the freezing point of a 0.100 m urea solution is "
     "measured (K_f = 1.86 K kg mol⁻¹). Find the ratio of the threshold frequency (in 10^14 Hz) to the freezing-point "
     "depression (K)."),
    ("glued_parts", "Calculate the molar mass of a gas whose density is 1.25 g L⁻¹ at STP, and the EMF of a Daniell cell "
     "with E° = 1.10 V at unit concentrations; give the molar mass divided by the EMF."),
    ("arbitrary_condition", "A 0.100 M solution of sucrose at 300 K is diluted until its osmotic pressure equals 3.5 % of the "
     "vapour pressure of water at 300 K (26.7 mm Hg). Find the final volume if the initial volume was 50.0 mL."),
    ("arbitrary_condition", "Copper is deposited from CuSO₄ solution until the mass of copper deposited (in g) equals the number "
     "of moles of argon in a 5.00 L flask at 2.00 atm and 300 K. Find the charge passed (C)."),
    ("arbitrary_condition", "Oxygen gas is heated until its rms speed (in m s⁻¹) equals 1000 times the EMF (in V) of a "
     "standard hydrogen–silver cell. Find the temperature."),
    ("arbitrary_condition", "A first-order reaction is allowed to proceed until the fraction remaining equals the degree of "
     "dissociation of 0.10 M acetic acid (Ka = 1.8 × 10^-5). Find the time if k = 0.0230 min⁻¹."),
]


def real_advanced() -> list:
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "jee_advanced", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            j = json.load(fh)
        for q in (j["questions"] if isinstance(j, dict) else j):
            if str(q.get("topic", "")).startswith("Physical") and q.get("question_type") in NUMERIC:
                out.append({"id": q["id"], "text": " ".join(str(q["question_text"]).split())})
    return out


def bad() -> list:
    out = [{"id": f"hand_{i}", "fault": f, "text": t} for i, (f, t) in enumerate(BAD_EXAMPLES)]
    from subject_config import get_subject_config
    try:
        with open(get_subject_config("physical")["output_file"], encoding="utf-8") as f:
            for r in json.load(f):
                if r["question_id"] in OWN_BAD:
                    out.append({"id": r["question_id"], "fault": OWN_BAD[r["question_id"]], "text": r["question"]})
    except OSError:
        pass
    return out


def score(items: list) -> list:
    def one(it):
        try:
            return refine.jev_decide({"exam_question": it["text"]}, qfirst.COHERENCE_QUESTIONS, role="coherence_calibration")
        except Exception:  # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, items))


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    good, badq = real_advanced(), bad()
    print(f"Scoring {len(good)} real JEE Advanced questions and {len(badq)} known bad ones with Jev ...")
    sg, sb = score(good), score(badq)
    G = [(it, s) for it, s in zip(good, sg) if s]
    B = [(it, s) for it, s in zip(badq, sb) if s]
    if len(G) < 20 or len(B) < 6:
        sys.exit(f"✗ Jev answered too few ({len(G)} real, {len(B)} bad); nothing written")
    cuts, report = {}, {}
    print()
    for k in qfirst.COHERENCE_QUESTIONS:
        real = [s.get(k, 0.0) for _, s in G]
        cut = round(max(pct(real, PERCENTILE), 0.05), 3)
        own = [s.get(k, 0.0) for it, s in B if it["fault"] == k]
        caught = sum(x >= cut for x in own)
        cuts[k] = cut
        report[k] = {"real_median": statistics.median(real), "cut": cut,
                     "bad_with_this_fault": len(own), "caught": caught}
        print(f"{k:20}  real JEE median {statistics.median(real):.0%}  cut {cut:.0%}  "
              f"bad ones with this fault caught: {caught}/{len(own)}  (their scores: "
              f"{', '.join(f'{x:.0%}' for x in own)})")
    flagged_real = sum(any(s.get(k, 0) >= cuts[k] for k in cuts) for _, s in G)
    caught_any = sum(any(s.get(k, 0) >= cuts[k] for k in cuts) for _, s in B)
    print(f"\nreal JEE Advanced questions flagged for any fault: {flagged_real}/{len(G)}")
    print(f"known bad questions caught for any fault:          {caught_any}/{len(B)}")
    print(f"(with the old single cut 50%: real flagged "
          f"{sum(any(s.get(k, 0) >= 0.5 for k in cuts) for _, s in G)}/{len(G)}, bad caught "
          f"{sum(any(s.get(k, 0) >= 0.5 for k in cuts) for _, s in B)}/{len(B)})")
    if caught_any < len(B) / 2:
        print("\n✗ the check catches fewer than half of the bad questions at these cuts: nothing written "
              "(the old 50 % cut stays). Tell the user.")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"thresholds": cuts, "percentile": PERCENTILE, "report": report, "jev_model": models.JEV_MODEL,
                   "real_flagged": flagged_real, "real_n": len(G), "bad_caught": caught_any, "bad_n": len(B),
                   "real": [{**it, "scores": s} for it, s in G], "bad": [{**it, "scores": s} for it, s in B]},
                  f, ensure_ascii=False, indent=1)
    print(f"\nwritten: {os.path.relpath(OUT, ROOT)}  (cost ${models.SPEND.total_cost:.4f})")


if __name__ == "__main__":
    main()
