"""
Fact questions — MCQ / MSQ built entirely by code.

Facts that are not computations (colloid types, defects, which indicator, ...) are kept
as data in two shapes:

    Category   items and the category each belongs to, e.g. defect -> how density changes.
               True statements pair an item with its own category; false ones swap in
               another item's category.
    Pool       hand-written statements, each true or false (minimal true/false pairs).

A question is four statements from one table or pool, labelled (A)-(D):
    "msq"            one or more correct — answer: every true letter
    "mcq_correct"    exactly one true statement — answer: its letter
    "mcq_incorrect"  exactly one false statement — answer: its letter
The answer key is the set of letters, so grading is exact and needs no model. Each wrong
choice is a trap ("marks a false statement as true").
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from core.engine.base import EngineError

LETTERS = "ABCD"
MODES = ("msq", "mcq_correct", "mcq_incorrect")


@dataclass(frozen=True)
class Category:
    id: str
    tx: tuple                   # concept-book entries it covers
    topic: str                  # chapter
    title: str                  # what the table is about, for the question lead-in
    template: str               # statement with {item} and {value}
    rows: tuple                 # (item, value) pairs
    distractors: tuple = ()     # extra values that belong to no item (for false statements)

    def statements(self):
        """Every true statement and, per item, every false one."""
        values = sorted({v for _, v in self.rows} | set(self.distractors))
        true, false = [], []
        for item, value in self.rows:
            true.append((self.template.format(item=item, value=value), True, item))
            for other in values:
                if other != value and not any(i == item and v == other for i, v in self.rows):
                    false.append((self.template.format(item=item, value=other), False, item))
        return true, false


@dataclass(frozen=True)
class Pool:
    id: str
    tx: tuple
    topic: str
    title: str
    true: tuple                 # true statements
    false: tuple                # false statements

    def statements(self):
        return [(s, True, s) for s in self.true], [(s, False, s) for s in self.false]


@dataclass
class FactQuestion:
    source: str                 # table / pool id
    tx: tuple
    topic: str
    mode: str
    lead: str                   # the question sentence
    options: list               # four statement texts, in letter order
    truth: list                 # bool per option
    answer: str                 # letters, e.g. "AC"
    traps: list = field(default_factory=list)

    @property
    def option_lines(self):
        return [f"({LETTERS[i]}) {o}" for i, o in enumerate(self.options)]


def _lead(mode, title):
    if mode == "msq":
        return f"Which of the following statements about {title} is/are correct? (One or more options may be correct.)"
    if mode == "mcq_correct":
        return f"Which one of the following statements about {title} is correct?"
    return f"Which one of the following statements about {title} is NOT correct?"


def build(source, mode: str, rng: random.Random, avoid: set = frozenset()) -> FactQuestion:
    """Four statements from `source`, one per item where possible, mixed by `mode`."""
    if mode not in MODES:
        raise ValueError(mode)
    true, false = source.statements()
    true = [s for s in true if s[0] not in avoid]
    false = [s for s in false if s[0] not in avoid]
    if mode == "msq":
        n_true = rng.randint(1, 3) if len(true) >= 3 else rng.randint(1, max(1, len(true)))
    elif mode == "mcq_correct":
        n_true = 1
    else:
        n_true = 3
    n_false = 4 - n_true
    if len(true) < n_true or len(false) < n_false:
        raise EngineError(f"{source.id}: not enough statements for {mode}")
    picked, items = [], set()

    def take(pool, n):
        rng.shuffle(pool)
        got = 0
        for s in pool:           # prefer statements about different items
            if got == n:
                break
            if s[2] in items:
                continue
            picked.append(s)
            items.add(s[2])
            got += 1
        for s in pool:           # top up if items ran out
            if got == n:
                break
            if s not in picked:
                picked.append(s)
                got += 1
        if got < n:
            raise EngineError(f"{source.id}: not enough distinct statements")

    take(list(true), n_true)
    take(list(false), n_false)
    rng.shuffle(picked)
    options = [s[0] for s in picked]
    truth = [s[1] for s in picked]
    if mode == "mcq_incorrect":
        answer = "".join(LETTERS[i] for i, t in enumerate(truth) if not t)
    else:
        answer = "".join(LETTERS[i] for i, t in enumerate(truth) if t)
    traps = []
    for i, t in enumerate(truth):
        letter = LETTERS[i]
        if mode == "mcq_incorrect":
            if t:
                traps.append({"id": f"{source.id}:{letter}", "desc": f"thinks a correct statement ({letter}) is wrong",
                              "wrong_answer": letter})
        elif not t:
            traps.append({"id": f"{source.id}:{letter}", "desc": f"accepts a false statement ({letter})",
                          "wrong_answer": "".join(sorted(set(answer) | {letter})) if mode == "msq" else letter})
    return FactQuestion(source=source.id, tx=tuple(source.tx), topic=source.topic, mode=mode,
                        lead=_lead(mode, source.title), options=options, truth=truth, answer=answer, traps=traps)


def letters_of(text) -> str:
    """'A and C', '(a), (c)', 'AC', 'Options A, C' -> 'AC'; '' if no letter A-D is found."""
    s = str(text or "").upper()
    s = re.sub(r"\bOPTIONS?\b", " ", s)
    found = re.findall(r"(?<![A-Z])([A-D])(?![A-Z])", s)
    if not found and re.fullmatch(r"\s*[A-D]{1,4}\s*", s):
        found = list(s.strip())
    return "".join(sorted(set(found)))
