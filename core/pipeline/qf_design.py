"""Question first, stage 2: DESIGN.

The designer plans the question (design_question); Jev checks the plan, with cut-offs calibrated on
real JEE Advanced designs (design_problems). One design per draw (DESIGN_TRIES)."""

from __future__ import annotations

import json
import os
import re

from core import models
from core.llm import CutOffError
from core.pipeline.qf_draw import TWISTS
from core.pipeline.qf_checks import COHERENCE_QUESTIONS, COHERENCE_REJECT_AT


def twist_block(twist: str | None, examples) -> str:
    """The twist part of the design prompt. A fixed twist (a refinement chose it): that twist and its
    examples. None: every twist with one example each, and the designer chooses (a random twist that
    did not suit the formulas killed draws: a "condition" twist on pure Bohr-orbit formulas, fit A/B run
    of 2026-11-19)."""
    if twist is not None:
        ex = "\n".join(f"- {e['text'][:600]}" for e in (examples or [])) or "(none)"
        return (f"How the formulas must be used (the twist): {TWISTS[twist]}\n\n"
                f"Real JEE Advanced questions with this twist, to show the LEVEL only (do not reuse their system, "
                f"set-up or what they ask):\n{ex}")
    by = examples if isinstance(examples, dict) else {}
    lines = []
    for t, text in TWISTS.items():
        lines.append(f"- {t}: {text}")
        for e in by.get(t) or []:
            lines.append(f"    level example (do not reuse its system, set-up or what it asks): {e['text'][:450]}")
    return ("How the formulas are used (the twist): CHOOSE the one twist below that lets THESE formulas make the "
            "hardest real question, and name it in \"twist\". Choose by what the formulas and the system allow, "
            "not by which is easiest to design.\n" + "\n".join(lines))


FINISH_CAP = 4000           # the finish-it call writes the design text only (it was cut off after the thinking)
THOUGHT_CHARS = 12000       # how much of the returned thinking the finish-it call is shown (its end, the plan)


def finish_design(prompt: str, cut: CutOffError) -> dict:
    """The design reply was cut off at the output limit, nearly always after the thinking, while the design
    itself was being written (run of 2026-11-19: ~7000 tokens of thinking, 1202 characters of design, $0.09
    lost). One cheap call, thinking low, has the designer finish it from what it wrote (and its thinking,
    when the provider returned it). Raises ValueError if that cannot be read either: the caller then writes
    without a design, as before."""
    if not cut.partial.strip() and not cut.reasoning:
        raise ValueError(f"design cut off before any text was written: {cut}")
    print("    design reply cut off at the output limit; asking the designer to finish it")
    thought = (f"\nYOUR THINKING SO FAR (end of it):\n{cut.reasoning[-THOUGHT_CHARS:]}\n" if cut.reasoning else "")
    finish = f"""{prompt}

Your earlier reply to this was cut off at the output limit. This is what you had written of the JSON:
{cut.partial}
{thought}
Do not start over and do not change your plan: keep what you wrote exactly, complete the design from where it
stops, and return the COMPLETE JSON object (every key) and nothing else."""
    return models.ask_json("designer", models.DESIGNER, "You design hard chemistry exam questions. Output JSON only.",
                           finish, temperature=0.2, retry_cut_off=False, max_tokens=FINISH_CAP,
                           reasoning_effort="low")


def drop_block(n_formulas: int) -> str:
    """With 4 or 5 formulas drawn, the designer may leave ONE out (never below 3): half of all draws died at
    design because one random formula did not fit the system the others make (28 draws, 2026-11-19)."""
    if n_formulas < 4:
        return ""
    return (f"\nIf exactly ONE of these {n_formulas} formulas cannot belong to the same real system as the others, "
            f"you may leave it out: name it in \"drop\" (its number) and design with the other {n_formulas - 1}, all "
            f"of which must then be needed. Leave none out if all fit; never more than one.\n")


def design_question(subject_name: str, formulas: str, twist: str | None, *, used: list | None = None,
                    rejected: str | None = None, examples=None, n_formulas: int = 0) -> dict:
    """The design step, the one creative step, done by models.DESIGNER thinking hard: ONE design built
    around a HIDDEN LINK (how the drawn formulas meet through a quantity the question never names, what
    the student must notice there, and the trap at it); or {"impossible": reason}. Difficulty comes
    from that link, not from a long chain of plug-ins (in the accepted bank the good
    questions each turn on one such link; the weak ones are 4-5 mechanical steps). The prompt is
    chemistry only: the format rules belong to the writer. twist None: the designer chooses it (examples
    is then {twist: [example]}) and the design carries it under "twist"."""
    rejected_block = (f"\nAn earlier design was rejected: {rejected}\nRespect each formula's listed cases and "
                      f"inputs exactly.\n") if rejected else ""
    used_lines = ("\nSituations already used in our questions (do not reuse them):\n"
                  + "\n".join(f"- {u}" for u in used) + "\n") if used else ""
    twist_field = (f'\n  "twist": "the twist you chose, one of: {", ".join(TWISTS)}",' if twist is None else "")
    if n_formulas >= 4:
        twist_field += '\n  "drop": null, or the number of the ONE formula left out,'
    prompt = f"""You are a senior JEE Advanced {subject_name} paper setter. DESIGN (do not write) ONE numerical
question that would sit among the hardest of a real paper. It must need ALL of these formulas, and no
chemistry beyond them except standard relations (n = m/M, a unit change, the ideal gas equation):
{formulas}
{drop_block(n_formulas)}
{twist_block(twist, examples)}
{used_lines}{rejected_block}
WHAT MAKES IT HARD. Not length. A hard question joins its formulas through a HIDDEN LINK: a quantity that
two formulas share in this system but that the question never names or gives, so the student must
realise the connection (two measurements fix the same unknowns together; a result has to be worked out
backwards from what is observed; a condition decides which relation applies; a quantity cancels or
does not). The trap sits at that link: a student who misses it uses a plausible but wrong relation and
gets a believable wrong number. A question where each formula's output is simply the next one's input,
with all data handed over in order, is NOT hard: avoid it.

Rules:
- ONE definite, real system: name the substances, the reaction(s) and the conditions. No alternatives
  ("X or Y"), no unspecified reaction.
- Every formula is needed for the one answer, and only real chemistry joins them: never an invented
  relation, never an arbitrary condition ("until X equals 1.2 % of Y"), never unrelated sub-problems.
- Each formula is used only within what its inputs describe (a formula "for all species gaseous" is not
  used on a reaction with a solid; a "one of" input takes one of its listed cases).
- Nothing the solver should work out is given: no ratio, n-factor, equivalent mass or intermediate that a
  formula computes.

Before you answer, check your design (each check failed in a real design; stage runs of 2026-11-17):
- Physically real: every condition can happen (each substance in the stated phase at that temperature and
  pressure; sensible values). "K_p equals K_c" for Δn = 1 forces T ≈ 12 K, where N2O4 is no gas.
- Determined: count the unknowns and the values the question gives; the given data must fix the answer
  (a volume with α unknown and no K given cannot be found).
- No textbook one-liner as the insight (K_p = K_c at T = 1/R; "simple cubic, so a = 2r").
- "hidden" truly unstated: nothing in "given" may reveal it, and the question must still be solvable
  without it.

If no such question can need all the formulas through real chemistry, return only {{"impossible": "why"}}.

LENGTH: your thinking and the full design TOGETHER must not exceed 2500 words. Plan briefly, decide, then
write the design; a reply that runs past its limit is cut off and lost.

Return JSON:
{{{twist_field}"system": "the one real system, substances, reactions and conditions",
  "hidden_link": "which quantity joins which formulas, and why the question never states it",
  "route": "for each formula, in the order a solver uses it: what it takes and what it gives here",
  "student_must_notice": "the non-obvious point that decides the answer",
  "trap": "the tempting wrong route at the link, and why a good student takes it",
  "given": "the quantities the question states (in words, no numbers)",
  "hidden": "the quantities it must NOT state",
  "asked": "the asked quantity, with its unit",
  "why_hard": "one sentence"}}"""
    if models.DESIGNER.startswith("google/gemini-3"):     # no budget: its own level, room to finish
        think = {"max_tokens": models.GEMINI3_DESIGN_CAP,
                 **({"reasoning_effort": models.GEMINI3_DESIGN_LEVEL} if models.GEMINI3_DESIGN_LEVEL else {})}
    elif models.router(models.DESIGNER) == "airouter":     # an effort level there (see models.py)
        think = {"max_tokens": models.AIROUTER_DESIGN_CAP, "reasoning_effort": models.AIROUTER_DESIGNER_EFFORT}
    else:
        think = {"max_tokens": models.DESIGNER_THINKING + 3500, "reasoning_tokens": models.DESIGNER_THINKING}
    try:
        out = models.ask_json("designer", models.DESIGNER, "You design hard chemistry exam questions. Output JSON only.",
                              prompt, temperature=0.8, retry_cut_off=False, **think)
    except CutOffError as e:
        out = finish_design(prompt, e)
    if out.get("impossible") and not (out.get("system") or out.get("designs")):
        return {"impossible": str(out["impossible"])}
    d = out
    if out.get("designs"):                       # the earlier two-design format
        ds = [x for x in out["designs"] if isinstance(x, dict)]
        try:
            d = ds[int(out.get("best", 0))]
        except (TypeError, ValueError, IndexError):
            d = ds[0] if ds else {}
    d = {k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in d.items()
         if v not in (None, "")}
    # both sets of names, so the writer and the logs read either format in full
    for new_k, old_k in (("system", "situation"), ("student_must_notice", "insight"), ("route", "links")):
        d.setdefault(new_k, d.get(old_k, ""))
        d.setdefault(old_k, d.get(new_k, ""))
    if not d.get("situation"):
        raise ValueError("the designer returned no design")
    drop = d.get("drop")
    try:
        drop = int(str(drop).lower().replace("formula", "").strip()) if drop not in (None, "", "null", "none") else None
    except ValueError:
        drop = None
    if drop is not None and not (n_formulas >= 4 and 1 <= drop <= n_formulas):
        print(f"    designer asked to leave out formula {d.get('drop')!r}, which is not allowed here; ignored")
        drop = None
    d["drop"] = drop                             # 1-based number of the formula left out, or None
    if twist is None:
        chosen = str(d.get("twist") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if chosen in TWISTS:
            d["twist"] = chosen
        else:                                    # keep the paid-for design; the caller picks a twist
            print(f"    designer named no valid twist ({d.get('twist')!r}); a random one is used")
            d.pop("twist", None)
    else:
        d["twist"] = twist
    return d


# The same three questions asked of the PLAN, right after the design (a fraction of a cent): a design
# that says the K of 2CO + O2 ⇌ 2CO2 "governs" FeO(s) + CO ⇌ Fe(s) + CO2 passed the feasibility check,
# which asks only whether a program could run.
# Off: in one run the Jev plan check (uncalibrated 50 % cut-off) rejected 3 of 4
# designs ("vague" at 50-61 % for concrete ones), and the feasibility check, once Luna ran it, rejected any
# design needing a formula run backwards (which find() does). Impossible designs are still caught after
# the number step (pick_numbers) and by Jev's check of the finished question.
DESIGN_GATES = False


DESIGN_COHERENCE_QUESTIONS = {
    "invented_relation": "The plan links two quantities by a relation that is not a real chemistry or physics "
                         "law or standard definition, for example using the equilibrium constant of one "
                         "reaction as if it were that of a different reaction.",
    "glued_parts": "The plan is several unrelated sub-problems about different systems, joined only by "
                   "arithmetic or by an artificial statement, rather than one coherent chemical situation.",
    "vague": "The plan does not name ONE definite reaction or system for each formula (it offers alternatives "
             "such as 'dimerization or dissociation' or leaves the reaction unspecified).",
}


def design_coherence(design: dict) -> str | None:
    """Why Jev finds the plan incoherent, or None (coherent, or Jev cannot be reached)."""
    from core.pipeline import refine
    text = (f"Situation: {design.get('situation', '')}\nHow the formulas link: {design.get('links', '')}\n"
            f"Asked: {design.get('asked', '')}")
    try:
        p = refine.jev_decide({"question_plan": text}, DESIGN_COHERENCE_QUESTIONS, role="design_coherence")
    except Exception as e:                       # noqa: BLE001
        print(f"    design coherence check skipped (Jev unavailable: {str(e)[:80]})")
        return None
    why = {"invented_relation": "it links quantities by a relation that is not real chemistry (for example "
                                "one reaction's K used for another reaction)",
           "glued_parts": "it glues unrelated sub-problems together instead of one chemical situation",
           "vague": "it does not name one definite reaction or system for each formula"}
    bad = [f"{why[k]} (Jev: {p[k]:.0%})" for k in why if p.get(k, 0) >= COHERENCE_REJECT_AT]
    return "; ".join(bad) or None


USED_SITUATIONS = 8      # recent accepted situations on the same chapters shown to the writer


SITUATION_CHARS = 160


def accepted_questions(config: dict) -> list:
    """Our accepted computed questions, newest last: [{"id", "text", "chapters"}] (the
    answer-format sentence cut off). Read from the subject's output file; [] if none."""
    path = config.get("output_file")
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)
    except (OSError, ValueError):
        return []
    # questions rejected on review (tools/results.py reject) are not "accepted": the writer is never shown them
    rejected_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results", "rejected.json")
    try:
        with open(rejected_path, encoding="utf-8") as f:
            rejected = set(json.load(f))
    except (OSError, ValueError, TypeError):
        rejected = set()
    out = []
    for r in recs if isinstance(recs, list) else []:
        if r.get("question_kind") == "fact" or not r.get("question") or r.get("question_id") in rejected:
            continue
        text = re.split(r"\s+Give the answer", str(r["question"]))[0]
        out.append({"id": r.get("question_id", "?"), "text": text, "chapters": list(r.get("chapters") or [])})
    return out


def used_situations(accepted: list, chapters) -> list:
    """The opening of the most recent accepted questions that share a chapter with this draw:
    the writer is told not to reuse those situations."""
    chapters = set(chapters or [])
    same = [q for q in accepted if chapters & set(q["chapters"])]
    out = []
    for q in reversed(same[-USED_SITUATIONS:]):
        t = " ".join(q["text"].split())
        out.append(t[:SITUATION_CHARS] + ("…" if len(t) > SITUATION_CHARS else ""))
    return out


DESIGN_TRIES = 1         # designs per draw: a design Jev rejects means a new draw (a Gemini Pro design costs
                         # 4-8 cents; one draw gave the same contrived equality three times)



def design_problem(design: dict, library: str) -> str | None:
    """The feasibility check, before any question is written: the coder (cheap, no thinking) says
    whether a program could compute the design's asked quantity by calling every formula with
    inputs the design provides, choice inputs taking one of their listed cases. Returns why not,
    or None (feasible, or the check could not be run: it never blocks)."""
    prompt = f"""A chemistry question is being planned. Before it is written, check that it can be solved
with ONLY the functions below (each is one formula; a "one of" input accepts only the listed cases).

PLANNED QUESTION:
- situation: {design.get("situation", "")}
- links: {design.get("links", "")}
- asked: {design.get("asked", "")}

FUNCTIONS:
{library}

Could a program compute the asked quantity from data such a question would state, calling EVERY
function above at least once, each with inputs this situation actually provides (for a "one of"
input: one of the listed cases, exactly)?

Any value the question can simply STATE counts as provided: a mass, a volume, a temperature, an EMF or
standard potential (E° is an EMF), a constant, a conductivity. Do not reject a design because a value
is not mentioned in the plan. Reject it ONLY if a function cannot fit this situation at all: a "one
of" input whose listed cases do not include what the situation needs, a formula about a quantity
the situation does not have (a crystal formula for a solution, a gas law for a solid), or an input
whose description restricts the reaction or system ("all species gaseous", "solid + X(g) ⇌ solid +
Y(g)", "ions of equal charge") when the situation's reaction does not satisfy it: a formula applies
only to what its inputs describe.

Return JSON: {{"feasible": true or false, "problem": "which function cannot be applied, and why (empty if feasible)"}}"""
    try:
        # the coder's own budget: 800 tokens suited Codestral, which does not think; Luna spent them all
        # thinking and replied empty, twice. A yes/no needs little thought.
        out = models.ask_json("coder", models.CODER, "You check whether a computation is possible. Output JSON only.",
                              prompt, max_tokens=models.coder_tokens(models.CODER), temperature=0.0,
                              reasoning_effort="low", fallbacks=models.CODER_FALLBACKS, retry_cut_off=False)
    except Exception as e:                       # noqa: BLE001 - never blocks a draw
        if getattr(e, "status_code", None) == 402:
            raise
        print(f"    feasibility check skipped ({type(e).__name__})")
        return None
    from core.llm import as_bool
    if as_bool(out.get("feasible"), default=True):
        return None
    return str(out.get("problem") or "a formula cannot be applied to this situation")


def design_plan_text(d: dict) -> str:
    """A design as the text Jev judges (the same for the calibration, tools/calibrate_design.py)."""
    return (f"System: {d.get('system') or d.get('situation', '')}\nCondition and link: {d.get('hidden_link', '')}\n"
            f"Route: {d.get('route') or d.get('links', '')}\nGiven: {d.get('given', '')}\nAsked: {d.get('asked', '')}")


def design_problems(design: dict) -> str | None:
    """Jev's coherence verdict on a DESIGN, before anything is written, with cut-offs calibrated on reviewed
    reverse-designs of real JEE Advanced questions (knowledge/design_coherence_calibration_physical.json).
    None when it is coherent, when there is no calibration (no check: an uncalibrated design check
    rejected good designs) or when Jev cannot be reached."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "knowledge",
                        "design_coherence_calibration_physical.json")
    try:
        with open(path, encoding="utf-8") as f:
            cuts = {k: float(v) for k, v in json.load(f)["thresholds"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    from core.pipeline import refine
    try:
        p = refine.jev_decide({"exam_question_plan": design_plan_text(design)}, COHERENCE_QUESTIONS,
                              role="design_check")
    except Exception as e:                       # noqa: BLE001
        print(f"    design check skipped (Jev unavailable: {str(e)[:80]})")
        return None
    why = {"invented_relation": "it links quantities by a relation that is not real chemistry",
           "glued_parts": "it glues unrelated sub-problems together instead of one chemical situation",
           "arbitrary_condition": "it links its parts by an arbitrary condition (an equality chosen only to "
                                  "connect them, such as a constant numerically equal to a pressure), not by "
                                  "something that physically follows in the situation"}
    bad = [f"{why[k]} (Jev: {p[k]:.0%})" for k in why if k in cuts and p.get(k, 0) >= cuts[k]]
    return "; ".join(bad) or None
