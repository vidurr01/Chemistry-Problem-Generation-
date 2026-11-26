"""
trace_check.py — why each ladder member that missed the key failed (docs/implementation_spec_2026-11-25.md §2).

Grading stays code: a member's answer matches the key or not. For a member that missed it:

    trap            its answer equals one of the engine's saved wrong answers (result.traps): no model call
    concept         missed the hidden step / a real concept error          (counts toward "hard")
    hallucination   invented or misremembered a fact, misread the question (the member's own fault)
    too_long        each step it did was right, but it lost track across too many states or items
    slip            arithmetic or copying error
    question_flawed its answer is a defensible reading of a flawed question, or it shows the data contradict,
                    the question is ambiguous, or the asked thing cannot exist
    unexplained     the checker's quote is not in the working (label discarded)
    unchecked       the checker could not be called (grading then behaves as before this module)

Only trap and concept count toward difficulty. question_flawed holds the question (flow._judge). The checker
never confirms the key: it can only raise a flag, and a flag means the question is regenerated.
Cause: three wrong physical questions of 2026-11-25 were accepted as Advanced because correct solvers were
graded as failing (Granite answered 23 = Na for "24.4 g/mol alkali metal"; GLM's objection that the data
contradict was only logged).
"""

from __future__ import annotations

import re

from core import answers, models

ENABLED = True
GENUINE = {"trap", "concept"}                     # failures that count toward "hard"
NOT_DIFFICULTY = {"hallucination", "too_long", "slip", "unexplained"}
LABELS = ("concept", "hallucination", "too_long", "slip", "question_flawed")
TRAP_TOL = 0.02                                   # as flow.CONSENSUS_TOL
MIN_QUOTE = 8                                     # characters: a shorter quote proves nothing
# reply limit, thinking included: 1500 cut Qwen off twice on one GLM working (live run 2026-11-26: ~1460 tokens
# a call at effort "low", one empty, one truncated JSON)
# 4000 still ran out on 12 of ~30 calls in the 60-question batch of 2026-11-26 (long physical workings):
# 8000 (about +$0.002 a call)
MAX_TOKENS = 8000

_SYSTEM = """You read one solver's working on a chemistry question. The answer key was computed by code from the
question's data. The solver's final answer differs from the key. Say WHY, with one label:

- "concept": the solver missed the question's key step or applied a wrong concept or formula. This INCLUDES
  getting wrong what the question asks the solver to work out: a product, an oxidation state, which reaction
  takes place, a route. A wrong product in a question that asks for the products is "concept", not
  "hallucination", even if the solver states it confidently.
- "hallucination": the solver invented or misread something the question itself states (a value, a condition,
  a reagent), or used a made-up fact that the question's key step does not depend on.
- "too_long": every step the solver did was right, but it lost track across too many reactions, states or items.
- "slip": an arithmetic, unit-conversion or copying error in an otherwise right method.
- "question_flawed": the solver's answer is a defensible reading of a flawed question: the stated data
  contradict each other, the question is ambiguous, an assumption the key needs is not stated, or the asked
  thing cannot exist (for example a computed atomic mass that matches no element of the asked kind).

Do NOT judge whether the key is right by solving the question yourself. Judge only from the working.
"quote" must be copied exactly from the working: the sentence that shows the reason (at least 8 characters).
Reply as JSON: {"label": "...", "quote": "...", "reason": "one sentence"}"""


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _member_value(g):
    fv = g.get("final_value")
    if isinstance(fv, list) and fv and isinstance(fv[0], (int, float)):
        return float(fv[0])
    return answers.numeric_value(g.get("final_answer"))


def trap_match(result, g) -> bool:
    """The member's answer equals one of the engine's saved wrong answers (within TRAP_TOL)."""
    v = _member_value(g)
    if v is None:
        return False
    for t in getattr(result, "traps", None) or []:
        w = _num(t.get("wrong_answer")) if isinstance(t, dict) else None
        if w is not None and abs(w - v) <= TRAP_TOL * max(abs(w), abs(v), 1e-300):
            return True
    return False


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def quote_found(quote: str, working: str) -> bool:
    q = _norm(quote)
    return len(q) >= MIN_QUOTE and q in _norm(working)


def _prompt(stem: str, key: str, member: dict) -> str:
    return (f"QUESTION:\n{stem}\n\nANSWER KEY (computed by code): {key}\n\n"
            f"SOLVER'S FINAL ANSWER: {member.get('final_answer')}\n\n"
            f"SOLVER'S WORKING:\n{str(member.get('working', ''))[:12000]}")


def check_member(stem: str, key: str, member: dict) -> dict:
    """{"label", "quote", "reason"} for one member that missed the key (a model call)."""
    try:
        out = models.ask_json("trace_checker", models.TRACE_CHECKER, _SYSTEM, _prompt(stem, key, member),
                              max_tokens=MAX_TOKENS, reasoning_effort=models.TRACE_CHECKER_EFFORT)
    except Exception as e:                        # noqa: BLE001 - no checker: grading as before this module
        return {"label": "unchecked", "quote": "", "reason": f"checker call failed: {str(e)[:160]}"}
    label = str(out.get("label", "")).strip().lower()
    quote, reason = str(out.get("quote", "")), str(out.get("reason", ""))[:500]
    if label not in LABELS:
        return {"label": "unchecked", "quote": quote, "reason": f"checker gave no known label ({label!r})"}
    if not quote_found(quote, member.get("working", "")):
        return {"label": "unexplained", "quote": quote, "reason": f"quote not in the working; checker said {label}: "
                                                                  f"{reason}"}
    return {"label": label, "quote": quote, "reason": reason}


def label_failures(result, stem: str, key: str, graded: list) -> None:
    """Set failure_label / failure_quote / failure_reason on every member that missed the key (in place)."""
    for g in graded:
        if g.get("answer_matches") or g.get("counts_as_solved") or g.get("discarded_as_nonsense"):
            continue
        if trap_match(result, g):
            lab = {"label": "trap", "quote": "", "reason": "answer equals a saved wrong answer of the engine"}
        else:
            lab = check_member(stem, key, g)
        g["failure_label"], g["failure_quote"], g["failure_reason"] = lab["label"], lab["quote"], lab["reason"]
        print(f"    [trace] {g['name']}: {lab['label']}" + (f" — {lab['reason'][:120]}" if lab["reason"] else ""))
