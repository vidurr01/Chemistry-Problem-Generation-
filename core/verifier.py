import json
import random


# MOCKED LLM INTERFACE
# Replace with: from openai import OpenAI; client = OpenAI(api_key="...")
# Note from paper: use two different model families (e.g. GPT-4o + Claude) to avoid
# self-enhancement bias when generator and verifier share the same model family.
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

                if random.random() < 0.2:
                    mock_response = json.dumps({
                        "independent_solution": "The product is compound X...",
                        "semantic_flaws": "Proposed stereochemistry is incorrect due to steric hindrance from the bulky substituent.",
                        "verdict": "FAIL",
                        "difficulty_rating": "N/A",
                        "feedback_for_generator": "The proposed stereochemistry is incorrect due to steric hindrance from the bulky substituent. Replace with a less hindered substrate or correct the stereochemical assignment."
                    }, indent=2)
                else:
                    mock_response = json.dumps({
                        "independent_solution": "The product is compound X...",
                        "semantic_flaws": "None found",
                        "verdict": "PASS",
                        "difficulty_rating": random.choice(["Beginner", "Intermediate", "Advanced"]),
                        "feedback_for_generator": ""
                    }, indent=2)

                return type("Response", (), {"choices": [Choice(mock_response)]})()


client = MockOpenAI()


def verify_problem(problem: str, solution: str, archetype: str) -> dict:
    """
    Blind-solver verifier: independently solves the problem, checks semantic validity,
    and rates difficulty within the given archetype.
    """
    prompt = f"""
You are an expert organic chemistry verifier operating as a Blind Solver.

Protocol:
1. Read the problem statement. Do NOT read the candidate solution yet.
2. Solve the problem independently, step by step.
3. Compare your independent solution to the candidate solution.
4. Check for semantic flaws:
   - Functional group incompatibilities
   - Mechanistically infeasible steps
   - Incorrect stereochemical assignments
   - Reagent or condition conflicts
5. Rate difficulty within the {archetype} archetype (Beginner / Intermediate / Advanced).

Candidate Problem:
{problem}

Candidate Solution:
{solution}

Return a JSON object with:
- "independent_solution": string (your solution, derived before reading the candidate)
- "semantic_flaws": string (specific flaws found, or "None found")
- "verdict": "PASS" or "FAIL"
- "difficulty_rating": "Beginner", "Intermediate", or "Advanced" (if PASS, else "N/A")
- "feedback_for_generator": string (specific and actionable if FAIL, else "")
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a chemistry verifier. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )

    return json.loads(response.choices[0].message.content.strip())
