"""
Model roster and the one call helper every pipeline stage uses.

Every role goes through OpenRouter. No model checks output from its own family:
Gemini writes and refines, DeepSeek extracts, the ladder (Meta, Z.ai, OpenAI) solves, Claude
diagnoses, Mistral writes the readable solution after acceptance.
"""

from __future__ import annotations

import os
import threading

from core.llm import call_json, load_env, parse_json

load_env()

# ── Roster ───────────────────────────────────────────────────────────────────
GENERATOR = "google/gemini-3.7-flash"                 # picks inputs, writes stems and clarification hints
REFINER = "google/gemini-3.8-flash"                   # too easy: reads the solvers' working, redesigns inputs or rewrites
EXTRACTOR = "deepseek/deepseek-v4-flash-0731"          # chemistry gate: lists the facts a stem states
VERIFIER = "anthropic/claude-haiku-5.5"                # mismatch verifier: reads every council attempt
SOLUTION_WRITER = "mistralai/mistral-small-3.2-24b-instruct"   # readable solution, accepted questions only
# Difficulty ladder, weakest first (flow.judge). Calibrated on real JEE papers (2026-10-14):
#                       Mains easy/medium  Mains hard  Advanced
#   llama-3.3-70b            fails 29 %     fails 68 %  fails 65 %   <- separates; decides accept
#   glm-5.3-flash            fails 14 %     fails 11 %  fails 29 %   <- difficulty label
#   gpt-6-luna               fails  7 %     fails  0 %  fails  8 %   <- difficulty label
# A question is accepted when the first step fails it; the step that first solves it (or
# none) is its difficulty label. Later steps are called only after the earlier ones fail.
LADDER = [
    ("llama-3.3-70b", "meta-llama/llama-3.3-70b-instruct"),   # Meta
    ("glm-5.3-flash", "z-ai/glm-5.3-flash"),                   # Z.ai
    ("gpt-6-luna", "openai/gpt-6-luna"),                       # OpenAI
]
COUNCIL = LADDER            # the solvers, in ladder order (council_eval.py and older code read COUNCIL)
COUNCIL_REASONING_EFFORT = "medium"
DIFFICULTY_LABELS = {        # first step that solves an accepted question -> its label
    "glm-5.3-flash": "advanced",
    "gpt-6-luna": "hard_advanced",
    None: "frontier",
}

ROSTER = {"generator": GENERATOR, "refiner": REFINER, "extractor": EXTRACTOR, "verifier": VERIFIER,
          "solution_writer": SOLUTION_WRITER, "solution_checker": VERIFIER, "ladder": [slug for _, slug in LADDER]}


def api_key() -> str:
    return os.environ.get("OPENROUTER_KEY", "")


def key_is_set() -> bool:
    k = api_key()
    return bool(k) and "your-openrouter-key-here" not in k


def _client():
    from openai import OpenAI
    return OpenAI(api_key=api_key(), base_url="https://openrouter.ai/api/v1")


# ── Spend tracking ───────────────────────────────────────────────────────────

class Spend:
    """Tokens and cost (USD, as OpenRouter reports it) per role for this process."""

    def __init__(self):
        self._lock = threading.Lock()
        self.by_role: dict = {}

    def add(self, role: str, usage) -> None:
        if usage is None:
            return
        get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
        with self._lock:
            r = self.by_role.setdefault(role, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
            r["calls"] += 1
            r["prompt_tokens"] += get("prompt_tokens") or 0
            r["completion_tokens"] += get("completion_tokens") or 0
            r["cost"] += float(get("cost") or 0.0)

    @property
    def total_cost(self) -> float:
        return sum(r["cost"] for r in self.by_role.values())

    def summary(self) -> dict:
        return {"total_cost_usd": round(self.total_cost, 5), "by_role": self.by_role}


SPEND = Spend()


def ask_json(role: str, model: str, system: str, user: str, *, max_tokens: int = 4000,
             temperature: float = 0.2, reasoning_effort: str | None = None) -> dict:
    """One chat call that must return a JSON object. Transient errors and unusable
    replies are retried (core.llm.call_json); token use and cost go to SPEND[role]."""
    extra = {"usage": {"include": True}}
    if reasoning_effort:
        extra["reasoning"] = {"effort": reasoning_effort}
    holder = {}

    def create():
        resp = _client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
        )
        holder["usage"] = getattr(resp, "usage", None)
        SPEND.add(role, holder["usage"])
        msg = resp.choices[0].message if getattr(resp, "choices", None) else None
        holder["reasoning"] = (getattr(msg, "reasoning", None)
                               or (getattr(msg, "model_extra", None) or {}).get("reasoning")) if msg else None
        return resp

    out = call_json(create, parse_json, label=role)
    if holder.get("reasoning") and isinstance(out, dict):
        out["_reasoning"] = str(holder["reasoning"])        # the model's thinking, when the provider returns it
    return out
