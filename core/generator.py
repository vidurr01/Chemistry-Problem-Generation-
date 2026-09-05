import json
from .blackboard import Blackboard


# MOCKED LLM INTERFACE
# Replace with: from openai import OpenAI; client = OpenAI(api_key="...")
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

                content = messages[-1]["content"]
                original = "Unknown"
                for line in content.split("\n"):
                    if line.strip().startswith("Seed Problem:"):
                        original = line.replace("Seed Problem:", "").strip()
                        break

                mock_response = json.dumps({
                    "augmented_problem": f"[AUGMENTED] {original} (RLM-selected constraints applied)",
                    "augmented_solution": "[AUGMENTED SOLUTION] Step-by-step solution in standard IUPAC nomenclature.",
                    "operators_applied": ["semantic_obfuscation"],
                    "reasoning": "Applied RLM-selected operators within Concept Book constraints."
                }, indent=2)

                return type("Response", (), {"choices": [Choice(mock_response)]})()


client = MockOpenAI()


def generate_augmented_problem(blackboard: Blackboard, constraints: dict) -> dict:
    """
    Generates (or refines) an augmented problem using RLM-selected constraints.
    On retry passes, the blackboard carries the full prior attempt history so the
    generator refines in place rather than regenerating from scratch.
    """
    last = blackboard.last_attempt()

    if last:
        prior_context = f"""
--- REFINE IN PLACE ---
This is attempt {last['attempt_number'] + 1}. Do NOT start from scratch.
Take the problem below and fix specifically what the verifier and solvers flagged.

Previous Problem:
{last['problem']}

Previous Solution:
{last['solution']}

Verifier Feedback: {last['verifier_feedback']}
Weak Solver Score: {last['weak_score']:.0f}% (target: <=60%)
Strong Solver Score: {last['strong_score']:.0f}% (target: >=85%)

Fix the flagged issue. Keep all other elements of the problem intact.
"""
    else:
        prior_context = ""

    prompt = f"""
You are an expert organic chemistry problem generator.

Seed Problem: {blackboard.seed['question']}
Original Solution: {blackboard.seed['answer']}
Archetype: {blackboard.archetype}

Target Difficulty Profile:
{json.dumps(blackboard.target_profile, indent=2)}

RLM-Selected Operators and Constraints:
{json.dumps(constraints, indent=2)}

{prior_context}

Rules:
- Express all compounds in standard IUPAC nomenclature.
- Apply ONLY the operators specified in the constraints above.
- The augmented problem must remain chemically feasible.
- The solution must be unambiguous and mechanistically complete.

Return a JSON object with:
- "augmented_problem": string
- "augmented_solution": string
- "operators_applied": list of operator names actually used
- "reasoning": string describing what was changed and why
"""

    response = client.chat.completions.create(
        model="gpt-4o",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a chemistry problem generator. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )

    return json.loads(response.choices[0].message.content.strip())
