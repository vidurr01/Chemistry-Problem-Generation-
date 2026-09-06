import json
from typing import Optional


def _fmt_score(s) -> str:
    """Format a solver score for display. Scores may be None when a solver call or
    grade failed (see the blind-solve / unmeasured-gate handling in the entrypoints);
    a None must not crash the '%.0f' formatting used in attempt summaries."""
    return f"{s:.0f}%" if isinstance(s, (int, float)) else "n/a"


class Blackboard:
    def __init__(self, seed: dict, archetype: str, target_profile: dict):
        self.seed = seed
        self.archetype = archetype
        self.target_profile = target_profile
        self.attempts = []

    def record_attempt(
        self,
        problem: str,
        solution: str,
        operators_used: list,
        verifier_result: dict,
        weak_score: float,
        strong_score: float,
    ):
        self.attempts.append({
            "attempt_number": len(self.attempts) + 1,
            "problem": problem,
            "solution": solution,
            "operators_used": operators_used,
            "verifier_verdict": verifier_result.get("verdict"),
            "verifier_feedback": verifier_result.get("feedback_for_generator", ""),
            "difficulty_rating": verifier_result.get("difficulty_rating", "N/A"),
            "weak_score": weak_score,
            "strong_score": strong_score,
        })

    def operators_tried(self) -> list:
        seen = []
        for a in self.attempts:
            for op in a.get("operators_used", []):
                if op not in seen:
                    seen.append(op)
        return seen

    def last_attempt(self) -> Optional[dict]:
        return self.attempts[-1] if self.attempts else None

    def context_summary(self) -> str:
        if not self.attempts:
            return "No previous attempts."
        lines = []
        for a in self.attempts:
            lines.append(
                f"Attempt {a['attempt_number']}: "
                f"Verdict={a['verifier_verdict']} | "
                f"Weak={_fmt_score(a['weak_score'])} | "
                f"Strong={_fmt_score(a['strong_score'])} | "
                f"Operators={a['operators_used']} | "
                f"Feedback='{a['verifier_feedback']}'"
            )
        return "\n".join(lines)

    def history(self) -> list:
        return self.attempts

    def to_dict(self) -> dict:
        return {
            "seed_id": self.seed.get("question_index"),
            "archetype": self.archetype,
            "target_profile": self.target_profile,
            "attempts": self.attempts,
        }
