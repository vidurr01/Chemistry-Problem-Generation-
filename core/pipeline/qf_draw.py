"""Question first, stage 1: DRAW.

3-5 random engine formulas; Jev scores FIT_CANDIDATES sets and the best one is written (best_draw).
Also the twists (TWISTS) and the real JEE examples shown for each twist (exemplars)."""

from __future__ import annotations

import json
import os


_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")


EXEMPLARS = os.path.join(_ROOT, "knowledge", "jee_adv_twist_exemplars_physical.json")


TWISTS = {
    "inverse": "Run the chain backwards: give a later result (one a student would normally be asked "
               "for) and ask for an INPUT of one of the formulas, so the solver has to work back "
               "through the formulas to it.",
    "two_state_ratio": "Two states or two systems go through the same formulas (two temperatures, two "
                       "samples, two gases, before and after a change); ask for the RATIO of one result "
                       "between them.",
    "two_state_difference": "Two states or two systems go through the same formulas; ask for the "
                            "DIFFERENCE of one result between them.",
    "simultaneous": "Two unknowns are tied by two relations that come from these formulas, so they have "
                    "to be found together (neither can be found first on its own).",
    # "two results become equal" drew "Kc numerically equal to a partial pressure" three designs running;
    # real JEE condition questions ask when a system reaches a physical state
    "condition": "Ask for a physical condition the experimenter sets (a temperature, pressure, volume, time "
                 "or amount) at which the system reaches a stated, physically meaningful state: a given "
                 "degree of dissociation or conversion, a gas's partial pressure or mole fraction reaching "
                 "a value, a precipitate just starting to form, a reaction becoming spontaneous. Never a "
                 "condition that equates quantities of different kinds (a constant numerically equal to a "
                 "pressure, Kp equal to Kc).",
}


_cache: dict = {}


def exemplars(twist: str, rng, k: int = 2) -> list:
    if "ex" not in _cache:
        with open(EXEMPLARS, encoding="utf-8") as f:
            _cache["ex"] = json.load(f)
    pool = _cache["ex"].get(twist, [])
    return rng.sample(pool, min(k, len(pool)))


# Before any design or writing, Jev (a fraction of a cent) judges whether a formula set can meet
# in ONE real situation. Its probabilities are not calibrated (good and bad sets both land between
# 18 and 52 %: a fixed cut-off at 0.5 skipped 11 draws in a row, among them the
# classic Z / van der Waals a / Boyle / critical-constants set), so it RANKS: each draw scores
# FIT_CANDIDATES random sets and writes the best one.
FIT_CANDIDATES = 6


# New sets are drawn until one reaches the floor. None: the calibrated floor (knowledge/fit_calibration_physical.json,
# 0.504 = the 20th percentile of real JEE Advanced sets): 79 % of real sets and ~15 % of random draws reach it, so
# about 7 sets (~1-2 batches) per draw. The 0.60 used until 2026-11-19 turned away a third of real JEE sets (half of
# the real 3-formula ones) and passed ~3 % of random draws: 7 batches in a row were rejected in a run.
# FIT_BATCHES only stops a run looping if Jev never says yes.
FIT_FLOOR = None


FIT_BATCHES = 30


FIT_PARALLEL = 3         # Jev calls in flight at once: queued sets after a hit are cancelled, not paid


def _fit_floor() -> float | None:
    """FIT_FLOOR, else the floor calibrated on real JEE Advanced formula sets (tools/calibrate_fit.py),
    else None (the best of one batch is written)."""
    if FIT_FLOOR is not None:
        return FIT_FLOOR
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "knowledge",
                        "fit_calibration_physical.json")
    try:
        with open(path, encoding="utf-8") as f:
            return float(json.load(f)["threshold"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


FIT_QUESTION = {"one_situation": (
    "Could a JEE Advanced paper setter write ONE natural numerical problem about a single real chemical "
    "system in which EVERY one of these formulas is genuinely needed, the result of one feeding another, "
    "without gluing unrelated sub-problems or inventing an artificial link? Answer yes only if such a "
    "problem is natural.")}


def pick_best(cands: list, scores: list):
    """The candidate with the highest score; None scores (Jev down) count as 0; the first on ties."""
    if not cands:
        return None
    best = max(range(len(cands)), key=lambda i: (scores[i] if scores[i] is not None else 0.0, -i))
    return cands[best]


def best_draw(adapter, chapter, bb, log):
    """Random formula sets, FIT_CANDIDATES to a batch, scored by Jev FIT_PARALLEL at a time: the
    FIRST set at or over the floor is taken at once (the rest of its batch is not scored). A batch
    with none: another batch (at most FIT_BATCHES), then the best set seen. With no floor, or Jev
    down: the best of one batch. Returns the candidate with "_fit"."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    floor = _fit_floor()
    best, best_p, seen = None, None, set()
    for batch in range(FIT_BATCHES):
        cands = []
        for _ in range(FIT_CANDIDATES * 2):
            if len(cands) >= FIT_CANDIDATES:
                break
            c = adapter.random_formulas(chapter, exclude=bb.tried_edges())
            if c is None:
                break
            key = tuple(sorted(c["txs"]))
            if key not in seen:
                seen.add(key)
                cands.append(c)
        if not cands:
            break
        # scored FIT_PARALLEL at a time; the first set at or over the floor is taken at once and the
        # sets not yet sent are cancelled (not scored, not paid)
        scores = [None] * len(cands)
        hit = None
        ex = ThreadPoolExecutor(max_workers=FIT_PARALLEL)
        futs = {ex.submit(formulas_fit, c["_steps"], True): i for i, c in enumerate(cands)}
        try:
            for f in as_completed(futs):
                i = futs[f]
                scores[i] = f.result()
                if floor is not None and scores[i] is not None and scores[i] >= floor:
                    hit = i
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        if hit is not None:
            top, p = cands[hit], scores[hit]
        else:
            top = pick_best(cands, scores)
            p = scores[cands.index(top)]
        if best is None or (p or 0.0) > (best_p or 0.0):
            best, best_p = top, p
        shown = [f"{x:.0%}" if x is not None else "?" for x in scores]
        log({"event": "formula_fit", "floor": floor, "scores": [{"txs": c["txs"], "p": x} for c, x in zip(cands, scores)]})
        if floor is None or best_p is None or best_p >= floor:
            n_scored = sum(x is not None for x in scores)
            if n_scored == 0:                    # it printed "Jev scored 0 random formula sets: ; writing the best"
                print(f"\n  [fit] Jev could not score the {len(cands)} formula sets; writing the first one drawn")
                break
            print(f"\n  [fit] Jev scored {n_scored} random formula sets: {', '.join(x for x in shown if x != '?')}; "
                  f"writing {'the first over the floor' if hit is not None else 'the best'}"
                  + (f" ({best_p:.0%})" if best_p is not None else "")
                  + (f", floor {floor:.0%}" if floor is not None and best_p is not None else ""))
            break
        if batch < FIT_BATCHES - 1:
            print(f"  [fit] batch {batch + 1}: best {max((x for x in scores if x is not None), default=0):.0%}, "
                  f"under the floor {floor:.0%}: drawing new formulas")
        else:
            print(f"\n  [fit] no set reached the floor {floor:.0%} in {FIT_BATCHES} batches; writing the best seen "
                  f"({best_p:.0%})")
    if best is None:
        return None
    return {**best, "_fit": best_p}


def formulas_fit(steps, quiet=False) -> float | None:
    """Jev's P(the drawn formulas make one natural problem); None if Jev cannot be reached (then
    the draw goes ahead: this check never blocks a run)."""
    from core.pipeline import refine
    try:
        p = refine.jev_decide({"formulas": formulas_text(steps)}, FIT_QUESTION, role="formula_fit")
    except Exception as e:                       # noqa: BLE001
        if not quiet:
            print(f"    formula-fit check skipped (Jev unavailable: {str(e)[:80]})")
        return None
    return p.get("one_situation")


def formulas_text(steps) -> str:
    """One line per formula, with what it is limited to: a 'choice' input means the formula
    covers only those cases (formula 54's n-factor covers two reactions, not any salt), so the
    designer and the writer must use one of them (an 'unknown metal sulfate'
    design could never be solved)."""
    out = []
    for i, s in enumerate(steps):
        line = f"Formula {i + 1}: {s.asks} — {s.formula}"
        # its inputs in words: conditions live there ("balanced equation (all species gaseous)",
        # "K_p of solid + X(g) ⇌ solid + Y(g)"); with the formula line alone the designer built a
        # Boudouard question neither formula covers
        line += "\n   takes: " + "; ".join(p.desc + (f" [{p.unit}]" if p.unit else "") for p in s.needs)
        limits = [f"{p.desc} must be one of: " + " | ".join(map(str, p.choices))
                  for p in s.needs if p.kind == "choice" and p.choices]
        if limits:
            line += "\n   ONLY for these cases (use one of them exactly): " + "; ".join(limits)
        out.append(line)
    return "\n".join(out)
