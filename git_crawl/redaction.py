from __future__ import annotations

import re

_CREDENTIAL_URL_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)([^/@\s]+)@")


def redact_url_credentials(value: str) -> str:
    """Redact userinfo credentials embedded in scheme-based URLs."""
    return _CREDENTIAL_URL_RE.sub(r"\1[REDACTED]@", value)


def redact_text(value: object) -> str:
    """Stringify a value and redact any scheme-based URL credentials inside it."""
    return redact_url_credentials(str(value))
