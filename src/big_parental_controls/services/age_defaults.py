"""Recommended settings per ECA age range, offered when the age is set.

The distribution ships /usr/share/big-parental-controls/age-defaults.json;
an administrator can override any range in
/etc/big-parental-controls/age-defaults.json (same format, untouched by
package updates). Nothing is applied without the parent's confirmation.

Format, every key optional (an absent key leaves that setting unchanged):

    {"0-12": {"daily_minutes": 90,
              "schedule": {"start": "08:00", "end": "20:00"},
              "dns": "cleanbrowsing"}}
"""

import json
import logging
import re
from pathlib import Path

from big_parental_controls.core.constants import DNS_PROVIDERS
from big_parental_controls.services.age_profile import ECA_RANGES
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()
log = logging.getLogger(__name__)

SHIPPED_FILE = Path("/usr/share/big-parental-controls/age-defaults.json")
LOCAL_FILE = Path("/etc/big-parental-controls/age-defaults.json")

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_time(value: object) -> tuple[int, int] | None:
    match = _HHMM.match(value) if isinstance(value, str) else None
    return (int(match[1]), int(match[2])) if match else None


def _clean_entry(entry: object) -> dict:
    """Keep only the valid settings of one range."""
    if not isinstance(entry, dict):
        return {}
    clean: dict = {}
    minutes = entry.get("daily_minutes")
    if isinstance(minutes, int) and not isinstance(minutes, bool) and 0 < minutes <= 1440:
        clean["daily_minutes"] = minutes
    schedule = entry.get("schedule")
    if isinstance(schedule, dict):
        start, end = _parse_time(schedule.get("start")), _parse_time(schedule.get("end"))
        if start and end and start < end:
            clean["schedule"] = {"start": schedule["start"], "end": schedule["end"]}
    if entry.get("dns") in DNS_PROVIDERS:
        clean["dns"] = entry["dns"]
    return clean


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def load(shipped: Path = SHIPPED_FILE, local: Path = LOCAL_FILE) -> dict[str, dict]:
    """Settings per ECA range; a range in *local* replaces the shipped one."""
    merged = {**_read(shipped), **_read(local)}
    return {r: _clean_entry(merged.get(r)) for r in ECA_RANGES}


def format_minutes(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if not hours:
        return _("%d min") % mins
    return f"{hours} h {mins:02d}" if mins else f"{hours} h"


def describe(entry: dict) -> list[str]:
    """One translated line per setting, for the confirmation UI."""
    lines = []
    if "daily_minutes" in entry:
        lines.append(_("Daily limit: %s") % format_minutes(entry["daily_minutes"]))
    if "schedule" in entry:
        sched = entry["schedule"]
        lines.append(_("Allowed hours: %(start)s to %(end)s") % sched)
    if "dns" in entry:
        lines.append(_("Web filter: %s") % DNS_PROVIDERS[entry["dns"]]["name"])
    return lines


def apply(username: str, uid: int, entry: dict) -> list[str]:
    """Apply *entry* to the user. Blocking. Returns the settings that failed."""
    from big_parental_controls.services import time_service
    from big_parental_controls.services.dns_service import DnsService

    failed = []
    if "daily_minutes" in entry:
        try:
            time_service.set_daily_limit(username, entry["daily_minutes"])
        except Exception:  # noqa: BLE001 — pkexec cancelled or helper error
            failed.append("daily_minutes")
    if "schedule" in entry:
        (sh, sm), (eh, em) = (
            _parse_time(entry["schedule"]["start"]),
            _parse_time(entry["schedule"]["end"]),
        )
        ranges = [{"start_hour": sh, "start_min": sm, "end_hour": eh, "end_min": em}]
        try:
            if not time_service.set_schedule(username, ranges):
                failed.append("schedule")
        except Exception:  # noqa: BLE001
            failed.append("schedule")
    if "dns" in entry:
        try:
            if not DnsService().set_dns_for_user(uid, entry["dns"]):
                failed.append("dns")
        except Exception:  # noqa: BLE001
            failed.append("dns")
    return failed
