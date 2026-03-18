"""App filter page — manage per-user app access."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from big_parental_controls.core.constants import GROUP_HELPER
from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.services.malcontent_service import MalcontentService
from big_parental_controls.services import desktop_hide_service
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class AppFilterPage(Gtk.Box):
    """Page for managing per-user app access control."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None
        self._selected_uid: int | None = None
        self._selected_username: str | None = None
        self._pending_changes: dict[str, bool] = {}
        self._app_rows: dict[str, Adw.SwitchRow] = {}
        self._build_ui()

    def _build_ui(self) -> None:
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

        # User selector
        selector_group = Adw.PreferencesGroup()
        self._user_combo = Adw.ComboRow()
        self._user_combo.set_title(_("User"))
        self._user_model = Gtk.StringList()
        self._user_combo.set_model(self._user_model)
        self._user_combo.connect("notify::selected", self._on_user_changed)
        selector_group.add(self._user_combo)
        inner.append(selector_group)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("application-x-executable-symbolic")
        self._empty_status.set_title(_("Select a User"))
        self._empty_status.set_description(_("Choose a supervised user to manage app access."))
        inner.append(self._empty_status)

        # Apps group
        self._apps_group = Adw.PreferencesGroup()
        self._apps_group.set_title(_("Installed Apps"))
        self._apps_group.set_visible(False)
        inner.append(self._apps_group)

        # Apply button
        self._apply_btn = Gtk.Button(label=_("Apply Changes"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.set_halign(Gtk.Align.END)
        self._apply_btn.connect("clicked", self._on_apply)
        inner.append(self._apply_btn)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

        self._populate_user_combo()

    def _populate_user_combo(self) -> None:
        """Populate user dropdown with supervised users."""
        self._supervised_users = []
        self._user_model.splice(0, self._user_model.get_n_items(), [])

        for user in self._accounts.list_users():
            if self._accounts.is_supervised(user):
                self._supervised_users.append(user)
                label = user.get_real_name() or user.get_user_name()
                self._user_model.append(label)

    def _on_user_changed(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._supervised_users):
            return

        user = self._supervised_users[idx]
        self._selected_uid = user.get_uid()
        self._selected_username = user.get_user_name()
        self._empty_status.set_visible(False)
        self._apps_group.set_visible(True)
        self._pending_changes.clear()
        self._apply_btn.set_sensitive(False)
        self._load_apps()

    def _load_apps(self) -> None:
        """Load installed apps and their blocked status."""
        # Clear rows
        while True:
            child = self._apps_group.get_first_child()
            if child is None:
                break
            if not isinstance(child, Adw.SwitchRow):
                child = child.get_next_sibling()
                if child is None:
                    break
                continue
            self._apps_group.remove(child)

        self._app_rows.clear()

        if self._selected_uid is None:
            return

        for app_info in Gio.AppInfo.get_all():
            if not app_info.should_show():
                continue
            exe = app_info.get_executable()
            if not exe:
                continue

            name = app_info.get_display_name()
            app_id = app_info.get_id() or exe

            allowed = True
            if self._malcontent:
                allowed = self._malcontent.is_appinfo_allowed(self._selected_uid, app_info)

            row = Adw.SwitchRow()
            row.set_title(name)
            row.set_subtitle(exe)
            row.set_active(allowed)
            row.connect("notify::active", self._on_app_toggled, app_id, exe)

            icon = app_info.get_icon()
            if icon:
                img = Gtk.Image.new_from_gicon(icon)
                img.set_pixel_size(32)
                row.add_prefix(img)

            self._apps_group.add(row)
            self._app_rows[app_id] = row

    def _on_app_toggled(
        self, row: Adw.SwitchRow, _pspec: object, app_id: str, exe: str
    ) -> None:
        self._pending_changes[exe] = row.get_active()
        self._apply_btn.set_sensitive(True)

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply pending changes via ACL batch."""
        if not self._selected_username or not self._pending_changes:
            return

        username = self._selected_username
        block_paths = [path for path, allowed in self._pending_changes.items() if not allowed]
        unblock_paths = [path for path, allowed in self._pending_changes.items() if allowed]

        def do_apply() -> None:
            import subprocess

            block_csv = ",".join(block_paths) if block_paths else ""
            unblock_csv = ",".join(unblock_paths) if unblock_paths else ""
            subprocess.run(
                ["pkexec", GROUP_HELPER, "acl-batch", username, block_csv, unblock_csv],
                check=True,
                timeout=60,
            )
            for path in block_paths:
                desktop_hide_service.hide_app(username, path)
            for path in unblock_paths:
                desktop_hide_service.unhide_app(username, path)

        def on_done(_result: object) -> None:
            self._pending_changes.clear()
            self._apply_btn.set_sensitive(False)
            self._show_success(_("App access updated."))

        def on_error(exc: Exception) -> None:
            self._show_error(str(exc))

        run_async(do_apply, on_done, on_error)

    def _show_success(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def refresh(self) -> None:
        """Refresh user list and app list."""
        self._populate_user_combo()
