import json
import os

# MOCKED LLM INTERFACE
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
                
                # Simple heuristic mock logic for demonstration
                content = messages[-1]['content'].lower()
                if "how many" in content or "count" in content:
                    archetype = "Counting/Enumeration"
                elif "mechanism" in content or "explain" in content:
                    archetype = "Deep Mechanistic Reasoning"
                elif "rank" in content or "compare" in content or "stability" in content:
                    archetype = "Comparative Ranking (GOC)"
                else:
                    # Default to long reaction chains for synthesis
                    archetype = "Long Reaction Chains"
                
                # Return the mocked response
                return type('Response', (), {'choices': [Choice(archetype)]})()

# Initialize the mock client (Replace with `from openai import OpenAI; client = OpenAI(api_key="...")` later)
client = MockOpenAI()

def classify_problem(problem_data):
    """
    Classifies a seed problem into one of four archetypes using an LLM.
    """
    prompt = f"""
    You are an expert organic chemist. Classify the following problem into one of these four archetypes:
    1. Long Reaction Chains
    2. Counting/Enumeration
    3. Deep Mechanistic Reasoning
    4. Comparative Ranking (GOC)

    Only output the name of the archetype, nothing else.

    Problem: {problem_data['question']}
    Solution: {problem_data['answer']}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a classification assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )
    
    return response.choices[0].message.content.strip()

def main():
    _here = os.path.dirname(os.path.abspath(__file__))
    input_file  = os.path.join(_here, "..", "data", "seeds", "merged_SEED.json")
    output_file = os.path.join(_here, "..", "data", "seeds", "classified_seeds.json")
    
    print(f"Loading seeds from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        seeds = json.load(f)
        
    print(f"Classifying {len(seeds)} seeds...")
    
    # Process a subset for testing if desired, or all of them
    # For now, we process all of them since it's a fast mock
    classified_seeds = []
    for i, seed in enumerate(seeds):
        archetype = classify_problem(seed)
        
        # Add archetype to the record
        classified_record = seed.copy()
        classified_record['archetype'] = archetype
        classified_seeds.append(classified_record)
        
        if (i + 1) % 50 == 0:
            print(f"Processed {i + 1}/{len(seeds)}")
            
    print(f"Saving classified seeds to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(classified_seeds, f, indent=4)
        
    print("Classification complete!")

if __name__ == "__main__":
    main()
