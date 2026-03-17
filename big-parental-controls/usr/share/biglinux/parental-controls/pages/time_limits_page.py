"""Time limits page — configure daily usage schedules for supervised users."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from services.accounts_service import AccountsServiceWrapper
from services.malcontent_service import MalcontentService
from services import time_service
from utils.i18n import setup_i18n

_ = setup_i18n()


class TimeLimitsPage(Gtk.Box):
    """Page for managing per-user session time limits."""

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)

        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None

        self._selected_uid = None
        self._selected_username = None
        self._range_widgets: list[dict] = []
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

        # Description
        desc = Gtk.Label(
            label=_(
                "Choose when the computer can be used. "
                "Outside these hours, this account will be locked."
            )
        )
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        desc.add_css_class("dim-label")
        inner.append(desc)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("preferences-system-time-symbolic")
        self._empty_status.set_title(_("No Supervised Accounts"))
        self._empty_status.set_description(
            _("Create one in the Users page first.")
        )
        self._empty_status.set_visible(False)
        inner.append(self._empty_status)

        # --- Allowed Hours section ---
        self._schedule_group = Adw.PreferencesGroup()
        self._schedule_group.set_title(_("Allowed Hours"))

        self._enable_row = Adw.SwitchRow(title=_("Enable time limits"))
        self._enable_row.set_subtitle(_("Only allow computer use during chosen hours"))
        self._enable_row.connect("notify::active", self._on_enable_toggled)
        self._schedule_group.add(self._enable_row)

        inner.append(self._schedule_group)

        # Container for compact time range rows (single boxed list)
        self._ranges_listbox = Gtk.ListBox()
        self._ranges_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._ranges_listbox.add_css_class("boxed-list")
        inner.append(self._ranges_listbox)

        # Add range button
        self._add_range_btn = Gtk.Button()
        add_content = Adw.ButtonContent(
            icon_name="list-add-symbolic", label=_("Add time range")
        )
        self._add_range_btn.set_child(add_content)
        self._add_range_btn.add_css_class("flat")
        self._add_range_btn.set_halign(Gtk.Align.START)
        self._add_range_btn.set_sensitive(False)
        self._add_range_btn.connect("clicked", self._on_add_range)
        inner.append(self._add_range_btn)

        # --- Daily duration limit group ---
        self._duration_group = Adw.PreferencesGroup()
        self._duration_group.set_title(_("Daily Usage Limit"))

        self._duration_enable_row = Adw.SwitchRow(
            title=_("Enable daily time limit")
        )
        self._duration_enable_row.set_subtitle(
            _("Automatically close the session after a set number of minutes")
        )
        self._duration_enable_row.connect(
            "notify::active", self._on_duration_enable_toggled
        )
        self._duration_group.add(self._duration_enable_row)

        self._duration_row = Adw.SpinRow.new_with_range(15, 720, 15)
        self._duration_row.set_title(_("Minutes per day"))
        self._duration_row.set_subtitle(
            _("Session ends when this limit is reached")
        )
        self._duration_row.set_value(120)
        self._duration_row.set_sensitive(False)
        self._duration_group.add(self._duration_row)

        inner.append(self._duration_group)

        # Apply button
        apply_box = Gtk.Box()
        apply_box.set_halign(Gtk.Align.END)

        self._apply_btn = Gtk.Button(label=_("Apply"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.connect("clicked", self._on_apply)
        apply_box.append(self._apply_btn)
        inner.append(apply_box)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

        # Start with empty state visible
        self._empty_status.set_visible(True)
        self._schedule_group.set_visible(False)
        self._ranges_listbox.set_visible(False)
        self._add_range_btn.set_visible(False)
        self._duration_group.set_visible(False)
        self._apply_btn.get_parent().set_visible(False)

    # ------------------------------------------------------------------
    # Time range management
    # ------------------------------------------------------------------

    def _add_time_range(self, start_h: int = 8, start_m: int = 0,
                        end_h: int = 22, end_m: int = 0) -> dict:
        """Add a compact time range row: [HH]:[MM] — [HH]:[MM] [🗑]."""
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Start time: HH:MM
        start_h_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        start_h_spin.set_value(start_h)
        start_h_spin.set_width_chars(2)
        start_h_spin.set_numeric(True)
        start_h_spin.set_wrap(True)
        start_h_spin.set_orientation(Gtk.Orientation.HORIZONTAL)
        start_h_spin.connect("output", self._format_two_digit)
        start_h_spin.set_valign(Gtk.Align.CENTER)
        start_h_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Start hour")]
        )
        box.append(start_h_spin)

        colon1 = Gtk.Label(label=":")
        colon1.set_valign(Gtk.Align.CENTER)
        box.append(colon1)

        start_m_spin = Gtk.SpinButton.new_with_range(0, 55, 5)
        start_m_spin.set_value(start_m)
        start_m_spin.set_width_chars(2)
        start_m_spin.set_numeric(True)
        start_m_spin.set_wrap(True)
        start_m_spin.set_orientation(Gtk.Orientation.HORIZONTAL)
        start_m_spin.connect("output", self._format_two_digit)
        start_m_spin.set_valign(Gtk.Align.CENTER)
        start_m_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Start minute")]
        )
        box.append(start_m_spin)

        sep = Gtk.Label(label="  —  ")
        sep.set_valign(Gtk.Align.CENTER)
        sep.add_css_class("dim-label")
        box.append(sep)

        # End time: HH:MM
        end_h_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        end_h_spin.set_value(end_h)
        end_h_spin.set_width_chars(2)
        end_h_spin.set_numeric(True)
        end_h_spin.set_wrap(True)
        end_h_spin.set_orientation(Gtk.Orientation.HORIZONTAL)
        end_h_spin.connect("output", self._format_two_digit)
        end_h_spin.set_valign(Gtk.Align.CENTER)
        end_h_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("End hour")]
        )
        box.append(end_h_spin)

        colon2 = Gtk.Label(label=":")
        colon2.set_valign(Gtk.Align.CENTER)
        box.append(colon2)

        end_m_spin = Gtk.SpinButton.new_with_range(0, 55, 5)
        end_m_spin.set_value(end_m)
        end_m_spin.set_width_chars(2)
        end_m_spin.set_numeric(True)
        end_m_spin.set_wrap(True)
        end_m_spin.set_orientation(Gtk.Orientation.HORIZONTAL)
        end_m_spin.connect("output", self._format_two_digit)
        end_m_spin.set_valign(Gtk.Align.CENTER)
        end_m_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("End minute")]
        )
        box.append(end_m_spin)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.append(spacer)

        delete_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        delete_btn.add_css_class("flat")
        delete_btn.add_css_class("error")
        delete_btn.set_valign(Gtk.Align.CENTER)
        delete_btn.set_tooltip_text(_("Remove this time range"))
        box.append(delete_btn)

        row.set_child(box)

        entry = {
            "row": row,
            "start_h": start_h_spin,
            "start_m": start_m_spin,
            "end_h": end_h_spin,
            "end_m": end_m_spin,
            "delete_btn": delete_btn,
        }
        self._range_widgets.append(entry)
        self._ranges_listbox.append(row)

        delete_btn.connect("clicked", self._on_delete_range, entry)
        for spin in (start_h_spin, start_m_spin, end_h_spin, end_m_spin):
            spin.connect("value-changed", lambda *_: self._apply_btn.set_sensitive(True))

        self._apply_btn.set_sensitive(True)
        return entry

    @staticmethod
    def _format_two_digit(spin):
        """Format spin button value with leading zero (e.g., 08, 00)."""
        val = int(spin.get_value())
        spin.set_text(f"{val:02d}")
        return True

    def _on_add_range(self, button):
        """User clicked 'Add time range'."""
        self._add_time_range()

    def _on_delete_range(self, button, entry):
        """Remove a time range from the UI."""
        self._ranges_listbox.remove(entry["row"])
        self._range_widgets.remove(entry)
        self._apply_btn.set_sensitive(True)

    def _clear_ranges(self):
        """Remove all time range rows from the UI."""
        for entry in list(self._range_widgets):
            self._ranges_listbox.remove(entry["row"])
        self._range_widgets.clear()

    def set_selected_user(self, user):
        """Called by window when the header dropdown selection changes."""
        if user is None:
            self._selected_uid = None
            self._selected_username = None
            self._empty_status.set_visible(True)
            self._schedule_group.set_visible(False)
            self._ranges_listbox.set_visible(False)
            self._add_range_btn.set_visible(False)
            self._duration_group.set_visible(False)
            self._apply_btn.get_parent().set_visible(False)
            return

        self._selected_uid = user.get_uid()
        self._selected_username = user.get_user_name()
        self._empty_status.set_visible(False)
        self._schedule_group.set_visible(True)
        self._ranges_listbox.set_visible(True)
        self._add_range_btn.set_visible(True)
        self._duration_group.set_visible(True)
        self._apply_btn.get_parent().set_visible(True)
        self._load_current_limits()

    def _load_current_limits(self):
        """Load current limits for the selected user from time_service."""
        if self._selected_uid is None or not self._selected_username:
            return

        username = self._selected_username

        # Load schedule (new format with ranges)
        self._clear_ranges()
        schedule = time_service.get_schedule(username)
        if schedule and schedule.get("ranges"):
            self._enable_row.set_active(True)
            for r in schedule["ranges"]:
                self._add_time_range(
                    r.get("start_hour", 8),
                    r.get("start_min", 0),
                    r.get("end_hour", 22),
                    r.get("end_min", 0),
                )
            self._add_range_btn.set_sensitive(True)
        else:
            self._enable_row.set_active(False)
            self._add_range_btn.set_sensitive(False)

        # Load daily limit
        daily = time_service.get_daily_limit(username)
        if daily > 0:
            self._duration_enable_row.set_active(True)
            self._duration_row.set_value(daily)
        else:
            self._duration_enable_row.set_active(False)
            self._duration_row.set_value(120)

        self._apply_btn.set_sensitive(False)

    def _on_enable_toggled(self, row, pspec):
        active = row.get_active()
        self._add_range_btn.set_sensitive(active)
        if active and not self._range_widgets:
            # Add a default range when enabling
            self._add_time_range(8, 22)
        self._apply_btn.set_sensitive(True)

    def _on_duration_enable_toggled(self, row, pspec):
        active = row.get_active()
        self._duration_row.set_sensitive(active)
        self._apply_btn.set_sensitive(True)

    def _on_apply(self, button):
        """Apply time limits to the selected user."""
        if self._selected_uid is None or not self._selected_username:
            return
        username = self._selected_username

        # Schedule (pam_time) — collect all ranges
        if self._enable_row.get_active() and self._range_widgets:
            ranges = []
            for entry in self._range_widgets:
                start_hour = int(entry["start_h"].get_value())
                start_min = int(entry["start_m"].get_value())
                end_hour = int(entry["end_h"].get_value())
                end_min = int(entry["end_m"].get_value())

                start_total = start_hour * 60 + start_min
                end_total = end_hour * 60 + end_min

                if end_total <= start_total:
                    self._show_error(
                        _("End time must be after start time in all ranges.")
                    )
                    return

                ranges.append({
                    "start_hour": start_hour,
                    "start_min": start_min,
                    "end_hour": end_hour,
                    "end_min": end_min,
                })

            time_service.set_schedule(username, ranges)

            # Also set malcontent with the overall time span
            if self._malcontent and ranges:
                try:
                    first = ranges[0]
                    last = ranges[-1]
                    start_sec = first["start_hour"] * 3600 + first.get("start_min", 0) * 60
                    end_sec = last["end_hour"] * 3600 + last.get("end_min", 0) * 60
                    self._malcontent.set_session_limits(
                        self._selected_uid, start_sec, end_sec,
                    )
                except GLib.Error:
                    pass
        else:
            time_service.remove_schedule(username)
            if self._malcontent:
                try:
                    self._malcontent.set_session_limits(
                        self._selected_uid, 0, 86400
                    )
                except GLib.Error:
                    pass

        # Daily duration limit
        if self._duration_enable_row.get_active():
            minutes = int(self._duration_row.get_value())
            time_service.set_daily_limit(username, minutes)
        else:
            time_service.remove_daily_limit(username)

        self._apply_btn.set_sensitive(False)
        self._show_success(_("Time settings applied."))

    def _show_success(self, message):
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message):
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def refresh(self):
        """Refresh current user limits (called on navigation)."""
        if self._selected_uid is not None:
            self._load_current_limits()
