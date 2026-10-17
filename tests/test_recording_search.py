from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect

from services.recording_service import FilterError, build_filters, search_takes

UTC = timezone.utc


def _ids(**raw):
    accepted_only = raw.pop("accepted_only", False)
    return [t.id for t in search_takes(accepted_only=accepted_only, **build_filters(**raw)).all()]


def test_no_filter_is_newest_first(make_profile, make_take):
    p = make_profile()
    a = make_take(p, attempt=1, created_at=datetime(2026, 10, 1, tzinfo=UTC))
    b = make_take(p, attempt=2, created_at=datetime(2026, 10, 2, tzinfo=UTC))
    c = make_take(p, attempt=3, created_at=datetime(2026, 10, 2, tzinfo=UTC))  # tie -> id desc
    assert _ids() == [c.id, b.id, a.id]


def test_phone_is_normalized(make_profile, make_take):
    me, other = make_profile("+14155550100"), make_profile("+14155550199")
    mine = make_take(me)
    make_take(other)
    assert _ids(phone="(415) 555-0100") == [mine.id]
    assert _ids(phone="+1 415 555 0100") == [mine.id]


def test_invalid_phone_raises():
    with pytest.raises(FilterError, match="phone"):
        build_filters(phone="12")


def test_bad_date_and_step_raise(app):
    with pytest.raises(FilterError, match="YYYY-MM-DD"):
        build_filters(date_from="10/14/2026")
    with pytest.raises(FilterError, match="step"):
        build_filters(step="name")


def test_pacific_evening_take_lands_on_local_day(app, make_profile, make_take):
    app.config["ADMIN_TIMEZONE"] = "America/Los_Angeles"
    p = make_profile()
    t = make_take(p, created_at=datetime(2026, 10, 15, 3, 0, tzinfo=UTC))  # 8 pm PDT Oct 14
    assert _ids(date_from="2026-10-14", date_to="2026-10-14") == [t.id]
    assert _ids(date_from="2026-10-15") == []
    assert _ids(date_to="2026-10-13") == []


def test_from_after_to_is_empty_not_error(make_profile, make_take):  # Review Focus 4
    make_take(make_profile())
    assert _ids(date_from="2026-10-20", date_to="2026-10-10") == []


def test_step_and_accepted_only(make_profile, make_take):
    p = make_profile()
    s = make_take(p, step="story", accepted=True)
    make_take(p, step="availability", attempt=1)
    r = make_take(p, step="story", attempt=2, accepted=False)
    assert set(_ids(step="story")) == {s.id, r.id}
    assert _ids(accepted_only=True) == [s.id]


def test_audio_not_loaded_and_profile_eager(make_profile, make_take, session):
    make_take(make_profile())
    session.expunge_all()
    take = search_takes().first()
    assert "audio" not in inspect(take).dict
    assert "profile" in inspect(take).dict


def test_decision_filter(make_profile, make_take):
    p = make_profile()
    yes = make_take(p, attempt=1, accepted=True)
    no = make_take(p, attempt=2, accepted=False)
    open_ = make_take(p, attempt=3)
    assert _ids(decision="accepted") == [yes.id]
    assert _ids(decision="re-recorded") == [no.id]
    assert _ids(decision="undecided") == [open_.id]
    assert len(_ids(decision="")) == 3
    with pytest.raises(FilterError, match="decision"):
        build_filters(decision="maybe")
