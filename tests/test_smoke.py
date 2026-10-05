def test_app_boots(app):
    assert app.config["TESTING"] is True
