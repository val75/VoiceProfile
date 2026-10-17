# app/cli.py
"""Admin CLI: raw voice recordings (`flask recordings ...`) and profile deletion
(`flask profile delete`). Registered in app.py."""
import json
import os

import click
from flask import current_app
from flask.cli import AppGroup

from extensions.database import db
from models.profile import WorkerProfile
from models.recording import VoiceRecording
from services.phone import normalize_phone
from services.profile_service import delete_profile, profile_footprint
from services.recording_service import FilterError, build_filters, search_takes
from services.timezones import as_utc, to_admin_local
from services.webm import with_duration


def _filters_or_fail(**raw) -> dict:
    try:
        return build_filters(**raw)
    except FilterError as e:
        raise click.ClickException(str(e))


def _ext(mime_type: str) -> str:
    for ext in ("webm", "ogg", "mp4"):
        if ext in (mime_type or ""):
            return ext
    return "bin"


recordings_cli = AppGroup("recordings", help="Raw voice recordings (admin only).")


@recordings_cli.command("export")
@click.argument("out_dir", type=click.Path(file_okay=False))
@click.option("--phone", help="Worker phone number (any common format).")
@click.option("--from", "date_from", help="First day, YYYY-MM-DD (ADMIN_TIMEZONE).")
@click.option("--to", "date_to", help="Last day, inclusive, YYYY-MM-DD (ADMIN_TIMEZONE).")
@click.option("--step", type=click.Choice(["story", "availability"]))
@click.option("--accepted-only", is_flag=True, help="Only takes the worker accepted.")
def export_cmd(out_dir, phone, date_from, date_to, step, accepted_only):
    """Write audio files + manifest.jsonl + profiles.jsonl. Contains personal data:
    never commit an export (the repo is public)."""
    filters = _filters_or_fail(phone=phone, date_from=date_from, date_to=date_to, step=step)
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    if os.path.exists(manifest_path):
        raise click.ClickException(f"{manifest_path} already exists; use an empty folder.")
    os.makedirs(out_dir, exist_ok=True)

    takes = search_takes(accepted_only=accepted_only, **filters).all()  # audio deferred
    profiles, total_bytes = {}, 0
    with open(manifest_path, "w", encoding="utf-8") as manifest:
        for t in takes:
            fname = f"{t.id}_{t.step}_a{t.attempt}.{_ext(t.mime_type)}"
            # One take's bytes at a time, without keeping them in the session.
            audio = db.session.query(VoiceRecording.audio).filter(VoiceRecording.id == t.id).scalar()
            audio = with_duration(audio, t.duration_ms)
            with open(os.path.join(out_dir, fname), "wb") as f:
                f.write(audio)
            total_bytes += len(audio)
            profiles[t.profile.id] = t.profile
            manifest.write(json.dumps({
                "id": t.id, "profile_id": t.profile.id, "phone": t.profile.phone_number,
                "step": t.step, "attempt": t.attempt,
                "created_at_utc": as_utc(t.created_at).isoformat(),
                "created_at_local": to_admin_local(t.created_at).isoformat(),
                "mime_type": t.mime_type, "size_bytes": t.size_bytes,
                "duration_ms": t.duration_ms, "status": t.status,
                "transcript": t.transcript, "stt_error": t.stt_error,
                "accepted": t.accepted, "edited_text": t.edited_text,
                "final_text": t.edited_text or t.transcript, "file": fname,
            }, ensure_ascii=False) + "\n")

    with open(os.path.join(out_dir, "profiles.jsonl"), "w", encoding="utf-8") as out:
        for p in profiles.values():
            out.write(json.dumps({
                "profile_id": p.id, "phone": p.phone_number, "name": p.name,
                "onboarding_state": p.onboarding_state,
                "profile_data": p.profile_data if p.onboarding_state == "completed" else None,
            }, ensure_ascii=False) + "\n")

    click.echo(f"Exported {len(takes)} take(s), {total_bytes / 1e6:.1f} MB, "
               f"{len(profiles)} profile(s) -> {out_dir}")


@recordings_cli.command("delete")
@click.option("--phone", help="All takes of this worker (privacy deletion request).")
@click.option("--id", "take_id", type=int, help="One take.")
@click.option("--before", help="All takes recorded before this day, YYYY-MM-DD (ADMIN_TIMEZONE).")
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
def delete_cmd(phone, take_id, before, yes):
    """Permanently delete recordings (exactly one of --phone / --id / --before)."""
    if sum(x is not None for x in (phone, take_id, before)) != 1:
        raise click.ClickException("Give exactly one of --phone, --id, --before.")
    query = VoiceRecording.query
    if phone is not None:
        e164 = _filters_or_fail(phone=phone).get("phone_e164")
        if e164 is None:
            raise click.ClickException("--phone is empty.")
        query = (query.join(WorkerProfile, VoiceRecording.profile_id == WorkerProfile.id)
                 .filter(WorkerProfile.phone_number == e164))
    elif take_id is not None:
        query = query.filter(VoiceRecording.id == take_id)
    else:
        start = _filters_or_fail(date_from=before)["start_utc"]
        if start is None:
            raise click.ClickException("--before is empty.")
        query = query.filter(VoiceRecording.created_at < start)

    rows = query.with_entities(VoiceRecording.id, VoiceRecording.size_bytes).all()
    if not rows:
        click.echo("No matching recordings.")
        return
    mb = sum(size for _, size in rows) / 1e6
    if not yes:
        click.confirm(f"Permanently delete {len(rows)} recording(s), {mb:.1f} MB?", abort=True)
    ids = query.with_entities(VoiceRecording.id).subquery()
    deleted = (VoiceRecording.query.filter(VoiceRecording.id.in_(db.select(ids.c.id)))
               .delete(synchronize_session=False))
    db.session.commit()
    current_app.logger.info("Deleted %d voice recording(s) via CLI", deleted)
    click.echo(f"Deleted {deleted} recording(s).")


profile_cli = AppGroup("profile", help="Worker profiles (admin only).")


@profile_cli.command("delete")
@click.option("--phone", help="Worker phone number (any common format).")
@click.option("--id", "profile_id", type=int, help="Profile id.")
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
def profile_delete_cmd(phone, profile_id, yes):
    """Permanently delete a profile with its reviews, recordings and sign-in rows."""
    if (phone is None) == (profile_id is None):
        raise click.ClickException("Give exactly one of --phone, --id.")
    if phone is not None:
        e164 = normalize_phone(phone)
        if e164 is None:
            raise click.ClickException(f"Not a valid phone number: {phone}")
        profile = WorkerProfile.query.filter_by(phone_number=e164).first()
    else:
        profile = db.session.get(WorkerProfile, profile_id)
    if profile is None:
        raise click.ClickException("No such profile.")

    fp = profile_footprint(profile)
    pid = profile.id
    click.echo(
        f"Profile {pid}: {profile.name or '(no name)'}, {profile.phone_number or '(no phone)'}, "
        f"state={profile.onboarding_state}\n"
        f"  reviews: {fp['reviews']}\n"
        f"  recordings: {fp['recordings']} ({fp['recording_bytes'] / 1e6:.1f} MB)\n"
        f"  sign-in codes: {fp['otp_codes']}, rate-limit rows: {fp['otp_requests']}"
    )
    if not yes:
        click.confirm("Permanently delete this profile and everything listed?", abort=True)
    counts = delete_profile(profile)
    click.echo(f"Deleted profile {pid} ({sum(counts.values())} related row(s)).")
