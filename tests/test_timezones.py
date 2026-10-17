import logging
from datetime import date, datetime, timezone

import pytest

from app import create_app
from services.timezones import (
    as_utc, local_days_to_utc_range, parse_day, resolve_zone, to_admin_local, zone_is_valid,
)

UTC = timezone.utc


def test_resolve_zone():
    assert resolve_zone(None) is UTC
    assert resolve_zone("") is UTC
    assert resolve_zone("Mars/Base") is UTC
    assert str(resolve_zone("America/Los_Angeles")) == "America/Los_Angeles"
    assert zone_is_valid("America/Los_Angeles") and not zone_is_valid("Mars/Base")


def test_as_utc_treats_naive_as_utc():
    assert as_utc(datetime(2026, 10, 15, 3, 0)) == datetime(2026, 10, 15, 3, 0, tzinfo=UTC)


def test_parse_day():
    assert parse_day("2026-10-14") == date(2026, 10, 14)
    assert parse_day("  ") is None and parse_day(None) is None
    with pytest.raises(ValueError):
        parse_day("14/10/2026")


def test_local_day_range_in_pacific(app):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"  # PDT = UTC-7 on this date
    start, end = local_days_to_utc_range(date(2026, 10, 14), date(2026, 10, 14))
    assert start == datetime(2026, 10, 14, 7, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
    assert local_days_to_utc_range(None, None) == (None, None)


def test_evening_pacific_take_displays_on_its_local_day(app):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    local = to_admin_local(datetime(2026, 10, 15, 3, 0))  # naive UTC, as SQLite returns it
    assert local.strftime("%Y-%m-%d %H:%M") == "2026-10-14 20:00"
    assert to_admin_local(None) is None


def test_utc_when_unset(app):
    app.config["ADMIN_TIMEZONE"] = ""
    assert to_admin_local(datetime(2026, 10, 15, 3, 0)).hour == 3


def _make_app(tz):
    return create_app(test_config={"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite://",
                                   "ADMIN_TIMEZONE": tz})


def test_startup_warns_on_invalid_timezone(caplog):
    with caplog.at_level(logging.WARNING):
        _make_app("Mars/Base")
    assert any("ADMIN_TIMEZONE" in r.getMessage() for r in caplog.records)


def test_no_timezone_warning_when_valid_or_blank(caplog):
    with caplog.at_level(logging.WARNING):
        _make_app("America/Los_Angeles")
        _make_app("")
    assert not any("ADMIN_TIMEZONE" in r.getMessage() for r in caplog.records)
