"""Calibrate the JEE-level check on real papers (about one cent).

Jev places each real NUMERICAL question of the subject of JEE Main and of JEE Advanced (data/jee_mains,
data/jee_advanced) on qfirst.LEVELS (0 = JEE Main easy ... 4 = JEE Advanced hard), and our own accepted
questions too. The floor is the score that PERCENTILE % of real JEE Advanced questions reach; how many real
JEE Main questions reach it is reported as well, so the check is used only if it separates them. Written
to knowledge/level_calibration_{subject}.json, which the pipeline reads for that subject only (no file: the
level check is off for it; it never borrows another subject's floor).

    python tools/calibrate_level.py                       # physical
    python tools/calibrate_level.py --subject inorganic
"""
import argparse
import glob
import json
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)
from core.pipeline import qfirst  # noqa: E402

TOPIC = {"physical": "Physical", "inorganic": "Inorganic", "organic": "Organic"}   # data's "topic" prefix
PERCENTILE = 20
NUMERIC = {"NAT", "Numerical", "NNI", "PNV", "Integer", "SDI"}


def real(folder: str, subject: str = "physical") -> list:
    out = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", folder, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            j = json.load(fh)
        for q in (j["questions"] if isinstance(j, dict) else j):
            if str(q.get("topic", "")).startswith(TOPIC[subject]) and q.get("question_type") in NUMERIC:
                out.append({"id": q["id"], "text": " ".join(str(q["question_text"]).split())})
    return out


def ours(subject: str = "physical") -> list:
    from subject_config import get_subject_config
    try:
        with open(get_subject_config(subject)["output_file"], encoding="utf-8") as f:
            return [{"id": r["question_id"], "text": r["question"], "label": r.get("difficulty_label")}
                    for r in json.load(f)]
    except OSError:
        return []


def score(items: list) -> list:
    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(lambda it: qfirst.jev_level(it["text"]), items))


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # "≥" crashed a piped run before the file was written
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", choices=sorted(TOPIC), default="physical")
    subject = ap.parse_args().subject
    out_path = os.path.join(ROOT, "knowledge", f"level_calibration_{subject}.json")
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    mains, adv, own = real("jee_mains", subject), real("jee_advanced", subject), ours(subject)
    print(f"Scoring {len(mains)} JEE Main and {len(adv)} JEE Advanced {subject} numerical questions, "
          f"and our {len(own)} accepted ones, with Jev ...")
    sm, sa, so = score(mains), score(adv), score(own)
    m = [x for x in sm if x is not None]
    a = [x for x in sa if x is not None]
    if len(m) < 20 or len(a) < 20:
        sys.exit(f"✗ Jev answered too few ({len(m)} Main, {len(a)} Advanced); nothing written")
    thr = round(pct(a, PERCENTILE), 3)
    main_pass = sum(x >= thr for x in m) / len(m)
    print(f"\nJEE Main      ({len(m)}): median {statistics.median(m):.2f}, range {min(m):.2f}-{max(m):.2f}")
    print(f"JEE Advanced  ({len(a)}): median {statistics.median(a):.2f}, range {min(a):.2f}-{max(a):.2f}")
    print(f"\nfloor {thr:.2f}: {100 - PERCENTILE}% of real Advanced questions reach it, {main_pass:.0%} of real Main do")
    if own:
        print("\nOur accepted questions:")
        for it, x in zip(own, so):
            flag = "" if x is None else ("  ≥ floor" if x >= thr else "  < floor")
            print(f"  {it['id']}  {('?' if x is None else f'{x:.2f}')}{flag}  (pipeline label: {it.get('label')})")
    usable = main_pass <= 0.5
    if not usable:
        print("\n✗ Jev does not separate Main from Advanced well enough here: the check stays OFF (no file written).")
        return
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"subject": subject, "threshold": thr, "percentile": PERCENTILE, "main_pass_rate": round(main_pass, 3),
                   "jev_model": models.JEV_MODEL, "levels": qfirst.LEVELS,
                   "main": [{**it, "score": x} for it, x in zip(mains, sm) if x is not None],
                   "advanced": [{**it, "score": x} for it, x in zip(adv, sa) if x is not None],
                   "ours": [{**it, "score": x} for it, x in zip(own, so)]},
                  f, ensure_ascii=False, indent=1)
    print(f"\nwritten: {os.path.relpath(out_path, ROOT)}  (the level check is now ON)  cost ${models.SPEND.total_cost:.4f}")


if __name__ == "__main__":
    main()
