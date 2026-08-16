"""Phone number normalization to E.164 (what Twilio requires)."""
from typing import Optional

import phonenumbers


def normalize_phone(raw: str, default_region: str = "US") -> Optional[str]:
    """Parse a user-entered phone number to E.164, or return None if invalid.

    Accepts natural input — spaces, dashes, parentheses, a leading national
    trunk zero, `00`/`+` international prefixes — and returns a clean E.164
    string like "+15551234567". `default_region` (ISO code, e.g. "US") is used
    only when the input has no explicit +country-code, so a bare national
    number is interpreted for the right country. Returns None if the number
    isn't parseable or isn't a valid number for its region.
    """
    if not raw:
        return None
    try:
        num = phonenumbers.parse(raw, default_region)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(num):
        return None
    return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
