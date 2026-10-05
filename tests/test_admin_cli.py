from models.admin import AdminUser


def test_add_admin_cli(app):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["add-admin", "ops@example.com"])
    assert result.exit_code == 0
    assert "ops@example.com" in result.output
    assert AdminUser.query.filter_by(email="ops@example.com").count() == 1


def test_disable_admin_cli(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["add-admin", "ops@example.com"])
    result = runner.invoke(args=["disable-admin", "ops@example.com"])
    assert result.exit_code == 0
    assert AdminUser.query.filter_by(email="ops@example.com").first().is_active is False


def test_list_admins_cli(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["add-admin", "a@example.com"])
    result = runner.invoke(args=["list-admins"])
    assert "a@example.com" in result.output


def test_enable_admin_cli(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["add-admin", "ops@example.com"])
    runner.invoke(args=["disable-admin", "ops@example.com"])
    result = runner.invoke(args=["enable-admin", "ops@example.com"])
    assert result.exit_code == 0
    assert "ops@example.com" in result.output
    assert AdminUser.query.filter_by(email="ops@example.com").first().is_active is True


def test_add_admin_on_disabled_admin_fails_honestly(app):
    runner = app.test_cli_runner()
    runner.invoke(args=["add-admin", "ops@example.com"])
    runner.invoke(args=["disable-admin", "ops@example.com"])
    result = runner.invoke(args=["add-admin", "ops@example.com"])
    assert result.exit_code != 0
    # Click 8.1 writes ClickException to stderr; CliRunner mixes it into output.
    assert "enable-admin" in result.output
    assert AdminUser.query.filter_by(email="ops@example.com").first().is_active is False


def test_disable_admin_not_found_exits_nonzero(app):
    result = app.test_cli_runner().invoke(args=["disable-admin", "nobody@example.com"])
    assert result.exit_code != 0
    assert "No admin found" in result.output


def test_enable_admin_not_found_exits_nonzero(app):
    result = app.test_cli_runner().invoke(args=["enable-admin", "nobody@example.com"])
    assert result.exit_code != 0
    assert "No admin found" in result.output
