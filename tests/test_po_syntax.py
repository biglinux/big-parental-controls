"""Every .po file must be syntactically valid gettext.

A stray text after a closing quote (as once happened in fr.po) makes
msgfmt fail or drop translations silently.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PO_FILES = sorted(p for p in REPO.rglob("*.po") if ".git" not in p.parts)

_STRING = r'"(?:[^"\\]|\\.)*"'
_VALID = re.compile(
    rf"^(?:#.*|(?:msgctxt|msgid|msgid_plural|msgstr(?:\[\d+\])?)\s+{_STRING}|{_STRING})?\s*$"
)


def test_po_files_found() -> None:
    assert PO_FILES


@pytest.mark.parametrize("po", PO_FILES, ids=lambda p: str(p.relative_to(REPO)))
def test_po_lines_are_valid(po: Path) -> None:
    bad = [
        f"{n}: {line[:80]}"
        for n, line in enumerate(po.read_text(encoding="utf-8").splitlines(), 1)
        if not _VALID.match(line)
    ]
    assert not bad, "\n".join(bad)
