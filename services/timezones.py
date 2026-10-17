"""Admin-facing time zone helpers. Stored times are always UTC."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import current_app


def resolve_zone(name: Optional[str]):
    """ZoneInfo for an IANA name; UTC when blank or unknown."""
    if not name:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def zone_is_valid(name: str) -> bool:
    return resolve_zone(name) is not timezone.utc


def admin_zone():
    return resolve_zone(current_app.config.get("ADMIN_TIMEZONE"))


def as_utc(dt: datetime) -> datetime:
    """A naive value (SQLite) is UTC; an aware one is converted to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_admin_local(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else as_utc(dt).astimezone(admin_zone())


def parse_day(value: Optional[str]) -> Optional[date]:
    """YYYY-MM-DD -> date; blank -> None; anything else raises ValueError."""
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def local_days_to_utc_range(
    day_from: Optional[date], day_to: Optional[date]
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """[start of day_from, start of the day after day_to) in the admin zone, as UTC."""
    zone = admin_zone()
    start = end = None
    if day_from:
        start = datetime.combine(day_from, time.min, tzinfo=zone).astimezone(timezone.utc)
    if day_to:
        end = datetime.combine(day_to + timedelta(days=1), time.min,
                               tzinfo=zone).astimezone(timezone.utc)
    return start, end
