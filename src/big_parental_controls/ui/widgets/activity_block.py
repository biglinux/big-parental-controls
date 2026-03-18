"""Activity block widget — weekly + hourly charts with session list.

Design inspired by Apple Screen Time / Google Family Link:
  1. Total time prominently displayed (big number)
  2. Weekly bar chart (click day to select)
  3. Week navigation arrows
  4. Hourly breakdown for selected day
  5. Session list for selected day
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.services.activity_service import ActivityService
from big_parental_controls.ui.widgets.usage_chart import (
    HourlyBarChart,
    WeeklyBarChart,
    _format_duration,
)
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class ActivityBlock(Gtk.Box):
    """Reusable activity block with professional chart layout.

    Layout:
        [Weekly Overview group]
            Total label (big)         ← e.g. "1h 29min"
            WeeklyBarChart            ← 7 clickable bars
            ← / → week nav
        [Hourly Detail group]
            HourlyBarChart            ← 24 bars for selected day
        [Sessions group]
            Session rows for selected day
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            **kwargs,
        )
        self._activity = ActivityService()
        self._username: str = ""
        self._daily_totals: dict[str, int] = {}
        self._session_rows: list[Adw.ActionRow] = []
        self._week_offset: int = 0
        self._build_ui()

    def _build_ui(self) -> None:
        # ── Weekly overview ───────────────────────────────────
        weekly_group = Adw.PreferencesGroup()

        # Big total label
        total_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=2,
        )
        total_box.set_halign(Gtk.Align.CENTER)
        total_box.set_margin_top(8)
        total_box.set_margin_bottom(4)

        self._total_label = Gtk.Label(label=_("No data"))
        self._total_label.add_css_class("title-1")
        total_box.append(self._total_label)

        self._total_sub = Gtk.Label(label="")
        self._total_sub.add_css_class("dim-label")
        self._total_sub.add_css_class("caption")
        total_box.append(self._total_sub)
        weekly_group.add(total_box)

        # Week navigation row
        nav_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
        )
        nav_box.set_halign(Gtk.Align.CENTER)
        nav_box.set_margin_top(4)

        self._prev_btn = Gtk.Button(icon_name="go-previous-symbolic")
        self._prev_btn.add_css_class("flat")
        self._prev_btn.add_css_class("circular")
        self._prev_btn.set_tooltip_text(_("Previous week"))
        self._prev_btn.connect("clicked", lambda _: self._shift_week(-1))
        nav_box.append(self._prev_btn)

        self._week_label = Gtk.Label()
        self._week_label.add_css_class("dim-label")
        nav_box.append(self._week_label)

        self._next_btn = Gtk.Button(icon_name="go-next-symbolic")
        self._next_btn.add_css_class("flat")
        self._next_btn.add_css_class("circular")
        self._next_btn.set_tooltip_text(_("Next week"))
        self._next_btn.connect("clicked", lambda _: self._shift_week(1))
        nav_box.append(self._next_btn)
        weekly_group.add(nav_box)

        # Weekly bar chart
        self._weekly_chart = WeeklyBarChart()
        self._weekly_chart.set_size_request(-1, 170)
        self._weekly_chart.connect("day-selected", self._on_day_selected)
        weekly_group.add(self._weekly_chart)

        # Excess usage banner (UK Code Standard 5)
        self._excess_banner = Adw.ActionRow()
        self._excess_banner.set_visible(False)
        self._excess_banner.add_prefix(
            Gtk.Image(icon_name="dialog-warning-symbolic")
        )
        self._excess_banner.add_css_class("warning")
        weekly_group.add(self._excess_banner)
        self.append(weekly_group)

        # ── Hourly detail ─────────────────────────────────────
        hourly_group = Adw.PreferencesGroup()
        hourly_group.set_title(_("Hours of the Day"))

        self._hourly_chart = HourlyBarChart()
        self._hourly_chart.set_size_request(-1, 140)
        hourly_group.add(self._hourly_chart)
        self.append(hourly_group)

        # ── Sessions ──────────────────────────────────────────
        self._sessions_group = Adw.PreferencesGroup()
        self._sessions_group.set_title(_("Sessions"))
        self.append(self._sessions_group)

        # Spinner
        self._spinner = Gtk.Spinner()
        self._spinner.set_visible(False)
        self._spinner.set_halign(Gtk.Align.CENTER)
        self.append(self._spinner)

    # ── Public API ────────────────────────────────────────────

    def load_user(self, username: str) -> None:
        """Load activity data for a user."""
        self._username = username
        self._spinner.set_visible(True)
        self._spinner.start()

        def fetch() -> dict:
            summary = self._activity.get_summary(username, days=30)
            return {"daily": summary.daily_totals}

        def on_done(data: dict) -> None:
            self._spinner.stop()
            self._spinner.set_visible(False)
            self._daily_totals = data["daily"]
            self._weekly_chart.set_daily_totals(self._daily_totals)
            self._update_week_label()
            self._weekly_chart.init_week()

        run_async(fetch, on_done)

    # ── Week navigation ───────────────────────────────────────

    def _shift_week(self, direction: int) -> None:
        self._week_offset += direction
        if self._week_offset > 0:
            self._week_offset = 0
        self._next_btn.set_sensitive(self._week_offset < 0)
        self._weekly_chart.set_week_offset(self._week_offset)
        self._update_week_label()

    def _update_week_label(self) -> None:
        if self._week_offset == 0:
            self._week_label.set_label(_("This week"))
        elif self._week_offset == -1:
            self._week_label.set_label(_("Last week"))
        else:
            self._week_label.set_label(
                _("%d weeks ago") % abs(self._week_offset)
            )
        self._next_btn.set_sensitive(self._week_offset < 0)

    # ── Day selection handler ─────────────────────────────────

    def _on_day_selected(
        self, _chart: WeeklyBarChart, date_str: str,
    ) -> None:
        total = self._daily_totals.get(date_str, 0)
        self._update_total(total, date_str)
        self._check_excess(total)
        self._load_day_details(date_str)

    def _update_total(self, total_minutes: int, date_str: str) -> None:
        self._total_label.set_label(_format_duration(total_minutes))
        self._total_sub.set_label(date_str)

    def _check_excess(self, total_minutes: int) -> None:
        limit = 240
        if total_minutes > limit * 1.2:
            hours, mins = divmod(total_minutes, 60)
            self._excess_banner.set_title(_("Extended usage detected"))
            self._excess_banner.set_subtitle(
                _("%(user)s used the computer for %(hours)dh %(mins)dmin today.")
                % {"user": self._username, "hours": hours, "mins": mins}
            )
            self._excess_banner.set_visible(True)
        else:
            self._excess_banner.set_visible(False)

    def _load_day_details(self, date_str: str) -> None:
        username = self._username

        def fetch() -> dict:
            hourly = self._activity.get_daily_hourly(username, date_str)
            sessions = self._activity.get_day_sessions(username, date_str)
            return {"hourly": hourly, "sessions": sessions}

        def on_done(data: dict) -> None:
            self._hourly_chart.set_data(data["hourly"])
            self._populate_sessions(data["sessions"])

        run_async(fetch, on_done)

    # ── Sessions list ─────────────────────────────────────────

    def _populate_sessions(self, sessions: list) -> None:
        for row in self._session_rows:
            self._sessions_group.remove(row)
        self._session_rows.clear()

        if not sessions:
            row = Adw.ActionRow()
            row.set_title(_("No sessions on this day"))
            row.add_css_class("dim-label")
            self._sessions_group.add(row)
            self._session_rows.append(row)
            return

        for s in sessions:
            row = Adw.ActionRow()
            start_str = s.start.strftime("%H:%M")
            end_str = (
                s.end.strftime("%H:%M") if s.end else _("still active")
            )
            row.set_title(f"{start_str} — {end_str}")

            dur = _format_duration(s.duration_minutes)
            type_label = {
                "wayland": _("Graphical session"),
                "remote": _("Remote session"),
                "tty": _("Console session"),
            }.get(s.session_type, _("Session"))
            row.set_subtitle(f"{dur}  •  {type_label}")

            icon_name = {
                "wayland": "video-display-symbolic",
                "remote": "network-workgroup-symbolic",
                "tty": "utilities-terminal-symbolic",
            }.get(s.session_type, "computer-symbolic")
            row.add_prefix(Gtk.Image(icon_name=icon_name))
            self._sessions_group.add(row)
            self._session_rows.append(row)
