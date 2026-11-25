"""
spend_cap.py: a hard spending limit for offline paid tools (the author, 2026-11-25, after a ₹48 pilot that had been
estimated at ₹5: "you need to consider the price as well").

    from tools.spend_cap import SpendCap
    cap = SpendCap(max_rs=10)          # rupees, at RS_PER_USD
    cap.check("before batch 3")        # raises SpendCapReached once the process has spent the limit

The spend is the process total models.SPEND reports (OpenRouter's own cost figures). Checked BEFORE each paid call,
so a run overshoots by at most one call.
"""

from __future__ import annotations

from core import models

RS_PER_USD = 88.0


class SpendCapReached(RuntimeError):
    pass


class SpendCap:
    def __init__(self, max_rs: float):
        self.max_rs = float(max_rs)

    def spent_rs(self) -> float:
        return float(models.SPEND.summary()["total_cost_usd"]) * RS_PER_USD

    def check(self, where: str = "") -> None:
        s = self.spent_rs()
        if s >= self.max_rs:
            raise SpendCapReached(f"spend ₹{s:.2f} reached the cap ₹{self.max_rs:.2f}"
                                  + (f" ({where})" if where else "") + "; stopped")
