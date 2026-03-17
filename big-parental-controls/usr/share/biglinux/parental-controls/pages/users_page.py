"""Users page — list, create, and manage supervised accounts."""

import os
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from services.accounts_service import AccountsServiceWrapper
from services.malcontent_service import MalcontentService, OARS_PRESETS
from services import acl_service, desktop_hide_service, time_service
from utils.async_runner import run_async
from utils.i18n import setup_i18n

_ = setup_i18n()

# Age group keys → UI labels (translatable)
AGE_GROUPS = [
    ("child", lambda: _("Child (under 10)")),
    ("preteen", lambda: _("Pre-teen (10–13)")),
    ("teen", lambda: _("Teen (13–16)")),
    ("young-adult", lambda: _("Young adult (16–18)")),
]


class UsersPage(Gtk.Box):
    """Page for managing user accounts and supervised profiles."""

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)

        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None

        self._is_admin = self._check_current_user_admin()
        self._build_ui()
        self.refresh_users()

    def _check_current_user_admin(self) -> bool:
        """Check if the current user is an administrator."""
        uid = os.getuid()
        user = self._accounts.get_user_by_uid(uid)
        if user is None:
            return False
        return self._accounts.is_admin(user) and not self._accounts.is_supervised(user)

    def _build_ui(self):
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        # Description
        desc = Gtk.Label(
            label=_(
                "Supervised accounts have extra protections to keep children safe. "
                "Only a parent or guardian can change these settings."
            )
        )
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        desc.set_hexpand(True)
        desc.add_css_class("dim-label")

        inner.append(desc)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("system-users-symbolic")
        self._empty_status.set_title(_("No Supervised Accounts"))
        self._empty_status.set_description(
            _("Create a supervised account so a child can use this computer safely.")
        )
        self._empty_status.set_visible(False)
        inner.append(self._empty_status)

        # User list
        self._users_list = Gtk.ListBox()
        self._users_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._users_list.add_css_class("boxed-list")
        inner.append(self._users_list)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def refresh_users(self):
        """Reload the user list from AccountsService."""
        while True:
            row = self._users_list.get_row_at_index(0)
            if row is None:
                break
            self._users_list.remove(row)

        users = self._accounts.list_users()
        has_users = bool(users)
        self._empty_status.set_visible(not has_users)
        self._users_list.set_visible(has_users)

        for user in users:
            row = self._create_user_row(user)
            self._users_list.append(row)

    def _delayed_refresh(self, select_username: str | None = None):
        """Refresh after AccountsService D-Bus propagation."""
        self.refresh_users()
        window = self.get_root()
        if hasattr(window, "refresh_user_dropdown"):
            window.refresh_user_dropdown(select_username)
        return GLib.SOURCE_REMOVE

    def _create_user_row(self, user):
        """Create an Adw.ActionRow for a user account."""
        row = Adw.ActionRow()
        row.set_title(user.get_real_name() or user.get_user_name())
        row.set_subtitle(user.get_user_name())

        # Icon
        icon_name = "system-users-symbolic"
        is_supervised = self._accounts.is_supervised(user)
        is_admin = self._accounts.is_admin(user)

        if is_supervised:
            icon_name = "emblem-readonly-symbolic"
            badge_text = _("Supervised")
        elif is_admin:
            icon_name = "starred-symbolic"
            badge_text = _("Administrator")
        else:
            badge_text = _("Standard")

        prefix_icon = Gtk.Image(icon_name=icon_name, pixel_size=32,
                               accessible_role=Gtk.AccessibleRole.PRESENTATION)
        row.add_prefix(prefix_icon)

        # Badge label
        badge = Gtk.Label(label=badge_text)
        if is_supervised:
            badge.add_css_class("accent")
        badge.add_css_class("caption")
        row.add_suffix(badge)

        # Edit button for supervised users
        if is_supervised:
            remove_btn = Gtk.Button(icon_name="user-trash-symbolic")
            remove_btn.set_valign(Gtk.Align.CENTER)
            remove_btn.set_tooltip_text(_("Remove supervised status"))
            remove_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("Remove supervised status")],
            )
            remove_btn.add_css_class("flat")
            remove_btn.connect(
                "clicked", self._on_remove_supervised, user
            )
            remove_btn.set_sensitive(self._is_admin)
            row.add_suffix(remove_btn)
        elif not is_admin:
            # Standard user — offer to make supervised
            supervise_btn = Gtk.Button(icon_name="emblem-readonly-symbolic")
            supervise_btn.set_valign(Gtk.Align.CENTER)
            supervise_btn.set_tooltip_text(_("Make supervised"))
            supervise_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("Make supervised")],
            )
            supervise_btn.add_css_class("flat")
            supervise_btn.connect(
                "clicked", self._on_make_supervised, user
            )
            supervise_btn.set_sensitive(self._is_admin)
            row.add_suffix(supervise_btn)

        return row

    def _on_add_clicked(self, button):
        """Show dialog to create a new supervised account."""
        if not self._is_admin:
            return
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Create Supervised Account"))
        dialog.set_body(
            _(
                "Create a new account with protections for a child or teenager. "
                "This account will have safe settings by default."
            )
        )

        # Build form content — single PreferencesGroup for HIG compliance
        form_group = Adw.PreferencesGroup()
        form_group.set_margin_top(12)

        username_row = Adw.EntryRow(title=_("Username"))
        username_row.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        form_group.add(username_row)

        fullname_row = Adw.EntryRow(title=_("Full Name"))
        form_group.add(fullname_row)

        password_row = Adw.PasswordEntryRow(title=_("Password"))
        form_group.add(password_row)

        confirm_row = Adw.PasswordEntryRow(title=_("Confirm Password"))
        form_group.add(confirm_row)

        # Inline mismatch label (hidden by default)
        mismatch_label = Gtk.Label(label=_("Passwords do not match."))
        mismatch_label.add_css_class("error")
        mismatch_label.add_css_class("caption")
        mismatch_label.set_halign(Gtk.Align.START)
        mismatch_label.set_margin_start(12)
        mismatch_label.set_visible(False)
        form_group.add(mismatch_label)

        def _update_create_sensitivity(*_args):
            pw = password_row.get_text()
            conf = confirm_row.get_text()
            user = username_row.get_text().strip()
            mismatch = bool(conf) and pw != conf
            mismatch_label.set_visible(mismatch)
            if mismatch:
                confirm_row.add_css_class("error")
            else:
                confirm_row.remove_css_class("error")
            # Enable Create only when form is valid
            can_create = bool(user) and bool(pw) and pw == conf
            dialog.set_response_enabled("create", can_create)

        username_row.connect("changed", _update_create_sensitivity)
        password_row.connect("changed", _update_create_sensitivity)
        confirm_row.connect("changed", _update_create_sensitivity)

        age_combo = Adw.ComboRow(title=_("Age group"))
        age_labels = [fn() for _, fn in AGE_GROUPS]
        age_combo.set_model(Gtk.StringList.new(age_labels))
        age_combo.set_selected(0)
        form_group.add(age_combo)

        dialog.set_extra_child(form_group)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("create", False)  # disabled until form valid

        dialog.connect(
            "response",
            self._on_create_response,
            username_row,
            fullname_row,
            password_row,
            confirm_row,
            age_combo,
        )

        window = self.get_root()
        dialog.present(window)

    def _on_create_response(
        self, dialog, response, username_row, fullname_row, password_row, confirm_row, age_combo
    ):
        if response != "create":
            return

        username = username_row.get_text().strip()
        fullname = fullname_row.get_text().strip()
        password = password_row.get_text()
        confirm = confirm_row.get_text()

        if not username or not password:
            self._show_error(_("Username and password are required."))
            return

        if len(username) > 32:
            self._show_error(_("Username must be 32 characters or less."))
            return

        if password != confirm:
            self._show_error(_("Passwords do not match."))
            return

        # Validate username (only lowercase, numbers, hyphens)
        import re
        if not re.match(r"^[a-z][a-z0-9_-]*$", username):
            self._show_error(
                _("Username must start with a lowercase letter and contain only letters, numbers, hyphens, and underscores.")
            )
            return

        # Check if username already exists
        import pwd
        try:
            pwd.getpwnam(username)
            self._show_error(_("A user named '%s' already exists.") % username)
            return
        except KeyError:
            pass  # Good — user does not exist

        # Single pkexec call: creates user + group + ACLs + noexec + desktop hiding
        # Password is written to a temp file (mode 0600) — pkexec cannot forward stdin.
        # The helper reads it and deletes it immediately.
        import tempfile
        pw_fd, pw_path = tempfile.mkstemp(prefix="bpc-pw-", dir="/tmp")
        try:
            os.write(pw_fd, password.encode())
            os.close(pw_fd)
            os.chmod(pw_path, 0o600)
        except OSError:
            os.close(pw_fd)
            os.unlink(pw_path)
            self._show_error(_("Failed to prepare credentials."))
            return

        # Show loading overlay
        loading_dialog = Adw.AlertDialog()
        loading_dialog.set_heading(_("Creating account…"))
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        spinner.set_halign(Gtk.Align.CENTER)
        loading_dialog.set_extra_child(spinner)
        loading_dialog.set_close_response("")
        window = self.get_root()
        loading_dialog.present(window)

        def _do_create():
            try:
                return subprocess.run(
                    ["pkexec", acl_service.GROUP_HELPER, "create-full", username, fullname or username, pw_path],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            finally:
                # Safety net: remove temp file if helper didn't
                try:
                    os.unlink(pw_path)
                except FileNotFoundError:
                    pass

        def _on_created(result):
            loading_dialog.force_close()

            if result.returncode != 0:
                # pkexec-specific exit codes
                if result.returncode == 126:
                    self._show_error(_("Authentication was cancelled."))
                    return
                if result.returncode == 127:
                    self._show_error(_("Helper script not found. Is the package installed correctly?"))
                    return
                detail = (result.stderr or result.stdout or "").strip()
                if not detail:
                    detail = _("Exit code %d") % result.returncode
                self._show_error(
                    _("Failed to create user account: %s") % detail
                )
                return

            # Wait for AccountsService to detect the new user
            GLib.timeout_add(1200, self._delayed_refresh, username)

            # Set Malcontent OARS filter (D-Bus, no pkexec)
            if self._malcontent:
                # Get UID of new user
                import pwd
                try:
                    uid = pwd.getpwnam(username).pw_uid
                except KeyError:
                    return

                age_idx = age_combo.get_selected()
                age_key = AGE_GROUPS[age_idx][0] if age_idx < len(AGE_GROUPS) else "child"
                oars = OARS_PRESETS.get(age_key, OARS_PRESETS["child"])

                self._malcontent.set_app_filter(
                    uid,
                    blocked_paths=[
                        "/usr/bin/big-store",
                        "/usr/bin/pamac-manager",
                        "/usr/bin/pamac-installer",
                    ],
                    oars_values=oars,
                    allow_user_installation=False,
                    allow_system_installation=False,
                )

        def _on_error(e):
            loading_dialog.force_close()
            self._show_error(str(e))

        run_async(
            _do_create,
            callback=_on_created,
            error_callback=_on_error,
        )

    def _apply_enforcement(self, username: str, uid: int | None = None) -> None:
        """Apply default ACL blocks, noexec, and OARS sync for a supervised user."""
        acl_service.apply_default_blocks(username)
        # Hide blocked apps from menu
        for path in acl_service.DEFAULT_SUPERVISED_BLOCKS:
            if os.path.exists(path):
                desktop_hide_service.hide_app(username, path)
        # Enable noexec on home directory
        try:
            subprocess.run(
                ["pkexec", acl_service.GROUP_HELPER, "noexec-enable", username],
                check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError:
            pass
        # Sync OARS-blocked apps to ACLs
        if uid is not None and self._malcontent:
            try:
                blocked_apps = self._malcontent.get_oars_blocked_apps(uid)
                acl_service.sync_oars_enforcement(username, blocked_apps)
                for app_info in blocked_apps:
                    exe = app_info.get_executable()
                    if exe:
                        desktop_hide_service.hide_app(username, exe)
            except (GLib.Error, OSError) as e:
                import logging
                logging.getLogger(__name__).warning("OARS sync failed: %s", e)
        # Enable noexec on /tmp and /dev/shm (system-wide, affects all users)
        try:
            subprocess.run(
                ["pkexec", acl_service.GROUP_HELPER, "noexec-tmp-enable"],
                check=True,
                timeout=30,
            )
        except subprocess.CalledProcessError:
            pass

    def _remove_enforcement(self, username: str) -> None:
        """Remove all enforcement for a user when removing supervision."""
        acl_service.unblock_all(username)
        desktop_hide_service.unhide_all(username)
        time_service.remove_all(username)
        # noexec-disable is batched into the group-helper call that also
        # removes the user from the supervised group, so we skip it here
        # to avoid a double pkexec prompt.

    def _on_remove_supervised(self, button, user):
        """Remove supervised status from user."""
        if not self._is_admin:
            return
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Remove Supervised Account"))
        dialog.set_body(
            _(
                "What would you like to do with %s's account?\n\n"
                "• <b>Remove restrictions</b> keeps the account but removes all parental protections.\n"
                "• <b>Delete account</b> permanently removes the account and all their files."
            ) % GLib.markup_escape_text(user.get_real_name())
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("unsupervise", _("Remove Restrictions"))
        dialog.add_response("delete", _("Delete Account"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response, user)
        dialog.present(self.get_root())

    def _on_remove_response(self, dialog, response, user):
        if response not in ("unsupervise", "delete"):
            return
        username = user.get_user_name()
        uid = user.get_uid()

        if self._malcontent:
            self._malcontent.clear_app_filter(uid)

        def _do_remove():
            # Single pkexec call handles everything:
            # ACLs, desktop unhide, time, group removal, noexec, /tmp cleanup
            subprocess.run(
                ["pkexec", acl_service.GROUP_HELPER, "remove-full", username],
                check=True,
                timeout=60,
            )

        def _on_removed(_result):
            if response == "delete":
                self._accounts.delete_user(uid, remove_files=True)
            GLib.timeout_add(800, self._delayed_refresh)

        run_async(
            _do_remove,
            callback=_on_removed,
            error_callback=lambda e: self._show_error(str(e)),
        )

    def refresh(self):
        """Public refresh (called on navigation)."""
        self.refresh_users()

    def _on_make_supervised(self, button, user):
        """Add supervised status to existing user."""
        if not self._is_admin:
            return
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Add Supervision"))
        dialog.set_body(
            _("Add protections to %s? Installing apps and changing settings will require a parent's permission.") % user.get_real_name()
        )

        # Age group selector
        age_group = Adw.PreferencesGroup()
        age_group.set_margin_top(12)
        age_combo = Adw.ComboRow(title=_("Age group"))
        age_labels = [fn() for _, fn in AGE_GROUPS]
        age_combo.set_model(Gtk.StringList.new(age_labels))
        age_combo.set_selected(0)
        age_group.add(age_combo)
        dialog.set_extra_child(age_group)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("supervise", _("Add Controls"))
        dialog.set_response_appearance("supervise", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_supervise_response, user, age_combo)
        dialog.present(self.get_root())

    def _on_supervise_response(self, dialog, response, user, age_combo):
        if response != "supervise":
            return

        username = user.get_user_name()
        uid = user.get_uid()

        def _do_enforce():
            # Single pkexec: adds to group + ACLs + desktop hiding + noexec
            subprocess.run(
                ["pkexec", acl_service.GROUP_HELPER, "enforce-defaults", username],
                check=True,
                timeout=60,
            )

        def _on_enforced(_result):
            # Set Malcontent OARS filter (D-Bus, no pkexec)
            if self._malcontent:
                age_idx = age_combo.get_selected()
                age_key = AGE_GROUPS[age_idx][0] if age_idx < len(AGE_GROUPS) else "child"
                oars = OARS_PRESETS.get(age_key, OARS_PRESETS["child"])

                self._malcontent.set_app_filter(
                    uid,
                    blocked_paths=[
                        "/usr/bin/big-store",
                        "/usr/bin/pamac-manager",
                        "/usr/bin/pamac-installer",
                    ],
                    oars_values=oars,
                    allow_user_installation=False,
                    allow_system_installation=False,
                )

            GLib.timeout_add(800, self._delayed_refresh, username)

        run_async(
            _do_enforce,
            callback=_on_enforced,
            error_callback=lambda e: self._show_error(_("Failed to apply supervised controls.")),
        )

    def _show_error(self, message: str):
        """Show an error dialog."""
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)
