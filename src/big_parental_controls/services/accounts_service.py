"""Wrapper around AccountsService GIR bindings for user management."""

import contextlib
import os
import subprocess
import tempfile
import time

import gi

gi.require_version("AccountsService", "1.0")
from gi.repository import AccountsService, GLib

from big_parental_controls.core.constants import (
    GROUP_HELPER,
    MIN_HUMAN_UID,
    SUPERVISED_GROUP,
)


class AccountsServiceWrapper:
    """Service for managing system user accounts."""

    def __init__(self) -> None:
        self._manager = AccountsService.UserManager.get_default()
        deadline = time.monotonic() + 5
        while not self._manager.props.is_loaded:
            if time.monotonic() > deadline:
                break
            GLib.MainContext.default().iteration(True)

    def list_users(self) -> list[AccountsService.User]:
        """List all human users (UID >= 1000, not nobody)."""
        users = self._manager.list_users()
        return [
            u
            for u in users
            if u.get_uid() >= MIN_HUMAN_UID and u.get_user_name() != "nobody"
        ]

    def get_user_by_uid(self, uid: int) -> AccountsService.User | None:
        """Find a user by UID."""
        for user in self._manager.list_users():
            if user.get_uid() == uid:
                return user
        return None

    def get_user_by_name(self, username: str) -> AccountsService.User | None:
        """Find a user by username."""
        return self._manager.get_user(username)

    def is_admin(self, user: AccountsService.User) -> bool:
        """Check if user has admin privileges (wheel group)."""
        return user.get_account_type() == AccountsService.UserAccountType.ADMINISTRATOR

    def is_supervised(self, user: AccountsService.User) -> bool:
        """Check if user is in the supervised group."""
        try:
            result = subprocess.run(
                ["id", "-nG", user.get_user_name()],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            )
        except subprocess.CalledProcessError:
            return False
        else:
            groups = result.stdout.strip().split()
            return SUPERVISED_GROUP in groups

    def get_current_user(self) -> AccountsService.User | None:
        """Return the AccountsService.User for the currently logged-in user."""
        username = os.environ.get("USER") or os.getlogin()
        return self.get_user_by_name(username)

    def is_current_user_supervised(self) -> bool:
        """Check if the user running this process is supervised."""
        try:
            import grp
            supervised_gid = grp.getgrnam(SUPERVISED_GROUP).gr_gid
            return supervised_gid in os.getgroups()
        except (KeyError, OSError):
            return False

    def create_supervised_user(
        self, username: str, fullname: str, password: str
    ) -> AccountsService.User | None:
        """Create a new supervised user with a single privileged helper call.

        The group-helper 'create-full' command handles useradd, chpasswd,
        group assignment, and ACL defaults in one pkexec session so the
        admin is prompted for credentials only once.
        """
        fd, pwfile = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(password)
            os.chmod(pwfile, 0o600)
            subprocess.run(
                ["pkexec", GROUP_HELPER, "create-full", username, fullname, pwfile],
                check=True,
                timeout=60,
            )
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(pwfile)
            raise
        # Helper deletes pwfile itself; wait for AccountsService to detect new user
        deadline = time.monotonic() + 5.0
        while True:
            GLib.MainContext.default().iteration(False)
            for user in self._manager.list_users():
                if user.get_user_name() == username:
                    return user
            if time.monotonic() > deadline:
                break
            GLib.MainContext.default().iteration(True)
        return None

    def remove_supervised_status(self, user: AccountsService.User) -> None:
        """Remove a user from the supervised group."""
        subprocess.run(
            ["pkexec", GROUP_HELPER, "remove", user.get_user_name()],
            check=False,
            timeout=30,
        )

    def remove_from_supervised(self, username: str) -> bool:
        """Remove a user from the supervised group by username."""
        result = subprocess.run(
            ["pkexec", GROUP_HELPER, "remove", username],
            check=False,
            timeout=30,
        )
        return result.returncode == 0

    def add_supervised_status(self, user: AccountsService.User) -> None:
        """Add a user to the supervised group."""
        subprocess.run(
            ["pkexec", GROUP_HELPER, "add", user.get_user_name()],
            check=True,
            timeout=30,
        )

    def delete_user(self, uid: int, remove_files: bool = False) -> bool:
        """Delete a user account via group-helper (includes parental controls cleanup)."""
        user = self.get_user_by_uid(uid)
        if user is None:
            return False
        username = user.get_user_name()
        if not username:
            return False
        try:
            result = subprocess.run(
                ["pkexec", GROUP_HELPER, "delete-user", username],
                check=False,
                timeout=60,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False
