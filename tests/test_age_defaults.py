"""Tests for age_defaults: file loading, /etc override, validation, apply."""

import json
import locale
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# The C gettext bindings only exist on Linux; let the tests run elsewhere.
for _name in ("bindtextdomain", "textdomain"):
    if not hasattr(locale, _name):
        setattr(locale, _name, lambda *_args: None)

from big_parental_controls.services import age_defaults  # noqa: E402
from big_parental_controls.services.age_profile import ECA_RANGES  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "big-parental-controls/usr/share/big-parental-controls/age-defaults.json"


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_file_is_valid() -> None:
    raw = json.loads(SHIPPED.read_text(encoding="utf-8"))
    loaded = age_defaults.load(SHIPPED, Path("/nonexistent"))
    assert set(raw) == set(ECA_RANGES)
    # Every shipped setting survives validation (no silent typo).
    assert {r: loaded[r] for r in raw} == raw


def test_missing_files_give_empty_ranges(tmp_path: Path) -> None:
    loaded = age_defaults.load(tmp_path / "a.json", tmp_path / "b.json")
    assert loaded == {r: {} for r in ECA_RANGES}


def test_local_range_replaces_shipped_range(tmp_path: Path) -> None:
    shipped = _write(
        tmp_path / "s.json",
        {"0-12": {"daily_minutes": 90, "dns": "cleanbrowsing"}, "13-15": {"daily_minutes": 120}},
    )
    local = _write(tmp_path / "l.json", {"0-12": {"daily_minutes": 60}})
    loaded = age_defaults.load(shipped, local)
    assert loaded["0-12"] == {"daily_minutes": 60}  # whole range replaced
    assert loaded["13-15"] == {"daily_minutes": 120}  # untouched


def test_broken_local_file_is_ignored(tmp_path: Path) -> None:
    shipped = _write(tmp_path / "s.json", {"0-12": {"daily_minutes": 90}})
    local = tmp_path / "l.json"
    local.write_text("{not json", encoding="utf-8")
    assert age_defaults.load(shipped, local)["0-12"] == {"daily_minutes": 90}


@pytest.mark.parametrize(
    "entry",
    [
        {"daily_minutes": 0},
        {"daily_minutes": 2000},
        {"daily_minutes": "90"},
        {"daily_minutes": True},
        {"schedule": {"start": "20:00", "end": "08:00"}},
        {"schedule": {"start": "8:00", "end": "20:00"}},
        {"schedule": {"start": "08:00"}},
        {"dns": "unknown-provider"},
        "not a dict",
    ],
)
def test_invalid_settings_are_dropped(tmp_path: Path, entry: object) -> None:
    shipped = _write(tmp_path / "s.json", {"0-12": entry})
    assert age_defaults.load(shipped, tmp_path / "none.json")["0-12"] == {}


@pytest.mark.parametrize(
    ("minutes", "text"), [(45, "45 min"), (60, "1 h"), (90, "1 h 30"), (125, "2 h 05")]
)
def test_format_minutes(minutes: int, text: str) -> None:
    assert age_defaults.format_minutes(minutes) == text


def test_describe_lists_each_setting() -> None:
    entry = {
        "daily_minutes": 90,
        "schedule": {"start": "08:00", "end": "20:00"},
        "dns": "cloudflare",
    }
    lines = age_defaults.describe(entry)
    assert len(lines) == 3
    assert "1 h 30" in lines[0]
    assert "08:00" in lines[1] and "20:00" in lines[1]
    assert "Cloudflare" in lines[2]
    assert age_defaults.describe({}) == []


@pytest.fixture
def services():
    """Fake time_service and dns_service (they need pkexec and GIR)."""
    time_service = MagicMock()
    time_service.set_schedule.return_value = True
    dns = MagicMock()
    dns.DnsService.return_value.set_dns_for_user.return_value = True
    pkg = sys.modules["big_parental_controls.services"]
    time_mod = ModuleType("big_parental_controls.services.time_service")
    time_mod.set_daily_limit = time_service.set_daily_limit
    time_mod.set_schedule = time_service.set_schedule
    dns_mod = ModuleType("big_parental_controls.services.dns_service")
    dns_mod.DnsService = dns.DnsService
    with (
        patch.dict(sys.modules, {time_mod.__name__: time_mod, dns_mod.__name__: dns_mod}),
        patch.object(pkg, "time_service", time_mod, create=True),
    ):
        yield time_service, dns.DnsService.return_value


def test_apply_all_settings(services) -> None:
    time_service, dns = services
    entry = {
        "daily_minutes": 90,
        "schedule": {"start": "08:30", "end": "20:00"},
        "dns": "cleanbrowsing",
    }
    assert age_defaults.apply("lana", 1001, entry) == []
    time_service.set_daily_limit.assert_called_once_with("lana", 90)
    time_service.set_schedule.assert_called_once_with(
        "lana", [{"start_hour": 8, "start_min": 30, "end_hour": 20, "end_min": 0}]
    )
    dns.set_dns_for_user.assert_called_once_with(1001, "cleanbrowsing")


def test_apply_only_given_settings(services) -> None:
    time_service, dns = services
    assert age_defaults.apply("lana", 1001, {"daily_minutes": 60}) == []
    time_service.set_schedule.assert_not_called()
    dns.set_dns_for_user.assert_not_called()


def test_apply_reports_failures(services) -> None:
    time_service, dns = services
    time_service.set_daily_limit.side_effect = RuntimeError("pkexec cancelled")
    dns.set_dns_for_user.return_value = False
    entry = {
        "daily_minutes": 90,
        "schedule": {"start": "08:00", "end": "20:00"},
        "dns": "cloudflare",
    }
    assert age_defaults.apply("lana", 1001, entry) == ["daily_minutes", "dns"]
