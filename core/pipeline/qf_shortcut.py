"""Question first: the SHORTCUT check. Does the design's hidden step change the answer?

The designer names one hidden step (qf_design: "hidden_step"). A question is only hard if a good student who
misses it gets a clearly different answer. Run 2 of 2026-11-25 claimed "α ≪ 1 fails for the dilute solution"
but asked κ₁ − κ₂, where the dilute κ is 2 % of the other: the shortcut gave 0.001716 against 0.001709, the
same to 3 significant figures. Granite failed it by arithmetic slips and the ladder called it Advanced.

Here the coder writes the program of a student who misses that step (one coder call, about $0.001); code runs it
on the question's own values and compares. Too close: the writer is told to choose values (or a set-up) where
the step matters. A shortcut program that does not run, or a coder that cannot write one, skips the check (it
never rejects a question by itself failing)."""

from __future__ import annotations

from core import models
from core.engine import sandbox

SHORTCUT_GAP = 0.05     # the shortcut answer must differ from the key by more than this fraction


def _prompt(stem: str, code: str, design: dict) -> str:
    return f"""A JEE question, the exact program that solves it, and the one hidden step of its design.

QUESTION:
{stem}

CORRECT PROGRAM (its variables, e.g. the given values, are already defined when it runs):
{code}

THE HIDDEN STEP a good student may miss: {design.get('hidden_step', '')}
THE TEMPTING WRONG ROUTE: {design.get('trap', '')}

Write the program of a good student who MISSES that hidden step and takes the usual route instead. Same
function name solve(), same variable names, same engine functions where the route is the same; change only
what missing the hidden step changes (you may write a formula in plain Python with math). Do not add any other
mistake. NO import line. If missing the step cannot change the method at all, return {{"same": "why"}}.
Return JSON: {{"code": "def solve():\\n    ..."}}"""


def shortcut_problem(design: dict | None, stem: str, code: str, run: dict, preset: dict | None,
                     bb=None) -> str | None:
    """A problem for the writer when the hidden step does not change the answer; None when it does, or when
    the check cannot be made (no design, no numeric answer, the shortcut program fails)."""
    if not design or not str(design.get("hidden_step") or "").strip():
        return None
    try:
        key = float(run["answer"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        out = models.ask_json("shortcut_coder", models.CODER, "You write exact scientific Python. Output JSON only.",
                              _prompt(stem, code, design), max_tokens=models.coder_tokens(models.CODER),
                              temperature=0.1)
    except Exception as e:                       # noqa: BLE001
        print(f"    shortcut check skipped (coder failed: {str(e)[:80]})")
        return None
    if str(out.get("same") or "").strip() and not str(out.get("code") or "").strip():
        why = str(out["same"]).strip()
        if bb is not None:
            bb.note("shortcut", same=why)
        print(f"    shortcut check: missing the hidden step does not change the method ({why[:120]})")
        return (f"the hidden step does not change the solution: a student who misses it solves it the same way "
                f"({why[:200]}); build the question so the step decides the answer")
    sc = str(out.get("code") or "")
    if not sc.strip():
        return None
    res = sandbox.evaluate(sc, [], any_step=True, preset=preset)
    try:
        wrong = float(res["answer"]) if res.get("ok") else None
    except (KeyError, TypeError, ValueError):
        wrong = None
    if bb is not None:
        bb.note("shortcut", code=sc, answer=wrong, key=key, error=None if res.get("ok") else res.get("error"))
    if wrong is None:
        print(f"    shortcut check skipped (the shortcut program did not run: {str(res.get('error'))[:80]})")
        return None
    gap = abs(wrong - key) / max(abs(key), abs(wrong), 1e-300)
    print(f"    shortcut check: missing the hidden step gives {wrong:.4g} against {key:.4g} ({gap:.1%} apart)")
    if gap > SHORTCUT_GAP:
        return None
    return (f"the hidden step does not change the answer: a student who misses it ({design.get('trap', '')[:160]}) "
            f"gets {wrong:.4g}, the right answer is {key:.4g} ({gap:.1%} apart). Choose values and ranges, or "
            f"change what is asked, so that missing the hidden step gives an answer at least 10% different")
