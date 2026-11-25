"""
ab_inorganic_statements.py: which way of choosing statements makes reaction-system questions harder? (plan step 3,
2026-11-25). Offline: the pipeline is not changed.

Same reaction systems in every arm; only the four statements differ:
    base    today's statements (inorg_system._msq): one fact about one species, a generic wrong value
    rival   rival-product traps: the statement is about a fact on which the real product and the RIVAL product
            (the same start with another reagent or condition in our graph) differ; a false statement carries the
            rival's value, so a student who picks the wrong product picks the trap
    cross   statements linking two letters: "<W> and <X> have the same number of unpaired electrons", "the oxidation
            state of Mn is higher in <X> than in <W>": both species must be identified and worked out
    picker  a model (models.GENERATOR) is shown the identities and a menu of everything code can key (base, rival
            and cross statements, with the allowed false values) and picks the four it judges hardest; code writes
            the text and keys every statement, so correctness never depends on the model

Controls: the plain reaction scheme (no prose rewrite) in every arm; the same number of true statements per system
in every arm; every key by code. Measured with the corrected ladder: Granite three tries (solved if right in two;
unreadable asked again), GLM one try, Jev's level score. Success bar (agreed): Granite solves at most about 2 of 6,
the rate on real medium-hard Advanced questions (calibration/ladder_vs_students_inorganic.py).

    python tools/ab_inorganic_statements.py --dry-run            # systems, every arm's question and key, no calls
    python tools/ab_inorganic_statements.py                      # paid
Output: outputs/ab_inorganic_statements.json (checkpointed after every system).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import answers, models                          # noqa: E402
from core.engine.base import ChainResult                  # noqa: E402
from core.engine.chem import Z_OF                         # noqa: E402
from core.engine.inorganic import properties as P         # noqa: E402
from core.llm import write_json_atomic                    # noqa: E402
from core.pipeline import inorg_qfirst as IQ              # noqa: E402
from core.pipeline import inorg_system as SY              # noqa: E402
from tools.spend_cap import SpendCap, SpendCapReached  # noqa: E402

OUT = os.path.join(ROOT, "outputs", "ab_inorganic_statements.json")
N_SYSTEMS = 15
ARMS = ("base", "rival", "cross", "picker")
OPTION = "ABCD"
SUP = str.maketrans("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹")


class _Adapter:
    config = {"graph_path": os.path.join(ROOT, "knowledge", "reaction_graph_inorg.json")}
    subject = "inorganic"


GRAPH = IQ._graph(_Adapter())


# ── statements: {"text", "true", "arm", "about"} ─────────────────────────────

def _single(L, f, k, v, e, true, shown=None):
    shown = v if true else shown
    return {"text": SY._text(SY.tag(L), f, k, shown, e), "true": true, "about": f"{L}:{k}={v} (shown {shown})"}


def base_items(D, rng):
    """(letter, fam, key, value, el) chosen as _msq chooses them: mixed kinds, at most two per letter."""
    pool = [(L, f, k, v, e) for L, fs in D["facts"].items() for f, k, v, e in fs]
    rng.shuffle(pool)
    chosen, used, seen = [], set(), set()
    for strict in (True, False):
        for it in pool:
            cat = SY.CATEGORY[it[1]]
            if it in chosen or (it[0], cat) in seen or (strict and cat in used):
                continue
            if sum(1 for c in chosen if c[0] == it[0]) >= 2:
                continue
            chosen.append(it)
            used.add(cat)
            seen.add((it[0], cat))
    return chosen


def base_statement(item, true, rng):
    L, f, k, v, e = item
    if true:
        return _single(L, f, k, v, e, True)
    w = SY._wrong(f, k, v, rng, el_is_metal=bool(e and P.is_transition(e)), el=e)
    return None if w is None or w == v else _single(L, f, k, v, e, False, w)


def rival_items(D):
    """Facts on which a letter's product and a rival product of the same start differ (same kind of fact, same
    element): [(item, rival value, rival species)]."""
    out = []
    for e in D["steps"]:
        L = D["labels"][e["to"]]
        mine = {f: (k, v, el) for f, k, v, el in D["facts"][L]}
        for o in GRAPH["out"].get(e["from"], []):
            if o["to"] == e["to"] or not SY._usable(o):
                continue
            for f, k, v, el in SY.facts(o["to"]):
                if f in mine and mine[f][2] == el and mine[f][1] != v and mine[f][0] == k:
                    out.append(((L, f, k, mine[f][1], el), v, o["to"]))
    seen, uniq = set(), []
    for it in out:                                   # one rival value per (letter, fact)
        if (it[0][0], it[0][1]) not in seen:
            seen.add((it[0][0], it[0][1]))
            uniq.append(it)
    return uniq


def cross_items(D):
    """Statements linking two letters, each with a true and a false wording: [(true_text, false_text, about)]."""
    T = SY.tag
    fx = {L: {f: (v, el) for f, k, v, el in fs} for L, fs in D["facts"].items()}
    out = []
    for A, B in itertools.combinations(sorted(fx), 2):
        a, b = fx[A], fx[B]
        if "unpaired" in a and "unpaired" in b:
            same = a["unpaired"][0] == b["unpaired"][0]
            s, d = (f"{T(A)} and {T(B)} have the same number of unpaired electrons",
                    f"{T(A)} and {T(B)} have different numbers of unpaired electrons")
            out.append((s if same else d, d if same else s, f"{A},{B}:unpaired"))
        if "moment" in a and "moment" in b and a["moment"][0] != b["moment"][0]:
            hi, lo = (A, B) if a["moment"][0] > b["moment"][0] else (B, A)
            out.append((f"{T(hi)} has a higher spin-only magnetic moment than {T(lo)}",
                        f"{T(lo)} has a higher spin-only magnetic moment than {T(hi)}", f"{A},{B}:moment"))
        if "hybrid" in a and "hybrid" in b and a["hybrid"][1] and b["hybrid"][1]:
            same = a["hybrid"][0] == b["hybrid"][0]
            s = f"{a['hybrid'][1]} in {T(A)} and {b['hybrid'][1]} in {T(B)} have the same hybridisation"
            d = f"{a['hybrid'][1]} in {T(A)} and {b['hybrid'][1]} in {T(B)} have different hybridisations"
            out.append((s if same else d, d if same else s, f"{A},{B}:hybrid"))
        if "geometry" in a and "geometry" in b and a["geometry"][1] and b["geometry"][1]:
            same = a["geometry"][0] == b["geometry"][0]
            s = (f"The geometry around {a['geometry'][1]} in {T(A)} is the same as that around "
                 f"{b['geometry'][1]} in {T(B)}")
            d = s.replace("is the same as", "differs from")
            out.append((s if same else d, d if same else s, f"{A},{B}:geometry"))
        if "oxidation" in a and "oxidation" in b and a["oxidation"][1] == b["oxidation"][1] and a["oxidation"][1]:
            el, va, vb = a["oxidation"][1], a["oxidation"][0], b["oxidation"][0]
            if va != vb:
                hi, lo = (A, B) if va > vb else (B, A)
                out.append((f"The oxidation state of {el} is higher in {T(hi)} than in {T(lo)}",
                            f"The oxidation state of {el} is higher in {T(lo)} than in {T(hi)}", f"{A},{B}:ox"))
            else:
                out.append((f"{el} has the same oxidation state in {T(A)} and {T(B)}",
                            f"The oxidation state of {el} differs between {T(A)} and {T(B)}", f"{A},{B}:ox"))
        if "d" in a and "d" in b and a["d"][1] and b["d"][1]:
            same = a["d"][0] == b["d"][0]
            s = f"The metals in {T(A)} and {T(B)} have the same number of d electrons"
            d = f"The metals in {T(A)} and {T(B)} have different numbers of d electrons"
            out.append((s if same else d, d if same else s, f"{A},{B}:d"))
    return out


# ── arms: four statements with a given truth pattern ─────────────────────────

def arm_base(D, truth, rng):
    items = base_items(D, rng)
    out = []
    for it in items:
        if len(out) == 4:
            break
        s = base_statement(it, truth[len(out)], rng)
        if s:
            out.append({**s, "arm": "base"})
    return out if len(out) == 4 else None


def arm_rival(D, truth, rng):
    rv = rival_items(D)
    out, used = [], set()
    for (L, f, k, v, e), wv, q in rv:
        if len(out) == 4 or (L, SY.CATEGORY[f]) in used or sum(1 for x in out if x["letter"] == L) >= 2:
            continue
        t = truth[len(out)]
        s = _single(L, f, k, v, e, t, None if t else wv)
        out.append({**s, "arm": "rival", "letter": L, "about": s["about"] + f" rival {q}"})
        used.add((L, SY.CATEGORY[f]))
    n_rival = len(out)
    for it in base_items(D, rng):                    # fill with today's statements
        if len(out) == 4:
            break
        if (it[0], SY.CATEGORY[it[1]]) in used or sum(1 for x in out if x.get("letter") == it[0]) >= 2:
            continue
        s = base_statement(it, truth[len(out)], rng)
        if s:
            out.append({**s, "arm": "base", "letter": it[0]})
            used.add((it[0], SY.CATEGORY[it[1]]))
    return (out, n_rival) if len(out) == 4 else (None, 0)


def arm_cross(D, truth, rng):
    cx = cross_items(D)
    rng.shuffle(cx)
    out, fams = [], set()
    for tt, ft, about in cx:
        fam = about.split(":")[1]
        if len(out) == 3 or fam in fams:
            continue
        t = truth[len(out)]
        out.append({"text": tt if t else ft, "true": t, "arm": "cross", "about": about})
        fams.add(fam)
    n_cross = len(out)
    for it in base_items(D, rng):
        if len(out) == 4:
            break
        s = base_statement(it, truth[len(out)], rng)
        if s:
            out.append({**s, "arm": "base"})
    return (out, n_cross) if len(out) == 4 else (None, 0)


def menu(D, rng):
    """Everything code can key, for the picker: [{"id", "kind", "text_true", "text_false"[], "about"}]."""
    items, n = [], 0
    rivals = {(r[0][0], r[0][1]): r for r in rival_items(D)}
    for L, fs in D["facts"].items():
        for f, k, v, e in fs:
            falses = []
            w = SY._wrong(f, k, v, rng, el_is_metal=bool(e and P.is_transition(e)), el=e)
            if w is not None and w != v:
                falses.append(SY._text(SY.tag(L), f, k, w, e))
            if (L, f) in rivals:
                falses.append(SY._text(SY.tag(L), f, k, rivals[(L, f)][1], e))
            n += 1
            items.append({"id": n, "kind": "single", "text_true": SY._text(SY.tag(L), f, k, v, e),
                          "text_false": list(dict.fromkeys(falses)), "about": f"{L}:{k}={v}",
                          "rival": (L, f) in rivals})
    for tt, ft, about in cross_items(D):
        n += 1
        items.append({"id": n, "kind": "two letters", "text_true": tt, "text_false": [ft], "about": about,
                      "rival": False})
    return items


def arm_picker(D, truth, rng, cand):
    m = menu(D, rng)
    ids = {it["id"]: it for it in m}
    want = sum(truth)
    who = "; ".join(f"{SY.tag(L)} = {SY.IP.pretty(s)}" for s, L in D["labels"].items())
    listing = "\n".join(f"{it['id']}. [{it['kind']}] TRUE: {it['text_true']}"
                        + "".join(f" | FALSE {j + 1}: {x}" for j, x in enumerate(it["text_false"]))
                        for it in m)
    prompt = f"""You set the hardest inorganic chemistry questions in JEE Advanced. A student reads only this:
Consider the following reactions (unbalanced):
{SY.scheme(cand)}
The lettered species are (the student is NOT told this): {who}.

Choose four statements from the menu for "Choose the correct option(s)". Exactly {want} must be TRUE. Make the
question as hard as possible for a strong student while staying fair: prefer statements that can only be judged
after working out the species correctly, statements that link two letters, and false statements that are true
for a tempting wrong product or a common misconception. Avoid statements a student can judge without
identifying anything. Use each menu item at most once.
MENU (each item: the TRUE wording, then the FALSE wordings you may use instead):
{listing}
Return JSON: {{"picks": [{{"id": 1, "use": "true"}} or {{"id": 2, "use": "false", "false": 1}}, ...], "why": "one line"}}"""
    for _ in range(2):
        try:
            out = models.ask_json("generator", models.GENERATOR, "You design chemistry exam questions. Output JSON only.",
                                  prompt, temperature=0.4, max_tokens=3000)
        except Exception:                            # noqa: BLE001
            continue
        st = []
        for p in out.get("picks") or []:
            it = ids.get(int(p.get("id", -1))) if str(p.get("id", "")).lstrip("-").isdigit() else None
            if it is None:
                break
            if p.get("use") == "false":
                j = int(p.get("false") or 1) - 1
                if not 0 <= j < len(it["text_false"]):
                    break
                st.append({"text": it["text_false"][j], "true": False, "arm": "picker", "about": it["about"]})
            else:
                st.append({"text": it["text_true"], "true": True, "arm": "picker", "about": it["about"]})
        if len(st) == 4 and len({s["text"] for s in st}) == 4 and sum(s["true"] for s in st) == want:
            rng.shuffle(st)
            return st, out.get("why")
    return None, None


# ── arm "reword": the model picks from a rival-led menu and words the statements; code keys and checks ────────

# the drift check lives in the pipeline (inorg_system), one copy for both
_norm, _tokens, faithful = SY._norm, SY._tokens, SY.faithful


def arm_reword(D, truth, rng, cand):
    """(statements, why, fallbacks). The model picks four statements from a menu that lists rival-product traps
    first, uses every letter, and words each one in JEE style; code keys every statement from the menu item and
    keeps a wording only if faithful() finds nothing lost or changed (else code's own wording, counted)."""
    m = menu(D, rng)
    m.sort(key=lambda it: not it["rival"])            # rival-product traps first
    ids = {it["id"]: it for it in m}
    want = sum(truth)
    who = "; ".join(f"{SY.tag(L)} = {SY.IP.pretty(s)}" for s, L in D["labels"].items())
    listing = "\n".join(f"{it['id']}. [{it['kind']}{', RIVAL-PRODUCT TRAP available' if it['rival'] else ''}] "
                        f"TRUE: {it['text_true']}" + "".join(f" | FALSE {j + 1}: {x}" for j, x in
                                                             enumerate(it["text_false"])) for it in m)
    prompt = f"""You set hard inorganic chemistry questions for JEE Advanced. A student reads only this:
Consider the following reactions (unbalanced):
{SY.scheme(cand)}
The lettered species are (the student is NOT told this): {who}.

Choose four statements from the menu for "Choose the correct option(s)". Exactly {want} must be TRUE.
- Make it hard but fair. Prefer RIVAL-PRODUCT TRAPS (a FALSE wording that is true for the product a student gets
  if they work out the wrong species), statements that link two letters, and statements that can only be judged
  after identifying the species. Avoid statements judged without identifying anything.
- Every lettered species ({', '.join(SY.tag(L) for L in D['labels'].values())}) must appear in at least one statement.
- Then write each chosen statement in natural, varied JEE Advanced wording ("wording"). It must say exactly what
  the menu wording says: keep every <letter> tag as written, every number as digits, every element symbol and every
  chemical term; add no facts and no negation; plain text with Unicode sub/superscripts, no LaTeX.
MENU (each item: the TRUE wording, then the FALSE wordings you may use instead):
{listing}
Return JSON: {{"picks": [{{"id": 1, "use": "true", "wording": "..."}} or {{"id": 2, "use": "false", "false": 1, "wording": "..."}}, ...], "why": "one line"}}"""
    for _ in range(2):
        try:
            out = models.ask_json("generator", models.GENERATOR, "You design chemistry exam questions. Output JSON only.",
                                  prompt, temperature=0.5, max_tokens=3500)
        except Exception:                            # noqa: BLE001
            continue
        st, fallbacks = [], 0
        for p in out.get("picks") or []:
            it = ids.get(int(p["id"])) if str(p.get("id", "")).isdigit() else None
            if it is None:
                break
            if p.get("use") == "false":
                j = int(p.get("false") or 1) - 1
                if not 0 <= j < len(it["text_false"]):
                    break
                code_text, true = it["text_false"][j], False
            else:
                code_text, true = it["text_true"], True
            lost = faithful(code_text, p.get("wording") or "")
            text = code_text if lost else str(p["wording"]).strip()
            fallbacks += bool(lost)
            st.append({"text": text, "true": true, "arm": "reword", "about": it["about"], "code_text": code_text,
                       "model_wording": p.get("wording"), "drift": lost, "rival": it["rival"] and not true})
        used = set(re.findall(r"<([A-Z])>", " ".join(s["text"] for s in st)))
        if (len(st) == 4 and len({s["text"] for s in st}) == 4 and sum(s["true"] for s in st) == want
                and used >= set(D["labels"].values())):
            rng.shuffle(st)
            return st, out.get("why"), fallbacks
    return None, None, 0


def reword_only(cand, st):
    """(statements, fallbacks): the same four code-keyed statements, each rewritten by the model in varied exam
    wording; a rewrite that copies the code wording or fails faithful() keeps the code wording (counted)."""
    listing = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(st))
    prompt = f"""These are the four options of a JEE Advanced inorganic chemistry question about the reactions below.
Rewrite EACH option so the four read like a well-written exam paper: vary the sentence structure from option to
option and do NOT copy the given sentence. Examples of the kind of change wanted (not of content):
  "<X> has a trigonal pyramidal shape"  ->  "The shape of <X> is trigonal pyramidal"
  "S in <G> is sp² hybridised"          ->  "The sulphur atom in <G> uses sp² hybrid orbitals"
  "The bond order of <Y> is 2.5"        ->  "<Y> has a bond order of 2.5"
Rules: the meaning must stay exactly the same (it is already true or false as written); keep every <letter> tag as
written, every number as digits, every element symbol and every chemical term (shape names, sp³d² etc.,
paramagnetic, dibasic, same/different, higher); add no negation, no facts, no hints; plain text with Unicode
sub/superscripts, no LaTeX.
Reactions:
{SY.scheme(cand)}
Options:
{listing}
Return JSON: {{"options": ["...", "...", "...", "..."]}}"""
    try:
        out = models.ask_json("generator", models.GENERATOR, "You edit chemistry exam papers. Output JSON only.",
                              prompt, temperature=0.7, max_tokens=2500)
        new = [str(x).strip() for x in out.get("options") or []]
    except Exception:                                # noqa: BLE001
        new = []
    res, fallbacks = [], 0
    for i, s in enumerate(st):
        w = new[i] if i < len(new) else ""
        lost = faithful(s["text"], w) if w else ["no rewrite"]
        copied = _norm(w).strip(" .") == _norm(s["text"]).strip(" .")
        keep = w and not lost and not copied
        fallbacks += not keep
        res.append({**s, "code_text": s["text"], "model_wording": w, "drift": lost, "copied": copied,
                    "text": w if keep else s["text"]})
    return res, fallbacks


# ── systems and questions ────────────────────────────────────────────────────

def systems(seed=20261125):
    """N_SYSTEMS systems where the rival and cross arms each have at least two statements of their own."""
    rng = random.Random(seed)
    bad = set(SY.load_memory()["unconfirmed_edges"])
    out, keys = [], set()
    for _ in range(4000):
        c = SY.draw(GRAPH, rng, bad=bad)
        if c is None or c["edges"][0] in keys:
            continue
        D = c["_system"]
        n_true = rng.choice((1, 2, 2, 3))
        truth = [True] * n_true + [False] * (4 - n_true)
        rng.shuffle(truth)
        r, nr = arm_rival(D, truth, random.Random(1))
        x, nx = arm_cross(D, truth, random.Random(1))
        if not r or not x or nr < 2 or nx < 2 or not arm_base(D, truth, random.Random(1)):
            continue
        keys.add(c["edges"][0])
        out.append((c, truth))
        if len(out) == N_SYSTEMS:
            break
    return out


def question(cand, st):
    stem = ("Consider the following reactions (unbalanced):\n" + SY.scheme(cand) + "\nChoose the correct option(s).\n"
            + "\n".join(f"({OPTION[i]}) {s['text']}" for i, s in enumerate(st)))
    key = "".join(OPTION[i] for i, s in enumerate(st) if s["true"])
    return stem, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", type=int, default=3, help="systems printed in full in the dry run")
    ap.add_argument("--arms", default=",".join(ARMS), help="arms to run, e.g. reword")
    ap.add_argument("--out", default=OUT, help="output JSON")
    ap.add_argument("--no-glm", action="store_true", help="Granite only (GLM is the costly label)")
    ap.add_argument("--max-rs", type=float, default=10.0, help="hard spend cap in rupees")
    args = ap.parse_args()
    sysl = systems()
    print(f"{len(sysl)} systems; arms {', '.join(ARMS)}")
    chem = {}
    for c, _t in sysl:
        for s in [c["_system"]["start"]]:
            chem[s[:2]] = chem.get(s[:2], 0) + 1
    if args.dry_run:
        for i, (c, truth) in enumerate(sysl):
            D = c["_system"]
            print(f"\n=== {i + 1}. {c['description']}  letters: "
                  + ", ".join(f"{SY.tag(L)}={s}" for s, L in D["labels"].items()))
            if i >= args.show:
                continue
            for arm in ARMS[:3]:
                st = {"base": lambda: arm_base(D, truth, random.Random(1)),
                      "rival": lambda: arm_rival(D, truth, random.Random(1))[0],
                      "cross": lambda: arm_cross(D, truth, random.Random(1))[0]}[arm]()
                stem, key = question(c, st)
                print(f"--- {arm}: key {key}")
                for s in st:
                    print(f"    [{'T' if s['true'] else 'F'}] {s['text']}   <{s['arm']}: {s['about']}>")
        return
    from unittest import mock
    from core.pipeline import flow, qf_checks, stages
    try:
        with open(args.out, encoding="utf-8") as f:
            done = {r["system"]: r for r in json.load(f)["records"]}
    except (OSError, ValueError, KeyError):
        done = {}
    records = []
    for i, (c, truth) in enumerate(sysl):
        if c["edges"][0] in done:
            records.append(done[c["edges"][0]])
            continue
        try:
            SpendCap(args.max_rs).check(f"system {i + 1}")
        except SpendCapReached as e:
            print(e)
            break
        D = c["_system"]
        rec = {"system": c["edges"][0], "description": c["description"],
               "labels": {L: s for s, L in D["labels"].items()}, "arms": {}}
        for arm in args.arms.split(","):
            why, fb = None, None
            if arm == "base":
                st = arm_base(D, truth, random.Random(1))
            elif arm == "rival":
                st = arm_rival(D, truth, random.Random(1))[0]
            elif arm == "cross":
                st = arm_cross(D, truth, random.Random(1))[0]
            elif arm == "reword":
                st, why, fb = arm_reword(D, truth, random.Random(1), c)
            elif arm == "rewordonly":                 # the rival arm's questions, reworded only
                st, fb = reword_only(c, arm_rival(D, truth, random.Random(1))[0])
            elif arm == "rewordbase":                 # today's statements, reworded only (like-for-like control)
                st, fb = reword_only(c, arm_base(D, truth, random.Random(1)))
            else:
                st, why = arm_picker(D, truth, random.Random(1), c)
            if not st:
                rec["arms"][arm] = {"skipped": True}
                continue
            stem, key = question(c, st)
            res = ChainResult(answer=key, unit="", kind="letters", asks=stem, trace=[], traps=[], constants=[])
            res.options = [s["text"] for s in st]
            spec = answers.answer_spec(key, "letters", "", flow._answer_instruction(object(), res), None)
            solve = IQ._measured_solver(res, stages.council_solve)
            row = {"stem": stem, "key": key, "statements": st, "why": why, "fallbacks": fb, "jev": qf_checks.jev_level(stem)}
            try:
                g = solve(stem, [models.LADDER[0][0]], spec)[0]
                row["granite"] = {"tries": g.get("bottom_tries"), "answers": g.get("bottom_answers"),
                                  "solved": flow._grade(res, g)["counts_as_solved"]}
                if not args.no_glm:
                    m = solve(stem, [models.LADDER[1][0]], spec)[0]
                    row["glm"] = {"answer": m.get("final_answer"),
                                  "solved": flow._grade(res, m)["counts_as_solved"]}
            except Exception as e:                   # noqa: BLE001  unreadable or a failed call: recorded
                row["error"] = str(e)[:160]
            rec["arms"][arm] = row
        records.append(rec)
        print(f"{i + 1:2}. {c['description'][:60]:60} " + "  ".join(
            f"{a}: G{'Y' if r.get('granite', {}).get('solved') else '-'}{r.get('granite', {}).get('tries', '')}"
            f" glm{'Y' if r.get('glm', {}).get('solved') else '-'}" for a, r in rec["arms"].items()
            if not r.get("skipped")), flush=True)
        write_json_atomic(args.out, {"arms": args.arms.split(","), "records": records, "spend": models.SPEND.summary()},
                          ensure_ascii=False)
    print("spend", models.SPEND.summary()["total_cost_usd"])


if __name__ == "__main__":
    main()
