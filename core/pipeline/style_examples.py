"""
style_examples.py — real JEE Advanced question stems shown to a question writer for WORDING ONLY.

Reviewer's decision, 2026-11-26 (docs/live_review_2026-11-26.md): our questions read unlike JEE Advanced, so the writer
sees a few real stems of the same subject and answer format, to learn how leads, question lines and statements are
phrased. The chemistry is never taken from them: the scheme, compounds and keys come from the engine, and copied()
rejects a draft that repeats a real stem's wording run of COPY_WORDS words. This relaxes the earlier rule "real JEE
content only as a yardstick" for wording only.
"""

from __future__ import annotations

import glob
import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COPY_WORDS = 10          # a shared run this long is copying (stock phrases such as "Choose the correct option(s)"
                         # are shorter)
_TYPES = {"msq": ("MSQ", "MCQ (Multiple Correct)"),
          "mcq_correct": ("MCQ", "MCQ (Single Correct)"),
          "count": ("NAT", "Numerical", "NNI", "SDI"),
          "integer": ("NAT", "Numerical", "NNI", "SDI")}
_TOPIC = {"organic": "Organic", "inorganic": "Inorganic", "physical": "Physical"}
_cache = {}


def _all(subject: str) -> list:
    if subject not in _cache:
        out = []
        for f in sorted(glob.glob(os.path.join(_ROOT, "data", "jee_advanced", "*.json"))):
            try:
                qs = json.load(open(f, encoding="utf-8")).get("questions") or []
            except (OSError, ValueError):
                continue
            for q in qs:
                text = str(q.get("question_text") or "").strip()
                if (_TOPIC[subject] in str(q.get("topic") or "") and len(text) > 60 and "image" not in text.lower()
                        and "[" not in text[:3]):
                    out.append({"type": str(q.get("question_type") or ""), "text": text})
        _cache[subject] = out
    return _cache[subject]


def stems(subject: str, fmt: str, rng, k: int = 3) -> list:
    """k real stems of the subject in the answer format (any format if too few), at most 700 characters each."""
    pool = _all(subject)
    same = [q for q in pool if q["type"] in _TYPES.get(fmt, ())]
    use = same if len(same) >= k else pool
    return [q["text"][:700] for q in rng.sample(use, min(k, len(use)))]


def block(examples: list) -> str:
    """The prompt block: what to take from the examples and what never to take."""
    if not examples:
        return ""
    ex = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(examples))
    return f"""
REAL JEE ADVANCED QUESTIONS — for WORDING AND STYLE ONLY:
{ex}
Write the way these are written: short, plain, impersonal sentences; the question line and the statements in the
form real papers use ("Which of the following statement(s) is(are) correct?", "The correct option(s) is(are)",
"The total number of ... is"); no story, no hints, no explanations in the question. Do NOT take anything else from
them: not their compounds, reactions, data, statements or what they ask. Your chemistry comes only from the design
and scheme above. Do not copy any of their sentences.
"""


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def copied(text: str, examples: list, n: int = COPY_WORDS) -> str | None:
    """The first run of n words the text shares with any example, or None."""
    words = _words(text)
    grams = {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}
    for ex in examples or ():
        w = _words(ex)
        for i in range(len(w) - n + 1):
            g = " ".join(w[i:i + n])
            if g in grams:
                return g
    return None
