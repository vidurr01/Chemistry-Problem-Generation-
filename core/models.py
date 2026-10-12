"""
Model roster and the one call helper every pipeline stage uses.

Every role goes through OpenRouter. No model checks output from its own family:
Gemini writes, DeepSeek extracts, the council (OpenAI, Qwen, Z.ai) solves, Claude
diagnoses, Mistral writes the readable solution after acceptance.
"""

from __future__ import annotations

import os
import threading

from core.llm import call_json, load_env, parse_json

load_env()

# ── Roster ───────────────────────────────────────────────────────────────────
GENERATOR = "google/gemini-3.7-flash"                 # picks inputs, writes stems and clarification hints
EXTRACTOR = "deepseek/deepseek-v4-flash-0731"          # chemistry gate: lists the facts a stem states
VERIFIER = "anthropic/claude-haiku-5.5"                # mismatch verifier: reads every council attempt
SOLUTION_WRITER = "mistralai/mistral-small-3.2-24b-instruct"   # readable solution, accepted questions only
COUNCIL = [
    ("gpt-6-luna", "openai/gpt-6-luna"),            # GPQA Diamond 87–90%
    ("qwen3.8-flash", "qwen/qwen3.8-flash"),         # 88.6%
    ("glm-5.3-flash", "z-ai/glm-5.3-flash"),         # 85–91%
]
COUNCIL_REASONING_EFFORT = "medium"
# Early stop: the two cheaper members solve first; the rest are called only when their
# answers could still change the decision (see flow.judge).
COUNCIL_FIRST = ("gpt-6-luna", "glm-5.3-flash")

ROSTER = {"generator": GENERATOR, "extractor": EXTRACTOR, "verifier": VERIFIER,
          "solution_writer": SOLUTION_WRITER, "council": [slug for _, slug in COUNCIL]}


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
        return resp

    return call_json(create, parse_json, label=role)
