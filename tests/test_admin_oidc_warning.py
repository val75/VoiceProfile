import logging

from app import create_app

_MSG = "Admin login is not configured"


def _make_app(debug, oidc_value):
    return create_app(test_config={
        "TESTING": True,
        "DEBUG": debug,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "OIDC_DISCOVERY_URL": oidc_value,
        "OIDC_CLIENT_ID": oidc_value,
        "OIDC_CLIENT_SECRET": oidc_value,
    })


def _warned(caplog):
    return any(
        r.levelno == logging.WARNING and _MSG in r.getMessage()
        for r in caplog.records
    )


def test_warns_when_oidc_unconfigured_outside_debug(caplog):
    with caplog.at_level(logging.WARNING):
        _make_app(debug=False, oidc_value=None)
    assert _warned(caplog)


def test_no_warning_when_oidc_configured(caplog):
    with caplog.at_level(logging.WARNING):
        _make_app(debug=False, oidc_value="set")
    assert not _warned(caplog)


def test_no_warning_in_debug(caplog):
    with caplog.at_level(logging.WARNING):
        _make_app(debug=True, oidc_value=None)
    assert not _warned(caplog)
