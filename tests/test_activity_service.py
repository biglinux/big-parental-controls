"""Tests for the activity_service module."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from big_parental_controls.services.activity_service import (
    ActivityService,
    AppUsageEntry,
    SessionEntry,
)


@pytest.fixture
def service() -> ActivityService:
    return ActivityService()


class TestParseLastLine:
    """Tests for _parse_last_line parsing."""

    def test_normal_session(self, service: ActivityService) -> None:
        line = (
            "rafael   tty5                          "
            "2026-03-17T03:58:54-03:00 - 2026-03-17T04:09:59-03:00  (00:11)"
        )
        entry = service._parse_last_line(line, "rafael")
        assert entry is not None
        assert entry.duration_minutes == 11
        assert entry.tty == "tty5"
        # On systems with a display manager (sddm/gdm), ttyN → "wayland"
        assert entry.session_type in ("tty", "wayland")

    def test_still_logged_in(self, service: ActivityService) -> None:
        line = (
            "bruno    tty2                          "
            "2026-03-17T17:55:53-03:00   still logged in"
        )
        entry = service._parse_last_line(line, "bruno")
        assert entry is not None
        assert entry.end is None
        assert entry.duration_minutes > 0

    def test_crash_session(self, service: ActivityService) -> None:
        line = (
            "bruno    tty3                          "
            "2026-03-17T06:32:28-03:00 - crash                    (11:18)"
        )
        entry = service._parse_last_line(line, "bruno")
        assert entry is not None
        assert entry.duration_minutes == 678  # 11h18m

    def test_pts_with_display(self, service: ActivityService) -> None:
        line = (
            "bruno    pts/0        :0               "
            "2026-03-17T04:28:32-03:00 - 2026-03-17T06:32:17-03:00  (02:03)"
        )
        entry = service._parse_last_line(line, "bruno")
        assert entry is not None
        assert entry.session_type == "wayland"
        assert entry.duration_minutes == 123

    def test_wrong_username_returns_none(self, service: ActivityService) -> None:
        line = (
            "rafael   tty5                          "
            "2026-03-17T03:58:54-03:00 - 2026-03-17T04:09:59-03:00  (00:11)"
        )
        assert service._parse_last_line(line, "bruno") is None

    def test_reboot_line_ignored(self, service: ActivityService) -> None:
        line = "reboot   system boot  6.18.12-1-MANJA* 2026-03-17T04:26:35-03:00   still running"
        assert service._parse_last_line(line, "reboot") is None

    def test_empty_line(self, service: ActivityService) -> None:
        assert service._parse_last_line("", "bruno") is None

    def test_remote_session(self, service: ActivityService) -> None:
        line = (
            "bruno    pts/1        192.168.1.41     "
            "2026-03-17T18:08:34-03:00 - 2026-03-17T18:08:34-03:00  (00:00)"
        )
        entry = service._parse_last_line(line, "bruno")
        assert entry is not None
        assert entry.session_type == "remote"


class TestAggregatDaily:
    """Tests for daily aggregation."""

    def test_empty_sessions(self, service: ActivityService) -> None:
        result = service._aggregate_daily([], 7)
        assert len(result) == 7
        assert all(v == 0 for v in result.values())

    def test_aggregates_by_day(self, service: ActivityService) -> None:
        now = datetime.now(tz=timezone(timedelta(hours=-3)))
        sessions = [
            SessionEntry(
                start=now - timedelta(hours=2),
                end=now - timedelta(hours=1),
                duration_minutes=60,
                tty="tty2",
                session_type="tty",
            ),
            SessionEntry(
                start=now - timedelta(hours=4),
                end=now - timedelta(hours=3),
                duration_minutes=60,
                tty="tty2",
                session_type="tty",
            ),
        ]
        result = service._aggregate_daily(sessions, 7)
        today_key = now.date().isoformat()
        assert result[today_key] == 120


class TestAggregateHourly:
    """Tests for hourly distribution."""

    def test_empty_sessions(self, service: ActivityService) -> None:
        result = service._aggregate_hourly([])
        assert len(result) == 24
        assert sum(result) == 0

    def test_single_hour_session(self, service: ActivityService) -> None:
        tz = timezone(timedelta(hours=-3))
        start = datetime(2026, 3, 17, 10, 0, tzinfo=tz)
        end = datetime(2026, 3, 17, 10, 30, tzinfo=tz)
        sessions = [
            SessionEntry(
                start=start, end=end,
                duration_minutes=30, tty="tty2", session_type="tty",
            )
        ]
        result = service._aggregate_hourly(sessions)
        assert result[10] == 30
        assert sum(result) == 30

    def test_multi_hour_session(self, service: ActivityService) -> None:
        tz = timezone(timedelta(hours=-3))
        start = datetime(2026, 3, 17, 9, 30, tzinfo=tz)
        end = datetime(2026, 3, 17, 11, 30, tzinfo=tz)
        sessions = [
            SessionEntry(
                start=start, end=end,
                duration_minutes=120, tty="tty2", session_type="tty",
            )
        ]
        result = service._aggregate_hourly(sessions)
        assert result[9] == 30   # 30 min remaining in hour 9
        assert result[10] == 60  # full hour 10
        assert result[11] == 30  # 30 min in hour 11
        assert sum(result) == 120


class TestExtractDuration:
    """Tests for duration regex extraction."""

    def test_simple_duration(self) -> None:
        line = "rafael   tty5  2026-03-17T03:58:54-03:00 - 2026-03-17T04:09:59-03:00  (00:11)"
        assert ActivityService._extract_duration_from_line(line) == 11

    def test_multi_hour_duration(self) -> None:
        line = "bruno    tty3  2026-03-17T06:32:28-03:00 - crash  (11:18)"
        assert ActivityService._extract_duration_from_line(line) == 678

    def test_days_plus_hours(self) -> None:
        line = "user     tty2  2026-03-01T00:00-03:00 - 2026-03-03T12:00-03:00  (2+12:00)"
        assert ActivityService._extract_duration_from_line(line) == 2 * 1440 + 720

    def test_no_duration(self) -> None:
        line = "bruno    tty2  2026-03-17T17:55:53-03:00   still logged in"
        assert ActivityService._extract_duration_from_line(line) == 0


class TestAppUsage:
    """Tests for per-application usage tracking."""

    def test_load_snapshot_file_valid(self, tmp_path: object) -> None:
        data = {
            "date": "2026-03-17",
            "snapshots": [
                {"t": "10:00", "p": ["firefox", "code"]},
                {"t": "10:01", "p": ["firefox"]},
                {"t": "10:02", "p": ["firefox", "nautilus"]},
            ],
        }
        path = str(tmp_path / "2026-03-17.json")
        with open(path, "w") as f:
            json.dump(data, f)

        result = ActivityService._load_snapshot_file(path)
        assert len(result) == 3
        assert result[0] == ["firefox", "code"]
        assert result[1] == ["firefox"]

    def test_load_snapshot_file_missing(self) -> None:
        result = ActivityService._load_snapshot_file("/nonexistent/file.json")
        assert result == []

    def test_load_snapshot_file_corrupt(self, tmp_path: object) -> None:
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not json{{{")
        result = ActivityService._load_snapshot_file(path)
        assert result == []

    def test_get_day_app_usage(self, tmp_path: object, monkeypatch: object) -> None:
        from big_parental_controls.core import constants
        monkeypatch.setattr(constants, "ACTIVITY_DIR", str(tmp_path))

        # Also patch the import in activity_service
        import big_parental_controls.services.activity_service as mod
        monkeypatch.setattr(mod, "ACTIVITY_DIR", str(tmp_path))

        user_dir = tmp_path / "testuser"
        user_dir.mkdir()
        data = {
            "date": "2026-03-17",
            "snapshots": [
                {"t": "10:00", "p": ["firefox", "code"]},
                {"t": "10:01", "p": ["firefox"]},
                {"t": "10:02", "p": ["firefox", "code", "nautilus"]},
            ],
        }
        with open(str(user_dir / "2026-03-17.json"), "w") as f:
            json.dump(data, f)

        svc = ActivityService()
        entries = svc.get_day_app_usage("testuser", "2026-03-17")
        assert len(entries) == 3
        # firefox appears in all 3 snapshots → 3 minutes
        assert entries[0].app == "firefox"
        assert entries[0].minutes == 3
        # code appears in 2 snapshots
        assert entries[1].app == "code"
        assert entries[1].minutes == 2
        # nautilus in 1
        assert entries[2].app == "nautilus"
        assert entries[2].minutes == 1

    def test_prettify_app_name(self) -> None:
        assert ActivityService._prettify_app_name("firefox") == "Firefox"
        assert ActivityService._prettify_app_name("gnome-terminal") == "Gnome terminal"
        assert ActivityService._prettify_app_name("my_app") == "My app"
