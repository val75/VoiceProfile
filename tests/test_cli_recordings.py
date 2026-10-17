import json
from datetime import datetime, timezone

from models.recording import VoiceRecording
from tests.test_webm_duration import WEBM, _duration


def _run(app, *args, input=None):
    return app.test_cli_runner().invoke(args=["recordings", *args], input=input)


def _lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_export_writes_audio_manifest_and_profiles(app, make_profile, make_take, tmp_path):
    done = make_profile("+14155550100", name="Ana", onboarding_state="completed",
                        profile_data={"summary": "cleaner"})
    busy = make_profile("+14155550199", name="Bo", onboarding_state="availability",
                        profile_data={"summary": "draft"})
    ok = make_take(done, audio=b"AAA", mime_type="audio/webm;codecs=opus", transcript="I clean",
                   edited_text="I clean houses", accepted=True, duration_ms=3000)
    bad = make_take(busy, audio=b"BB", mime_type="audio/mp4", stt_error="boom")
    ok_id, bad_id, done_id, busy_id = ok.id, bad.id, done.id, busy.id
    out = tmp_path / "exp"
    result = _run(app, "export", str(out))
    assert result.exit_code == 0, result.output
    assert (out / f"{ok_id}_story_a1.webm").read_bytes() == b"AAA"
    assert (out / f"{bad_id}_story_a1.mp4").read_bytes() == b"BB"
    rows = {r["id"]: r for r in _lines(out / "manifest.jsonl")}
    assert rows[ok_id]["final_text"] == "I clean houses" and rows[ok_id]["phone"] == "+14155550100"
    assert rows[ok_id]["accepted"] is True and rows[ok_id]["duration_ms"] == 3000
    assert rows[bad_id]["status"] == "failed" and rows[bad_id]["final_text"] is None
    assert rows[ok_id]["created_at_utc"].endswith("+00:00")
    profiles = {r["profile_id"]: r for r in _lines(out / "profiles.jsonl")}
    assert profiles[done_id]["profile_data"] == {"summary": "cleaner"}
    assert profiles[busy_id]["profile_data"] is None
    assert "2 take(s)" in result.output


def test_export_filters(app, make_profile, make_take, tmp_path):
    p = make_profile()
    keep_id = make_take(p, attempt=1, accepted=True).id
    make_take(p, attempt=2, accepted=False)
    out = tmp_path / "exp"
    assert _run(app, "export", str(out), "--accepted-only", "--phone", "4155550100").exit_code == 0
    assert [r["id"] for r in _lines(out / "manifest.jsonl")] == [keep_id]


def test_export_refuses_existing_manifest_and_bad_phone(app, tmp_path):
    out = tmp_path / "exp"
    out.mkdir()
    (out / "manifest.jsonl").write_text("")
    assert _run(app, "export", str(out)).exit_code == 1
    assert _run(app, "export", str(tmp_path / "new"), "--phone", "12").exit_code == 1


def test_delete_needs_exactly_one_selector(app):
    assert _run(app, "delete", "--yes").exit_code == 1
    assert _run(app, "delete", "--id", "1", "--before", "2026-01-01", "--yes").exit_code == 1


def test_delete_by_phone_with_confirmation(app, make_profile, make_take):
    me, other = make_profile("+14155550100"), make_profile("+14155550199")
    make_take(me, attempt=1)
    make_take(me, attempt=2)
    make_take(other)
    aborted = _run(app, "delete", "--phone", "(415) 555-0100", input="n\n")
    assert aborted.exit_code == 1 and VoiceRecording.query.count() == 3
    result = _run(app, "delete", "--phone", "(415) 555-0100", input="y\n")
    assert result.exit_code == 0 and "Deleted 2" in result.output
    assert VoiceRecording.query.count() == 1


def test_delete_by_id_and_before(app, make_profile, make_take):
    p = make_profile()
    old_id = make_take(p, attempt=1, created_at=datetime(2026, 1, 5, tzinfo=timezone.utc)).id
    new_id = make_take(p, attempt=2, created_at=datetime(2026, 10, 5, tzinfo=timezone.utc)).id
    assert _run(app, "delete", "--before", "2026-06-01", "--yes").exit_code == 0
    assert [i for (i,) in VoiceRecording.query.with_entities(VoiceRecording.id)] == [new_id]
    assert _run(app, "delete", "--id", str(new_id), "--yes").exit_code == 0
    assert VoiceRecording.query.count() == 0
    assert "No matching" in _run(app, "delete", "--id", str(old_id), "--yes").output


def test_export_fills_in_webm_duration(app, make_profile, make_take, tmp_path):
    t = make_take(make_profile(), audio=WEBM, mime_type="audio/webm", duration_ms=10416)
    tid = t.id
    out = tmp_path / "exp"
    assert _run(app, "export", str(out)).exit_code == 0
    data = (out / f"{tid}_story_a1.webm").read_bytes()
    assert _duration(data) == 10416.0 and len(data) == len(WEBM)
