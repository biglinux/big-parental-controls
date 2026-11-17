"""Remaining screen time of a supervised user (shared by the CLI and the tray).

Read-only: uses the same files as big-parental-daemon
(/var/lib/big-parental-controls/time-{limits,state,extra}.json and
/etc/security/time.conf), so it needs no privileges and no extra daemon.

Usage:
  big-time-left                one line of plain text
  big-time-left --notify       desktop notification with the details
  big-time-left --alert KIND N desktop alert sent by big-parental-daemon
                               (KIND: daily-warn, daily-done, schedule-warn,
                               schedule-end), so its texts are translated with
                               the rest of the application
"""

import functools
import gettext
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

from big_parental_controls.core.constants import GETTEXT_DOMAIN, LOCALE_DIR

STATE_DIR = Path(os.environ.get("BPC_STATE_DIR", "/var/lib/big-parental-controls"))
TIME_CONF = Path(os.environ.get("BPC_TIME_CONF", "/etc/security/time.conf"))
WARN_MIN = 5
LOW_MIN = 15

# Extra-time defaults. They must match EXTRA_STEP_MIN / EXTRA_MAX_REQUESTS in
# big-age-signal/src/main.rs (checked by tests/test_time_left.py).
EXTRA_STEP_MIN = 15
EXTRA_MAX_REQUESTS = 3

_DAY_MAP = {"Mo": 0, "Tu": 1, "We": 2, "Th": 3, "Fr": 4, "Sa": 5, "Su": 6}


def _ensure_locale_env() -> None:
    """Started without a session environment (e.g. by the daemon or by hand):
    fall back to the system locale so gettext still picks a language."""
    if any(os.environ.get(v) for v in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")):
        return
    try:
        for line in Path("/etc/locale.conf").read_text().splitlines():
            if line.startswith("LANG="):
                os.environ["LANG"] = line[5:].strip().strip('"')
    except OSError:
        pass


@functools.cache
def _tr() -> tuple[Callable[[str], str], Callable[[str, str, int], str]]:
    """(gettext, ngettext) of the application catalogue, loaded once."""
    _ensure_locale_env()
    t = gettext.translation(GETTEXT_DOMAIN, localedir=LOCALE_DIR, fallback=True)
    return t.gettext, t.ngettext


# ── Pure logic (no translation, unit-tested) ─────────────────────────────


def fmt(minutes: int) -> str:
    h, m = divmod(max(minutes, 0), 60)
    return f"{h}h{m:02d}" if h else f"{m} min"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def day_applies(day_str: str, wday: int) -> bool:
    """pam_time day spec (Al, Wk, Wd, MoTu...) applies to weekday `wday` (0 = Monday)."""
    if not day_str or "Al" in day_str:
        return True
    days = set()
    if "Wk" in day_str:
        days |= set(range(5))
    if "Wd" in day_str:
        days |= {5, 6}
    remain = day_str.replace("Wk", "").replace("Wd", "")
    for i in range(0, len(remain) - 1, 2):
        if remain[i : i + 2] in _DAY_MAP:
            days.add(_DAY_MAP[remain[i : i + 2]])
    return wday in days


def schedule_left(user: str, now: datetime, shift: int = 0) -> tuple[int, str | None] | None:
    """None = no rule; (0, None) = outside; (minutes, end "HH:MM") = inside.

    `shift` pushes the end of the allowed period by that many minutes
    (parent-approved extra time), like big-parental-daemon does.
    """
    try:
        content = TIME_CONF.read_text()
    except OSError:
        return None
    rule = None
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(";", 3)
        if len(parts) == 4 and parts[2] == user:
            rule = parts[3].strip()
    if rule is None:
        return None
    now_min = now.hour * 60 + now.minute - shift
    if now_min < 0:  # the extension never crosses midnight
        return (0, None)
    best_end = None
    for seg in rule.split("|"):
        m = re.search(r"(\d{2})(\d{2})-(\d{2})(\d{2})$", seg.strip())
        if not m:
            continue
        start = int(m[1]) * 60 + int(m[2])
        end = int(m[3]) * 60 + int(m[4])
        if day_applies(seg.strip()[: m.start()], now.weekday()) and start <= now_min < end:
            best_end = end if best_end is None else max(best_end, end)
    if best_end is None:
        return (0, None)
    end = best_end + shift
    return (best_end - now_min, f"{end // 60 % 24:02d}:{end % 60:02d}")


def extra_settings(cfg: dict) -> dict:
    """Per-child extra-time settings (time-limits.json -> <user>.extra)."""
    e = cfg.get("extra") or {}

    def num(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return min(max(int(e.get(key, default)), lo), hi)
        except (TypeError, ValueError):
            return default

    return {
        "step": num("step", EXTRA_STEP_MIN, 5, 120),
        "max_requests": num("max_requests", EXTRA_MAX_REQUESTS, 0, 10),
        "extend_schedule": bool(e.get("extend_schedule", False)),
    }


def compute(user: str, now: datetime) -> dict:
    today = date.today().isoformat()
    limits = load_json(STATE_DIR / "time-limits.json").get(user, {})
    settings = extra_settings(limits)
    usage = load_json(STATE_DIR / "time-state.json")
    used = usage.get(user, 0) if usage.get("_date") == today else 0
    extra_all = load_json(STATE_DIR / "time-extra.json")
    extra = extra_all.get(user, {}) if extra_all.get("_date") == today else {}
    bonus = int(extra.get("minutes", 0) or 0)
    requests = int(extra.get("requests", 0) or 0)
    base = int(limits.get("daily_minutes", 0) or 0)
    daily = base + bonus if base > 0 else 0
    quota_left = max(daily - used, 0) if daily > 0 else None
    sched = schedule_left(user, now)
    if sched and bonus and settings["extend_schedule"]:
        pushed = schedule_left(user, now, bonus)
        if pushed and pushed[1] and (sched[1] is None or pushed[0] > sched[0]):
            sched = pushed
    sched_left, sched_end = sched if sched else (None, None)
    candidates = [v for v in (quota_left, sched_left) if v is not None]
    applies = base > 0 or (settings["extend_schedule"] and sched is not None)
    return {
        "remaining": min(candidates) if candidates else None,
        "quota_left": quota_left,
        "sched_left": sched_left,
        "sched_end": sched_end,
        "bonus": bonus if applies else 0,
        "step": settings["step"],
        "max_requests": settings["max_requests"],
        "extend_schedule": settings["extend_schedule"],
        # child requests still possible today
        "requests_left": max(settings["max_requests"] - requests, 0) if applies else 0,
    }


def request_extra(pin: str) -> str:
    """Asks big-parental-daemon for more minutes (parent PIN); returns its code."""
    try:
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        reply = bus.call_sync(
            "br.com.biglinux.ParentalDaemon", "/br/com/biglinux/ParentalDaemon",
            "br.com.biglinux.TimeExtra1", "RequestExtra", GLib.Variant("(s)", (pin,)),
            GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 10000, None)
        return reply.unpack()[0]
    except Exception:  # noqa: BLE001 — daemon down, D-Bus policy missing...
        return "error"


# ── Translated texts ─────────────────────────────────────────────────────


def title() -> str:
    _, _n = _tr()
    return _("Time left")


def short_label(rem: int | None) -> str:
    _, _n = _tr()
    if rem is None:
        return _("No limit")
    return _("Time is up") if rem <= 0 else fmt(rem)


def details(info: dict) -> str:
    _, _n = _tr()
    lines = []
    if info["quota_left"] is not None:
        line = _("Daily quota: %s left") % fmt(info["quota_left"])
        if info.get("bonus"):
            line += " " + _("(incl. +%d min granted)") % info["bonus"]
        lines.append(line)
    if info["sched_left"] is not None and info["sched_end"]:
        lines.append(_("Allowed hours: ends at %(end)s (in %(left)s)")
                     % {"end": info["sched_end"], "left": fmt(info["sched_left"])})
    return "\n".join(lines) or _("No time limit is set.")


def result_text(code: str) -> str:
    """Human message for a RequestExtra result code."""
    _, _n = _tr()
    kind, _sep, arg = code.partition(":")
    if kind == "ok":
        return _("Granted: +%s min!") % (arg or EXTRA_STEP_MIN)
    if kind == "locked":
        return _("Too many attempts: try again in %s min.") % (arg or "?")
    return {
        "bad_pin": _("Wrong code."),
        "max": _("No more requests today."),
        "disabled": _("Time requests are disabled."),
        "no_pin": _("No parent code is set."),
    }.get(kind, _("The request could not be completed."))


def alert_text(kind: str, n: int) -> tuple[str, str]:
    """(summary, body) of the alerts sent by big-parental-daemon."""
    _, _n = _tr()
    if kind == "daily-warn":
        return (_n("%d minute left", "%d minutes left", n) % n,
                _n("Your screen time for today ends in %d minute.",
                   "Your screen time for today ends in %d minutes.", n) % n)
    if kind == "daily-done":
        return (_("Screen time is up"),
                _("Your daily screen time of %d min has been reached.") % n)
    if kind == "schedule-warn":
        return (_n("%d minute left", "%d minutes left", n) % n,
                _n("The allowed hours end in %d minute.",
                   "The allowed hours end in %d minutes.", n) % n)
    return (_("Allowed hours are over"), _("The allowed usage period has ended."))


def notify(summary: str, body: str, urgent: bool = False) -> None:
    _, _n = _tr()
    cmd = ["notify-send", "--icon=preferences-system-time",
           f"--app-name={_('Parental Controls')}"]
    if urgent:
        cmd.append("--urgency=critical")
    subprocess.run([*cmd, summary, body], check=False)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else ""

    if mode == "--alert":
        if len(argv) != 3 or not argv[2].isdigit():
            print("usage: big-time-left --alert KIND MINUTES", file=sys.stderr)
            return 2
        notify(*alert_text(argv[1], int(argv[2])), urgent=True)
        return 0

    user = os.environ.get("BPC_USER") or os.environ.get("USER") or ""
    info = compute(user, datetime.now())
    short = short_label(info["remaining"])
    if mode == "--notify":
        notify(f"{title()}: {short}", details(info))
    else:
        print(short)
    return 0
