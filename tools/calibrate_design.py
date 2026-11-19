"""Calibrate Jev's check of a DESIGN (before anything is written) on real JEE Advanced questions.

Real questions have no designs, so a cheap model describes each one in our design format ("reverse
design"); every such design is reviewed by hand before it counts. Then Jev asks the three coherence
questions (qfirst.COHERENCE_QUESTIONS) about each design, written as qfirst.design_plan_text; per fault the
cut-off is the PERCENTILE-th percentile of the reviewed real designs' scores, as for questions
(tools/calibrate_coherence.py); bad designs (BAD_DESIGNS: the failed designs of 2026-11-16/17 and
hand-written ones, labelled by fault) show what it catches. Written to
knowledge/design_coherence_calibration_physical.json, which qfirst.design_problems reads (no file: no check).

    python tools/calibrate_design.py reverse        # ~3-6 cents: Gemini Flash describes ~30 real questions
    (each entry gets a suggested review, "ok" or "bad", with a note and who suggested it; the sheet
     knowledge/design_calibration_review_sheet.md shows them; the author checks them)
    python tools/calibrate_design.py accept         # records the suggestions as the author's review
    python tools/calibrate_design.py score          # Jev, a fraction of a cent
"""
import importlib.util
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.engine import physical as ph  # noqa: E402
from core.pipeline import qfirst, refine  # noqa: E402

DESIGNS = os.path.join(ROOT, "knowledge", "design_calibration_designs_physical.json")
OUT = os.path.join(ROOT, "knowledge", "design_coherence_calibration_physical.json")
PERCENTILE = 95
N_REAL = 30
FIELDS = ("system", "hidden_link", "route", "student_must_notice", "trap", "given", "hidden", "asked", "why_hard")

# Bad designs, labelled by fault. The first three are real failed designs (2026-11-16/17), shortened.
BAD_DESIGNS = [
    ("arbitrary_condition", {
        "system": "N2O4(g) <=> 2 NO2(g) in a rigid closed vessel of volume V at temperature T.",
        "hidden_link": "The condition that the numerical value of Kp (atm) equals the numerical value of Kc (mol/L) "
                       "while the total pressure reaches a set value P_set.",
        "route": "Kc from amounts and V; Dalton for the partial pressures; Kp from them; impose Kp = Kc numerically "
                 "(forces RT = 1) with P_total = P_set to find V.",
        "given": "initial mass of N2O4; the total pressure at which Kp = Kc numerically; R",
        "asked": "the volume of the vessel (L)"}),
    ("invented_relation", {
        "system": "N2 + 3H2 <=> 2NH3 in a rigid reactor; an identical reactor holds neon; a valve is opened until "
                  "the synthesis reactor reaches a target pressure.",
        "hidden_link": "The volume V links Kc to Kp through Kp = Kc(RT)^Δn; V is found from the neon reactor.",
        "route": "Dalton for the reactive gases after neon enters; Kc from moles and V; Kp equals Kc(RT)^Δn with V "
                 "as the bridge; V from the neon data.",
        "given": "the reaction; T; the 1:3 ratio; the amount and pressure of neon; the target total pressure",
        "asked": "the minimum amount of neon (mol)"}),
    ("arbitrary_condition", {
        "system": "A rigid vessel of pure PCl5(g) at 500 K: PCl5 <=> PCl3 + Cl2.",
        "hidden_link": "The condition sets Kc numerically equal to the partial pressure of PCl5, which fixes all "
                       "partial pressures from Kp and T.",
        "route": "Kc = Kp/(RT); Kc = P_PCl5 gives P_PCl5; Kp gives P_PCl3 = P_Cl2; Dalton gives P_total; the mass "
                 "and the ideal gas law give V.",
        "given": "the reaction, T, Kp, the initial mass of PCl5",
        "asked": "the volume of the vessel (L)"}),
    ("arbitrary_condition", {
        "system": "A first-order decomposition of N2O5 at 318 K in a closed flask.",
        "hidden_link": "The reaction is stopped when the fraction of N2O5 remaining equals the mole fraction of "
                       "glucose in a separate 10 % glucose solution.",
        "route": "mole fraction of glucose from its mass; first-order law gives the time for that fraction.",
        "given": "k at 318 K; the glucose solution's composition",
        "asked": "the time (min)"}),
    ("arbitrary_condition", {
        "system": "Electrolysis of aqueous CuSO4 with copper electrodes.",
        "hidden_link": "The current is passed until the mass of copper deposited (g) equals the pH of a 0.01 M "
                       "acetic acid solution.",
        "route": "pH of acetic acid from Ka; Faraday's law gives the charge for that mass.",
        "given": "Ka of acetic acid; the current",
        "asked": "the time of electrolysis (s)"}),
    ("invented_relation", {
        "system": "A sample of impure KMnO4 analysed by titration and by spectroscopy.",
        "hidden_link": "The Gibbs energy of the redox reaction is the product of the sample's purity and the number "
                       "of absorption peaks.",
        "route": "purity from the titre; ΔG° = −(purity × peaks × 100); E° from ΔG°.",
        "given": "the titre and the spectrum",
        "asked": "E° of the cell (V)"}),
    ("invented_relation", {
        "system": "A metal crystallising in an fcc lattice dissolved in mercury to form an amalgam.",
        "hidden_link": "The boiling-point elevation of the amalgam is proportional to the edge length of the "
                       "metal's unit cell.",
        "route": "edge length from density; ΔTb = 0.001 × a; molality from ΔTb.",
        "given": "the metal's density and molar mass",
        "asked": "the molality of the amalgam"}),
    ("glued_parts", {
        "system": "4.40 g of CO2 collected at STP; separately, a first-order reaction with a 10.0 min half-life.",
        "hidden_link": "None: the two systems are joined by multiplying their results.",
        "route": "moles of CO2 from mass; k from the half-life; their product.",
        "given": "the mass of CO2; the half-life",
        "asked": "moles of CO2 × k (min⁻¹)"}),
    ("glued_parts", {
        "system": "The work function of sodium; separately, the freezing point of a 0.100 m urea solution.",
        "hidden_link": "None: the threshold frequency is divided by the freezing-point depression.",
        "route": "threshold frequency from the work function; ΔTf = Kf m; their ratio.",
        "given": "the work function; Kf; the molality",
        "asked": "the ratio of the two"}),
    ("glued_parts", {
        "system": "A Daniell cell; separately, a gas of density 1.25 g/L at STP.",
        "hidden_link": "None: the molar mass of the gas is divided by the cell's EMF.",
        "route": "EMF from E°; molar mass from density; the quotient.",
        "given": "E°, the concentrations, the gas density",
        "asked": "molar mass ÷ EMF"}),
]


def _fmap():
    spec = importlib.util.spec_from_file_location("fmap", os.path.join(ROOT, "docs", "advanced_formula_map.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.MAP


def real_questions() -> list:
    """Real numeric JEE Advanced physical questions whose solution uses 2+ engine formulas (as our designs
    do; then 1-formula ones if fewer than N_REAL), spread over the years."""
    spec = importlib.util.spec_from_file_location("cc", os.path.join(ROOT, "tools", "calibrate_coder.py"))
    cc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cc)
    allq = cc.real_questions()
    fmap = _fmap()
    for q in allq:
        q["note"] = fmap[q["id"]][2]
    multi = [q for q in allq if len(set(q["txs"])) >= 2]
    single = [q for q in allq if len(set(q["txs"])) < 2]
    picked = cc.spread(multi, N_REAL) if len(multi) >= N_REAL else multi + cc.spread(single, N_REAL - len(multi))
    return picked


def reverse_one(q: dict) -> dict:
    formulas = qfirst.formulas_text([ph.step(t) for t in dict.fromkeys(q["txs"])])
    prompt = f"""Below is a REAL JEE Advanced chemistry question (with its official answer). Describe its design: how
it is built, in the JSON format below. Describe only what this question actually does; invent nothing, do not
improve or change it. Keep each field to one or two sentences.

Question: {q['text']}
Official answer: {q['answer']}
How its solution uses its formulas (a note): {q['note']}
The formulas its solution uses:
{formulas}

Return JSON:
{{"system": "the one real system: substances, reactions, conditions",
  "hidden_link": "which quantity joins which formulas, and why the question never states it (or 'none' if the
                  formulas simply follow one another)",
  "route": "for each formula, in the order a solver uses it: what it takes and what it gives here",
  "student_must_notice": "the non-obvious point that decides the answer",
  "trap": "the tempting wrong route",
  "given": "the quantities the question states (in words, no numbers)",
  "hidden": "the quantities it does not state",
  "asked": "the asked quantity, with its unit",
  "why_hard": "one sentence"}}"""
    out = models.ask_json("design_reverse", models.GENERATOR, "You describe exam questions. Output JSON only.", prompt,
                          max_tokens=5000, temperature=0.2, retry_cut_off=False,
                          reasoning_effort="low")        # Gemini 3: a level, not a budget (designer, 2026-11-17)
    return {k: out.get(k, "") for k in FIELDS}


def do_reverse():
    qs = real_questions()
    print(f"Gemini Flash ({models.GENERATOR}) describes {len(qs)} real JEE Advanced questions as designs ...")

    def one(q):
        try:
            return {**q, "design": reverse_one(q), "review": None, "review_note": ""}
        except Exception as e:  # noqa: BLE001
            return {**q, "design": None, "error": f"{type(e).__name__}: {str(e)[:160]}", "review": None}
    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, qs))
    with open(DESIGNS, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in rows if r.get("design"))
    print(f"{ok}/{len(rows)} designs written to {os.path.relpath(DESIGNS, ROOT)} for review "
          f"(cost ${models.SPEND.total_cost:.4f})")


def jev(design: dict):
    try:
        return refine.jev_decide({"exam_question_plan": qfirst.design_plan_text(design)}, qfirst.COHERENCE_QUESTIONS,
                                 role="design_calibration")
    except Exception:  # noqa: BLE001
        return None


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def do_score():
    with open(DESIGNS, encoding="utf-8") as f:
        rows = json.load(f)
    good = [r for r in rows if r.get("design") and r.get("review") == "ok"]
    unreviewed = [r["id"] for r in rows if r.get("design") and r.get("review") is None]
    if unreviewed:
        sys.exit(f"✗ {len(unreviewed)} designs not reviewed yet: {', '.join(unreviewed[:6])} ...")
    print(f"Jev scores {len(good)} reviewed real designs and {len(BAD_DESIGNS)} bad ones ...")
    with ThreadPoolExecutor(max_workers=8) as ex:
        sg = list(ex.map(jev, [r["design"] for r in good]))
        sb = list(ex.map(jev, [d for _, d in BAD_DESIGNS]))
    G = [(r, s) for r, s in zip(good, sg) if s]
    B = [(f, d, s) for (f, d), s in zip(BAD_DESIGNS, sb) if s]
    if len(G) < 15 or len(B) < 6:
        sys.exit(f"✗ too few answers ({len(G)} real, {len(B)} bad); nothing written")
    cuts, report = {}, {}
    for k in qfirst.COHERENCE_QUESTIONS:
        real = [s.get(k, 0.0) for _, s in G]
        cut = round(max(pct(real, PERCENTILE), 0.05), 3)
        own = [s.get(k, 0.0) for f, _, s in B if f == k]
        cuts[k] = cut
        report[k] = {"real_median": statistics.median(real), "cut": cut, "bad_n": len(own),
                     "caught": sum(x >= cut for x in own)}
        print(f"{k:20}  real median {statistics.median(real):.0%}  cut {cut:.0%}  bad caught "
              f"{report[k]['caught']}/{len(own)}  ({', '.join(f'{x:.0%}' for x in own)})")
    flagged = sum(any(s.get(k, 0) >= cuts[k] for k in cuts) for _, s in G)
    caught = sum(any(s.get(k, 0) >= cuts[k] for k in cuts) for _, _, s in B)
    print(f"\nreal designs flagged: {flagged}/{len(G)}   bad designs caught: {caught}/{len(B)}")
    if caught < len(B) / 2:
        print("✗ catches fewer than half of the bad designs: nothing written (no design check)")
        return
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"thresholds": cuts, "percentile": PERCENTILE, "report": report, "jev_model": models.JEV_MODEL,
                   "real_flagged": flagged, "real_n": len(G), "bad_caught": caught, "bad_n": len(B),
                   "real": [{"id": r["id"], "scores": s} for r, s in G],
                   "bad": [{"fault": f, "scores": s} for f, _, s in B]}, f, ensure_ascii=False, indent=1)
    print(f"written: {os.path.relpath(OUT, ROOT)}  (cost ${models.SPEND.total_cost:.4f})")


def do_accept():
    """The author accepts the suggested reviews: each becomes "review", recorded as accepted by the author."""
    with open(DESIGNS, encoding="utf-8") as f:
        rows = json.load(f)
    for r in rows:
        if r.get("design") and r.get("suggested_review") in ("ok", "bad"):
            r["review"] = r["suggested_review"]
            r["review_note"] = r.get("suggested_note", "")
            r["review_by"] = f"suggested by {r.get('suggested_by', '?')}; accepted by the author"
    with open(DESIGNS, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"{sum(r.get('review') == 'ok' for r in rows)} ok, {sum(r.get('review') == 'bad' for r in rows)} bad: "
          f"recorded as accepted by the author → next: score")


if __name__ == "__main__":
    if not models.key_is_set():
        sys.exit("✗ no API key in .env")
    {"reverse": do_reverse, "accept": do_accept, "score": do_score}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
