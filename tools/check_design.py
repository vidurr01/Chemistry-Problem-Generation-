"""What Jev says about the saved design (a fraction of a cent; nothing is changed).

Asks Jev the three coherence questions the pipeline asks about a written question (invented relation,
glued parts, arbitrary condition), here about the design in output/step_by_step/state.json, and shows each
probability beside the cut calibrated on real JEE Advanced questions (knowledge/coherence_calibration_
physical.json). The cuts were set on question text, not designs: read the numbers as a first look.

    python tools/check_design.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.pipeline import qfirst, refine  # noqa: E402

STATE = os.path.join(ROOT, "output", "step_by_step", "state.json")


def main():
    with open(STATE, encoding="utf-8") as f:
        d = json.load(f).get("design") or {}
    if not d:
        sys.exit("✗ no design saved: run tools/step_by_step.py design first")
    p = refine.jev_decide({"exam_question_plan": qfirst.design_plan_text(d)}, qfirst.COHERENCE_QUESTIONS,
                          role="design_check")
    cuts = qfirst._coherence_cuts()
    for k in qfirst.COHERENCE_QUESTIONS:
        flag = "FLAGGED" if p.get(k, 0) >= cuts[k] else "ok"
        print(f"{k:20} Jev {p.get(k, 0):6.1%}   cut {cuts[k]:5.1%}   {flag}")
    print(f"\nSpent: ${models.SPEND.total_cost:.4f}")


if __name__ == "__main__":
    main()
