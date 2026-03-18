"""Activity data collection — aggregates usage data from system sources.

Sources:
- `last` command: session history (login/logout) from wtmp
- Daemon snapshot files: per-process usage from /var/lib/big-parental-controls/activity/
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from big_parental_controls.core.constants import ACTIVITY_DIR

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True)
class SessionEntry:
    """Single login session for a user."""

    start: datetime
    end: datetime | None
    duration_minutes: int
    tty: str
    session_type: str = ""  # wayland, x11, tty


@dataclass(frozen=True, slots=True)
class DailyUsage:
    """Total usage for a single day."""

    date: str  # YYYY-MM-DD
    minutes: int


@dataclass(frozen=True, slots=True)
class AppUsageEntry:
    """Usage summary for a single application."""

    app: str
    display_name: str
    minutes: int


@dataclass(slots=True)
class ActivitySummary:
    """Aggregated activity data for a user."""

    username: str
    sessions: list[SessionEntry] = field(default_factory=list)
    daily_totals: dict[str, int] = field(default_factory=dict)  # date -> minutes
    hourly_distribution: list[int] = field(default_factory=lambda: [0] * 24)
    app_usage: list[AppUsageEntry] = field(default_factory=list)


class ActivityService:
    """Collect and aggregate usage data for supervised users.

    Uses `last` to parse wtmp session data and reads daemon snapshot
    files for per-application usage tracking.
    """

    def get_session_history(self, username: str, days: int = 7) -> list[SessionEntry]:
        """Return login sessions from wtmp for the given user."""
        return self._parse_last_output(username, days)

    def get_daily_usage(self, username: str, days: int = 30) -> dict[str, int]:
        """Return daily usage in minutes: {'2026-03-17': 145, ...}."""
        sessions = self._parse_last_output(username, days)
        return self._aggregate_daily(sessions, days)

    def get_hourly_distribution(self, username: str, days: int = 7) -> list[int]:
        """Return 24-element list with total minutes per hour slot."""
        sessions = self._parse_last_output(username, days)
        return self._aggregate_hourly(sessions)

    def get_summary(self, username: str, days: int = 7) -> ActivitySummary:
        """Return full activity summary for a user."""
        sessions = self._parse_last_output(username, days)
        merged = self._merge_overlapping(sessions)
        return ActivitySummary(
            username=username,
            sessions=merged,
            daily_totals=self._aggregate_daily(merged, days),
            hourly_distribution=self._aggregate_hourly(merged),
            app_usage=self.get_app_usage(username, days),
        )

    def get_daily_hourly(self, username: str, date_str: str) -> list[int]:
        """Return 24-element list with minutes per hour for a specific date.

        Args:
            username: User to query.
            date_str: Date in YYYY-MM-DD format.
        """
        sessions = self._parse_last_output(username, days=30)
        merged = self._merge_overlapping(sessions)
        day_sessions = [s for s in merged if s.start.date().isoformat() == date_str]
        return self._aggregate_hourly(day_sessions)

    def get_day_sessions(self, username: str, date_str: str) -> list[SessionEntry]:
        """Return merged sessions for a specific date."""
        sessions = self._parse_last_output(username, days=30)
        merged = self._merge_overlapping(sessions)
        return [s for s in merged if s.start.date().isoformat() == date_str]

    # ── App usage from daemon snapshots ───────────────────────────

    def get_app_usage(self, username: str, days: int = 7) -> list[AppUsageEntry]:
        """Return per-app usage in minutes, sorted by most used.

        Reads the daemon's snapshot files from ACTIVITY_DIR/{username}/*.json.
        Each snapshot records which processes were running; each snapshot
        represents ~1 minute of usage.
        """
        snapshots = self._load_snapshots(username, days)
        usage: dict[str, int] = {}
        for snap in snapshots:
            for proc in snap:
                usage[proc] = usage.get(proc, 0) + 1

        entries = [
            AppUsageEntry(
                app=app,
                display_name=self._prettify_app_name(app),
                minutes=minutes,
            )
            for app, minutes in usage.items()
        ]
        entries.sort(key=lambda e: e.minutes, reverse=True)
        return entries

    def get_day_app_usage(self, username: str, date_str: str) -> list[AppUsageEntry]:
        """Return per-app usage for a specific date."""
        user_dir = os.path.join(ACTIVITY_DIR, username)
        path = os.path.join(user_dir, f"{date_str}.json")
        snapshots = self._load_snapshot_file(path)
        usage: dict[str, int] = {}
        for snap in snapshots:
            for proc in snap:
                usage[proc] = usage.get(proc, 0) + 1

        entries = [
            AppUsageEntry(
                app=app,
                display_name=self._prettify_app_name(app),
                minutes=minutes,
            )
            for app, minutes in usage.items()
        ]
        entries.sort(key=lambda e: e.minutes, reverse=True)
        return entries

    def _load_snapshots(self, username: str, days: int) -> list[list[str]]:
        """Load process lists from daemon snapshot files."""
        user_dir = os.path.join(ACTIVITY_DIR, username)
        if not os.path.isdir(user_dir):
            return []

        today = datetime.now().date()
        all_procs: list[list[str]] = []
        for i in range(days):
            d = today - timedelta(days=i)
            path = os.path.join(user_dir, f"{d.isoformat()}.json")
            all_procs.extend(self._load_snapshot_file(path))
        return all_procs

    @staticmethod
    def _load_snapshot_file(path: str) -> list[list[str]]:
        """Load snapshots from a single daily JSON file.

        File format: {"date": "YYYY-MM-DD", "snapshots": [{"t": "HH:MM", "p": [...]}]}
        """
        if not os.path.isfile(path):
            return []
        try:
            with open(path) as f:
                data = json.load(f)
            return [snap["p"] for snap in data.get("snapshots", []) if snap.get("p")]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return []

    @staticmethod
    def _prettify_app_name(comm: str) -> str:
        """Convert a process comm name to a human-readable label."""
        name = comm.replace("-", " ").replace("_", " ")
        return name.capitalize() if name else comm

    # ── Internal parsers ──────────────────────────────────────────

    def _parse_last_output(self, username: str, days: int) -> list[SessionEntry]:
        """Parse `last` command output for session history.

        `last` reads /var/log/wtmp directly — no sudo needed.
        """
        since_dt = datetime.now() - timedelta(days=days)
        since_str = since_dt.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            result = subprocess.run(
                [
                    "last",
                    "-n",
                    "10000",
                    username,
                    "--time-format",
                    "iso",
                    "--since",
                    since_str,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

        if result.returncode != 0:
            return []

        sessions: list[SessionEntry] = []
        for line in result.stdout.splitlines():
            entry = self._parse_last_line(line, username)
            if entry:
                sessions.append(entry)

        return sessions

    def _parse_last_line(self, line: str, username: str) -> SessionEntry | None:
        """Parse a single line from `last --time-format iso`.

        Example lines:
          rafael   tty5   2026-03-17T03:58:54-03:00 - 2026-03-17T04:09:59-03:00  (00:11)
          bruno    pts/0  :0  2026-03-17T17:56:39-03:00   still logged in
          bruno    tty2        2026-03-17T04:27:09-03:00 - crash  (02:05)
        """
        if not line.startswith(username):
            return None

        # Skip reboot/shutdown lines
        if line.startswith("reboot") or line.startswith("wtmp"):
            return None

        parts = line.split()
        if len(parts) < 3:
            return None

        tty = parts[1]
        session_type = self._infer_session_type(tty, parts)

        # Find the ISO timestamp (starts with a year like 2026-)
        timestamps = [p for p in parts if self._looks_like_iso(p)]
        if not timestamps:
            return None

        start_dt = self._parse_iso(timestamps[0])
        if start_dt is None:
            return None

        end_dt: datetime | None = None
        still_logged_in = "still logged in" in line or "still running" in line
        is_crash = "crash" in line

        if len(timestamps) >= 2 and not still_logged_in and not is_crash:
            end_dt = self._parse_iso(timestamps[1])

        # Compute duration from parenthesized value or from timestamps
        duration = self._extract_duration_from_line(line)
        if duration == 0 and end_dt and start_dt:
            delta = end_dt - start_dt
            duration = max(0, int(delta.total_seconds() / 60))
        elif duration == 0 and still_logged_in:
            delta = datetime.now().astimezone() - start_dt
            duration = max(0, int(delta.total_seconds() / 60))

        # For crash sessions, derive end from start + duration
        if is_crash and end_dt is None and duration > 0:
            end_dt = start_dt + timedelta(minutes=duration)

        return SessionEntry(
            start=start_dt,
            end=end_dt,
            duration_minutes=duration,
            tty=tty,
            session_type=session_type,
        )

    @staticmethod
    def _looks_like_iso(s: str) -> bool:
        """Quick check if a string looks like an ISO datetime."""
        return len(s) > 18 and s[4] == "-" and s[7] == "-" and "T" in s

    @staticmethod
    def _parse_iso(s: str) -> datetime | None:
        """Parse ISO 8601 datetime string."""
        try:
            return datetime.fromisoformat(s)
        except ValueError:
            return None

    @staticmethod
    def _extract_duration_from_line(line: str) -> int:
        """Extract duration in minutes from parenthesized (HH:MM) at end of line."""
        # Look for pattern like (00:11) or (2+03:45)
        import re

        m = re.search(r"\((?:(\d+)\+)?(\d+):(\d+)\)\s*$", line)
        if not m:
            return 0
        days_part = int(m.group(1)) if m.group(1) else 0
        hours = int(m.group(2))
        minutes = int(m.group(3))
        return days_part * 1440 + hours * 60 + minutes

    @staticmethod
    def _infer_session_type(tty: str, parts: list[str]) -> str:
        """Infer session type from tty and context.

        On modern Wayland systems (SDDM/GDM), graphical sessions run
        on ttyN (e.g. tty2). We detect this by checking for a display
        manager or by the presence of a seat via loginctl.
        """
        if tty.startswith("pts/"):
            # pts with local display → graphical terminal inside desktop
            if len(parts) > 2 and parts[2].startswith(":"):
                return "wayland"
            return "remote"
        if tty.startswith("tty"):
            # On systems with a display manager, ttyN = graphical session
            # SDDM allocates different VTs (tty2, tty3, tty5, tty7…)
            import os

            dm_indicators = (
                "/run/sddm",
                "/run/gdm",
                "/run/lightdm",
            )
            for indicator in dm_indicators:
                if os.path.exists(indicator):
                    return "wayland"
            return "tty"
        return ""

    # ── Session merging ─────────────────────────────────────────

    @staticmethod
    def _merge_overlapping(
        sessions: list[SessionEntry],
    ) -> list[SessionEntry]:
        """Merge overlapping/adjacent sessions into usage periods.

        Multiple TTY/pts sessions that overlap in time (e.g. graphical
        session on tty2 + terminal on pts/0) are merged into a single
        period showing total computer usage.
        """
        if not sessions:
            return []

        now = datetime.now().astimezone()
        items = []
        for s in sessions:
            end = s.end or now
            items.append((s.start, end, s.session_type))

        # Sort by start time
        items.sort(key=lambda x: x[0])

        merged: list[SessionEntry] = []
        cur_start, cur_end, cur_type = items[0]

        for start, end, stype in items[1:]:
            # Overlap or adjacent (within 2 min gap)
            if start <= cur_end + timedelta(minutes=2):
                cur_end = max(cur_end, end)
                # Prefer graphical type
                if stype == "wayland":
                    cur_type = stype
            else:
                dur = max(0, int((cur_end - cur_start).total_seconds() / 60))
                still_active = cur_end >= now - timedelta(minutes=1)
                merged.append(
                    SessionEntry(
                        start=cur_start,
                        end=None if still_active else cur_end,
                        duration_minutes=dur,
                        tty="",
                        session_type=cur_type,
                    )
                )
                cur_start, cur_end, cur_type = start, end, stype

        dur = max(0, int((cur_end - cur_start).total_seconds() / 60))
        still_active = cur_end >= now - timedelta(minutes=1)
        merged.append(
            SessionEntry(
                start=cur_start,
                end=None if still_active else cur_end,
                duration_minutes=dur,
                tty="",
                session_type=cur_type,
            )
        )

        return merged

    # ── Aggregation helpers ───────────────────────────────────────

    @staticmethod
    def _aggregate_daily(sessions: list[SessionEntry], days: int) -> dict[str, int]:
        """Aggregate session durations by day."""
        totals: dict[str, int] = {}

        # Pre-fill with zeros for the requested date range
        today = datetime.now().date()
        for i in range(days):
            d = today - timedelta(days=i)
            totals[d.isoformat()] = 0

        for s in sessions:
            date_key = s.start.date().isoformat()
            if date_key in totals:
                totals[date_key] += s.duration_minutes

        return totals

    @staticmethod
    def _aggregate_hourly(sessions: list[SessionEntry]) -> list[int]:
        """Aggregate total minutes per hour-of-day slot (0-23)."""
        hours = [0] * 24
        for s in sessions:
            if s.duration_minutes <= 0:
                continue

            start_hour = s.start.hour
            start_min = s.start.minute

            remaining = s.duration_minutes
            current_hour = start_hour
            # Minutes remaining in the starting hour
            first_chunk = min(remaining, 60 - start_min)
            hours[current_hour % 24] += first_chunk
            remaining -= first_chunk
            current_hour += 1

            while remaining > 0:
                chunk = min(remaining, 60)
                hours[current_hour % 24] += chunk
                remaining -= chunk
                current_hour += 1

        return hours
