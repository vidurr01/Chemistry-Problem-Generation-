"""
The generation pipeline (engine-first, council-measured).

    walk → Blackboard → pick inputs → engine → write stem → chemistry gate → duplicate
    check → council (closed book) → mismatch verifier (all members) → grade in code →
    hints for failed members → accept → readable solution

run_groundup_final.py drives one question per run through core.pipeline.flow.
"""
