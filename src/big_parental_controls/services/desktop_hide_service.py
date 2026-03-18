"""Service for hiding/unhiding .desktop entries for supervised users."""

import contextlib
import logging
import os
import shutil
import subprocess

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from big_parental_controls.core.constants import GROUP_HELPER

log = logging.getLogger(__name__)


def _get_user_apps_dir(username: str) -> str:
    """Get the user-local applications directory path."""
    try:
        result = subprocess.run(
            ["getent", "passwd", username],
            capture_output=True, text=True, check=True,
            timeout=10,
        )
        home = result.stdout.strip().split(":")[5]
    except (subprocess.CalledProcessError, IndexError):
        home = f"/home/{username}"
    return os.path.join(home, ".local", "share", "applications")


def _find_desktop_id_for_binary(binary_path: str) -> str | None:
    """Find the .desktop file ID for a given binary path."""
    resolved = os.path.realpath(binary_path) if os.path.exists(binary_path) else binary_path
    basename = os.path.basename(resolved)

    for app_info in Gio.AppInfo.get_all():
        exe = app_info.get_executable()
        if not exe:
            continue
        full_exe = exe if exe.startswith("/") else (shutil.which(exe) or exe)
        full_exe_resolved = os.path.realpath(full_exe) if os.path.exists(full_exe) else full_exe

        if full_exe == binary_path or full_exe_resolved == resolved:
            desktop_id = app_info.get_id()
            if desktop_id:
                return desktop_id
        if os.path.basename(full_exe) == basename:
            desktop_id = app_info.get_id()
            if desktop_id:
                return desktop_id
    return None


def hide_app(username: str, binary_path: str) -> bool:
    """Hide an app from the user's menu by creating a NoDisplay .desktop override."""
    desktop_id = _find_desktop_id_for_binary(binary_path)
    if not desktop_id:
        log.debug("No .desktop found for %s — skipping hide", binary_path)
        return False

    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "desktop-hide", username, desktop_id],
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError:
        log.error("Failed to hide %s for %s", desktop_id, username)
        return False

    _refresh_menu_cache(username)
    return True


def unhide_app(username: str, binary_path: str) -> bool:
    """Unhide an app from the user's menu by removing the NoDisplay override."""
    desktop_id = _find_desktop_id_for_binary(binary_path)
    if not desktop_id:
        log.debug("No .desktop found for %s — skipping unhide", binary_path)
        return False

    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "desktop-unhide", username, desktop_id],
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError:
        log.error("Failed to unhide %s for %s", desktop_id, username)
        return False

    _refresh_menu_cache(username)
    return True


def unhide_all(username: str) -> bool:
    """Remove all .desktop overrides created by us for a user."""
    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "desktop-unhide-all", username],
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError:
        log.error("Failed to unhide all for %s", username)
        return False

    _refresh_menu_cache(username)
    return True


def _refresh_menu_cache(username: str) -> None:
    """Refresh the desktop menu cache for the user's environment."""
    if shutil.which("kbuildsycoca6"):
        try:
            subprocess.run(
                ["pkexec", GROUP_HELPER, "refresh-menu-cache", username],
                check=False,
                timeout=15,
            )
        except subprocess.CalledProcessError:
            log.debug("kbuildsycoca6 refresh failed for %s", username)

    if shutil.which("dbus-send"):
        with contextlib.suppress(subprocess.CalledProcessError, subprocess.TimeoutExpired):
            subprocess.run(
                [
                    "sudo", "-u", username,
                    "dbus-send", "--session",
                    "--dest=org.Cinnamon",
                    "/org/Cinnamon",
                    "org.Cinnamon.ReloadTheme",
                ],
                check=False,
                timeout=5,
            )
