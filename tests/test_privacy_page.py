def test_privacy_discloses_recordings(client):
    # Collapse whitespace: the template wraps sentences across lines.
    text = " ".join(client.get("/privacy").get_data(as_text=True).split())
    assert "Voice recordings." in text
    assert "Only authorized ShareGud staff can listen to them." in text
    assert "Copies in our backups are removed within 14 days." in text
