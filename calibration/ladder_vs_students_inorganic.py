"""
ladder_vs_students_inorganic.py: is our "medium-hard" bar realistic for inorganic, measured so that memorised
answers cannot help?

The inorganic pipeline calls a question too easy when Granite (or, since 2026-11-25, GLM) solves it. This measures
those two models on REAL JEE Advanced inorganic questions whose real student results are known
(data/jee_advanced, performance_data.percent_full_marks, 2022-2025), each in two versions:
    original  as printed (options laid out one per line)
    altered   the same chemistry, but nothing to recall: options rotated by one place (every key changes), or one
              given value changed with the key worked out again by hand (ALTERED below)
The models were very likely trained on these papers (the author, 2026-11-25), so a solve of the original can be
recall. The altered version's solve rate, set against the students' results, is the fair yardstick; the gap
between the two shows how much recall helped.

Five stored keys were wrong or doubtful on a hand check (2026-11-25) and are left out (DOUBTFUL). Each question is
solved TRIES times per model and version with the pipeline's own solver call and grader, so the numbers compare
directly with what the ladder does to our generated questions. Real JEE is only a yardstick: nothing from it goes
into generation.

    python calibration/ladder_vs_students_inorganic.py --dry-run     # every question and key, no calls
    python calibration/ladder_vs_students_inorganic.py               # paid: 17 x 2 versions x 2 models x 3 tries
Output: calibration/ladder_vs_students_inorganic.json (checkpointed after every question).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import answers, models                          # noqa: E402
from core.engine.base import ChainResult                  # noqa: E402
from core.llm import write_json_atomic                    # noqa: E402
from core.pipeline import flow, stages                    # noqa: E402

OUT = os.path.join(ROOT, "calibration", "ladder_vs_students_inorganic.json")
TRIES = 3
MODELS = [name for name, _ in models.LADDER[:2]]           # granite, glm
CHOICE = {"MCQ", "MSQ", "MCQ (Multiple Correct)", "MCQ (Single Correct)"}
NUMBER = {"NAT", "NNI", "Numerical", "SDI"}
FIGURE = re.compile(r"figure|diagram|shown below|image|graph", re.I)

# stored key wrong or doubtful on a hand check (2026-11-25): left out
DOUBTFUL = {
    "2022P2_Chem_Q15": "stored D (75%); fcc + alternate tetrahedral voids gives pi*sqrt(3)/16 = 34%, B; and it is "
                       "solid state, not inorganic",
    "2022P2_Chem_Q4": "stored 2; Xe + O2F2 gives XeF4, whose hydrolysis gives 4 HF per mol",
    "2024P2_Chem_Q17": "stored 1; Q is K2Zn3[Fe(CN)6]2, 3 Zn",
    "2022P2_Chem_Q11": "stored BC; whether B itself counts is unsure",
    "2024P2_Chem_Q12": "stored 3; depends on whether P4 and [Co(CN)4]4- count as tetrahedral",
}

# Mains (2026-11-25): most stored "MCQ" are "which statements are correct" whose real choices (1)-(4) and key are
# missing, or have a merged (E), or are orderings; only true single-answer questions are used, keys checked by hand
MAINS_NOT_SINGLE = re.compile(r"\(E\)|arrange|order|statements? (is|are)|correct statement|following are|"
                              r"which of the following are", re.I)
MAINS_DOUBTFUL = {
    "2022Mains_25JulMorning_Chem_Q11": "Br2 + excess F2 'is a halate': dubious as written",
    "2022Mains_28JulEvening_Chem_Q8": "single-correct question with stored key ABD",
}

# numerical questions: (text in the question, its replacement, new key, unit). Each new key worked out by hand:
ALTERED = {
    # Cu(NO3)2 0.03 mol -> I2 0.015 mol -> S 0.015 mol = 0.48 g (was 0.02 -> 0.01 -> 0.32 g)
    "2022P1_Chem_Q4": ("3.74 g", "5.61 g", 0.48, "g"),
    # P4 0.015 mol -> PH3 0.015 -> CuSO4 0.0225 mol x 159 = 3.58 g (was 2.38 g)
    "2022P1_Chem_Q5": ("1.24 g", "1.86 g", 3.58, "g"),
    # 10 H2S + 4 MnO4- + 12 H+ -> 10 S + 4 Mn2+ + 16 H2O: x = 16, y = 20 (was 8 + 10 = 18)
    "2023P2_Chem_Q8": ("H2S (5 moles)", "H2S (10 moles)", 36, ""),
    # SOCl2 (sp3) replaced by BrF5 (sp3d2): 5 -> 4
    "2023P2_Chem_Q9": ("and SOCl2", "and BrF5", 4, ""),
    # [Co(CO)4]- has 84 electrons, as Ni(CO)4: 1 -> 2
    "2024P1_Chem_Q11": ("and Ir(CO)₃", "[Co(CO)₄]⁻ and Ir(CO)₃", 2, ""),
    # [Co(NH3)6]3+ is low-spin d6, diamagnetic: 1 -> 2
    "2024P1_Chem_Q13": ("and [Co(en)₃]³⁺", "[Co(NH₃)₆]³⁺ and [Co(en)₃]³⁺", 2, ""),
    # 2 K3[Fe(CN)6] + 2 KI -> 2 K4[Fe(CN)6] + I2: four moles of P need 4 KI (was 2)
    "2024P2_Chem_Q16": ("two moles of P", "four moles of P", 4, "mol"),
}
ROTATE = {"A": "D", "B": "A", "C": "B", "D": "C"}          # new (A) = old (B) ... new (D) = old (A)


_ASK = re.compile(r"\s*Choose the correct option\(s\)\.?", re.I)


def _options(text):
    """(question, {"A": text, ...}) or None. The markers are found in order, (A) then the first (B) after it ...:
    an option may itself contain "(C)" ("coke (C)"), which a plain split broke."""
    pos, at = 0, []
    for L in "ABCD":
        i = text.find(f"({L})", pos)
        if i < 0:
            return None
        at.append(i)
        pos = i + 3
    at.append(len(text))
    opts = {L: _ASK.sub("", text[at[k] + 3:at[k + 1]]).strip() for k, L in enumerate("ABCD")}
    return _ASK.sub("", text[:at[0]]).strip(), opts


def _choice(q, text, kind):
    split = _options(text)
    if split is None:
        return None
    head, opts = split
    key = "".join(sorted(re.findall(r"[A-D]", str(q["correct_answer"]))))
    multi = kind in ("MSQ", "MCQ (Multiple Correct)")
    tail = "Choose all the correct options." if multi else "Choose the one correct option."

    def stem(o):
        return head + "\n" + "\n".join(f"({L}) {o[L]}" for L in "ABCD") + "\n" + tail
    rotated = {new: opts[old] for old, new in ROTATE.items()}
    return ({"stem": stem(opts), "answer": key, "kind": "letters", "unit": ""},
            {"stem": stem(rotated), "answer": "".join(sorted(ROTATE[L] for L in key)), "kind": "letters", "unit": ""})


def _number(q, text, kind):
    if q["id"] not in ALTERED:
        return None
    old, new, key2, unit = ALTERED[q["id"]]
    if old not in text:
        raise SystemExit(f"{q['id']}: {old!r} is not in the question text")
    key = float(re.findall(r"-?\d+(?:\.\d+)?", str(q["correct_answer"]))[0])
    integer = float(key).is_integer() and float(key2).is_integer()
    tail = "Give the answer as an integer." if integer else "Give the answer correct to two decimal places."

    def item(t, k):
        tol = 0.001 if integer else 0.0101 / abs(k)             # JEE accepts +-0.01 on two decimals
        return {"stem": f"{t}\n{tail}", "answer": k, "kind": "count" if integer else "number", "unit": unit,
                "tolerance": tol}
    return item(text, key), item(text.replace(old, new, 1), key2)


def questions(qset: str = "advanced") -> list:
    """advanced: inorganic with real student results (choice with options, or numerical with ALTERED keys).
    mains (2026-11-25, is the ladder able to tell Mains from Advanced?): inorganic multiple-choice with the options
    written in the question; no student results exist for Mains."""
    out = []
    folder = "jee_advanced" if qset == "advanced" else "jee_mains"
    for f in sorted(glob.glob(os.path.join(ROOT, "data", folder, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        for q in (d if isinstance(d, list) else d.get("questions", d)):
            if not str(q.get("topic", "")).lower().startswith("inorg") or q["id"] in DOUBTFUL:
                continue
            pct = (q.get("performance_data") or {}).get("percent_full_marks")
            text, kind = q["question_text"], q["question_type"]
            if (qset == "advanced" and pct is None) or FIGURE.search(text):
                continue
            if qset == "mains" and (kind != "MCQ" or q["id"] in MAINS_DOUBTFUL or not str(q.get("correct_answer"))
                                    or MAINS_NOT_SINGLE.search(text)):
                continue
            made = _choice(q, text, kind) if kind in CHOICE else _number(q, text, kind) if kind in NUMBER else None
            if made:
                out.append({"id": q["id"], "type": kind, "pct_full": pct, "original": made[0], "altered": made[1]})
    return out


def _result(v) -> ChainResult:
    r = ChainResult(answer=v["answer"], unit=v["unit"], kind=v["kind"], asks=v["stem"], trace=[], traps=[],
                    constants=[])
    r.tolerance = v.get("tolerance", 0.001)
    r.options = []
    return r


def main():
    global TRIES
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set", dest="qset", choices=["advanced", "mains"], default="advanced")
    ap.add_argument("--models", default=",".join(MODELS), help="ladder steps to run, e.g. granite-4.2-8b")
    ap.add_argument("--versions", default="original,altered")
    ap.add_argument("--max-rs", type=float, default=10.0, help="hard spend cap in rupees")
    ap.add_argument("--tries", type=int, default=3, help="answers per model and version")
    ap.add_argument("--out", default=None, help="output JSON (default: the set's own file)")
    args = ap.parse_args()
    from tools.spend_cap import SpendCap, SpendCapReached
    cap = SpendCap(args.max_rs)
    names, versions = args.models.split(","), args.versions.split(",")
    TRIES = args.tries
    out_path = args.out or (OUT if args.qset == "advanced" else OUT.replace(".json", "_mains.json"))
    qs = questions(args.qset)
    print(f"{len(qs)} real {args.qset} inorganic questions (no picture); "
          f"{len(DOUBTFUL)} Advanced keys left out as doubtful")
    if args.dry_run:
        for q in qs:
            print(f"\n=== {q['id']} ({q['type']}): full marks {q['pct_full']}% of candidates")
            for v in ("original", "altered"):
                x = q[v]
                print(f"--- {v}: key {x['answer']}{(' ' + x['unit']) if x['unit'] else ''}\n{x['stem']}")
        return
    try:
        with open(out_path, encoding="utf-8") as f:
            done = {r["id"]: r for r in json.load(f)["records"]}
    except (OSError, ValueError, KeyError):
        done = {}
    records = []
    for q in qs:
        if q["id"] in done:
            records.append(done[q["id"]])
            continue
        try:
            cap.check(q["id"])
        except SpendCapReached as e:
            print(e)
            break
        rec = {k: q[k] for k in ("id", "type", "pct_full")} | {"versions": {}}
        for v in versions:
            res = _result(q[v])
            spec = answers.answer_spec(res.answer, res.kind, res.unit, flow._answer_instruction(object(), res), None)
            per = {}
            for name in names:
                got = []
                for _ in range(TRIES):
                    try:
                        m = stages.council_solve(q[v]["stem"], [name], spec)[0]
                        got.append({"answer": m.get("final_answer"), "value": m.get("final_value"),
                                    "solved": flow._grade(res, m)["counts_as_solved"]})
                    except Exception as e:                   # noqa: BLE001  recorded, never graded
                        got.append({"answer": None, "solved": None, "error": str(e)[:120]})
                per[name] = got
            rec["versions"][v] = {"key": q[v]["answer"], "tries": per}
        records.append(rec)
        print(f"{q['id']:18} full {q['pct_full']}%  " + "  ".join(
            f"{v[:4]} " + " ".join(f"{n.split('-')[0]} {sum(1 for t in rec['versions'][v]['tries'][n] if t['solved'])}"
                                   f"/{TRIES}" for n in names) for v in versions), flush=True)
        write_json_atomic(out_path, {"models": names, "tries": TRIES, "doubtful": DOUBTFUL, "records": records,
                                "spend": models.SPEND.summary()}, ensure_ascii=False)
    print("spend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
