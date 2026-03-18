"""Users page — manage supervised accounts."""

import subprocess
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from big_parental_controls.core.constants import GROUP_HELPER
from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.services import acl_service
from big_parental_controls.services.malcontent_service import MalcontentService, OARS_PRESETS
from big_parental_controls.services import time_service
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


def _save_user_age_profile(username: str, age_range: str) -> None:
    """Persist ECA Digital age range via group-helper (requires root)."""
    try:
        subprocess.run(
            ["pkexec", GROUP_HELPER, "set-age-profile", username, age_range],
            check=False,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


class UsersPage(Gtk.Box):
    """Page for creating, removing, and managing supervised accounts."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None
        self._sup_rows: list[Adw.ActionRow] = []
        self._other_rows: list[Adw.ActionRow] = []
        self._build_ui()
        self._refresh_users()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

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

        # Prominent create button — visible and clear for all users
        create_group = Adw.PreferencesGroup()
        self._add_btn = Adw.ButtonRow()
        self._add_btn.set_title(_("Create Supervised User"))
        self._add_btn.set_start_icon_name("list-add-symbolic")
        self._add_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Create supervised user")]
        )
        self._add_btn.connect("activated", self._on_create_clicked)
        create_group.add(self._add_btn)
        inner.append(create_group)

        self._all_group = Adw.PreferencesGroup()
        self._all_group.set_title(_("Other Users"))
        self._all_group.set_description(_("Add supervision to an existing account."))

        inner.append(self._all_group)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)

        self._overlay = Gtk.Overlay()
        self._overlay.set_child(toolbar)
        self.append(self._overlay)

    def _refresh_users(self) -> None:
        """Reload the list of unsupervised users."""
        for row in self._other_rows:
            self._all_group.remove(row)
        self._sup_rows.clear()
        self._other_rows.clear()

        users = self._accounts.list_users()
        for user in users:
            is_sup = self._accounts.is_supervised(user)
            is_adm = self._accounts.is_admin(user)
            if is_sup or is_adm:
                continue

            row = Adw.ActionRow()
            row.set_title(user.get_real_name() or user.get_user_name())
            row.set_subtitle(user.get_user_name())

            icon = Gtk.Image(
                icon_name="avatar-default-symbolic",
                pixel_size=32,
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
            )
            row.add_prefix(icon)

            add_btn = Gtk.Button(icon_name="list-add-symbolic")
            add_btn.add_css_class("flat")
            add_btn.set_valign(Gtk.Align.CENTER)
            add_btn.set_tooltip_text(_("Add supervision"))
            add_btn.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [_("Add supervision to %s") % user.get_user_name()],
            )
            add_btn.connect("clicked", self._on_add_supervised, user)
            row.add_suffix(add_btn)

            self._all_group.add(row)
            self._other_rows.append(row)

    def _on_create_clicked(self, _button: Gtk.Button) -> None:
        """Show dialog to create a new supervised user."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Create Supervised User"))
        dialog.set_body(_("Set up a new supervised account on this computer."))

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)

        group = Adw.PreferencesGroup()

        username_row = Adw.EntryRow()
        username_row.set_title(_("Username"))
        group.add(username_row)

        fullname_row = Adw.EntryRow()
        fullname_row.set_title(_("Full Name"))
        group.add(fullname_row)

        password_row = Adw.PasswordEntryRow()
        password_row.set_title(_("Password"))
        group.add(password_row)

        confirm_row = Adw.PasswordEntryRow()
        confirm_row.set_title(_("Confirm Password"))
        group.add(confirm_row)

        age_row = Adw.ComboRow()
        age_row.set_title(_("Age Group"))
        age_model = Gtk.StringList.new(
            [_("Child (0–12)"), _("Adolescent (13–15)"), _("Adolescent (16–17)"), _("Adult (18+)")]
        )
        age_row.set_model(age_model)
        group.add(age_row)

        content.append(group)
        dialog.set_extra_child(content)

        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("create", _("Create"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_response_enabled("create", False)

        # Mirror state: while True, typing in username mirrors to fullname.
        # Set False the moment the user manually edits fullname.
        mirror = [True]
        fullname_hid: list[int | None] = [None]

        def _validate(*_args: object) -> None:
            uname = username_row.get_text().strip()
            pwd = password_row.get_text()
            conf = confirm_row.get_text()
            ok = bool(uname) and bool(pwd) and pwd == conf
            dialog.set_response_enabled("create", ok)
            if pwd and conf and pwd != conf:
                confirm_row.add_css_class("error")
            else:
                confirm_row.remove_css_class("error")

        def _on_username_changed(row: Adw.EntryRow) -> None:
            if mirror[0]:
                hid = fullname_hid[0]
                if hid is not None:
                    fullname_row.handler_block(hid)
                fullname_row.set_text(row.get_text())
                if hid is not None:
                    fullname_row.handler_unblock(hid)
            _validate()

        def _on_fullname_changed(row: Adw.EntryRow) -> None:
            # User manually typed in fullname → stop mirroring.
            # If they clear it → resume mirroring.
            mirror[0] = not bool(row.get_text())
            _validate()

        username_row.connect("changed", _on_username_changed)
        fullname_hid[0] = fullname_row.connect("changed", _on_fullname_changed)
        password_row.connect("changed", _validate)
        confirm_row.connect("changed", _validate)

        dialog.connect(
            "response",
            self._on_create_response,
            username_row,
            fullname_row,
            password_row,
            confirm_row,
            age_row,
        )
        dialog.present(self.get_root())

    def _on_create_response(
        self,
        dialog: Adw.AlertDialog,
        response: str,
        username_row: Adw.EntryRow,
        fullname_row: Adw.EntryRow,
        password_row: Adw.PasswordEntryRow,
        confirm_row: Adw.PasswordEntryRow,
        age_row: Adw.ComboRow,
    ) -> None:
        if response != "create":
            return

        username = username_row.get_text().strip()
        fullname = fullname_row.get_text().strip()
        password = password_row.get_text()

        if not username or not password:
            self._show_error(_("Username and password are required."))
            return

        # ECA Digital age ranges: 0-12, 13-15, 16-17, 18+
        eca_ranges = ["0-12", "13-15", "16-17", "18+"]
        # Map ECA range to malcontent OARS preset
        oars_map = {"0-12": "child", "13-15": "preteen", "16-17": "teen", "18+": "young-adult"}
        age_range = eca_ranges[age_row.get_selected()]
        age_group = oars_map[age_range]

        loading = self._show_loading_overlay(_("Creating user %s…") % username)
        self._add_btn.set_sensitive(False)

        def do_create() -> str:
            user = self._accounts.create_supervised_user(username, fullname, password)
            if user is None:
                raise RuntimeError(_("Failed to create user."))

            if self._malcontent and age_group in OARS_PRESETS:
                try:
                    self._malcontent.set_app_filter(
                        user.get_uid(),
                        oars_values=OARS_PRESETS[age_group],
                    )
                except Exception:  # noqa: BLE001 — malcontent D-Bus is optional
                    pass
            _save_user_age_profile(user.get_user_name(), age_range)
            return username

        def on_done(result: str) -> None:
            self._hide_loading_overlay(loading)
            self._add_btn.set_sensitive(True)
            window = self.get_root()
            if hasattr(window, "refresh_main_and_pop"):
                window.refresh_main_and_pop()
                window.show_toast(_("User %s created.") % result)
            else:
                self._refresh_users()
                self._show_success(_("User %s created.") % result)

        def on_error(exc: Exception) -> None:
            self._hide_loading_overlay(loading)
            self._add_btn.set_sensitive(True)
            self._show_error(str(exc))

        run_async(do_create, on_done, on_error)

    def _on_remove_supervised(self, _button: Gtk.Button, user: object) -> None:
        """Confirm and remove supervised status from user."""
        username = user.get_user_name()
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Remove Supervision"))
        dialog.set_body(
            _("Remove all restrictions from %s? This cannot be undone.") % username
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_remove_response, user)
        dialog.present(self.get_root())

    def _on_remove_response(
        self, dialog: Adw.AlertDialog, response: str, user: object
    ) -> None:
        if response != "remove":
            return

        username = user.get_user_name()
        uid = user.get_uid()

        def do_remove() -> str:
            self._accounts.remove_supervised_status(user)
            acl_service.unblock_all(username)
            time_service.remove_all(username)
            if self._malcontent:
                try:
                    self._malcontent.clear_app_filter(uid)
                except Exception:  # noqa: BLE001 — malcontent D-Bus is optional
                    pass
            return username

        def on_done(result: str) -> None:
            self._refresh_users()
            self._show_success(_("Supervision removed from %s.") % result)

        def on_error(exc: Exception) -> None:
            self._show_error(str(exc))

        run_async(do_remove, on_done, on_error)

    def _on_add_supervised(self, _button: Gtk.Button, user: object) -> None:
        """Add supervised status to an existing user."""
        username = user.get_user_name()
        loading = self._show_loading_overlay(_("Adding supervision…"))

        def do_add() -> str:
            self._accounts.add_supervised_status(user)
            acl_service.apply_default_blocks(username)
            return username

        def on_done(result: str) -> None:
            self._hide_loading_overlay(loading)
            window = self.get_root()
            if hasattr(window, "refresh_main_and_pop"):
                window.refresh_main_and_pop()
                window.show_toast(_("%s is now supervised.") % result)
            else:
                self._refresh_users()
                self._show_success(_("%s is now supervised.") % result)

        def on_error(exc: Exception) -> None:
            self._hide_loading_overlay(loading)
            self._show_error(str(exc))

        run_async(do_add, on_done, on_error)

    def _show_success(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def _show_loading_overlay(self, message: str) -> Gtk.Box:
        """Overlay the entire page with a semi-transparent loading screen."""
        backdrop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        backdrop.add_css_class("bpc-loading-overlay")
        backdrop.set_hexpand(True)
        backdrop.set_vexpand(True)

        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        center.set_hexpand(True)
        center.set_vexpand(True)

        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        spinner.set_size_request(48, 48)
        spinner.set_halign(Gtk.Align.CENTER)
        center.append(spinner)

        lbl = Gtk.Label(label=message)
        lbl.add_css_class("title-3")
        center.append(lbl)

        backdrop.append(center)
        self._overlay.add_overlay(backdrop)
        return backdrop

    def _hide_loading_overlay(self, widget: Gtk.Box) -> None:
        self._overlay.remove_overlay(widget)

    def refresh(self) -> None:
        """Refresh the user list."""
        self._refresh_users()
