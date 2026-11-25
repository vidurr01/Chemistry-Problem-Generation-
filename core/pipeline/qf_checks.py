"""Question first, stage 6: CHECKS.

Before any program: Jev's level check (level_problem). After the numbers: the code checks of the
question itself (question_problems, unneeded) and Jev's coherence check (coherence_problems). explain()
turns a problem into words the writer can act on."""

from __future__ import annotations

import json
import os
import re

from core import answers
from core.pipeline import gate
from core.pipeline.qf_draw import calibration_path
from core.pipeline.qf_text import _scaled_equal, _trivial, stated_numbers, too_close_to_past
from core.pipeline.qf_writer import preview_text


COHERENCE_REJECT_AT = 0.5   # Jev: a draft this likely to invent a relation or glue parts is rewritten


# Step mistakes that must give distinct, believable wrong answers. 1 since 2026-11-19 (the author): at 2 it was the
# commonest way a draw died (3 of 5 draws in one run), it ignores the designer's conceptual trap, and some real
# JEE Advanced questions cannot meet it (2017P1_Q26's formulas know two mistakes between them). Difficulty is
# guarded by Jev's level check and the ladder, not by this count.
MIN_TRAPS = 1


def _squash(s) -> str:
    return " ".join(answers.normalise_text(s).replace("−", "-").split())


# Dropping an unneeded formula must leave at least this many. 3, as when draws had 3-5 formulas: since draws have
# 2-3 (2026-11-25), a drawn formula is the design's and a program that skips one goes back to the coder.
DROP_KEEPS = 3


def unneeded(drawn, run) -> list:
    """Drawn formulas the solving program did not use or whose result does not change the answer,
    when dropping them still leaves DROP_KEEPS: those are dropped, not a reason to reject the
    question (a rewrite costs a writer call and the ladder never needed them either)."""
    bad = [t for t in drawn if t in set(run.get("unused_steps") or ()) | set(run.get("irrelevant_steps") or ())]
    return bad if bad and len(drawn) - len(bad) >= DROP_KEEPS else []


def question_problems(stem: str, run: dict, txs, constants: list, examples=(), accepted=(), built=False) -> list:
    """What is wrong with the question itself: the writer fixes these. built=True skips the formula and
    typical-mistake checks (kept for callers that check those themselves; the pipeline does not)."""
    probs = []
    irrelevant = [] if built else [t for t in run.get("irrelevant_steps", []) if t in txs]
    if irrelevant:
        from core.engine import physical as ph
        probs.append("the result of " + "; ".join(f"'{ph.step(t).asks}'" for t in irrelevant)
                     + " does not change the answer; every formula must matter")
    stem_nums = stated_numbers(stem)
    givens = [float(g["value"]) for g in run["givens"]
              if isinstance(g["value"], (int, float)) and not isinstance(g["value"], bool)]
    const_nums = [n for c in run["constants"] for n in stated_numbers(c)]
    for x in run["intermediates"]:
        if _trivial(x) or any(_scaled_equal(x, gv) for gv in givens + const_nums):
            continue
        if any(n != 0 and abs(n - x) <= 0.005 * abs(x) for n in stem_nums):
            probs.append(f"the question states {x:.4g}, which is a result the solution has to compute; "
                         f"remove it")
    if not built and len(run["traps"]) < MIN_TRAPS:
        probs.append(f"only {len(run['traps'])} of the typical mistakes changes the answer; choose values "
                     f"where at least {MIN_TRAPS} of them give clearly different answers")
    for c in constants:
        nums = stated_numbers(c.split("=", 1)[1] if "=" in c else c)
        if nums and not any(_scaled_equal(nums[0], n) for n in stem_nums):
            probs.append(f"state this constant in the Given line: {c}")
    computed = gate.computed_values(stem)
    if computed:
        probs.append(f"the question gives a computed value, which reveals the method: {'; '.join(computed)}")
    close = too_close_to_past(stem, givens, examples)
    if close:
        probs.append(f"not new: {close}; write a new hard question, not a copy or a re-dressed version of it")
    close = too_close_to_past(stem, givens, accepted)
    if close:
        probs.append(f"repeats our own accepted question: {close.replace('example', 'question')}; "
                     f"choose a different situation and values")
    return probs


COHERENCE_QUESTIONS = {
    "invented_relation": "The question links two quantities by a relation that is not a real chemistry or "
                         "physics law or standard definition (an equation made up for this question, such as "
                         "a Gibbs energy defined as a product of a sample's purity and a number of orbital "
                         "peaks).",
    "glued_parts": "The question is several unrelated sub-problems about different systems, joined only by "
                   "arithmetic or by an artificial statement, rather than one coherent chemical situation.",
    "arbitrary_condition": "The question connects its parts by an arbitrary condition chosen only to link them "
                           "(for example 'until the heat absorbed equals 1.20% of the electrical energy used'), "
                           "not by something that physically follows from the situation.",
}


# The coherence cut-offs: None = as calibrated (the 95th percentile of the real questions' scores: 9 of 77
# real questions rejected, 14 of 14 bad ones caught); a number = that percentile of the same real scores
# (99: 2 of 77 rejected, 14 of 14 caught). Under trial on real questions; not chosen yet.
COHERENCE_PERCENTILE = None


LOOSER_PERCENTILE = 99


def _pct(xs, p):
    """The p-th percentile, as tools/calibrate_coherence.py computes it."""
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _coherence_cuts(percentile=None, subject: str = "physical") -> dict:
    """Per-question cut-offs calibrated on real JEE Advanced questions of the subject and known bad ones
    (tools/calibrate_coherence.py), else COHERENCE_REJECT_AT for each. percentile: that percentile of the
    calibration's real scores instead of the stored cut-offs."""
    path = calibration_path("coherence", subject)
    try:
        with open(path, encoding="utf-8") as f:
            cal = json.load(f)
        if percentile is not None:
            return {k: _pct([r["scores"][k] for r in cal["real"]], percentile) for k in COHERENCE_QUESTIONS}
        cuts = cal["thresholds"]
        return {k: float(cuts.get(k, COHERENCE_REJECT_AT)) for k in COHERENCE_QUESTIONS}
    except (OSError, ValueError, KeyError, TypeError):
        return {k: COHERENCE_REJECT_AT for k in COHERENCE_QUESTIONS}


def coherence_scores(stem: str) -> dict | None:
    """Jev's probability of each fault (COHERENCE_QUESTIONS); None if Jev cannot be reached."""
    from core.pipeline import refine
    try:
        return refine.jev_decide({"exam_question": stem}, COHERENCE_QUESTIONS, role="coherence_check")
    except Exception as e:                       # noqa: BLE001
        print(f"    coherence check skipped (Jev unavailable: {str(e)[:80]})")
        return None


def coherence_problems(stem: str, scores: dict | None = None, percentile="default",
                       subject: str = "physical") -> list:
    """Jev's verdict on whether the question is real chemistry: [] if it is (or if Jev cannot be
    reached: this check never blocks a run), else what to fix. scores: Jev's, if already asked;
    percentile: the cut-offs to judge them by (default COHERENCE_PERCENTILE)."""
    p = coherence_scores(stem) if scores is None else scores
    if p is None:
        return []
    out = []
    pct = COHERENCE_PERCENTILE if percentile == "default" else percentile
    cut = _coherence_cuts(subject=subject) if pct is None else _coherence_cuts(pct, subject)
    if p.get("invented_relation", 0) >= cut["invented_relation"]:
        out.append(f"it links quantities by an invented relation (Jev: {p['invented_relation']:.0%}); use only the "
                   f"formulas listed and standard relations, or return impossible")
    if p.get("arbitrary_condition", 0) >= cut["arbitrary_condition"]:
        out.append(f"it links its parts by an arbitrary condition (Jev: {p['arbitrary_condition']:.0%}); connect them "
                   f"by what physically follows in one situation (the same gas, the same sample, the same current)")
    if p.get("glued_parts", 0) >= cut["glued_parts"]:
        out.append(f"it glues unrelated sub-problems together (Jev: {p['glued_parts']:.0%}); make it one coherent "
                   f"chemical situation, or return impossible")
    return out


# The level check (after the writer, before any program is paid for): Jev places the question on an
# ordered scale. It blocks only once calibrated on real papers (tools/calibrate_level.py writes the
# floor): no uncalibrated gate.
LEVELS = ["JEE Main easy: one formula, direct substitution",
          "JEE Main medium: two or three standard steps in a familiar set-up",
          "JEE Main hard: several steps, but every step is a standard routine",
          "JEE Advanced medium: needs one non-obvious connection or condition the student must spot",
          "JEE Advanced hard: the key link is hidden; a strong student can miss it and get a plausible wrong answer"]


LEVEL_INSTRUCTIONS = ("How hard is this chemistry exam question for a well-prepared Indian JEE aspirant? Judge the "
                      "reasoning it requires, not the length of the arithmetic.")


def _level_floor(subject: str = "physical") -> float | None:
    """The level floor calibrated on real JEE papers of the subject (tools/calibrate_level.py); None: not calibrated."""
    path = calibration_path("level", subject)
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f)["threshold"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def jev_level(text: str) -> float | None:
    """Jev's level score of a question (0 = JEE Main easy … 4 = JEE Advanced hard); None if Jev cannot
    be reached (then nothing is blocked)."""
    from core.pipeline import refine
    try:
        return refine.jev_score({"exam_question": text}, LEVEL_INSTRUCTIONS, LEVELS)["score"]
    except Exception as e:                       # noqa: BLE001
        print(f"    level check skipped (Jev unavailable: {str(e)[:80]})")
        return None


def level_problem(q: dict, subject: str = "physical") -> str | None:
    """Why the written question is below JEE Advanced level, or None (at level, not calibrated, or Jev
    down). Said to the writer in terms it can act on."""
    floor = _level_floor(subject)
    if floor is None:
        return None
    score = jev_level(preview_text(q))
    if score is None:
        return None
    name = LEVELS[min(len(LEVELS) - 1, max(0, round(score)))].split(":")[0]
    print(f"    [level] Jev: {score:.2f} ({name}); floor {floor:.2f}")
    if score >= floor:
        return None
    return (f"it reads as {name} (level {score:.2f} of 4; JEE Advanced needs at least {floor:.2f}): the solver can "
            f"follow the formulas step by step. Make the connection between them non-obvious: keep the hidden "
            f"link unstated, ask for a quantity that must be worked out backwards or fixed by two results together, "
            f"and do not hand over the data in the order they are used")


_IMPOSSIBLE_VALUE = re.compile(r"must be (?:between|positive|negative|non-?negative|a fraction|at most|at least)"
                               r"|got -?[0-9.e+]+|impossible result|comes out (?:zero|negative)")


def explain(problem: str, drawn=None, consistent: bool = False) -> str:
    """The writer-facing form of a problem: an engine range error (a purity of 72264 %) means the
    stated data contradict each other, which the writer must be told plainly."""
    if "your ranges" in problem or "your answer_range" in problem:
        return problem                           # the number step's own words, already the writer's
    if consistent and _IMPOSSIBLE_VALUE.search(problem):
        # numbers by construction: the engine computed them, so they agree; a solver reaching an impossible
        # value misread the question: the writer must not be told its data are inconsistent
        return (f"a careful solver misread the question ({problem}). Your numbers are consistent: the engine "
                f"computed them. Make the wording plain: say exactly what each stated value is and which "
                f"quantity is asked; avoid anything that suggests a different reading")
    if _IMPOSSIBLE_VALUE.search(problem):
        return (f"{problem}. With the values you stated, a step gives an impossible result: the data are "
                f"inconsistent with each other. Recheck every amount and its unit (mg or g, mL or L, % or "
                f"fraction) and choose values that give a physically possible result")
    # A formula the question does not need: in the coder's words the writer never learns WHICH formula and
    # HOW to bring it in, so it is named here.
    unused = [int(t) for t in re.findall(r"step_(\d+)", problem)] if re.search(
        r"never calls|does not change the answer|does not affect the answer", problem) else []
    unused += _unused_by_name(problem, drawn)
    out = []
    if unused:
        from core.engine import physical as ph
        for t in dict.fromkeys(unused):
            try:
                st = ph.step(t)
            except Exception:                    # noqa: BLE001
                continue
            out.append(f"Your question does not need the formula '{st.asks}: {st.formula}', so a solver skips it. "
                       f"Change the question so the answer depends on it: state the inputs this formula takes "
                       f"(not its result, and not a value it gives) and make its result feed another formula or "
                       f"the answer")
    for n in re.findall(r"the question states (\S+) but the program never takes it", problem):
        out.append(f"the question states {n.rstrip(',;')}, which no formula uses: remove that number")
    return "; ".join(out) if out else problem


def _unused_by_name(problem: str, drawn=None) -> list:
    """Formula numbers named by their result in a 'does not change the answer' problem."""
    m = re.search(r"the result of (.+?) does not change the answer", problem)
    if not m:
        return []
    from core.engine import physical as ph
    names = re.findall(r"'([^']+)'", m.group(1))
    pool = list(drawn) if drawn else list(ph.STEPS)
    return [t for t in pool if ph.step(t).asks in names]


# ---- Trace checks (2026-11-25 post-mortem: 3 of 17 accepted physical questions were wrong) -------------------
# The engine's chain builder follows roles (base.roles_consistent), but a question-first program wires steps
# freely, so nothing stopped K_c from k_f/k_b reaching K_p = K_x P^Δn (GEN_20261125T022806), two routes to ΔS
# that disagree (GEN_20261125T031247), or "the alkali metal" coming out as 24.4 g/mol (GEN_20261125T041311).

# Inputs that are the same kind of quantity as another input of the same step (van 't Hoff's K₂ is the
# same kind of constant as K₁).
SAME_ROLE_INPUTS = {136: {"K2": "equilibrium_constant"}}

# Quantities taken as constant over the question (JEE treats ΔH° and ΔS° as temperature-independent): two
# steps giving different values for one of them mean the stated data contradict each other.
CONSTANT_OUTPUTS = {"delta_h": ("ΔH°", "kJ mol⁻¹"), "delta_s": ("ΔS°", "J K⁻¹ mol⁻¹")}
CONSTANT_RTOL = 0.03

ROLE_WORDS = {"Kc": "K_c (concentration units)", "Kp": "K_p (pressures in atm)", "K°": "K° (thermodynamic)",
              "Kx": "K_x (mole fractions)"}

_ALKALI = ("Li", "Na", "K", "Rb", "Cs")
_ALKALINE_EARTH = ("Be", "Mg", "Ca", "Sr", "Ba")
ELEMENT_MASS_TOL = 0.6     # g mol⁻¹: the table is rounded (Mg 24.0 for 24.31) and answers have 3 s.f.


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _same(a, b, rtol=1e-4):           # trace outputs are rounded to 5 significant figures
    return abs(a - b) <= rtol * max(abs(a), abs(b), 1e-300)


def role_problems(trace) -> list:
    """A value a step gave with one role (K_c) reaching an input that wants another (K_p): follows values
    through the program's trace by identity, as base.roles_consistent does for engine chains."""
    from core.engine import physical as ph
    from core.engine.base import role_ok
    tagged = []                                  # (value, role, tx that gave it)
    probs = []
    for rec in trace or ():
        try:
            st = ph.step(int(rec.get("tx")))
        except Exception:                        # noqa: BLE001
            continue
        params = {p.key: p for p in st.needs}
        ins = rec.get("inputs") or {}
        wired = {}
        for key, val in ins.items():
            v = _num(val)
            if v is None:
                continue
            hit = next(((r, t) for (x, r, t) in reversed(tagged) if _same(x, v)), None)
            if hit is None:
                continue
            wired[key] = hit
            p = params.get(key)
            if p is not None and getattr(p, "role", None) and not role_ok(p, hit[0]):
                want = p.role if isinstance(p.role, tuple) else (p.role,)
                probs.append(
                    f"the solution uses {ROLE_WORDS.get(hit[0], hit[0])} from '{ph.step(hit[1]).formula}' "
                    f"in '{st.formula}', which needs {' or '.join(ROLE_WORDS.get(w, w) for w in want)}; "
                    f"these are different constants and must not be mixed")
        for key, other in SAME_ROLE_INPUTS.get(st.tx, {}).items():
            v = _num(ins.get(key))
            if v is not None and other in wired:
                tagged.append((v, *wired[other]))       # K₂ is the same kind as K₁, from the same source
        inherited = next(iter(wired.values()), (None,))[0] if st.keeps_role else None
        for key, val in (rec.get("outputs") or {}).items():
            v = _num(val)
            role = st.roles.get(key) or inherited
            if v is not None and role:
                tagged.append((v, role, st.tx))
    return list(dict.fromkeys(probs))


def consistency_problems(trace) -> list:
    """Two steps giving one constant quantity (ΔH°, ΔS°) different values: the question states more data than
    it needs and they disagree (031247: ΔS° −66.8 from (∂E°/∂T) but −146 from K and ΔH°)."""
    from core.engine import physical as ph
    if any("delta_cp" in (rec.get("inputs") or {}) for rec in trace or ()):
        return []                                # ΔC_p given: ΔH° and ΔS° change with T (033339's tangent)
    seen = {}
    for rec in trace or ():
        for key, val in (rec.get("outputs") or {}).items():
            v = _num(val)
            if key in CONSTANT_OUTPUTS and v is not None:
                seen.setdefault(key, []).append((v, rec.get("tx")))
    probs = []
    for key, vals in seen.items():
        for i, (a, ta) in enumerate(vals):
            for b, tb in vals[i + 1:]:
                tol = CONSTANT_RTOL * max(abs(a), abs(b))
                # exact negatives: the program passed a slope with the other sign and did not use that result
                # (025814: ΔH° +86.47 from "slope −10400", −86.47 used); the stated data agree
                if abs(a - b) > tol and abs(a - b) > 1e-6 and abs(a + b) > 1e-3 * max(abs(a), abs(b)):
                    name, unit = CONSTANT_OUTPUTS[key]
                    fa, fb = (ph.step(int(t)).formula if t is not None else "?" for t in (ta, tb))
                    probs.append(f"the stated data contradict each other: {name} is {a:.4g} {unit} by '{fa}' "
                                 f"but {b:.4g} {unit} by '{fb}'; state only the data one route needs, or "
                                 f"values that agree")
                    break
            else:
                continue
            break
    return probs


def answer_real_problems(asks: str, answer) -> list:
    """An asked-for element's atomic mass must be a real element's (041311: 'the alkali metal M' = 24.4)."""
    from core.engine.chem import ATOMIC_MASS
    a = _num(answer)
    text = (asks or "").lower()
    if a is None or not re.search(r"(atomic|molar) (mass|weight) of (the |an |a )?(unknown )?"
                                  r"(alkali|alkaline|metal|element)", text):
        return []
    pool = (_ALKALI if "alkali metal" in text else _ALKALINE_EARTH if "alkaline earth" in text
            else tuple(ATOMIC_MASS))
    if any(abs(ATOMIC_MASS[s] - a) <= ELEMENT_MASS_TOL for s in pool if s in ATOMIC_MASS):
        return []
    kind = "alkali metal" if pool is _ALKALI else "alkaline earth metal" if pool is _ALKALINE_EARTH else "element"
    return [f"the answer {a:.4g} g mol⁻¹ is not the atomic mass of any {kind}; choose values that give a real "
            f"{kind}"]


def trace_problems(run: dict, asks: str) -> list:
    return (role_problems(run.get("trace")) + consistency_problems(run.get("trace"))
            + answer_real_problems(asks, run.get("answer")))
