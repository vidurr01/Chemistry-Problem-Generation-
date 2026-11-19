"""Does a model keep to a thinking budget? (well under a cent per model)

Sends one short chemistry task with OpenRouter's reasoning.max_tokens set to BUDGET (the designer's way,
models.ask_json(reasoning_tokens=...)) and reports how many tokens it thought, whether it still returned
the JSON, how long it took and what it cost. A model that ignores the budget thinks until the reply limit
(BUDGET + 800) and comes back cut off with no answer.

    python tools/check_thinking.py moonshotai/kimi-k2.6
    python tools/check_thinking.py moonshotai/kimi-k2.6 google/gemini-3.8-flash --budget 1000
    python tools/check_thinking.py moonshotai/kimi-k2.6 --no-thinking      # thinking switched off
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import models  # noqa: E402  (loads .env)

TASK = ("N2O4(g) <=> 2 NO2(g). 0.10 mol N2O4 is put in a 1.0 L flask at 400 K; at equilibrium the total "
        "pressure is 4.6 atm (R = 0.0821 L atm K^-1 mol^-1). Find the degree of dissociation. "
        'Reply with JSON only: {"alpha": <number>}')


def one(model: str, budget: int, off: bool = False) -> float:
    t = time.time()
    try:
        resp = models._client(models.router(model)).chat.completions.create(
            model=models.route_model(model), messages=[{"role": "user", "content": TASK}], max_tokens=budget + 800, temperature=0.2,
            extra_body={"usage": {"include": True},
                        "reasoning": {"enabled": False} if off else {"max_tokens": budget}})
    except Exception as e:  # noqa: BLE001
        print(f"✗ {model:34} [{models.router(model)}] {type(e).__name__}: {str(e)[:160]}")
        return 0.0
    secs = time.time() - t
    u = resp.usage
    get = (lambda o, k: o.get(k) if isinstance(o, dict) else getattr(o, k, None))
    details = get(u, "completion_tokens_details") or {}
    thought = get(details, "reasoning_tokens")
    out = get(u, "completion_tokens") or 0
    cost = float(get(u, "cost") or get(u, "total_cost") or 0.0)     # airouter: total_cost
    ch = resp.choices[0]
    text = (ch.message.content or "").strip().replace("\n", " ")
    kept = (thought or 0) <= (50 if off else budget * 1.15)
    print(f"{'✓' if kept and ch.finish_reason != 'length' else '✗'} {model:34} [{models.router(model)}] thought {thought} tokens "
          f"(budget {budget}), {out} out in all, finish {ch.finish_reason}, {secs:.0f} s, ${cost:.4f}")
    print(f"   reply: {text[:120] or '(empty)'}")
    return cost


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+")
    ap.add_argument("--budget", type=int, default=1000, help="thinking tokens allowed")
    ap.add_argument("--no-thinking", action="store_true", help="switch thinking off instead")
    args = ap.parse_args()
    if not models.key_is_set():
        sys.exit("✗ OPENROUTER_KEY is not set in .env")
    spent = sum(one(m, args.budget, args.no_thinking) for m in args.models)
    print(f"\n(alpha should be about 0.40)\nSpent: ${spent:.4f}")


if __name__ == "__main__":
    main()
