"""ECA Digital age range of a supervised user and the matching OARS preset.

The range is stored in user-profiles.json (written as root by group-helper)
and read by big-age-signal. The OARS preset is the app filter malcontent
applies in GNOME Software, Discover and Flatpak.
"""

import json
import subprocess
from pathlib import Path

from big_parental_controls.core.constants import GROUP_HELPER

PROFILES_FILE = Path("/var/lib/big-parental-controls/user-profiles.json")
ECA_RANGES = ("0-12", "13-15", "16-17", "18+")
DEFAULT_RANGE = "18+"

# ECA range -> key of malcontent_service.OARS_PRESETS (None: no content limit).
# The presets are tuned for "child" ~7, "preteen" 10-12, "teen" 13-15 and
# "young-adult" 16-17, so each range gets the preset of its own ages.
ECA_TO_OARS: dict[str, str | None] = {
    "0-12": "preteen",
    "13-15": "teen",
    "16-17": "young-adult",
    "18+": None,
}

# Installed by the malcontent package; without it AccountsService rejects
# every app filter call.
MALCONTENT_INTERFACE = Path(
    "/usr/share/accountsservice/interfaces/com.endlessm.ParentalControls.AppFilter.xml"
)


def read_age_range(username: str, profiles_file: Path = PROFILES_FILE) -> str:
    """Stored range of *username*, DEFAULT_RANGE when unknown."""
    try:
        profiles = json.loads(profiles_file.read_text(encoding="utf-8"))
        age_range = profiles[username]["age_range"]
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_RANGE
    return age_range if age_range in ECA_RANGES else DEFAULT_RANGE


def write_age_range(username: str, age_range: str) -> bool:
    """Persist *age_range* through group-helper (pkexec). Blocking."""
    if age_range not in ECA_RANGES:
        return False
    try:
        result = subprocess.run(
            ["pkexec", GROUP_HELPER, "set-age-profile", username, age_range],
            check=False,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def malcontent_available(interface_file: Path = MALCONTENT_INTERFACE) -> bool:
    """True when the malcontent AccountsService interface is installed."""
    return interface_file.is_file()


def apply_oars_preset(malcontent: object, uid: int, age_range: str) -> bool:
    """Set the OARS app filter matching *age_range*. Blocking.

    Installation stays forbidden, as when the account was created; only the
    content ratings change. Returns False when malcontent refused or failed.
    """
    from big_parental_controls.services.malcontent_service import OARS_PRESETS

    preset = ECA_TO_OARS.get(age_range)
    try:
        malcontent.set_app_filter(uid, oars_values=OARS_PRESETS[preset] if preset else {})
    except Exception:  # noqa: BLE001 — GLib.Error and D-Bus failures
        return False
    return True
