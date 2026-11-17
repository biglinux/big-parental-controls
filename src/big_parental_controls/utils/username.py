"""Login name helpers (no GTK dependency, so they can be unit-tested)."""

import re
import unicodedata

# Same rule as useradd's default: lowercase ASCII, starts with a letter or
# "_", then letters, digits, "_" or "-", 32 characters at most.
LOGIN_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def to_login(text: str) -> str:
    """Valid Linux login derived from what was typed (issue #2).

    "Jéçica" -> "jecica", "Anne Marie" -> "anne-marie": accents removed,
    lowercase, spaces become "-", anything else dropped, 32 chars max.
    Returns "" when nothing usable is left (e.g. "123").
    """
    ascii_text = (
        unicodedata.normalize("NFKD", text.strip())
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    login = re.sub(r"\s+", "-", ascii_text)
    login = re.sub(r"[^a-z0-9_-]", "", login)
    login = login.lstrip("0123456789-")[:32]
    return login if LOGIN_RE.match(login) else ""
