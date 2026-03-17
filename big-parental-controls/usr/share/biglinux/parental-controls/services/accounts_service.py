"""Wrapper around AccountsService GIR bindings for user management."""

import subprocess
import time

import gi

gi.require_version("AccountsService", "1.0")
from gi.repository import AccountsService, GLib


class AccountsServiceWrapper:
    """Service for managing system user accounts."""

    SUPERVISED_GROUP = "supervised"
    MIN_HUMAN_UID = 1000
    GROUP_HELPER = "/usr/lib/big-parental-controls/group-helper"

    def __init__(self):
        self._manager = AccountsService.UserManager.get_default()
        # Ensure the manager has loaded users (timeout after 5s)
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
            if u.get_uid() >= self.MIN_HUMAN_UID and u.get_user_name() != "nobody"
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
            return self.SUPERVISED_GROUP in groups

    def create_supervised_user(
        self, username: str, fullname: str, password: str
    ) -> AccountsService.User | None:
        """Create a new standard (non-admin) supervised user.

        Returns the new User object or None on failure.
        """
        # Create user as standard (not administrator)
        user = self._manager.create_user(
            username, fullname, AccountsService.UserAccountType.STANDARD
        )
        if user is None:
            return None

        # Set password
        user.set_password(password, "")

        # Add to supervised group via privileged helper
        subprocess.run(
            ["pkexec", self.GROUP_HELPER, "add", username],
            check=True,
            timeout=30,
        )

        return user

    def remove_supervised_status(self, user: AccountsService.User) -> None:
        """Remove a user from the supervised group (promote to regular)."""
        subprocess.run(
            ["pkexec", self.GROUP_HELPER, "remove", user.get_user_name()],
            check=False,
            timeout=30,
        )

    def add_supervised_status(self, user: AccountsService.User) -> None:
        """Add a user to the supervised group."""
        subprocess.run(
            ["pkexec", self.GROUP_HELPER, "add", user.get_user_name()],
            check=True,
            timeout=30,
        )

    def delete_user(self, uid: int, remove_files: bool = False) -> bool:
        """Delete a user account."""
        user = self.get_user_by_uid(uid)
        if user is None:
            return False
        return self._manager.delete_user(user, remove_files)
