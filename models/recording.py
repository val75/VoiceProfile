# app/models/recording.py

from datetime import datetime, timezone

from extensions.database import db


class VoiceRecording(db.Model):
    """One raw audio take of an onboarding voice step (story / availability).

    Kept for debugging and for building Whisper / extraction test cases. Admin
    access only — never exposed to the worker. Audio is deferred so listing
    takes never loads the bytes.
    """
    __tablename__ = "voice_recordings"
    __table_args__ = (
        db.UniqueConstraint("profile_id", "step", "attempt", name="uq_voice_recording_take"),
    )

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer, db.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    step = db.Column(db.String(20), nullable=False)
    attempt = db.Column(db.Integer, nullable=False)  # 1-based per (profile, step)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
        index=True,
    )
    audio = db.deferred(db.Column(db.LargeBinary, nullable=False))
    mime_type = db.Column(db.String(100), nullable=False)  # as sent by the browser
    size_bytes = db.Column(db.Integer, nullable=False)
    duration_ms = db.Column(db.Integer)  # browser-reported
    transcript = db.Column(db.Text)      # Whisper output for this take
    stt_error = db.Column(db.Text)       # why transcription failed
    accepted = db.Column(db.Boolean)     # None = undecided, False = re-recorded
    decided_at = db.Column(db.DateTime(timezone=True))
    edited_text = db.Column(db.Text)     # worker's correction, only if it differs

    profile = db.relationship("WorkerProfile")

    @property
    def status(self) -> str:
        if self.transcript is not None:
            return "transcribed"
        if self.stt_error is not None:
            return "failed"
        return "stuck"  # in flight, or the request died before Whisper answered
