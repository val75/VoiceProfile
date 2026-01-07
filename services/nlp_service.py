# app/services/nlp_services.py

def extract_profile_data(text):
    """
        Simple rule-based parser.
    """

    # MVP stub: simple keyword extraction
    data = {"raw_text": text}
    lower = text.lower()

    if "driver" in lower:
        data["job_title"] = "Driver"
    if "uber" in lower:
        data["employer"] = "Uber"
    if "since 2020" in lower or "2020" in lower:
        data["start_year"] = 2020

    data["name"] = "Unnamed Worker"
    return data
