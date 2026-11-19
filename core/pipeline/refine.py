"""
refine.py — the refinement loop of the question-first flow: what to change when the weakest
ladder step solved a question.

    1. the refiner, Jev (TypeSafe's System One decision model, models.JEV_MODEL), reads the
       question, the drawn formulas and how the weakest solver solved it (through the Decisions API
       of OpenRouter, or of airouter.in once OpenRouter is out of credit), and answers ONE choice
       question over the CASES below not used yet: its pick, and probabilities over them that sum
       to 1 (classify; Jev returns no text)
    2. code picks the cases (pick): Jev's own pick first, then those at or above PICK_AT, at most
       PER_ROUND, never a case already used on this question; if none qualifies, the single most
       likely unused one
    3. code applies what a case needs before the rewrite (a new twist, one more drawn formula)
    4. the writer (models.GENERATOR) rewrites the question with each picked case's fixed
       instruction (instructions); the rewrite then goes through every code check again

The refiner only decides; it never writes the question. If Jev cannot be reached, an unused
case is chosen at random.
"""

from __future__ import annotations

import json

from core import models
from core.llm import TRANSIENT_STATUS, as_number

PICK_AT = 0.6           # a case at or above this probability is applied
PER_ROUND = 1           # one case per refinement round: the writer gets only that case's instruction
WORKING_CHARS = 2500    # how much of the solver's working the refiner reads

HEADER = ("Your earlier question was solved easily by a weak model, so it is not yet a JEE Advanced question. "
          "Make it genuinely harder by applying ONLY the changes below. Never make it harder by messier "
          "numbers or longer sentences. It must stay fair, complete and unambiguous, with exactly one answer, "
          "and still need every formula listed above.")

# id: (why it was easy: what the refiner looks for, what the writer is told to do)
CASES = {
    "cue_word": (
        "A word or phrase in the question named the concept, law, process or method (for example "
        "'isothermal reversible', 'buffer', 'limiting reagent', 'first order', 'colligative'), so the solver "
        "knew which formula to use without having to recognise it.",
        "The question named the concept or method{evidence}. Remove every word that names a law, process, "
        "method or type of system. Describe instead what is physically done and observed, as in an experiment "
        "(not 'isothermal reversible expansion' but 'the gas is allowed to expand very slowly in a cylinder "
        "kept in a large water bath at 300 K'). The solver must recognise the concept from the description "
        "alone. Keep the same twist and, where possible, the same values."),
    "ready_data": (
        "The data were given in exactly the form the formulas use (amount in mol, temperature in K, the "
        "concentration of the species itself, a stated condition), so the solver only substituted.",
        "The data were handed over in the form the formulas use{evidence}. Give one or two values one level "
        "earlier, as a JEE examiner would: a mass and the substance instead of an amount in mol; a temperature "
        "in °C; a pressure in mm Hg or bar; a solution as % w/w with its density; a quantity described by the "
        "experiment (the volume of titrant used, the mass of residue left) instead of stated. Each step back "
        "must be a standard one (n = m/M, a unit change, a mass or volume balance). Never state a value the "
        "solution computes."),
    "shortcut_worked": (
        "The usual shortcut or approximation (small degree of dissociation, ignoring water's ions, the "
        "obvious limiting reagent, ideal behaviour, neglecting a small term) gave the right answer.",
        "The usual shortcut or approximation gave the right answer{evidence}. Choose new values, and if "
        "needed a new system, where that shortcut gives a clearly different answer: a degree of dissociation "
        "that is not small, a limiting reagent that is not the obvious one, a solution dilute enough that "
        "water's ions matter, a term that cannot be neglected. These typical mistakes must each give a "
        "clearly different, believable answer: {traps}. The correct method must still give one clear answer."),
    "plugin_order": (
        "The solver only had to apply the formulas in order, from the given data straight to the asked "
        "quantity, with no step that needed working backwards or setting up an equation.",
        "The question was a straight plug-in in solution order{evidence}. Change what is asked: {twist} "
        "State a result that would normally be asked, and ask for a quantity that would normally be given, "
        "so the solver has to set up the relation and work back through the formulas."),
    "one_system": (
        "There was one system in one state, so a single pass through the formulas answered it; nothing had "
        "to be compared, combined or solved together.",
        "The question had one system in one state{evidence}. {twist} Introduce a second state or a second "
        "system (another temperature, another sample, before and after a change) so that the same relations "
        "must be set up twice and combined; neither part alone may give the answer."),
    "too_few_steps": (
        "The reasoning was short: the answer came after one or two real steps, and the other formulas were "
        "trivial or barely used.",
        "The reasoning was too short{evidence}. One more formula has been added to the list above: {added}. "
        "Rewrite the question so that this formula is genuinely needed in the middle of the reasoning, its "
        "result changing the answer. Do not attach it as a separate, unrelated part."),
    "textbook_pattern": (
        "The question followed a standard textbook exercise pattern (its layout, phrasing or data set), so "
        "the solver recognised it and followed a memorised route.",
        "The solver recognised a standard textbook exercise{evidence}. Keep the formulas but move the problem "
        "into an unusual yet realistic setting (an industrial process, a laboratory analysis, an "
        "environmental, geological or biological system) where the solver must first decide which relations "
        "apply. Avoid the usual phrasing and the usual data layout of textbook problems."),
    "trivial_units": (
        "All data were in consistent units that went straight into the formulas, so no conversion could go "
        "wrong.",
        "The units made the arithmetic trivial{evidence}. State the data in units a JEE paper uses that must "
        "be converted correctly, and differently for different formulas (kJ and J, °C and K, mm Hg or bar and "
        "atm, mL and L, per gram and per mole), so that a unit slip changes the answer. Keep the asked unit."),
}

TWIST_FOR = {"plugin_order": ("inverse", "condition"),
             "one_system": ("two_state_ratio", "two_state_difference", "simultaneous")}


def _jev_post(state, questions: dict, role: str) -> dict:
    """One Jev (TypeSafe System One) request through OpenRouter's Decisions API; its "answers".
    Raises RuntimeError when Jev cannot be reached."""
    import urllib.request
    key = models.api_key(models.JEV_MODEL)
    if not models.key_is_set(models.JEV_MODEL):
        raise RuntimeError("no API key in .env (OPENROUTER_KEY or AIROUTER_KEY)")
    where = models.router(models.JEV_MODEL)
    models.SERVED.setdefault(models.JEV_MODEL, set()).add(f"{where}:{models.route_model(models.JEV_MODEL, where)}")
    payload = {"model": models.route_model(models.JEV_MODEL, where), "state": state, "questions": questions}
    if where == "airouter":
        # airouter names it "input" and takes text ("input is required", then "input must be a string or an
        # array of messages", 2026-11-17): the state as JSON text
        payload["input"] = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        # and the questions as a list ("questions must be a non-empty array"), each with its id
        payload["questions"] = [_airouter_question(k, v) for k, v in questions.items()]
    body = json.dumps(payload)
    # a User-Agent: airouter's Cloudflare refuses urllib's own ("403 error code: 1010", 2026-11-17)
    req = urllib.request.Request(models.decisions_url(models.JEV_MODEL), data=body.encode("utf-8"), method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "prahlada-question-pipeline/1.0"})
    last = None
    import time
    for attempt in range(4):                             # transient errors are retried, with a pause
        if attempt:                                      # (airouter drops connections, 2026-11-17)
            time.sleep(5 * attempt)
        try:
            if where == "airouter":
                # through the openai client, as the chat calls that work: airouter's Cloudflare kept closing
                # urllib's TLS connections ("UNEXPECTED_EOF_WHILE_READING", 2026-11-17)
                out = models._client("airouter").post("/decisions", cast_to=object, body=json.loads(body))
            else:
                with urllib.request.urlopen(req, timeout=30) as r:
                    out = json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:                           # noqa: BLE001
            if getattr(e, "code", None) == 402 and where == "openrouter" and models.openrouter_out() \
                    and models.router(models.JEV_MODEL) == "airouter":
                return _jev_post(state, questions, role)  # OpenRouter out of credit: the same call on airouter
            body_text = ""
            try:                                         # the router's own reason (a wrong model name ...)
                body_text = e.read().decode("utf-8", "replace")[:300]
            except Exception:                            # noqa: BLE001
                pass
            last = f"{type(e).__name__}: {e} {body_text}".strip()
            # a refusal with a status no retry can change (400 bad request, 401/403 key, 404 model) is said at
            # once: it was retried 4 times with ~30 s of pauses. No status (a dropped connection): retried.
            status = getattr(e, "code", None) or getattr(e, "status_code", None)
            if isinstance(status, int) and status not in TRANSIENT_STATUS:
                raise RuntimeError(f"Jev request failed: {last}")
    else:
        raise RuntimeError(f"Jev request failed: {last}")
    if where == "airouter":
        ans = out.get("answers")
        if isinstance(ans, list):               # a list back as well: keyed by id again
            ans = {a.get("id") or a.get("name"): a for a in ans if isinstance(a, dict)}
        if isinstance(ans, dict):               # into the shape the callers read (OpenRouter's)
            ans = {k: _airouter_answer(a, questions.get(k) or {}) if isinstance(a, dict) else a
                   for k, a in ans.items()}
            out = {**out, "answers": ans}
        if not ans or not set(questions) <= set(ans):
            raise RuntimeError(f"Jev on airouter: unexpected reply: {json.dumps(out)[:400]}")
    usage = out.get("usage") or {}
    used = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    cost = usage.get("cost", usage.get("total_cost"))
    models.SPEND.add(role, {"prompt_tokens": used, "completion_tokens": 0,
                                 "cost": cost if cost is not None else used * models.JEV_USD_PER_INPUT_TOKEN})
    return out.get("answers") or {}


def _airouter_question(qid: str, q: dict) -> dict:
    """One question in airouter's own shape (2026-11-17, from its errors): "predicate" for yes/no,
    "choices" for a choice's options, "levels" for a score's ordered levels."""
    out = {"name": qid, "type": {"noul": "predicate"}.get(q["type"], q["type"]),
           "instructions": q.get("instructions", "")}
    if q["type"] == "choice":                   # "Each choice needs a string or boolean value"
        out["choices"] = [{"value": k, "description": v} for k, v in q["criteria"].items()]
    elif q["type"] == "score":                  # "Each level needs a non-empty label"
        out["levels"] = [{"label": str(lv)} for lv in q["criteria"]]
    return out


def _airouter_answer(a: dict, q: dict) -> dict:
    """airouter's answer in OpenRouter's shape: "noul" for yes/no; "probabilities" as {option: p} (choice)
    or {level index: p} (score) where airouter gives a list; "choice" as the option key; "score" as the
    expected level index when absent."""
    a = {**a, "noul": a.get("noul", a.get("predicate", a.get("probability")))}
    probs = a.get("probabilities")
    if isinstance(probs, list):
        levels = [str(x) for x in (q.get("criteria") or [])] if q.get("type") == "score" else []
        out = {}
        for i, item in enumerate(probs):
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                key, p = i, item
            elif isinstance(item, dict):
                key = item.get("value", item.get("label", item.get("name", item.get("id", i))))
                p = item.get("probability", item.get("p"))
            else:
                continue
            if q.get("type") == "score" and not isinstance(key, int):
                key = levels.index(str(key)) if str(key) in levels else i
            if as_number(p) is not None:
                out[key] = float(as_number(p))
        a["probabilities"] = out
    if isinstance(a.get("choice"), dict):
        c = a["choice"]
        a["choice"] = c.get("value", c.get("label", c.get("name")))
    if q.get("type") == "score" and as_number(a.get("score")) is None and a.get("probabilities"):
        pr = a["probabilities"]
        tot = sum(pr.values()) or 1.0
        a["score"] = sum(int(k) * v for k, v in pr.items() if isinstance(k, int)) / tot
    return a


def jev_decide(state: dict, questions: dict, role: str = "refiner") -> dict:
    """{question id: P(yes)} for yes/no ("noul") questions, each judged on its own."""
    answers = _jev_post(state, {q: {"type": "noul", "instructions": text} for q, text in questions.items()}, role)
    res = {}
    for q, a in answers.items():
        p = as_number((a or {}).get("noul"))
        if p is not None:
            res[q] = max(0.0, min(1.0, float(p)))
    if not res:
        raise RuntimeError(f"Jev returned no answers: {json.dumps(answers)[:200]}")
    return res


def jev_choose(state: dict, instructions: str, criteria: dict, role: str = "refiner") -> dict:
    """ONE choice among `criteria` (option key -> description): {"choice", "confidence",
    "probabilities"} with the probabilities over all options summing to 1, so the options are
    weighed against each other (8 separate yes/no questions were each judged alone)."""
    answers = _jev_post(state, {"pick": {"type": "choice", "instructions": instructions, "criteria": criteria}}, role)
    a = answers.get("pick") or {}
    probs = {k: max(0.0, min(1.0, float(v))) for k, v in (a.get("probabilities") or {}).items()
             if k in criteria and as_number(v) is not None}
    choice = a.get("choice") if a.get("choice") in criteria else (max(probs, key=probs.get) if probs else None)
    if choice is None:
        raise RuntimeError(f"Jev returned no choice: {json.dumps(answers)[:200]}")
    conf = as_number(a.get("confidence"))
    return {"choice": choice, "confidence": float(conf) if conf is not None else probs.get(choice, 0.0),
            "probabilities": probs or {choice: 1.0}}


def jev_score(state: dict, instructions: str, levels: list, role: str = "level_check") -> dict:
    """Jev's ordered-scale ("score") question: {"score": expected level index (fractional, 0 = first
    level), "probabilities": {index: p}, "confidence"}."""
    answers = _jev_post(state, {"level": {"type": "score", "instructions": instructions, "criteria": levels}}, role)
    a = answers.get("level") or {}
    sc = as_number(a.get("score"))
    if sc is None:
        raise RuntimeError(f"Jev returned no score: {json.dumps(answers)[:200]}")
    probs = {int(k): float(v) for k, v in (a.get("probabilities") or {}).items() if as_number(v) is not None}
    conf = as_number(a.get("confidence"))
    return {"score": float(sc), "probabilities": probs, "confidence": float(conf) if conf is not None else None}


def classify(stem: str, formulas: str, working: str, used: set) -> dict:
    """{case id: {"p": probability, "evidence": ""}} from Jev: ONE choice question over the cases
    not used yet, so their probabilities sum to 1 and the likeliest is Jev's pick. Raises
    RuntimeError when Jev cannot be reached (the caller then picks at random)."""
    state = {"question": stem, "formulas_it_is_built_on": formulas,
             "how_a_weak_model_solved_it": working[:WORKING_CHARS] or "(not available)"}
    criteria = {cid: why for cid, (why, _) in CASES.items() if cid not in used}
    if not criteria:
        return {}
    out = jev_choose(state, "This exam question was too easy for the weak model. Which ONE reason explains "
                            "that best?", criteria)
    print(f"    Jev's pick: {out['choice']} (confidence {out['confidence']:.0%})")
    # Jev's choice is marked: pick() applies it first, so the case printed above is the case applied (the
    # probabilities alone sometimes ranked another case first, and that one was applied instead)
    return {cid: {"p": p, "evidence": "", "chosen": cid == out["choice"]}
            for cid, p in out["probabilities"].items() if cid in CASES}


def pick(probs: dict, used: set, rng=None) -> list:
    """The cases to apply this round: Jev's own choice first (when it gave one), then the most likely."""
    free = sorted(((bool(v.get("chosen")), v["p"], cid) for cid, v in probs.items() if cid not in used),
                  reverse=True)
    chosen = [cid for mark, p, cid in free if mark or p >= PICK_AT][:PER_ROUND]
    if not chosen and free:
        chosen = [free[0][2]]
    if not chosen:                               # the refiner gave nothing usable: any unused case
        rest = [c for c in CASES if c not in used]
        if rest and rng is not None:
            chosen = [rng.choice(rest)]
    return chosen


def instructions(chosen: list, probs: dict, *, twist_text: str = "", added: str = "", traps=()) -> str:
    """The writer's instructions for the chosen cases: HEADER and one fixed paragraph per case."""
    parts = [HEADER]
    for i, cid in enumerate(chosen, 1):
        ev = (probs.get(cid) or {}).get("evidence") or ""
        text = CASES[cid][1].format(evidence=f" ({ev})" if ev else "", twist=twist_text, added=added,
                                    traps="; ".join(traps) or "the typical mistakes of these formulas")
        parts.append(f"{i}. {text}")
    return "\n".join(parts)
