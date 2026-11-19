"""Checks the OpenRouter key and every model the pipeline uses, with one tiny call each
(about a cent in all). Prints OK or the error per model, and the total spent.

    python tools/check_models.py
    python tools/check_models.py --jev          # only Jev's three question types
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import models  # noqa: E402  (loads .env)


def main() -> int:
    if not models.key_is_set():
        print("✗ no API key in .env (OPENROUTER_KEY, or AIROUTER_KEY for airouter.in)")
        return 1
    print(f"routers: OpenRouter {'yes' if models._has('openrouter') else 'no'}, airouter "
          f"{'yes' if models._has('airouter') else 'no'} (OpenRouter first; airouter once it runs out)\n")
    checks = [
        ("writer", models.GENERATOR),
        ("designer", models.DESIGNER),
        ("coder", models.CODER),
        *[("coder fallback", m) for m in models.CODER_FALLBACKS],
        *([("coder (last try)", models.CODER_STRONG)] if models.CODER_STRONG else []),
        ("solution checker", models.SOLUTION_CHECKER),
        ("solution writer", models.SOLUTION_WRITER),
        *[(f"ladder: {name}", slug) for name, slug in models.LADDER],
        ("refiner (old flow)", models.REFINER),
        ("extractor (gate)", models.EXTRACTOR),
    ]
    seen, failed = set(), 0
    if "--jev" in sys.argv:
        checks = []
    for role, model in checks:
        if model in seen:
            continue
        seen.add(model)
        t = time.time()
        before = models.SPEND.by_role.get("key_check", {}).get("completion_tokens", 0)
        try:
            out = models.ask_json("key_check", model, "Output JSON only.",
                                  'Reply with exactly {"ok": true}', max_tokens=400, temperature=0.0)
            ok = out.get("ok") is True
            used = models.SPEND.by_role.get("key_check", {}).get("completion_tokens", 0) - before
            out.pop("_reasoning", None)
            # a reply of ~5 tokens that took long is the router's delay; hundreds of tokens is hidden thinking
            print(f"{'✓' if ok else '?'} {role:22} {models.router(model)[:2] + ' ' + models.route_model(model):40} {time.time() - t:5.1f}s  "
                  f"{used:>4} tokens out  reply {out}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"✗ {role:22} {model:40} {type(e).__name__}: {str(e)[:160]}")
    t = time.time()
    try:
        from core.pipeline import refine
        p = refine.jev_decide({"text": "Water boils at 100 °C at 1 atm."},
                              {"true": "Is the statement true?"}, role="key_check")
        print(f"✓ {'Jev (refine, checks)':22} {models.JEV_MODEL:40} {time.time() - t:5.1f}s  P(true) = {p.get('true')}")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"✗ {'Jev (refine, checks)':22} {models.JEV_MODEL:40} {type(e).__name__}: {str(e)[:160]}")
    t = time.time()
    try:
        from core.pipeline import refine
        c = refine.jev_choose({"text": "2 H2 + O2 -> 2 H2O"}, "What kind of reaction is this?",
                              {"combustion": "a substance burns in oxygen", "neutralisation": "an acid meets a base",
                               "decomposition": "one substance breaks into several"}, role="key_check")
        print(f"✓ {'Jev choice (refinement)':22} {models.JEV_MODEL:40} {time.time() - t:5.1f}s  "
              f"{c['choice']} ({c['confidence']:.0%})")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"✗ {'Jev choice (refinement)':22} {models.JEV_MODEL:40} {type(e).__name__}: {str(e)[:160]}")
    t = time.time()
    try:
        from core.pipeline import refine
        from core.pipeline import qfirst
        sc = refine.jev_score({"exam_question": "Find the number of moles in 18 g of water."},
                              qfirst.LEVEL_INSTRUCTIONS, qfirst.LEVELS, role="key_check")
        print(f"✓ {'Jev score (level)':22} {models.JEV_MODEL:40} {time.time() - t:5.1f}s  level {sc['score']:.2f}")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"✗ {'Jev score (level)':22} {models.JEV_MODEL:40} {type(e).__name__}: {str(e)[:160]}")
    print(f"\nSpent: ${models.SPEND.total_cost:.4f}")
    print("All models answered." if not failed else f"{failed} model(s) failed: see ✗ above.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
