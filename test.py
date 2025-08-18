import subprocess
import json
import re

def query_phi3(message):
    """
    Send the message to Phi3:mini via subprocess and return the raw response.
    """
    prompt = f"""
    You are an incident analysis assistant.
    Task: Analyze the following incident report and return ONLY valid JSON.

    Message: "{message}"

    Output JSON format:
    {{
        "location": "Extracted location or 'Unknown / Outside Lebanon'",
        "incident_type": "Choose one of: accident, shooting, protest, fire, natural_disaster, other",
        "threat_level": "yes or no"
    }}

    Important:
    - If the message contains phrases like "لا تهديد" (no threat), threat_level must be "no".
    - Respond with JSON only, no explanations.
    """
    
    # Run Ollama via subprocess
    result = subprocess.run(
        ["ollama", "run", "phi3:mini"],
        input=prompt.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    return result.stdout.decode("utf-8").strip()


def extract_json(response_text):
    """
    Extract only the first JSON object from the model response,
    correctly handling ```json ... ``` blocks.
    """
    # Try to extract inside ```json ... ``` first
    match = re.search(r"```json\s*(\{.*?\})\s*```", response_text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback: find any { ... } block
    match = re.search(r"\{.*?\}", response_text, flags=re.DOTALL)
    if match:
        return match.group().strip()
    
    return None



def clean_data(data):
    """
    Ensure required fields exist and normalize Arabic text.
    """
    # Default values
    defaults = {
        "location": "Unknown / Outside Lebanon",
        "incident_type": "other",
        "threat_level": "no"
    }

    for key, default in defaults.items():
        if key not in data or not data[key].strip():
            data[key] = default
        else:
            # Normalize Arabic text direction (optional)
            data[key] = data[key].strip()

    # Ensure threat_level is lowercase yes/no
    if data.get("threat_level", "").lower() not in ["yes", "no"]:
        data["threat_level"] = "no"

    return data


if __name__ == "__main__":
    test_message = "وقع إطلاق نار في بيروت ولكن لا تهديد على المدنيين"

    # Query Phi3
    response = query_phi3(test_message)
    print("🔹 Raw Phi3 response:\n", response)

    # Extract JSON from response
    json_text = extract_json(response)
    if json_text:
        try:
            data = json.loads(json_text)
            data = clean_data(data)
            print("✅ Parsed JSON:", data)

            # Save JSON to file
            with open("incident_test.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            print("📂 Result saved to incident_test.json")

        except json.JSONDecodeError:
            print("❌ Extracted text is not valid JSON:\n", json_text)
    else:
        print("❌ No JSON found in the model response")
