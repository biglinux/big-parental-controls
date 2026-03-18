"""Activity page — displays usage charts and session history for supervised users."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.daemon_client.client import DaemonClient
from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.services.activity_service import ActivityService
from big_parental_controls.ui.widgets.usage_chart import HourlyBarChart, WeeklyBarChart
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class ActivityPage(Gtk.Box):
    """Page showing usage graphs and session history per supervised user."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._accounts = AccountsServiceWrapper()
        self._activity = ActivityService()
        self._daemon = DaemonClient()
        self._selected_username: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
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

        # User selector
        selector_group = Adw.PreferencesGroup()
        self._user_combo = Adw.ComboRow()
        self._user_combo.set_title(_("User"))
        self._user_model = Gtk.StringList()
        self._user_combo.set_model(self._user_model)
        self._user_combo.connect("notify::selected", self._on_user_changed)
        selector_group.add(self._user_combo)
        inner.append(selector_group)

        # Monitoring toggles
        self._monitoring_group = Adw.PreferencesGroup()
        self._monitoring_group.set_title(_("Monitored Users"))
        self._monitoring_group.set_description(
            _(
                "Choose which supervised accounts have activity tracking. "
                "The system checks running programs every minute."
            )
        )
        inner.append(self._monitoring_group)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("utilities-system-monitor-symbolic")
        self._empty_status.set_title(_("Select a User"))
        self._empty_status.set_description(
            _("Choose a supervised user to view activity.")
        )
        inner.append(self._empty_status)

        # Daily usage chart
        self._daily_group = Adw.PreferencesGroup()
        self._daily_group.set_title(_("Daily Usage"))
        self._daily_group.set_description(_("Minutes of screen time per day"))
        self._daily_group.set_visible(False)

        self._daily_chart = WeeklyBarChart()
        self._daily_chart.set_size_request(-1, 220)
        self._daily_group.add(self._daily_chart)
        inner.append(self._daily_group)

        # Hourly distribution chart
        self._hourly_group = Adw.PreferencesGroup()
        self._hourly_group.set_title(_("Time of Day"))
        self._hourly_group.set_description(_("When this user is most active"))
        self._hourly_group.set_visible(False)

        self._hourly_chart = HourlyBarChart()
        self._hourly_chart.set_size_request(-1, 100)
        self._hourly_group.add(self._hourly_chart)
        inner.append(self._hourly_group)

        # Recent sessions list
        self._sessions_group = Adw.PreferencesGroup()
        self._sessions_group.set_title(_("Recent Sessions"))
        self._sessions_group.set_visible(False)
        inner.append(self._sessions_group)

        # Loading spinner
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._spinner.set_halign(Gtk.Align.CENTER)
        inner.append(self._spinner)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

        self._populate_user_combo()

    def _populate_user_combo(self) -> None:
        self._supervised_users: list = []
        self._user_model.splice(0, self._user_model.get_n_items(), [])
        for user in self._accounts.list_users():
            if self._accounts.is_supervised(user):
                self._supervised_users.append(user)
                label = user.get_real_name() or user.get_user_name()
                self._user_model.append(label)
        self._populate_monitoring_toggles()

    def _populate_monitoring_toggles(self) -> None:
        """Build switch rows for each supervised user."""
        # Clear existing rows
        while child := self._monitoring_group.get_first_child():
            self._monitoring_group.remove(child)

        def fetch_monitored() -> list[str]:
            return self._daemon.get_monitored_users()

        def on_done(monitored: list[str]) -> None:
            for user in self._supervised_users:
                uname = user.get_user_name()
                row = Adw.SwitchRow()
                row.set_title(user.get_real_name() or uname)
                row.set_subtitle(uname)
                row.set_active(uname in monitored)
                row.connect(
                    "notify::active", self._on_monitoring_toggled, user
                )
                self._monitoring_group.add(row)

        run_async(fetch_monitored, on_done)

    def _on_monitoring_toggled(
        self, row: Adw.SwitchRow, _pspec: object, user: object
    ) -> None:
        """Enable/disable monitoring for a user via D-Bus."""
        username = user.get_user_name()
        uid = user.get_uid()

        if row.get_active():
            def enable() -> bool:
                return self._daemon.enable_user(username, uid)
            run_async(enable, lambda _ok: None)
        else:
            def disable() -> bool:
                return self._daemon.disable_user(username)
            run_async(disable, lambda _ok: None)

    def _on_user_changed(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._supervised_users):
            return
        user = self._supervised_users[idx]
        self._selected_username = user.get_user_name()
        self._load_data()

    def _load_data(self) -> None:
        if not self._selected_username:
            return

        self._empty_status.set_visible(False)
        self._spinner.set_visible(True)
        self._spinner.start()

        username = self._selected_username

        def fetch() -> dict:
            summary = self._activity.get_summary(username, days=7)
            return {
                "daily": sorted(summary.daily_totals.items()),
                "hourly": summary.hourly_distribution,
                "sessions": summary.sessions[:20],
            }

        def on_done(data: dict) -> None:
            self._spinner.stop()
            self._spinner.set_visible(False)
            self._show_data(data)

        run_async(fetch, on_done)

    def _show_data(self, data: dict) -> None:
        # Daily chart
        daily = data["daily"]
        daily_labels = [
            (d.split("-")[2] if "-" in d else d, m) for d, m in daily
        ]
        self._daily_chart.set_data(daily_labels)
        total_min = sum(m for _, m in daily_labels)
        self._daily_chart.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [
                _("Bar chart: %d total minutes across %d days")
                % (total_min, len(daily_labels))
            ],
        )
        self._daily_group.set_visible(True)

        # Hourly chart
        hourly = data["hourly"]
        self._hourly_chart.set_data(hourly)
        peak_h = (
            hourly.index(max(hourly)) if max(hourly) > 0 else 0
        )
        self._hourly_chart.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Hourly chart: peak activity at %d:00") % peak_h],
        )
        self._hourly_group.set_visible(True)

        # Sessions list
        self._clear_session_rows()
        sessions = data["sessions"]
        for s in sessions:
            row = Adw.ActionRow()
            start_str = s.start.strftime("%Y-%m-%d %H:%M")
            end_str = (
                s.end.strftime("%H:%M") if s.end else _("still active")
            )
            row.set_title(f"{start_str} — {end_str}")
            dur_h, dur_m = divmod(s.duration_minutes, 60)
            subtitle = (
                _("%dh %dmin") % (dur_h, dur_m)
                if dur_h
                else _("%d min") % dur_m
            )
            row.set_subtitle(f"{subtitle}  •  {s.tty}")

            icon_name = {
                "wayland": "video-display-symbolic",
                "tty": "utilities-terminal-symbolic",
                "remote": "network-workgroup-symbolic",
            }.get(s.session_type, "computer-symbolic")
            icon = Gtk.Image(
                icon_name=icon_name,
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
            )
            row.add_prefix(icon)
            self._sessions_group.add(row)

        self._sessions_group.set_visible(bool(sessions))

    def _clear_session_rows(self) -> None:
        """Remove all rows from sessions group."""
        while True:
            child = self._sessions_group.get_first_child()
            if child is None:
                break
            self._sessions_group.remove(child)

    def refresh(self) -> None:
        if self._selected_username:
            self._load_data()
