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
    "schedule": [
      {"day": "monday", "start": "09:00", "end": "17:00"}
    ],
    "shift_preference": "one of: morning, afternoon, evening, night, flexible",
    "notes": "Any additional availability details"
  }
}

Rules:
- Output ONLY the JSON object, no markdown, no explanation, no code fences.
- Create one entry in "work_experience" for each distinct kind of work the person describes.
- If the worker mentions the same kind of work more than once (for example naming it briefly and then describing it in detail), merge those into a single entry — do not duplicate.
- "duration" is how long the person did THAT kind of work, and "duration_unit" is the unit they used. Capture the unit they actually said: "4 months" -> duration 4, duration_unit "months"; "2 years" -> duration 2, duration_unit "years"; "a couple weeks" -> duration 2, duration_unit "weeks".
- "duration" MUST be a whole number. For a fractional length, use the smaller unit so the value stays whole: "a year and a half" -> duration 18, duration_unit "months"; "half a year" -> duration 6, duration_unit "months"; "two and a half years" -> duration 30, duration_unit "months". Never output a fractional duration like 1.5.
- NEVER add up durations across entries: different jobs often overlap in time, so a combined total would be misleading.
- Omit both "duration" and "duration_unit" when no length of time is given for that work.
- For availability, create one entry in "schedule" for each day the worker can work. Use lowercase English day names ("monday" ... "sunday").
- If the worker mentioned specific hours for a day, include "start" and "end" in 24-hour HH:MM format. Convert spoken times: "9am" -> "09:00", "5pm" -> "17:00", "noon" -> "12:00", "midnight" -> "00:00".
- If the worker said the same hours apply to multiple days (e.g. "Friday and Saturday 9am to 5pm"), include the same start/end on EACH of those day entries — do not deduplicate the hours.
- "shift_preference" is only for vague descriptors like "mornings" or "flexible". If you already captured specific start/end hours for the days the worker mentioned, OMIT "shift_preference".
- Omit "schedule" entirely if no days were mentioned at all.
- If information is unclear or not mentioned, omit that field entirely rather than guessing.\
"""


def _build_user_prompt(transcripts: dict) -> str:
    parts = ["Here are the transcripts from a worker's onboarding interview:\n"]
    labels = {
        "name": "Name",
        "story": "Work story",
        "availability": "Availability",
        # Legacy keys from the earlier multi-question flow, kept so older
        # profiles can still be re-extracted from their stored transcripts.
        "skills": "Kinds of work",
        "experience": "How long and where",
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


def extract_profile_data(transcripts: dict, model: str = None, base_url: str = None) -> dict:
    """
    Extract structured profile data from onboarding transcripts using a local LLM.

    Args:
        transcripts: dict like {"name": "...", "story": "...", "availability": "..."}
        model: override the configured LLM_MODEL (e.g. for the eval harness sweeping
            candidate models). Defaults to config["LLM_MODEL"].
        base_url: override the configured LLM_URL to target a different GPU host
            (e.g. Lab/T4 vs Production/DGX-2). Defaults to config["LLM_URL"].

    Returns:
        Structured profile_data dict matching the JSONB schema.

    Raises:
        ExtractionError: If the LLM is unreachable or returns unparseable output after retries.
    """
    config = current_app.config
    client = OpenAI(
        base_url=base_url or config["LLM_URL"],
        api_key="ollama",
    )
    model = model or config["LLM_MODEL"]
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
