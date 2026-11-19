"""
regress.py — every wrong output a run produced, saved with the pipeline STAGE it went wrong in,
and replayed through that stage only. A code change is checked against these cases before
new questions are generated: an old failure that comes back, or one that was meant to be fixed
and is not, shows up here instead of in a live run.

Cases live in tests/regressions/<stage>/<id>.json. Two kinds of stage:

    offline (code only; free, exact, also run by the unittest suite)
        grade     flow._grade        a member's answer -> solved? (code only)
        parse     answers            a solver's answer line -> the value graded
        program   sandbox.evaluate   a solve() program -> its answer, or rejected

    live (a real model is called; costs API money; judged by how often it now goes right)
        ladder    stages._solve      a ladder model solves the stem -> matches the reference?
        coder     qf_coder.solver_program   the coder writes the program -> right answer, no bad pattern

A model-stage case cannot be replayed exactly: once a prompt changes, the model's reply changes.
It is sent to the model again and counted ("2/3 now right"), never asserted bit for bit.

Status: "open" (still failing: the bug is known, not yet fixed) or "fixed" (a guard: it must keep
passing). The unittest suite fails on a fixed case that fails again, and on an open case that
now passes (so it gets marked fixed); open cases that still fail are reported as skipped.

    python -m tools.regress list [--stage S]
    python -m tools.regress run [--stage S] [--id ID]                 # offline stages
    python -m tools.regress run --live [--stage S] [--repeats 3]      # model stages too
    python -m tools.regress candidates outputs/runs/<run>.json        # wrong outputs in a run log
    python -m tools.regress save outputs/runs/<run>.json <n> [--stage S] [--id ID] [--note TEXT]
    python -m tools.regress mark <id> fixed|open
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "regressions"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OFFLINE = ("grade", "parse", "program")
LIVE = ("ladder", "coder")          # no verifier stage since 2026-11-19 (the verifier was removed)
STAGES = OFFLINE + LIVE


# ── cases ─────────────────────────────────────────────────────────────────────

def load_cases(stage: str | None = None, case_id: str | None = None) -> list:
    out = []
    for p in sorted(CASES.glob("*/*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        c["_path"] = str(p.relative_to(ROOT))
        if c.get("stage") != p.parent.name:
            raise ValueError(f"{c['_path']}: stage {c.get('stage')!r} but filed under {p.parent.name}/")
        if c["stage"] not in STAGES:
            raise ValueError(f"{c['_path']}: unknown stage {c['stage']!r} (one of {', '.join(STAGES)})")
        if (stage is None or c["stage"] == stage) and (case_id is None or c["id"] == case_id):
            out.append(c)
    return out


def write_case(case: dict) -> Path:
    if case["stage"] not in STAGES:
        raise ValueError(f"unknown stage {case['stage']!r}")
    path = CASES / case["stage"] / f"{case['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in case.items() if not k.startswith("_")}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _reference(ref: dict):
    """The engine's answer as the grading code sees it."""
    return SimpleNamespace(answer=ref["answer"], unit=ref.get("unit") or "", kind=ref.get("kind") or "real",
                           tolerance=ref.get("tolerance", 0.01), answer_substances=ref.get("substances"),
                           fmt=ref.get("fmt"))


def _spec(ref: dict) -> dict:
    from core import answers
    from core.pipeline import flow
    r = _reference(ref)
    fmt = ref.get("fmt") or flow._answer_instruction(None, r)
    return answers.answer_spec(r.answer, r.kind, r.unit, fmt, r.answer_substances)


def _allowed(want, got) -> bool:
    """An expected value is one value or a list of allowed values."""
    return got in want if isinstance(want, list) else got == want


def _close(a, b, tol) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-300)


# ── offline stages ────────────────────────────────────────────────────────────

def run_grade(case) -> tuple:
    from core.pipeline import flow
    inp, want = case["input"], case["expect"]
    g = flow._grade(_reference(inp["reference"]), inp["member"], inp.get("diagnosis") or {})
    bad = [f"{k} = {g.get(k)!r}, expected {v!r}" for k, v in want.items() if not _allowed(v, g.get(k))]
    return not bad, "; ".join(bad) or f"counts_as_solved = {g['counts_as_solved']}"


def run_parse(case) -> tuple:
    from core import answers
    inp, want = case["input"], case["expect"]
    done = answers.complete_answer(answers.parse_answer_line(inp["answer_line"]), _spec(inp["reference"]))
    if not want.get("ok", True):
        return not done.get("ok"), f"ok = {done.get('ok')} ({done.get('reason')})"
    if not done.get("ok"):
        return False, f"line not usable: {done.get('reason')}"
    got = done.get("final_value")
    exp = want.get("final_value")
    if exp is None:
        return True, f"final_value = {got}"
    tol = want.get("tolerance", 1e-3)
    ok = isinstance(got, list) and len(got) == len(exp) and all(_close(a, b, tol) for a, b in zip(got, exp))
    return ok, f"final_value = {got}, expected {exp}"


def run_program(case) -> tuple:
    from core.engine import sandbox
    inp, want = case["input"], case["expect"]
    run = sandbox.evaluate(inp["code"], inp["txs"], any_step=inp.get("any_step", True), preset=inp.get("preset"))
    if want.get("rejected"):
        return not run.get("ok"), ("rejected: " + str(run.get("error"))[:200]) if not run.get("ok") \
            else f"accepted (answer {run.get('answer')}); it should be rejected"
    if not run.get("ok"):
        return False, f"did not run: {str(run.get('error'))[:200]}"
    if "error_contains" in want:
        return False, "ran, but an error was expected"
    ok = _close(run["answer"], want["answer"], want.get("tolerance", 0.01))
    return ok, f"answer {run['answer']}, expected {want['answer']}"


# ── live stages ───────────────────────────────────────────────────────────────

def _slug(name_or_slug: str) -> str:
    from core import models
    return dict(models.LADDER).get(name_or_slug, name_or_slug)


def run_ladder(case) -> tuple:
    from core.pipeline import flow, stages
    inp = case["input"]
    rec = stages._solve(_slug(inp["model"]), inp["stem"], spec=_spec(inp["reference"]))
    m = flow._code_match(_reference(inp["reference"]), rec)
    want = case["expect"].get("matches", True)
    return m is want, f"{rec.get('final_answer')!r} (reference {inp['reference']['answer']})"


class _NoBoard:
    """solver_program notes its attempts on the run's blackboard; a replay has none."""
    current = None

    def note(self, *a, **k):
        pass


def run_coder(case) -> tuple:
    from core.engine import sandbox
    from core.pipeline import qf_coder
    inp, want = case["input"], case["expect"]
    code, why = qf_coder.solver_program(inp["question"], inp["txs"], _NoBoard(), tries=inp.get("tries"))
    if code is None:
        return False, f"no program: {str(why)[:200]}"
    for pat in want.get("forbid", []):
        if re.search(pat, code):
            return False, f"program contains the forbidden pattern {pat!r}"
    run = sandbox.evaluate(code, inp["txs"], any_step=True, preset=inp.get("values"))
    if not run.get("ok"):
        return False, f"program does not run on the question's values: {str(run.get('error'))[:200]}"
    if "answer" not in want:
        return True, f"answer {run['answer']}"
    ok = _close(run["answer"], want["answer"], want.get("tolerance", 0.01))
    return ok, f"answer {run['answer']}, expected {want['answer']}"


RUNNERS = {"grade": run_grade, "parse": run_parse, "program": run_program,
           "ladder": run_ladder, "coder": run_coder}


def replay(case, repeats: int = 1) -> dict:
    """{"passed", "detail", "rate"}: an offline case runs once; a live one `repeats` times and
    passes when at least expect.min_rate (default 0.5) of the attempts went right."""
    fn = RUNNERS[case["stage"]]
    if case["stage"] in OFFLINE:
        try:
            ok, detail = fn(case)
        except Exception as e:                             # noqa: BLE001 - a crash is a failure
            ok, detail = False, f"raised {type(e).__name__}: {str(e)[:200]}"
        return {"passed": ok, "detail": detail, "rate": float(ok)}
    results = []
    for _ in range(repeats):
        try:
            results.append(fn(case))
        except Exception as e:                             # noqa: BLE001
            results.append((False, f"raised {type(e).__name__}: {str(e)[:160]}"))
    rate = sum(ok for ok, _ in results) / len(results)
    return {"passed": rate >= case["expect"].get("min_rate", 0.5), "rate": rate,
            "detail": " | ".join(d for _, d in results)}


# ── capture from a run log (outputs/runs/<time>_<subject>.json) ───────────────

_PADDING = re.compile(r"\(\s*(\w+)\s*/\s*\1\s*\)|\(\s*(\w+)\s*-\s*\2\s*\)")


def _result_from(qf: dict):
    """The engine's result as the judge saw it, rebuilt from the run log's 'qfirst' note."""
    from core.pipeline import qfirst
    run = {k: qf.get(k) for k in ("answer", "trace", "traps", "constants", "tolerance", "givens", "depth")}
    return qfirst.make_result(run, qf["asks"], qf.get("unit") or "", qf.get("twist") or "", qf.get("code") or "")


def candidates(run_path: str) -> list:
    """Outputs in a run log that look wrong, each with the stage to file it under and a ready case.
    The list is a suggestion: what is really wrong is for a person to decide."""
    from core.pipeline import flow
    log = json.loads(Path(run_path).read_text(encoding="utf-8"))
    found = []
    for ci, ch in enumerate(log.get("chains", [])):
        qf = None
        for ei, e in enumerate(ch.get("events", [])):
            where = f"{Path(run_path).name} chain {ci} event {ei}"
            if e["stage"] == "qfirst":
                qf = e
            if e["stage"] == "program" and e.get("code") and _PADDING.search(e["code"]):
                found.append({"what": f"program pads with x/x or x-x to 'use' a value (answer {e.get('answer')})",
                              "where": where, "stage": "program", "case": {
                                  "input": {"code": e["code"], "txs": ch["chain"].get("txs") or [],
                                            "preset": e.get("probe_values")},
                                  "expect": {"rejected": True}}})
            if e["stage"] != "council" or qf is None:
                continue
            res = _result_from(qf)
            ref = {"answer": res.answer, "unit": res.unit, "kind": res.kind, "tolerance": res.tolerance}
            for m in e.get("members", []):
                d = m.get("diagnosis") or {}
                member = {k: m.get(k) for k in ("working", "final_answer", "unit", "final_value", "substance",
                                                "objection")}
                short = f"{m['name']}: {m.get('final_answer')!r} vs {res.answer} {res.unit}"
                if d.get("failure_type") == "slip" or (m.get("counts_as_solved") and not m.get("answer_matches")):
                    found.append({"what": f"ladder arithmetic slip, {short}", "where": where, "stage": "ladder",
                                  "case": {"input": {"model": m["name"], "stem": qf["stem"], "reference": ref},
                                           "expect": {"matches": True}}})
                if m.get("counts_as_solved") and not m.get("answer_matches"):
                    found.append({"what": f"wrong answer counted as solved, {short}", "where": where,
                                  "stage": "grade", "case": {
                                      "input": {"reference": ref, "member": member, "diagnosis": d},
                                      "expect": {"counts_as_solved": False}}})
    return found


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cmd_list(a):
    for c in load_cases(a.stage):
        print(f"  {c['stage']:<9} {c.get('status', 'open'):<6} {c['id']}  —  {c.get('what_went_wrong', '')[:90]}")


def _cmd_run(a):
    stages = [a.stage] if a.stage else list(OFFLINE + (LIVE if a.live else ()))
    if a.stage in LIVE and not a.live:
        sys.exit(f"{a.stage} calls a model: add --live (it costs API calls)")
    cases = [c for c in load_cases(case_id=a.id) if c["stage"] in stages]
    if not cases:
        print("no cases")
        return
    regressions, still_open, newly_fixed = [], [], []
    for c in cases:
        r = replay(c, a.repeats)
        status = c.get("status", "open")
        mark = "PASS" if r["passed"] else "FAIL"
        rate = f" {r['rate']:.0%}" if c["stage"] in LIVE else ""
        print(f"  {mark}{rate:<5} [{c['stage']}] {c['id']} ({status}): {r['detail'][:200]}")
        if status == "fixed" and not r["passed"]:
            regressions.append(c["id"])
        elif status != "fixed" and r["passed"]:
            newly_fixed.append(c["id"])
        elif status != "fixed":
            still_open.append(c["id"])
    print(f"\n{len(cases)} cases: {len(regressions)} regressed, {len(still_open)} still open, "
          f"{len(newly_fixed)} now pass (mark them: python -m tools.regress mark <id> fixed)")
    if regressions:
        print("REGRESSED: " + ", ".join(regressions))
        sys.exit(1)


def _cmd_candidates(a):
    found = candidates(a.run)
    for i, f in enumerate(found):
        print(f"  [{i}] {f['stage']:<9} {f['what'][:110]}  ({f['where']})")
    if not found:
        print("  nothing that looks wrong (check by hand: a failure only a person can see is not listed)")


def _cmd_save(a):
    found = candidates(a.run)
    f = found[a.n]
    stage = a.stage or f["stage"]
    case = {"id": a.id or _slugify(f"{Path(a.run).stem}-{f['what']}"), "stage": stage, "status": "open",
            "found_in": f["where"], "what_went_wrong": a.note or f["what"], **f["case"]}
    print(f"saved {write_case(case).relative_to(ROOT)} — check its 'expect' before relying on it")


def _cmd_mark(a):
    [c] = load_cases(case_id=a.id) or sys.exit(f"no case {a.id}")
    c["status"] = a.status
    write_case(c)
    print(f"{a.id}: {a.status}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tools.regress", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list")
    s.add_argument("--stage", choices=STAGES)
    s.set_defaults(fn=_cmd_list)
    s = sub.add_parser("run")
    s.add_argument("--stage", choices=STAGES)
    s.add_argument("--id")
    s.add_argument("--live", action="store_true", help="also run model stages (costs API calls)")
    s.add_argument("--repeats", type=int, default=1, help="attempts per live case")
    s.set_defaults(fn=_cmd_run)
    s = sub.add_parser("candidates")
    s.add_argument("run")
    s.set_defaults(fn=_cmd_candidates)
    s = sub.add_parser("save")
    s.add_argument("run")
    s.add_argument("n", type=int)
    s.add_argument("--stage", choices=STAGES)
    s.add_argument("--id")
    s.add_argument("--note")
    s.set_defaults(fn=_cmd_save)
    s = sub.add_parser("mark")
    s.add_argument("id")
    s.add_argument("status", choices=("open", "fixed"))
    s.set_defaults(fn=_cmd_mark)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
