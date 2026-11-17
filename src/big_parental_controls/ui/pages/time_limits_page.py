"""Time limits page — manage per-user screen time schedules and duration limits."""

import contextlib
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from big_parental_controls.services.malcontent_service import MalcontentService
from big_parental_controls.services import extra_time_service, time_left, time_service
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class TimeLimitsPage(Gtk.Box):
    """Page for managing time-based restrictions per supervised user."""

    def __init__(self, user: object, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None
        self._selected_uid: int = user.get_uid()
        self._selected_username: str = user.get_user_name()
        self._range_widgets: list[dict] = []
        self._loading = False
        self._build_ui()

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

        # User info
        info_group = Adw.PreferencesGroup()
        info_row = Adw.ActionRow()
        info_row.set_title(self._selected_username)
        info_row.add_prefix(Gtk.Image(icon_name="avatar-default-symbolic"))
        info_group.add(info_row)
        inner.append(info_group)

        # Schedule group
        self._schedule_group = Adw.PreferencesGroup()
        self._schedule_group.set_title(_("Allowed Hours"))
        self._schedule_group.set_description(
            _("When this user is allowed to log in.")
        )
        self._schedule_group.set_visible(True)

        self._enable_row = Adw.SwitchRow()
        self._enable_row.set_title(_("Enable schedule"))
        self._enable_row.connect("notify::active", self._on_enable_toggled)
        self._schedule_group.add(self._enable_row)

        inner.append(self._schedule_group)

        # Ranges listbox
        self._ranges_listbox = Gtk.ListBox()
        self._ranges_listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self._ranges_listbox.add_css_class("boxed-list")
        self._ranges_listbox.set_visible(True)
        inner.append(self._ranges_listbox)

        # Add range button
        self._add_range_btn = Gtk.Button(label=_("Add Time Range"))
        self._add_range_btn.set_halign(Gtk.Align.START)
        self._add_range_btn.add_css_class("flat")
        self._add_range_btn.set_sensitive(False)
        self._add_range_btn.set_visible(True)
        self._add_range_btn.connect("clicked", self._on_add_range)
        inner.append(self._add_range_btn)

        # Daily duration group
        self._duration_group = Adw.PreferencesGroup()
        self._duration_group.set_title(_("Daily Usage Limit"))
        self._duration_group.set_description(
            _("Maximum time this user can stay logged in per day.")
        )
        self._duration_group.set_visible(True)

        self._duration_enable_row = Adw.SwitchRow()
        self._duration_enable_row.set_title(_("Enable daily limit"))
        self._duration_enable_row.connect("notify::active", self._on_duration_enable_toggled)
        self._duration_group.add(self._duration_enable_row)

        self._duration_row = Adw.SpinRow.new_with_range(15, 720, 15)
        self._duration_row.set_title(_("Minutes per day"))
        self._duration_row.set_value(120)
        self._duration_row.set_sensitive(False)
        self._duration_row.connect("notify::value", lambda *_: self._apply_btn.set_sensitive(True))
        self._duration_group.add(self._duration_row)

        inner.append(self._duration_group)

        self._build_extra_group(inner)

        # Apply button
        self._apply_btn = Gtk.Button(label=_("Apply"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.set_halign(Gtk.Align.END)
        self._apply_btn.set_visible(True)
        self._apply_btn.connect("clicked", self._on_apply)
        inner.append(self._apply_btn)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)
        self.append(toolbar)

        self._load_current_limits()

    # ── Extra time (approved by a parent with the parent code) ──────────

    def _build_extra_group(self, inner: Gtk.Box) -> None:

        group = Adw.PreferencesGroup()
        group.set_title(_("Extra Time"))
        group.set_description(
            _("The child can ask for more time from the clock icon; "
              "a parent approves by typing the parent code.")
        )

        self._extra_enable_row = Adw.SwitchRow()
        self._extra_enable_row.set_title(_("Allow requests for extra time"))
        self._extra_enable_row.connect("notify::active", self._on_extra_toggled)
        group.add(self._extra_enable_row)

        self._extra_step_row = Adw.SpinRow.new_with_range(5, 60, 5)
        self._extra_step_row.set_title(_("Minutes per request"))
        self._extra_step_row.connect("notify::value", self._mark_dirty)
        group.add(self._extra_step_row)

        self._extra_max_row = Adw.SpinRow.new_with_range(1, 10, 1)
        self._extra_max_row.set_title(_("Maximum requests per day"))
        self._extra_max_row.connect("notify::value", self._mark_dirty)
        group.add(self._extra_max_row)

        self._extra_sched_row = Adw.SwitchRow()
        self._extra_sched_row.set_title(_("Also push back the end of allowed hours"))
        self._extra_sched_row.set_subtitle(
            _("The open session may continue after the end time; "
              "logging in again afterwards stays impossible.")
        )
        self._extra_sched_row.connect("notify::active", self._mark_dirty)
        group.add(self._extra_sched_row)

        self._pin_row = Adw.ActionRow()
        self._pin_row.set_title(_("Parent code"))
        pin_btn = Gtk.Button(label=_("Change…"))
        pin_btn.set_valign(Gtk.Align.CENTER)
        pin_btn.connect("clicked", self._on_set_pin)
        self._pin_row.add_suffix(pin_btn)
        group.add(self._pin_row)

        self._today_row = Adw.ActionRow()
        self._today_row.set_title(_("Today"))
        self._grant_btn = Gtk.Button()
        self._grant_btn.set_valign(Gtk.Align.CENTER)
        self._grant_btn.connect("clicked", self._on_grant_now)
        self._today_row.add_suffix(self._grant_btn)
        group.add(self._today_row)

        inner.append(group)

    def _mark_dirty(self, *_args: object) -> None:
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _on_extra_toggled(self, row: Adw.SwitchRow, _pspec: object) -> None:
        active = row.get_active()
        for r in (self._extra_step_row, self._extra_max_row, self._extra_sched_row):
            r.set_sensitive(active)
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _load_extra(self) -> None:
        was_loading, self._loading = self._loading, True
        s = time_service.get_extra_settings(self._selected_username)
        self._extra_enable_row.set_active(s["max_requests"] > 0)
        self._extra_step_row.set_value(s["step"])
        self._extra_max_row.set_value(s["max_requests"] or time_left.EXTRA_MAX_REQUESTS)
        self._extra_sched_row.set_active(s["extend_schedule"])
        self._on_extra_toggled(self._extra_enable_row, None)

        has = extra_time_service.has_pin()
        self._pin_row.set_subtitle(
            _("Set") if has else _("Not set — requests are refused until it is set")
            if has is False else _("Unknown (parental daemon not reachable)")
        )

        info = time_left.compute(self._selected_username, datetime.now())
        self._today_row.set_subtitle(
            _("%(bonus)d min granted, %(left)d request(s) left")
            % {"bonus": info["bonus"], "left": info["requests_left"]}
        )
        self._grant_btn.set_label(_("Grant %d min now") % s["step"])
        self._loading = was_loading

    def _on_set_pin(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Parent code"))
        dialog.set_body(_("4 to 8 digits. It is asked on the child's session "
                          "to approve extra time."))
        group = Adw.PreferencesGroup()
        pin_row = Adw.PasswordEntryRow()
        pin_row.set_title(_("New code"))
        confirm_row = Adw.PasswordEntryRow()
        confirm_row.set_title(_("Confirm code"))
        group.add(pin_row)
        group.add(confirm_row)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_response_enabled("save", False)

        def validate(*_args: object) -> None:
            pin = pin_row.get_text()
            ok = pin.isascii() and pin.isdigit() and 4 <= len(pin) <= 8
            dialog.set_response_enabled("save", ok and pin == confirm_row.get_text())

        pin_row.connect("changed", validate)
        confirm_row.connect("changed", validate)

        def on_response(_d: Adw.AlertDialog, response: str) -> None:
            if response != "save":
                return
            if extra_time_service.set_pin(pin_row.get_text()):
                self._show_success(_("Parent code saved."))
            else:
                self._show_error(_("The parent code could not be saved."))
            self._load_extra()

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    def _on_grant_now(self, _button: Gtk.Button) -> None:
        minutes = int(self._extra_step_row.get_value())
        res = extra_time_service.grant(self._selected_username, minutes)
        if res == "ok":
            self._show_success(_("%d extra minutes granted for today.") % minutes)
        elif res == "no_limit":
            self._show_error(_("This user has no daily limit or extendable schedule."))
        else:
            self._show_error(_("Extra time could not be granted."))
        self._load_extra()

    def _load_current_limits(self) -> None:
        """Load current limits for the user."""
        username = self._selected_username

        self._loading = True
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

        daily = time_service.get_daily_limit(username)
        if daily > 0:
            self._duration_enable_row.set_active(True)
            self._duration_row.set_value(daily)
        else:
            self._duration_enable_row.set_active(False)
            self._duration_row.set_value(120)

        self._load_extra()

        self._loading = False
        self._apply_btn.set_sensitive(False)

    def _clear_ranges(self) -> None:
        """Remove all time range widgets."""
        for entry in self._range_widgets:
            self._ranges_listbox.remove(entry["row"])
        self._range_widgets.clear()

    def _add_time_range(
        self,
        start_h: int = 8,
        start_m: int = 0,
        end_h: int = 22,
        end_m: int = 0,
    ) -> None:
        """Add a time range row (HH:MM — HH:MM) with a delete button."""
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        start_h_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        start_h_spin.set_value(start_h)
        start_h_spin.set_width_chars(2)
        start_h_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Start hour")]
        )
        start_h_spin.connect("value-changed", lambda *_: self._apply_btn.set_sensitive(True))

        colon1 = Gtk.Label(label=":")

        start_m_spin = Gtk.SpinButton.new_with_range(0, 59, 5)
        start_m_spin.set_value(start_m)
        start_m_spin.set_width_chars(2)
        start_m_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Start minute")]
        )
        start_m_spin.connect("value-changed", lambda *_: self._apply_btn.set_sensitive(True))

        dash = Gtk.Label(label="—")

        end_h_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        end_h_spin.set_value(end_h)
        end_h_spin.set_width_chars(2)
        end_h_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("End hour")]
        )
        end_h_spin.connect("value-changed", lambda *_: self._apply_btn.set_sensitive(True))

        colon2 = Gtk.Label(label=":")

        end_m_spin = Gtk.SpinButton.new_with_range(0, 59, 5)
        end_m_spin.set_value(end_m)
        end_m_spin.set_width_chars(2)
        end_m_spin.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("End minute")]
        )
        end_m_spin.connect("value-changed", lambda *_: self._apply_btn.set_sensitive(True))

        entry = {
            "row": row,
            "start_h": start_h_spin,
            "start_m": start_m_spin,
            "end_h": end_h_spin,
            "end_m": end_m_spin,
        }

        del_btn = Gtk.Button(icon_name="edit-delete-symbolic")
        del_btn.add_css_class("flat")
        del_btn.set_tooltip_text(_("Delete range"))
        del_btn.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Delete time range")]
        )
        del_btn.connect("clicked", self._on_delete_range, entry)

        for widget in (start_h_spin, colon1, start_m_spin, dash, end_h_spin, colon2, end_m_spin):
            box.append(widget)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        box.append(spacer)
        box.append(del_btn)

        row.set_child(box)
        self._ranges_listbox.append(row)
        self._range_widgets.append(entry)

    def _on_add_range(self, _button: Gtk.Button) -> None:
        self._add_time_range()
        self._apply_btn.set_sensitive(True)

    def _on_delete_range(self, _button: Gtk.Button, entry: dict) -> None:
        self._ranges_listbox.remove(entry["row"])
        self._range_widgets.remove(entry)
        self._apply_btn.set_sensitive(True)

    def _on_enable_toggled(self, row: Adw.SwitchRow, _pspec: object) -> None:
        active = row.get_active()
        self._add_range_btn.set_sensitive(active)
        if active and not self._range_widgets and not self._loading:
            self._add_time_range(8, 0, 22, 0)
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _on_duration_enable_toggled(self, row: Adw.SwitchRow, _pspec: object) -> None:
        active = row.get_active()
        self._duration_row.set_sensitive(active)
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply time limits to the user."""
        username = self._selected_username

        # Schedule
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

            if self._malcontent and ranges:
                with contextlib.suppress(GLib.Error):
                    first = ranges[0]
                    last = ranges[-1]
                    start_sec = first["start_hour"] * 3600 + first.get("start_min", 0) * 60
                    end_sec = last["end_hour"] * 3600 + last.get("end_min", 0) * 60
                    self._malcontent.set_session_limits(self._selected_uid, start_sec, end_sec)
        else:
            time_service.remove_schedule(username)
            if self._malcontent:
                with contextlib.suppress(GLib.Error):
                    self._malcontent.set_session_limits(self._selected_uid, 0, 86400)

        # Daily duration limit + extra-time settings (one privileged write)
        minutes = (
            int(self._duration_row.get_value())
            if self._duration_enable_row.get_active() else 0
        )
        enabled = self._extra_enable_row.get_active()
        time_service.save_daily_and_extra(username, minutes, {
            "step": int(self._extra_step_row.get_value()),
            "max_requests": int(self._extra_max_row.get_value()) if enabled else 0,
            "extend_schedule": enabled and self._extra_sched_row.get_active(),
        })

        self._apply_btn.set_sensitive(False)
        self._show_success(_("Time settings applied."))
        self._load_current_limits()

    def _show_success(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def refresh(self) -> None:
        """Refresh current user limits."""
        self._load_current_limits()
