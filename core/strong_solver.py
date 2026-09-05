import json
import random


STRONG_SCORE_FLOOR = 85  # problem accepted only if strong solver scores >= this


# MOCKED LLM INTERFACE
# Replace with actual strong model (e.g. o3, Claude Opus, GPT-4o with CoT, etc.)
class MockOpenAI:
    class chat:
        class completions:
            @staticmethod
            def create(model, messages, **kwargs):
                class Choice:
                    class Message:
                        def __init__(self, content):
                            self.content = content
                    def __init__(self, content):
                        self.message = self.Message(content)

                mock_response = json.dumps({
                    "attempted_solution": "The product is compound X. Full mechanism: step 1... step 2... (strong solver).",
                    "score": random.randint(55, 98),
                    "reasoning": "Strong solver identified the correct product and mechanism."
                }, indent=2)

                return type("Response", (), {"choices": [Choice(mock_response)]})()


client = MockOpenAI()


def solve_strong(problem: str, solution: str, archetype: str) -> dict:
    """
    Strong solver: higher-capability model (ideally with extended reasoning / CoT).
    Score >= STRONG_SCORE_FLOOR confirms the problem is valid and solvable.
    Score < STRONG_SCORE_FLOOR suggests the problem is broken or unsolvable.
    """
    prompt = f"""
You are an expert organic chemist with deep knowledge of mechanisms, stereochemistry,
and reaction conditions. You have access to extended reasoning — work through the problem
step by step before committing to a final answer.

Problem:
{problem}

Archetype: {archetype}

Solve the problem rigorously. Show full mechanistic reasoning.
Then compare your answer to the reference solution and score yourself 0-100:
- 100: completely correct product, mechanism, and stereochemistry
- 0: completely wrong

Reference Solution (for scoring only — do not use it to answer):
{solution}

Return a JSON object with:
- "attempted_solution": string (your full step-by-step solution)
- "score": integer 0-100
- "reasoning": string explaining the score and any discrepancies found
"""

    response = client.chat.completions.create(
        model="o3",  # placeholder — swap to actual strong/RLM model
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are an expert chemist. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=1.0  # RLMs use temperature=1
    )

    return json.loads(response.choices[0].message.content.strip())
