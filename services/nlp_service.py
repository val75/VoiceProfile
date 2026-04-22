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
  "skills": [
    {
      "name": "Skill Name",
      "category": "one of: construction, warehouse, food_service, driving, cleaning, retail, admin, maintenance, general_labor, other",
      "years_experience": 3
    }
  ],
  "experience": {
    "total_years": 8,
    "roles": [
      {
        "title": "Job Title",
        "employer": "Company Name",
        "duration": "2 years",
        "description": "Brief description of responsibilities"
      }
    ],
    "summary": "One sentence summary of work background"
  },
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
- Use lowercase for days of the week.
- If the person mentions years of experience for a skill, include years_experience on that skill.
- If specific time ranges are not mentioned, omit time_ranges.
- If information is unclear or not mentioned, omit that field entirely rather than guessing.\
"""


def _build_user_prompt(transcripts: dict) -> str:
    parts = ["Here are the transcripts from a worker's onboarding interview:\n"]
    labels = {
        "name": "Name",
        "skills": "Skills & Abilities",
        "experience": "Work Experience",
        "availability": "Availability",
    }
    for key, label in labels.items():
        text = transcripts.get(key, "")
        if text:
            parts.append(f'{label}: "{text}"')
    parts.append("\nExtract the structured profile data as JSON.")
    return "\n".join(parts)


def _parse_json_response(content: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
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
