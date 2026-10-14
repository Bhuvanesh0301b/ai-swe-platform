import json
import re

def extract_json(raw_text: str) -> dict:
    """
    LLMs sometimes wrap JSON responses in markdown code fences despite
    instructions not to, and sometimes emit literal newline characters inside
    JSON string values (e.g. multi-line code) instead of properly escaping
    them as \\n. This handles both cases gracefully.
    """
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned.strip())
    cleaned = re.sub(r"```$", "", cleaned.strip())
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # strict=False tolerates literal control characters (like raw newlines)
        # inside JSON string values, which is the most common LLM formatting slip.
        return json.loads(cleaned, strict=False)