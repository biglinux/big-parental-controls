"""D-Bus client for the big-parental-daemon system service.

Communicates with `br.com.biglinux.ParentalMonitor1` on the system bus.
All D-Bus calls run in a thread to avoid blocking the GTK main loop.
"""

from __future__ import annotations

import json
import subprocess


BUS_NAME = "br.com.biglinux.ParentalDaemon"
OBJECT_PATH = "/br/com/biglinux/ParentalDaemon"
MONITOR_IFACE = "br.com.biglinux.ParentalMonitor1"
AGE_IFACE = "br.com.biglinux.AgeSignal1"


def _call(interface: str, method: str, *args: str) -> str | None:
    """Call a D-Bus method on the system bus via busctl."""
    cmd = [
        "busctl", "call", "--system",
        BUS_NAME, OBJECT_PATH, interface, method,
    ]
    # Append signature and arguments if provided
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


class DaemonClient:
    """Client for big-parental-daemon D-Bus interfaces."""

    def is_available(self) -> bool:
        """Check if the daemon is running on the system bus."""
        raw = _call(
            "org.freedesktop.DBus.Properties",
            "Get", "ss", MONITOR_IFACE, "Version",
        )
        return raw is not None

    def get_age_range(self) -> str:
        """Get age range of the calling user."""
        raw = _call(AGE_IFACE, "GetAgeRange")
        if raw and '"' in raw:
            return raw.split('"')[1]
        return "adult"

    def is_minor(self) -> bool:
        """Check if the calling user is supervised."""
        raw = _call(AGE_IFACE, "IsMinor")
        return raw is not None and "true" in raw.lower()

    def enable_user(self, username: str, uid: int) -> bool:
        """Enable monitoring for a supervised user."""
        raw = _call(MONITOR_IFACE, "EnableUser", "su", username, str(uid))
        return raw is not None and "true" in raw.lower()

    def disable_user(self, username: str) -> bool:
        """Disable monitoring for a user."""
        raw = _call(MONITOR_IFACE, "DisableUser", "s", username)
        return raw is not None and "true" in raw.lower()

    def get_monitored_users(self) -> list[str]:
        """Get list of currently monitored usernames."""
        raw = _call(MONITOR_IFACE, "GetMonitoredUsers")
        if raw is None:
            return []
        # busctl output format: "as N "user1" "user2" ..."
        parts = raw.split('"')
        return [parts[i] for i in range(1, len(parts), 2)]

    def get_app_usage(self, username: str, days: int = 7) -> list[dict]:
        """Get app usage summary. Returns list of {app, display_name, minutes}."""
        raw = _call(MONITOR_IFACE, "GetAppUsage", "su", username, str(days))
        return self._parse_json_string(raw, [])

    def get_daily_totals(self, username: str, days: int = 7) -> dict[str, int]:
        """Get daily usage totals. Returns {date: minutes}."""
        raw = _call(MONITOR_IFACE, "GetDailyTotals", "su", username, str(days))
        return self._parse_json_string(raw, {})

    def get_hourly_distribution(
        self, username: str, days: int = 7
    ) -> list[int]:
        """Get 24-slot hourly distribution."""
        raw = _call(
            MONITOR_IFACE, "GetHourlyDistribution", "su", username, str(days)
        )
        result = self._parse_json_string(raw, [0] * 24)
        if len(result) != 24:
            return [0] * 24
        return result

    def get_recent_sessions(
        self, username: str, limit: int = 20
    ) -> list[dict]:
        """Get recent sessions."""
        raw = _call(
            MONITOR_IFACE, "GetRecentSessions", "su", username, str(limit)
        )
        return self._parse_json_string(raw, [])

    @staticmethod
    def _parse_json_string(raw: str | None, default: object) -> object:
        """Extract JSON from busctl string response."""
        if raw is None:
            return default
        # busctl wraps string responses: s "{"key": "val"}"
        # Find the first and last quote of the JSON content
        first_quote = raw.find('"')
        if first_quote < 0:
            return default
        last_quote = raw.rfind('"')
        if last_quote <= first_quote:
            return default
        json_str = raw[first_quote + 1 : last_quote]
        # Unescape busctl escaping
        json_str = json_str.replace('\\"', '"')
        try:
            return json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            return default
