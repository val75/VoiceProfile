# app/services/stt_services.py
import requests
from flask import current_app


class SpeechToTextError(Exception):
    pass


def transcribe_audio(file_storage):
    """
        file_storage: werkzeug FileStorage (from request.files)
        returns: transcribed text (str)
    """

    current_app.logger.info(
        f"Calling Whisper at {current_app.config['WHISPER_URL']}"
    )
    whisper_url = current_app.config["WHISPER_URL"]
    api_key = current_app.config["WHISPER_API_KEY"]

    files = {
        "file": (
            file_storage.filename,
            file_storage.stream,
            file_storage.mimetype
        )
    }

    headers = {
        "X-API-Key": api_key
    }

    try:
        response = requests.post(
            whisper_url,
            files=files,
            headers=headers,
            timeout=60,
        )
    except requests.RequestException as e:
        raise SpeechToTextError("Whisper service unreachable") from e

    if response.status_code != 200:
        raise SpeechToTextError(response.text)

    data = response.json()
    return data["text"]
