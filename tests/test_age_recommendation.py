"""Tests for "use as recommended settings": current settings -> /etc file."""

import json
import locale
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# The C gettext bindings only exist on Linux; let the tests run elsewhere.
for _name in ("bindtextdomain", "textdomain"):
    if not hasattr(locale, _name):
        setattr(locale, _name, lambda *_args: None)

from big_parental_controls.services import age_defaults, dns_providers  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHARE = REPO / "big-parental-controls/usr/share/big-parental-controls"
HELPER = REPO / "big-parental-controls/usr/lib/big-parental-controls/group-helper"
PROVIDERS = dns_providers.load(SHARE / "dns-providers.json", Path("/nonexistent"))

# Lana's real settings on the test laptop (written by earlier versions)
LANA_LIMITS = {
    "schedule": {
        "ranges": [{"start_hour": 9, "start_min": 0, "end_hour": 21, "end_min": 0}],
        "days": None,
    },
    "daily_minutes": 120,
}
LANA_DNS = {"provider": "custom", "dns1": "86.54.11.12", "dns2": "86.54.11.212"}


@pytest.fixture
def current():
    """Fake time_service / DnsService returning the given user settings."""
    state = {"minutes": 0, "schedule": None, "dns": None}
    time_mod = ModuleType("big_parental_controls.services.time_service")
    time_mod.get_daily_limit = lambda _u: state["minutes"]
    time_mod.get_schedule = lambda _u: state["schedule"]
    dns_mod = ModuleType("big_parental_controls.services.dns_service")
    dns_mod.DnsService = MagicMock()
    dns_mod.DnsService.return_value.get_dns_for_user.side_effect = lambda _uid: state["dns"]
    pkg = sys.modules["big_parental_controls.services"]
    with (
        patch.dict(sys.modules, {time_mod.__name__: time_mod, dns_mod.__name__: dns_mod}),
        patch.object(pkg, "time_service", time_mod, create=True),
        patch.object(dns_providers, "load", return_value=PROVIDERS),
    ):
        yield state


def test_from_current_lana(current) -> None:
    current.update(minutes=120, schedule=LANA_LIMITS["schedule"], dns=LANA_DNS)
    entry, skipped = age_defaults.from_current("lana", 1001)
    assert entry == {
        "daily_minutes": 120,
        "schedule": {"start": "09:00", "end": "21:00"},
        "dns": "dns4eu:strict",  # DNS4EU typed as custom is recognised
    }
    assert skipped == []


def test_from_current_nothing(current) -> None:
    assert age_defaults.from_current("kid", 1002) == ({}, [])


def test_from_current_schedule_not_representable(current) -> None:
    two_ranges = {
        "ranges": [
            {"start_hour": 8, "end_hour": 12},
            {"start_hour": 14, "end_hour": 20},
        ],
        "days": None,
    }
    current.update(schedule=two_ranges)
    assert age_defaults.from_current("kid", 1002) == ({}, ["schedule"])
    current.update(schedule={"ranges": [{"start_hour": 8, "end_hour": 20}], "days": ["monday"]})
    assert age_defaults.from_current("kid", 1002) == ({}, ["schedule"])


def test_from_current_unknown_custom_dns(current) -> None:
    current.update(dns={"provider": "custom", "dns1": "10.0.0.53", "dns2": "10.0.0.54"})
    entry, _skipped = age_defaults.from_current("kid", 1002)
    assert entry == {"dns": {"dns1": "10.0.0.53", "dns2": "10.0.0.54"}}


def _helper_save_script() -> str:
    """The python code group-helper runs for age-defaults-save."""
    text = HELPER.read_text(encoding="utf-8")
    block = text[text.index("    age-defaults-save)") :]
    return re.search(r"<< 'PYEOF'\n(.*?)\nPYEOF", block, re.S).group(1)


def _helper_save(path: Path, age_range: str, entry: object) -> int:
    raw = entry if isinstance(entry, str) else json.dumps(entry)
    return subprocess.run(
        [sys.executable, "-c", _helper_save_script(), str(path), age_range, raw],
        capture_output=True,
        check=False,
    ).returncode


def test_saved_recommendation_is_offered_back(current, tmp_path: Path) -> None:
    """from_current -> group-helper -> load(): Lana's settings come back."""
    current.update(minutes=120, schedule=LANA_LIMITS["schedule"], dns=LANA_DNS)
    entry, _skipped = age_defaults.from_current("lana", 1001)
    local = tmp_path / "age-defaults.json"
    assert _helper_save(local, "0-12", entry) == 0
    loaded = age_defaults.load(SHARE / "age-defaults.json", local, PROVIDERS)
    assert loaded["0-12"] == {
        "daily_minutes": 120,
        "schedule": {"start": "09:00", "end": "21:00"},
        "dns": dns_providers.resolve("dns4eu:strict", PROVIDERS),
    }
    assert loaded["13-15"]["daily_minutes"] == 120  # shipped value, untouched


def test_helper_merges_ranges(tmp_path: Path) -> None:
    local = tmp_path / "age-defaults.json"
    assert _helper_save(local, "0-12", {"daily_minutes": 60}) == 0
    assert _helper_save(local, "13-15", {"dns": "cleanbrowsing:adult"}) == 0
    assert _helper_save(local, "0-12", {"daily_minutes": 90}) == 0
    assert json.loads(local.read_text()) == {
        "0-12": {"daily_minutes": 90},
        "13-15": {"dns": "cleanbrowsing:adult"},
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"daily_minutes": 0},
        {"daily_minutes": "90"},
        {"schedule": {"start": "21:00", "end": "09:00"}},
        {"schedule": {"start": "9:00", "end": "21:00"}},
        {"dns": "evil; rm -rf /"},
        {"dns": {"dns1": "not-an-ip"}},
        {"unknown": 1},
        "not json",
        [],
    ],
)
def test_helper_rejects_invalid(tmp_path: Path, entry: object) -> None:
    local = tmp_path / "age-defaults.json"
    assert _helper_save(local, "0-12", entry) != 0
    assert not local.exists()


def test_save_local_calls_helper() -> None:
    done = subprocess.CompletedProcess([], 0)
    with patch("subprocess.run", return_value=done) as run:
        assert age_defaults.save_local("0-12", {"daily_minutes": 60}) is True
    args = run.call_args.args[0]
    assert args[2:4] == ["age-defaults-save", "0-12"]
    assert json.loads(args[4]) == {"daily_minutes": 60}
    assert age_defaults.save_local("12", {}) is False
