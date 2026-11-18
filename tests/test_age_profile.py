"""Tests for age_profile: stored ECA range, malcontent detection, OARS preset."""

import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from big_parental_controls.services import age_profile


@pytest.fixture
def profiles(tmp_path: Path) -> Path:
    return tmp_path / "user-profiles.json"


def test_read_stored_range(profiles: Path) -> None:
    profiles.write_text(json.dumps({"lana": {"age_range": "13-15"}}))
    assert age_profile.read_age_range("lana", profiles) == "13-15"


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        json.dumps({}),
        json.dumps({"lana": {}}),
        json.dumps({"lana": {"age_range": "99"}}),
        "[]",
    ],
)
def test_read_falls_back_to_default(profiles: Path, content: str | None) -> None:
    if content is not None:
        profiles.write_text(content)
    assert age_profile.read_age_range("lana", profiles) == age_profile.DEFAULT_RANGE


def test_write_calls_group_helper() -> None:
    done = subprocess.CompletedProcess([], 0)
    with patch.object(age_profile.subprocess, "run", return_value=done) as run:
        assert age_profile.write_age_range("lana", "0-12") is True
    assert run.call_args.args[0][1:] == [
        age_profile.GROUP_HELPER,
        "set-age-profile",
        "lana",
        "0-12",
    ]


def test_write_reports_cancelled_password() -> None:
    cancelled = subprocess.CompletedProcess([], 126)
    with patch.object(age_profile.subprocess, "run", return_value=cancelled):
        assert age_profile.write_age_range("lana", "0-12") is False


def test_write_rejects_unknown_range() -> None:
    with patch.object(age_profile.subprocess, "run") as run:
        assert age_profile.write_age_range("lana", "12") is False
    run.assert_not_called()


def test_malcontent_available(tmp_path: Path) -> None:
    iface = tmp_path / "AppFilter.xml"
    assert age_profile.malcontent_available(iface) is False
    iface.write_text("<node/>")
    assert age_profile.malcontent_available(iface) is True


def test_every_range_has_a_preset_entry() -> None:
    assert set(age_profile.ECA_TO_OARS) == set(age_profile.ECA_RANGES)
    assert age_profile.ECA_TO_OARS["18+"] is None


@pytest.fixture
def presets():
    """Stand-in for malcontent_service, which needs the Malcontent GIR."""
    fake = ModuleType("big_parental_controls.services.malcontent_service")
    fake.OARS_PRESETS = {
        name: {"preset": name} for name in ("child", "preteen", "teen", "young-adult")
    }
    with patch.dict(sys.modules, {fake.__name__: fake}):
        yield fake.OARS_PRESETS


@pytest.mark.parametrize(
    ("age_range", "preset"),
    [("0-12", "preteen"), ("13-15", "teen"), ("16-17", "young-adult"), ("18+", None)],
)
def test_apply_oars_preset(presets, age_range: str, preset: str | None) -> None:
    malcontent = MagicMock()
    assert age_profile.apply_oars_preset(malcontent, 1001, age_range) is True
    expected = presets[preset] if preset else {}
    malcontent.set_app_filter.assert_called_once_with(1001, oars_values=expected)


def test_apply_oars_preset_failure(presets) -> None:
    malcontent = MagicMock()
    malcontent.set_app_filter.side_effect = RuntimeError("AccountsService")
    assert age_profile.apply_oars_preset(malcontent, 1001, "0-12") is False
