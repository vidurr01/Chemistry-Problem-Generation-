"""
Tier 1 — deterministic duplicate check.

An accepted question is remembered by its exact inputs: the engine steps it was built
from and the value of every given. A new question with the same signature is the
same question again, whatever its wording, so it is refused before the council runs.
Only acceptance writes to the store, so a rejected attempt never blocks a later one.

(Before the engine existed this check hashed the numbers found in the stem and failed
a question whose answer disagreed with an accepted one; with engine-computed answers
that conflict cannot happen, so what is left to catch is the duplicate itself.)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.llm import write_json_atomic

STORE = Path(__file__).resolve().parent.parent / "outputs" / "verifier_seen_inputs.json"


def _canonical(value):
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def signature(subject: str, txs: list, givens: dict) -> str:
    """Hash of (subject, engine steps in order, every given value)."""
    payload = json.dumps({"subject": subject, "txs": list(txs), "givens": _canonical(givens)},
                         sort_keys=True, ensure_ascii=False)
    return "v2:" + hashlib.sha256(payload.encode()).hexdigest()


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def duplicate_of(sig: str, path: Path = STORE):
    """The question id of an accepted question with this signature, or None."""
    for entry in _load(path).get(sig, []):
        if entry.get("question_id"):
            return entry["question_id"]
    return None


def record(sig: str, question_id: str, answer, path: Path = STORE) -> None:
    seen = _load(path)
    seen.setdefault(sig, []).append({"question_id": question_id, "answer": answer})
    write_json_atomic(path, seen, ensure_ascii=False)
