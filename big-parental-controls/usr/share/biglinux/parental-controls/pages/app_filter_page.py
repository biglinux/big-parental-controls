"""App filter page — manage allowed/blocked applications for supervised users."""

import shutil
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from services.accounts_service import AccountsServiceWrapper
from services.malcontent_service import MalcontentService
from services import acl_service
from utils.async_runner import run_async
from utils.i18n import setup_i18n

_ = setup_i18n()


class AppFilterPage(Gtk.Box):
    """Page for managing per-user application access controls.

    Changes are collected locally and applied in a single batch
    via the Apply button (one pkexec call for ACL + desktop hiding).
    """

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)

        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None

        self._selected_uid = None
        self._selected_username = None
        self._toggling = False
        # Pending changes: {full_path: True (allow) | False (block)}
        self._pending: dict[str, bool] = {}
        self._build_ui()

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

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("application-x-executable-symbolic")
        self._empty_status.set_title(_("No Supervised Accounts"))
        self._empty_status.set_description(
            _("Create one in the Users page to get started.")
        )
        self._empty_status.set_visible(True)
        inner.append(self._empty_status)

        # App list
        self._app_list = Gtk.ListBox()
        self._app_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._app_list.add_css_class("boxed-list")
        self._app_list.set_visible(False)
        inner.append(self._app_list)

        # Apply button — shown only when there are pending changes
        self._apply_box = Gtk.Box()
        self._apply_box.set_halign(Gtk.Align.END)
        self._apply_box.set_visible(False)

        self._apply_btn = Gtk.Button(label=_("Apply"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.connect("clicked", self._on_apply)
        self._apply_box.append(self._apply_btn)
        inner.append(self._apply_box)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def set_selected_user(self, user):
        """Called by window when the header dropdown selection changes."""
        # Discard pending if switching users
        self._pending.clear()
        self._apply_box.set_visible(False)

        if user is None:
            self._selected_uid = None
            self._selected_username = None
            self._empty_status.set_visible(True)
            self._app_list.set_visible(False)
            return

        self._selected_uid = user.get_uid()
        self._selected_username = user.get_user_name()
        self._empty_status.set_visible(False)
        self._app_list.set_visible(True)
        self._refresh_app_list()

    def _refresh_app_list(self):
        """Refresh the application list for the selected user."""
        while True:
            row = self._app_list.get_row_at_index(0)
            if row is None:
                break
            self._app_list.remove(row)

        if self._selected_uid is None or self._malcontent is None:
            return

        try:
            app_filter = self._malcontent.get_app_filter(self._selected_uid)
        except GLib.Error:
            app_filter = None

        apps = Gio.AppInfo.get_all()
        apps.sort(key=lambda a: (a.get_display_name() or "").lower())

        for app_info in apps:
            if not app_info.should_show():
                continue

            executable = app_info.get_executable()
            if not executable:
                continue

            is_blocked = False
            if app_filter:
                is_blocked = not app_filter.is_appinfo_allowed(app_info)

            row = Adw.SwitchRow()
            row.set_title(app_info.get_display_name() or executable)
            row.set_active(not is_blocked)

            icon = app_info.get_icon()
            if icon:
                img = Gtk.Image.new_from_gicon(icon)
                img.set_pixel_size(32)
                row.add_prefix(img)

            full_path = executable if executable.startswith("/") else (shutil.which(executable) or executable)
            row.connect("notify::active", self._on_app_toggled, full_path)
            self._app_list.append(row)

    def _on_app_toggled(self, row, pspec, full_path):
        """Record pending change — no immediate pkexec call."""
        if self._toggling:
            return

        allowed = row.get_active()
        self._pending[full_path] = allowed
        self._apply_box.set_visible(bool(self._pending))

    def _on_apply(self, button):
        """Apply all pending changes in a single batch."""
        if not self._pending or not self._selected_username or self._selected_uid is None:
            return

        username = self._selected_username

        # Separate into block and unblock lists
        to_block = [p for p, allowed in self._pending.items() if not allowed]
        to_unblock = [p for p, allowed in self._pending.items() if allowed]

        # 1. Update Malcontent app filter (D-Bus, no pkexec)
        if self._malcontent:
            try:
                current = self._malcontent.get_app_filter(self._selected_uid)

                # Build full blocked list
                apps = Gio.AppInfo.get_all()
                blocked_paths = []
                for app_info in apps:
                    exe = app_info.get_executable()
                    if not exe:
                        continue
                    p = exe if exe.startswith("/") else (shutil.which(exe) or exe)
                    if p and not current.is_path_allowed(p):
                        blocked_paths.append(p)

                # Apply pending changes
                for path in to_unblock:
                    blocked_paths = [p for p in blocked_paths if p != path]
                for path in to_block:
                    if path not in blocked_paths:
                        blocked_paths.append(path)

                # Preserve OARS
                oars_values = {}
                for section in current.get_oars_sections():
                    oars_values[section] = current.get_oars_value(section)

                self._malcontent.set_app_filter(
                    self._selected_uid,
                    blocked_paths=blocked_paths,
                    oars_values=oars_values if oars_values else None,
                    allow_user_installation=current.is_user_installation_allowed(),
                    allow_system_installation=current.is_system_installation_allowed(),
                )
            except GLib.Error:
                self._show_error(_("Failed to update app filter."))
                return

        # 2. Single pkexec: ACL + desktop hide/unhide
        block_csv = ",".join(to_block) if to_block else ""
        unblock_csv = ",".join(to_unblock) if to_unblock else ""

        def _do_acl_batch():
            subprocess.run(
                [
                    "pkexec", acl_service.GROUP_HELPER,
                    "acl-batch", username, block_csv, unblock_csv,
                ],
                check=True,
                timeout=60,
            )

        def _on_acl_done(_result):
            self._pending.clear()
            self._apply_box.set_visible(False)
            window = self.get_root()
            if hasattr(window, "show_toast"):
                window.show_toast(_("App permissions updated."))

        run_async(
            _do_acl_batch,
            callback=_on_acl_done,
            error_callback=lambda e: self._show_error(_("Failed to apply file permissions.")),
        )

    def _show_error(self, message: str):
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def refresh(self):
        """Refresh app list for the current user (called on navigation)."""
        if self._selected_uid is not None:
            self._refresh_app_list()
