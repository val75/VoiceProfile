from config import _parse_admin_emails


def test_parse_admin_emails_basic():
    assert _parse_admin_emails("A@x.com, b@y.com") == {"a@x.com", "b@y.com"}


def test_parse_admin_emails_empty():
    assert _parse_admin_emails("") == set()
    assert _parse_admin_emails(None) == set()


def test_parse_admin_emails_strips_blanks():
    assert _parse_admin_emails("a@x.com, ,,  b@y.com ") == {"a@x.com", "b@y.com"}
