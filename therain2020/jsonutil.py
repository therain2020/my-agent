"""Safe JSON extraction from LLM response text.

Replaces the fragile `text[text.find("{"):text.rfind("}")+1]` pattern
that appeared in 6 places across the old codebase.
"""

import json
import re


def safe_parse_json(text: str) -> dict | list:
    """Extract the first complete JSON object or array from LLM response text.

    Handles markdown code blocks, leading/trailing text, and nested
    braces/brackets by counting depth. Raises ValueError if no valid
    JSON is found.
    """
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = text.strip()
    if not text:
        raise ValueError("Empty input")

    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == start_char:
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])

    raise ValueError(f"No valid JSON found in: {text[:200]}...")
