import json
import random


WEAK_SCORE_CEILING = 60  # problem accepted only if weak solver scores <= this


# MOCKED LLM INTERFACE
# Replace with actual weak model (e.g. GPT-4o-mini, Haiku, etc.)
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
                    "attempted_solution": "The product is compound X (weak solver attempt).",
                    "score": random.randint(20, 75),
                    "reasoning": "Weak solver partial attempt — missed stereochemical details."
                }, indent=2)

                return type("Response", (), {"choices": [Choice(mock_response)]})()


client = MockOpenAI()


def solve_weak(problem: str, solution: str, archetype: str) -> dict:
    """
    Weak solver: lower-capability model attempting the problem.
    Score <= WEAK_SCORE_CEILING means the problem is hard enough to accept.
    """
    prompt = f"""
You are a chemistry undergraduate student solving an organic chemistry problem.
You have solid foundational knowledge but may miss edge cases, atypical reagent behaviour,
or subtle stereochemical distinctions.

Problem:
{problem}

Archetype: {archetype}

Attempt to solve the problem as best you can.
Then compare your answer to the reference solution and score yourself 0-100:
- 100: completely correct product, mechanism, and stereochemistry
- 0: completely wrong

Reference Solution (for scoring only — do not use it to answer):
{solution}

Return a JSON object with:
- "attempted_solution": string (your answer before reading the reference)
- "score": integer 0-100
- "reasoning": string explaining where you lost points
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # placeholder — swap to actual weak model
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a chemistry undergraduate. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return json.loads(response.choices[0].message.content.strip())
