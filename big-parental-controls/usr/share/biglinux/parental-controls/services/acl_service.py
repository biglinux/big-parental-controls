"""Service for managing filesystem ACL restrictions on supervised accounts."""

import json
import logging
import subprocess

log = logging.getLogger(__name__)

GROUP_HELPER = "/usr/lib/big-parental-controls/group-helper"
ACL_STATE_FILE = "/var/lib/big-parental-controls/acl-blocks.json"

DEFAULT_SUPERVISED_BLOCKS = [
    "/usr/bin/pacman",
    "/usr/bin/pamac-manager",
    "/usr/bin/pamac-installer",
    "/usr/bin/pamac-daemon",
    "/usr/bin/yay",
    "/usr/bin/paru",
    "/usr/bin/flatpak",
    "/usr/bin/snap",
    "/usr/bin/docker",
    "/usr/bin/podman",
    "/usr/bin/ncat",
    "/usr/bin/nmap",
    "/usr/bin/socat",
    "/usr/bin/curl",
    "/usr/bin/wget",
    "/usr/bin/ssh",
]


def _load_state() -> dict:
    """Load the ACL state file."""
    try:
        with open(ACL_STATE_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def apply_default_blocks(username: str) -> bool:
    """Apply default ACL blocks for a supervised user via the helper."""
    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "enforce-defaults", username],
            check=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.error("Failed to apply default blocks for %s", username)
        return False


def sync_oars_enforcement(username: str, blocked_apps: list) -> None:
    """Synchronize OARS-blocked apps to filesystem ACLs.

    Args:
        username: The supervised user.
        blocked_apps: List of Gio.AppInfo objects that are blocked by OARS.
    """
    import shutil

    paths_to_block: list[str] = []
    for app_info in blocked_apps:
        exe = app_info.get_executable()
        if not exe:
            continue
        full_path = exe if exe.startswith("/") else (shutil.which(exe) or exe)
        if full_path and full_path.startswith("/"):
            paths_to_block.append(full_path)

    if not paths_to_block:
        return

    block_csv = ",".join(paths_to_block)
    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "acl-batch", username, block_csv, ""],
            check=True,
            timeout=60,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.error("Failed to sync OARS enforcement for %s", username)


def unblock_all(username: str) -> bool:
    """Remove all ACL blocks for a user.

    This is handled by the remove-full command in group-helper,
    but this function provides a standalone ACL-only cleanup.
    """
    state = _load_state()
    paths = state.get(username, [])
    if not paths:
        return True

    unblock_csv = ",".join(paths)
    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "acl-batch", username, "", unblock_csv],
            check=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        log.error("Failed to unblock all for %s", username)
        return False
