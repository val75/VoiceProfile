# app/services/nlp_service.py

import json
import re
import logging
from datetime import datetime, timezone

from openai import OpenAI, APITimeoutError, APIConnectionError
from flask import current_app

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    """Raised when profile data extraction fails."""
    pass


SYSTEM_PROMPT = """\
You are a structured data extractor. Given voice transcripts from a worker's onboarding interview, \
extract structured profile data as JSON.

Output ONLY valid JSON matching this exact schema (omit any field not mentioned in the transcripts):

{
  "work_experience": [
    {
      "work_type": "Type of work, e.g. Auto mechanic",
      "category": "one of: construction, warehouse, food_service, driving, cleaning, retail, admin, maintenance, general_labor, other",
      "duration": 2,
      "duration_unit": "one of: years, months, weeks",
      "employer": "Company or place, if mentioned",
      "context": "Brief description of what they did, if mentioned"
    }
  ],
  "summary": "One sentence summary of the worker's overall background",
  "availability": {
    "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
    "shift_preference": "one of: morning, afternoon, evening, night, flexible",
    "time_ranges": [
      {"start": "06:00", "end": "14:00"}
    ],
    "notes": "Any additional availability details"
  }
}

Rules:
- Output ONLY the JSON object, no markdown, no explanation, no code fences.
- Create one entry in "work_experience" for each distinct kind of work the person describes.
- A kind of work named in the skills answer and described again in the experience answer is the SAME entry — merge them into one, do not duplicate.
- "duration" is how long the person did THAT kind of work, and "duration_unit" is the unit they used. Capture the unit they actually said: "4 months" -> duration 4, duration_unit "months"; "2 years" -> duration 2, duration_unit "years"; "a couple weeks" -> duration 2, duration_unit "weeks".
- NEVER add up durations across entries: different jobs often overlap in time, so a combined total would be misleading.
- Omit both "duration" and "duration_unit" when no length of time is given for that work.
- Use lowercase for days of the week.
- If specific time ranges are not mentioned, omit time_ranges.
- If information is unclear or not mentioned, omit that field entirely rather than guessing.\
"""


def _build_user_prompt(transcripts: dict) -> str:
    parts = ["Here are the transcripts from a worker's onboarding interview:\n"]
    labels = {
        "name": "Name",
        "skills": "Kinds of work",
        "experience": "How long and where",
        "availability": "Availability",
    }
    for key, label in labels.items():
        text = transcripts.get(key, "")
        if text:
            parts.append(f'{label}: "{text}"')
    parts.append("\nExtract the structured profile data as JSON.")
    return "\n".join(parts)


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences and minor syntax errors."""
    content = content.strip()

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try repairing malformed JSON (missing commas, trailing commas, etc.)
    try:
        from json_repair import repair_json
        return json.loads(repair_json(content))
    except Exception:
        pass

    raise ExtractionError(f"Could not parse JSON from LLM response: {content[:200]}")


def extract_profile_data(transcripts: dict) -> dict:
    """
    Extract structured profile data from onboarding transcripts using a local LLM.

    Args:
        transcripts: dict like {"name": "...", "skills": "...", "experience": "...", "availability": "..."}

    Returns:
        Structured profile_data dict matching the JSONB schema.

    Raises:
        ExtractionError: If the LLM is unreachable or returns unparseable output after retries.
    """
    config = current_app.config
    client = OpenAI(
        base_url=config["LLM_URL"],
        api_key="ollama",
    )
    model = config["LLM_MODEL"]
    timeout = config["LLM_TIMEOUT"]

    user_prompt = _build_user_prompt(transcripts)
    last_error = None

    # One retry on failure
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                timeout=timeout,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            result = _parse_json_response(content)

            # Add metadata
            result["extracted_at"] = datetime.now(timezone.utc).isoformat()
            result["model_used"] = model

            return result

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            logger.warning("LLM request failed (attempt %d): %s", attempt + 1, e)
        except ExtractionError as e:
            last_error = e
            logger.warning("JSON parse failed (attempt %d): %s", attempt + 1, e)
        except Exception as e:
            last_error = e
            logger.error("Unexpected LLM error (attempt %d): %s", attempt + 1, e)

    raise ExtractionError(f"Profile extraction failed after 2 attempts: {last_error}")
