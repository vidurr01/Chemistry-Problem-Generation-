import json
from .blackboard import Blackboard


# MOCKED RLM INTERFACE
# Replace with: from openai import OpenAI; client = OpenAI(api_key="...")
# and swap model to "o3" or equivalent RLM
class MockRLM:
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

                if "Long Reaction Chains" in content:
                    result = {
                        "selected_operators": ["add_reaction_step", "semantic_obfuscation"],
                        "specific_constraints": {
                            "add_reaction_step": {"from": "alkene", "to": "epoxide", "reagents": ["mCPBA"]},
                            "semantic_obfuscation": {"style": "lab-manual nomenclature"}
                        },
                        "reasoning": "Long chain archetype: add a step to increase synthetic depth, obfuscate naming to raise interpretive load."
                    }
                elif "Counting" in content or "Enumeration" in content:
                    result = {
                        "selected_operators": ["conceptual_fragility", "distractor_plausibility"],
                        "specific_constraints": {
                            "conceptual_fragility": {"concept": "stereospecific ring opening"},
                            "distractor_plausibility": {"distractor": "competing nucleophiles"}
                        },
                        "reasoning": "Counting archetype: fragile filtering criterion raises difficulty; distractors make wrong counts tempting."
                    }
                elif "Mechanistic" in content:
                    result = {
                        "selected_operators": ["conceptual_fragility", "number_of_exceptions"],
                        "specific_constraints": {
                            "conceptual_fragility": {"concept": "rearrangement during elimination"},
                            "number_of_exceptions": {"exception": "bulky bases favoring Hofmann"}
                        },
                        "reasoning": "Mechanistic archetype: insight-dependent — fragile edge-case concept with atypical reagent behaviour."
                    }
                else:  # Comparative Ranking / GOC
                    result = {
                        "selected_operators": ["expand_comparison_set", "distractor_plausibility"],
                        "specific_constraints": {
                            "expand_comparison_set": {"modification": "add electron withdrawing group"},
                            "distractor_plausibility": {"distractor": "acid-sensitive protecting groups"}
                        },
                        "reasoning": "GOC archetype: expanded comparison set with plausible distractors is the core difficulty lever."
                    }

                return type("Response", (), {"choices": [Choice(json.dumps(result, indent=2))]})()


client = MockRLM()


def reason_over_concept_book(blackboard: Blackboard, concept_book: dict) -> dict:
    """
    RLM reasons over the concept book given the full blackboard state.
    Returns selected operators and exact constraints for the generator.
    """
    context = blackboard.context_summary()
    operators_tried = blackboard.operators_tried()

    prompt = f"""
You are a reasoning model specialising in organic chemistry problem design.

Task: select the best operators from the Concept Book to augment the seed problem
toward the target difficulty profile, given the full history of previous attempts.

Seed Problem: {blackboard.seed['question']}
Archetype: {blackboard.archetype}

Target Difficulty Profile:
{json.dumps(blackboard.target_profile, indent=2)}

Available Operators (Concept Book):
{json.dumps(concept_book, indent=2)}

Operators already used across previous attempts: {operators_tried}

Full Attempt History:
{context}

Reasoning instructions:
1. Work through which operators are valid for this archetype specifically.
2. If an operator caused a verifier rejection, reason about whether to retry it differently
   or avoid it entirely this pass.
3. If weak solver scored too high (problem not hard enough), push harder on interpretive operators.
4. If strong solver scored too low (problem may be unsolvable), prioritise chemical grounding
   over difficulty escalation.
5. Select 1-3 operators. Specify exactly how each should be applied.

Return a JSON object with:
- "selected_operators": list of operator names from the concept book
- "specific_constraints": dict mapping each operator name to exact parameters
- "reasoning": string explaining the selection logic
"""

    response = client.chat.completions.create(
        model="o3",  # RLM — swap to actual model when available
        messages=[
            {"role": "system", "content": "You are a chemistry reasoning model. Output JSON only."},
            {"role": "user", "content": prompt}
        ],
        temperature=1.0
    )

    return json.loads(response.choices[0].message.content.strip())
