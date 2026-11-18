"""User detail page — all settings and activity for a single supervised user."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.daemon_client.client import DaemonClient
from big_parental_controls.services import age_defaults, age_profile
from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.ui.compliance import (
    confirm_delete_data,
    show_consent_dialog,
    start_export_data,
)
from big_parental_controls.ui.widgets.activity_block import ActivityBlock
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()

class UserDetailPage(Gtk.Box):
    """All settings and activity graphs for a single supervised user."""

    def __init__(self, user: object, window: object, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._user = user
        self._window = window
        self._username: str = user.get_user_name()
        self._uid: int = user.get_uid()
        self._accounts = AccountsServiceWrapper()
        self._daemon = DaemonClient()

        session_user = self._accounts.get_user_by_uid(os.getuid())
        self._session_is_admin: bool = (
            session_user is None or not self._accounts.is_supervised(session_user)
        )

        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(700)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        inner.append(self._build_summary_block())
        inner.append(self._build_profile_block())
        inner.append(self._build_app_filter_block())
        inner.append(self._build_dns_block())
        inner.append(self._build_time_block())

        # Activity block (charts + sessions)
        self._activity_block = ActivityBlock()
        inner.append(self._activity_block)

        inner.append(self._build_actions_block())

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)

        self._overlay = Gtk.Overlay()
        self._overlay.set_child(toolbar)
        self.append(self._overlay)

        self._activity_block.load_user(self._username)

    def _show_loading_overlay(self) -> None:
        backdrop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        backdrop.add_css_class("bpc-loading-overlay")
        backdrop.set_valign(Gtk.Align.FILL)
        backdrop.set_halign(Gtk.Align.FILL)
        backdrop.set_hexpand(True)
        backdrop.set_vexpand(True)
        spinner = Gtk.Spinner()
        spinner.set_size_request(48, 48)
        spinner.set_halign(Gtk.Align.CENTER)
        spinner.set_valign(Gtk.Align.CENTER)
        spinner.start()
        backdrop.append(spinner)
        backdrop.set_can_target(True)
        self._loading_backdrop = backdrop
        self._overlay.add_overlay(backdrop)

    def _hide_loading_overlay(self) -> None:
        backdrop = getattr(self, "_loading_backdrop", None)
        if backdrop is not None:
            self._overlay.remove_overlay(backdrop)
            self._loading_backdrop = None

    def _build_summary_block(self) -> Adw.PreferencesGroup:
        """User info and online status."""
        group = Adw.PreferencesGroup()
        group.set_title(self._user.get_real_name() or self._username)

        status_row = Adw.ActionRow()
        status_row.set_title(_("Account"))
        status_row.set_subtitle(self._username)
        status_row.add_prefix(
            Gtk.Image(icon_name="avatar-default-symbolic")
        )
        group.add(status_row)
        return group

    def _build_profile_block(self) -> Adw.PreferencesGroup:
        """Age profile and activity data management."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Profile"))

        # Age range selector
        age_row = Adw.ComboRow()
        age_row.set_title(_("Age Group"))
        age_row.set_subtitle(_("ECA Digital classification"))
        age_model = Gtk.StringList.new(
            [_("Child (0\u201312)"), _("Adolescent (13\u201315)"), _("Adolescent (16\u201317)"), _("Adult (18+)")]
        )
        age_row.set_model(age_model)

        current = age_profile.read_age_range(self._username)
        age_row.set_selected(age_profile.ECA_RANGES.index(current))
        self._age_handler = age_row.connect("notify::selected", self._on_age_changed)
        group.add(age_row)

        if not age_profile.malcontent_available():
            oars_row = Adw.ActionRow()
            oars_row.set_title(_("Age-based app ratings unavailable"))
            oars_row.set_subtitle(
                _("Install the malcontent package to filter software stores by age.")
            )
            oars_row.add_prefix(Gtk.Image(icon_name="dialog-information-symbolic"))
            group.add(oars_row)

        # Delete Activity Data
        delete_row = Adw.ActionRow()
        delete_row.set_title(_("Delete Activity Data"))
        delete_row.set_subtitle(
            _("Permanently remove all collected data (LGPD Art. 18)")
        )
        delete_row.set_activatable(True)
        delete_row.add_css_class("error")
        delete_row.add_suffix(Gtk.Image(icon_name="user-trash-symbolic"))
        delete_row.connect("activated", self._on_delete_data)
        group.add(delete_row)

        # Export Activity Data
        export_row = Adw.ActionRow()
        export_row.set_title(_("Export Activity Data"))
        export_row.set_subtitle(
            _("Download data as JSON file (GDPR Art. 20)")
        )
        export_row.set_activatable(True)
        export_row.add_suffix(Gtk.Image(icon_name="document-save-symbolic"))
        export_row.connect("activated", self._on_export_data)
        group.add(export_row)

        return group

    def _build_monitoring_block(self) -> Adw.PreferencesGroup:
        """Toggle for process monitoring with consent dialog."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Monitoring"))
        group.set_description(
            _("Track which programs are used and for how long.")
        )

        banner = Adw.ActionRow()
        banner.set_title(_("Activity Monitoring"))
        banner.set_subtitle(
            _(
                "Usage data stays exclusively on this device. "
                "In accordance with ECA Digital, LGPD, UK Children's "
                "Code, and EU DSA, parents may review usage patterns. "
                "No data is transmitted externally."
            )
        )
        banner.add_prefix(
            Gtk.Image(icon_name="dialog-information-symbolic")
        )
        group.add(banner)

        self._monitor_switch = Adw.SwitchRow()
        self._monitor_switch.set_title(_("Enable monitoring"))
        self._monitor_switch.set_subtitle(
            _("Checks running programs every minute")
        )
        group.add(self._monitor_switch)

        delete_row = Adw.ActionRow()
        delete_row.set_title(_("Delete Activity Data"))
        delete_row.set_subtitle(
            _("Permanently remove all collected data (LGPD Art. 18)")
        )
        delete_row.set_activatable(True)
        delete_row.add_css_class("error")
        delete_row.add_suffix(
            Gtk.Image(icon_name="user-trash-symbolic")
        )
        delete_row.connect("activated", self._on_delete_data)
        group.add(delete_row)

        export_row = Adw.ActionRow()
        export_row.set_title(_("Export Activity Data"))
        export_row.set_subtitle(
            _("Download data as JSON file (GDPR Art. 20)")
        )
        export_row.set_activatable(True)
        export_row.add_suffix(
            Gtk.Image(icon_name="document-save-symbolic")
        )
        export_row.connect("activated", self._on_export_data)
        group.add(export_row)

        def fetch() -> bool:
            monitored = self._daemon.get_monitored_users()
            return self._username in monitored

        def on_done(is_monitored: bool) -> None:
            self._monitor_switch.set_active(is_monitored)
            if self._session_is_admin:
                self._monitor_switch.connect(
                    "notify::active", self._on_monitor_toggled
                )
            else:
                self._monitor_switch.set_sensitive(False)

        run_async(fetch, on_done)
        return group

    def _on_monitor_toggled(
        self, row: Adw.SwitchRow, _pspec: object
    ) -> None:
        if row.get_active():
            show_consent_dialog(
                window=self._window,
                user=self._user,
                on_accepted=self._do_enable_monitoring,
                on_rejected=self._revert_monitor_switch,
            )
        else:
            def disable() -> bool:
                return self._daemon.disable_user(self._username)
            run_async(disable, lambda _ok: None)

    def _do_enable_monitoring(self) -> None:
        def enable() -> bool:
            return self._daemon.enable_user(
                self._username, self._uid
            )
        run_async(enable, lambda _ok: None)

    def _revert_monitor_switch(self) -> None:
        self._monitor_switch.disconnect_by_func(
            self._on_monitor_toggled
        )
        self._monitor_switch.set_active(False)
        self._monitor_switch.connect(
            "notify::active", self._on_monitor_toggled
        )

    def _on_delete_data(self, _row: Adw.ActionRow) -> None:
        confirm_delete_data(self._window, self._username)

    def _on_export_data(self, _row: Adw.ActionRow) -> None:
        start_export_data(self._window, self._username)

    def _build_time_block(self) -> Adw.PreferencesGroup:
        """Screen time limits — link to full editor."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Screen Time"))
        edit_row = Adw.ActionRow()
        edit_row.set_title(_("Edit Time Limits"))
        edit_row.set_subtitle(
            _("Set allowed hours and daily duration")
        )
        edit_row.set_activatable(True)
        edit_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        edit_row.connect(
            "activated",
            lambda _r: self._window.show_time_limits(self._user),
        )
        group.add(edit_row)
        return group

    def _on_age_changed(self, row: Adw.ComboRow, _pspec: object) -> None:
        age_range = age_profile.ECA_RANGES[row.get_selected()]
        entry = age_defaults.load()[age_range]
        if not entry:
            self._save_age(row, age_range, {})
            return

        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Apply recommended settings?"))
        dialog.set_body(
            _("Recommended for this age group:")
            + "\n\n"
            + "\n".join(age_defaults.describe(entry))
            + "\n\n"
            + _("They replace the current settings of this user.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("age", _("Change Age Only"))
        dialog.add_response("apply", _("Apply"))
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("apply")
        dialog.set_close_response("cancel")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response == "cancel":
                self._show_stored_age(row)
            else:
                self._save_age(row, age_range, entry if response == "apply" else {})

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    def _show_stored_age(self, row: Adw.ComboRow) -> None:
        stored = age_profile.read_age_range(self._username)
        with row.handler_block(self._age_handler):
            row.set_selected(age_profile.ECA_RANGES.index(stored))

    def _save_age(self, row: Adw.ComboRow, age_range: str, recommended: dict) -> None:
        row.set_sensitive(False)

        def task() -> tuple[bool, list[str]]:
            saved = age_profile.write_age_range(self._username, age_range)
            if not saved:
                return False, []
            if age_profile.malcontent_available():
                from big_parental_controls.services.malcontent_service import (
                    MalcontentService,
                )

                age_profile.apply_oars_preset(MalcontentService(), self._uid, age_range)
            failed = age_defaults.apply(self._username, self._uid, recommended)
            return True, failed

        def done(result: tuple[bool, list[str]]) -> None:
            saved, failed = result
            row.set_sensitive(True)
            if not saved:
                # Show the stored value again (e.g. password dialog cancelled).
                self._show_stored_age(row)
                self._window.show_toast(_("Could not save the age group."))
            elif failed:
                self._window.show_toast(_("Some recommended settings could not be applied."))
            elif recommended:
                self._window.show_toast(_("Recommended settings applied."))

        run_async(task, done, lambda _exc: done((False, [])))

    def _build_app_filter_block(self) -> Adw.PreferencesGroup:
        """App access control — link to full editor."""
        group = Adw.PreferencesGroup()
        group.set_title(_("App Access"))
        edit_row = Adw.ActionRow()
        edit_row.set_title(_("Manage Allowed Apps"))
        edit_row.set_subtitle(
            _("Choose which applications this user can run")
        )
        edit_row.set_activatable(True)
        edit_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        edit_row.connect(
            "activated",
            lambda _r: self._window.show_app_filter(self._user),
        )
        group.add(edit_row)
        return group

    def _build_dns_block(self) -> Adw.PreferencesGroup:
        """Web filter — link to full editor."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Web Filter"))
        edit_row = Adw.ActionRow()
        edit_row.set_title(_("Edit Web Filter"))
        edit_row.set_subtitle(
            _("Choose DNS provider to block inappropriate content")
        )
        edit_row.set_activatable(True)
        edit_row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        edit_row.connect(
            "activated",
            lambda _r: self._window.show_dns_settings(self._user),
        )
        group.add(edit_row)
        return group

    def _build_actions_block(self) -> Adw.PreferencesGroup:
        """Destructive actions: remove supervision or delete user."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Account Actions"))

        remove_row = Adw.ActionRow()
        remove_row.set_title(_("Remove Supervision"))
        remove_row.set_subtitle(
            _("Keep the account but remove parental controls")
        )
        remove_row.set_activatable(True)
        remove_row.add_css_class("error")
        remove_row.connect("activated", self._on_remove_supervision)
        group.add(remove_row)

        delete_row = Adw.ActionRow()
        delete_row.set_title(_("Delete User"))
        delete_row.set_subtitle(
            _("Permanently remove the account and all data")
        )
        delete_row.set_activatable(True)
        delete_row.add_css_class("error")
        delete_row.connect("activated", self._on_delete_user)
        group.add(delete_row)

        return group

    def _on_remove_supervision(self, _row: Adw.ActionRow) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Remove Supervision?"))
        dialog.set_body(
            _("This will remove parental controls from %s. "
              "The account will remain but without restrictions.")
            % self._username
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance(
            "remove", Adw.ResponseAppearance.DESTRUCTIVE
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_remove_response)
        dialog.present(self._window)

    def _on_remove_response(
        self, dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "remove":
            return

        self._show_loading_overlay()

        username = self._username

        def do_remove() -> bool:
            return self._accounts.remove_from_supervised(username)

        def on_done(_ok: bool) -> None:
            self._hide_loading_overlay()
            self._window.refresh_main_and_pop()
            self._window.show_toast(
                _("Supervision removed from %s.") % username
            )

        run_async(do_remove, on_done)

    def _on_delete_user(self, _row: Adw.ActionRow) -> None:
        """First confirmation: ask if user should be deleted."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Delete User '%s'?") % self._username)
        dialog.set_body(
            _("This will permanently delete the account and the "
              "home folder with all files. This action cannot be undone.")
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete Permanently"))
        dialog.set_response_appearance(
            "delete", Adw.ResponseAppearance.DESTRUCTIVE
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_first_response)
        dialog.present(self._window)

    def _on_delete_first_response(
        self, _dialog: Adw.AlertDialog, response: str,
    ) -> None:
        if response != "delete":
            return
        # Second confirmation
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Are you sure?"))
        dialog.set_body(
            _("ALL data of user '%s' will be permanently erased, "
              "including documents, photos and settings. "
              "This action CANNOT be undone.") % self._username
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("confirm", _("Yes, delete everything"))
        dialog.set_response_appearance(
            "confirm", Adw.ResponseAppearance.DESTRUCTIVE
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_delete_final_response)
        dialog.present(self._window)

    def _on_delete_final_response(
        self, _dialog: Adw.AlertDialog, response: str,
    ) -> None:
        if response != "confirm":
            return

        self._show_loading_overlay()
        username = self._username
        uid = self._user.get_uid()

        def do_delete() -> bool:
            return self._accounts.delete_user(uid, remove_files=True)

        def on_done(ok: bool) -> None:
            self._hide_loading_overlay()
            if ok:
                self._window.refresh_main_and_pop()
                self._window.show_toast(
                    _("User '%s' has been deleted.") % username
                )
            else:
                self._window.show_toast(
                    _("Failed to delete user '%s'.") % username
                )

        run_async(do_delete, on_done)
