"""Recommended settings per ECA age range, offered when the age is set.

The distribution ships /usr/share/big-parental-controls/age-defaults.json;
an administrator can override any range in
/etc/big-parental-controls/age-defaults.json (same format, untouched by
package updates). Nothing is applied without the parent's confirmation.

Format, every key optional (an absent key leaves that setting unchanged):

    {"0-12": {"daily_minutes": 90,
              "schedule": {"start": "08:00", "end": "20:00"},
              "dns": "cleanbrowsing:strict"}}

"dns" is "provider:level" (dns-providers.json), a provider alone (its
strictest level) or {"dns1": "...", "dns2": "..."} for custom servers.
"""

import json
import logging
import re
from pathlib import Path

from big_parental_controls.services import dns_providers
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


def _clean_entry(entry: object, providers: dict) -> dict:
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
    dns = dns_providers.resolve(entry.get("dns"), providers)
    if dns:
        clean["dns"] = dns
    return clean


def resolve_entry(entry: object, providers: dict | None = None) -> dict:
    """Validated settings of one range, "dns" resolved (as load() returns)."""
    return _clean_entry(entry, dns_providers.load() if providers is None else providers)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def load(
    shipped: Path = SHIPPED_FILE,
    local: Path = LOCAL_FILE,
    providers: dict | None = None,
) -> dict[str, dict]:
    """Settings per ECA range; a range in *local* replaces the shipped one.

    "dns" comes back resolved: {"provider", "level", "dns1", "dns2"}.
    """
    if providers is None:
        providers = dns_providers.load()
    merged = {**_read(shipped), **_read(local)}
    return {r: _clean_entry(merged.get(r), providers) for r in ECA_RANGES}


def format_minutes(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if not hours:
        return _("%d min") % mins
    return f"{hours} h {mins:02d}" if mins else f"{hours} h"


def describe(entry: dict, providers: dict | None = None) -> list[str]:
    """One translated line per setting, for the confirmation UI."""
    lines = []
    if "daily_minutes" in entry:
        lines.append(_("Daily limit: %s") % format_minutes(entry["daily_minutes"]))
    if "schedule" in entry:
        sched = entry["schedule"]
        lines.append(_("Allowed hours: %(start)s to %(end)s") % sched)
    if "dns" in entry:
        if providers is None:
            providers = dns_providers.load()
        lines.append(_("Web filter: %s") % dns_providers.describe(entry["dns"], providers))
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
            dns = entry["dns"]
            if dns["provider"] == "custom":
                ok = DnsService().set_dns_for_user(
                    uid, "custom", custom_dns1=dns["dns1"], custom_dns2=dns["dns2"]
                )
            else:
                ok = DnsService().set_dns_for_user(uid, dns["provider"], level=dns["level"])
            if not ok:
                failed.append("dns")
        except Exception:  # noqa: BLE001
            failed.append("dns")
    return failed


def from_current(username: str, uid: int) -> tuple[dict, list[str]]:
    """The user's current settings in age-defaults.json format.

    Returns (entry, skipped): *skipped* names the settings that cannot be a
    recommendation (several time ranges, or hours limited to some days).
    """
    from big_parental_controls.services import time_service
    from big_parental_controls.services.dns_service import DnsService

    entry: dict = {}
    skipped: list[str] = []
    minutes = time_service.get_daily_limit(username)
    if minutes:
        entry["daily_minutes"] = minutes
    schedule = time_service.get_schedule(username)
    if schedule and schedule.get("ranges"):
        ranges, days = schedule["ranges"], schedule.get("days")
        if len(ranges) == 1 and (not days or len(set(days)) == 7):
            r = ranges[0]
            entry["schedule"] = {
                "start": f"{r['start_hour']:02d}:{r.get('start_min', 0):02d}",
                "end": f"{r['end_hour']:02d}:{r.get('end_min', 0):02d}",
            }
        else:
            skipped.append("schedule")
    config = DnsService().get_dns_for_user(uid)
    if config:
        match = dns_providers.identify(config, dns_providers.load())
        if match:
            entry["dns"] = f"{match[0]}:{match[1]}"
        else:
            entry["dns"] = {"dns1": config["dns1"], "dns2": config.get("dns2", config["dns1"])}
    return entry, skipped


def save_local(age_range: str, entry: dict) -> bool:
    """Store *entry* as the recommendation for *age_range* in LOCAL_FILE
    (through group-helper, which validates it). Blocking."""
    import subprocess

    from big_parental_controls.core.constants import GROUP_HELPER

    if age_range not in ECA_RANGES:
        return False
    try:
        result = subprocess.run(
            ["pkexec", GROUP_HELPER, "age-defaults-save", age_range, json.dumps(entry)],
            check=False,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0
