"""Service for managing filesystem ACL restrictions on supervised accounts."""

import json
import logging
import subprocess

from big_parental_controls.core.constants import (
    ACL_STATE_FILE,
    GROUP_HELPER,
)

log = logging.getLogger(__name__)


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
    """Synchronize OARS-blocked apps to filesystem ACLs."""
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
    """Remove all ACL blocks for a user."""
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
