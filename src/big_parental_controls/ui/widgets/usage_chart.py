"""Reusable Cairo chart widgets for usage visualization.

Widgets:
- WeeklyBarChart: 7-day bar chart with clickable day selection
- HourlyBarChart: 24-column bar chart for a single day
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GObject, Gtk

from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


def _get_accent_color(widget: Gtk.Widget) -> Gdk.RGBA:
    """Get the Adwaita accent color from the current theme."""
    color = Gdk.RGBA()
    result = widget.get_style_context().lookup_color("accent_bg_color")
    if isinstance(result, tuple):
        found, color = result
        if found:
            return color
    color.red, color.green, color.blue, color.alpha = 0.208, 0.518, 0.894, 1.0
    return color


def _get_fg_color(widget: Gtk.Widget) -> Gdk.RGBA:
    """Get the foreground text color from the theme."""
    color = Gdk.RGBA()
    result = widget.get_style_context().lookup_color("window_fg_color")
    if isinstance(result, tuple):
        found, color = result
        if found:
            return color
    color.red, color.green, color.blue, color.alpha = 0.8, 0.8, 0.8, 1.0
    return color


def _get_dim_color(widget: Gtk.Widget) -> Gdk.RGBA:
    """Get a dimmed color for labels and gridlines."""
    fg = _get_fg_color(widget)
    fg.alpha = 0.5
    return fg


def _format_duration(minutes: int) -> str:
    """Format minutes as human-readable string."""
    if minutes <= 0:
        return _("No activity")
    hours, mins = divmod(minutes, 60)
    return _("%dh %dmin") % (hours, mins) if hours else _("%d min") % mins


# ── Weekly Bar Chart ──────────────────────────────────────────


class WeeklyBarChart(Gtk.DrawingArea):
    """7-day bar chart with clickable day selection.

    Shows daily totals as bars. Clicking a bar selects that day.
    Selected bar is rendered with full accent color, others dimmed.

    Signals:
        day-selected(date_str: str) — emitted when user picks a day.
    """

    __gtype_name__ = "WeeklyBarChart"
    __gsignals__ = {
        "day-selected": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    _DAY_ABBREV = [_("Mon"), _("Tue"), _("Wed"), _("Thu"),
                   _("Fri"), _("Sat"), _("Sun")]

    def __init__(self) -> None:
        super().__init__()
        self._daily_totals: dict[str, int] = {}
        self._dates: list[date] = []
        self._values: list[int] = []
        self._selected_idx: int = -1
        self._hover_idx: int = -1
        self._week_offset: int = 0
        self.set_draw_func(self._on_draw)
        self.set_content_height(170)
        self.set_content_width(400)
        self.set_accessible_role(Gtk.AccessibleRole.IMG)

        # Click to select a day
        click = Gtk.GestureClick()
        click.connect("released", self._on_click)
        self.add_controller(click)

        # Hover for tooltips
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    # ── public API ──

    def set_daily_totals(self, totals: dict[str, int]) -> None:
        """Provide daily totals and refresh the chart."""
        self._daily_totals = totals

    def set_week_offset(self, offset: int) -> None:
        """Set the week offset (0=this week, -1=last week, etc.)."""
        self._week_offset = min(0, offset)
        self._rebuild()

    def init_week(self) -> None:
        """Initialize display and select today (or last day of week)."""
        self._rebuild()

    def get_selected_date(self) -> str:
        """Return YYYY-MM-DD of selected day."""
        if 0 <= self._selected_idx < len(self._dates):
            return self._dates[self._selected_idx].isoformat()
        return date.today().isoformat()

    # ── internal ──

    def _rebuild(self) -> None:
        today = date.today()
        start = today - timedelta(days=today.weekday()) + timedelta(
            weeks=self._week_offset,
        )
        self._dates = [start + timedelta(days=i) for i in range(7)]
        self._values = [
            self._daily_totals.get(d.isoformat(), 0) for d in self._dates
        ]
        # Select today if in range, else last day
        target = today if today in self._dates else self._dates[-1]
        self._selected_idx = self._dates.index(target)
        self.queue_draw()
        self.emit("day-selected", self._dates[self._selected_idx].isoformat())

    def _bar_rect(self, idx: int, width: int, height: int) -> tuple:
        """Return (x, y, w, h) for bar at index."""
        ml, mr, mt, mb = 12, 12, 20, 36
        chart_w = width - ml - mr
        chart_h = height - mt - mb
        col_w = chart_w / 7
        bar_w = col_w * 0.55
        gap = (col_w - bar_w) / 2
        max_val = max(self._values) if self._values else 1
        val = self._values[idx] if idx < len(self._values) else 0
        bar_h = (val / max(max_val, 1)) * chart_h if val > 0 else 0
        x = ml + idx * col_w + gap
        y = mt + chart_h - bar_h
        return x, y, bar_w, bar_h

    def _idx_at(self, px: float, width: int) -> int:
        """Return bar index at pixel x."""
        ml, mr = 12, 12
        chart_w = width - ml - mr
        col_w = chart_w / 7
        idx = int((px - ml) / col_w) if col_w > 0 else -1
        return idx if 0 <= idx < 7 else -1

    def _on_click(
        self, _g: Gtk.GestureClick, _n: int, x: float, _y: float,
    ) -> None:
        idx = self._idx_at(x, self.get_width())
        if idx >= 0 and idx != self._selected_idx:
            self._selected_idx = idx
            self.queue_draw()
            self.emit("day-selected", self._dates[idx].isoformat())

    def _on_motion(
        self, _ctrl: Gtk.EventControllerMotion, x: float, _y: float,
    ) -> None:
        idx = self._idx_at(x, self.get_width())
        if idx != self._hover_idx:
            self._hover_idx = idx
            if 0 <= idx < len(self._values):
                d = self._dates[idx]
                val = self._values[idx]
                self.set_tooltip_text(
                    f"{d.strftime('%A')} — {_format_duration(val)}"
                )
            self.queue_draw()

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        self._hover_idx = -1
        self.set_tooltip_text(None)
        self.queue_draw()

    def _on_draw(
        self, _area: Gtk.DrawingArea, cr: object, width: int, height: int,
    ) -> None:
        ml, mr, mt, mb = 12, 12, 20, 36
        chart_w = width - ml - mr
        chart_h = height - mt - mb
        col_w = chart_w / 7

        accent = _get_accent_color(self)
        fg = _get_fg_color(self)
        dim = _get_dim_color(self)

        # Background gridlines
        cr.set_line_width(0.5)
        for frac in (0.5, 1.0):
            y = mt + chart_h * (1 - frac)
            cr.set_source_rgba(dim.red, dim.green, dim.blue, 0.12)
            cr.move_to(ml, y)
            cr.line_to(ml + chart_w, y)
            cr.stroke()

        # Bars
        for i in range(7):
            bx, by, bw, bh = self._bar_rect(i, width, height)
            val = self._values[i] if i < len(self._values) else 0

            if val <= 0:
                # Empty placeholder dot
                cx = bx + bw / 2
                cy = mt + chart_h - 2
                cr.set_source_rgba(dim.red, dim.green, dim.blue, 0.3)
                cr.arc(cx, cy, 2, 0, 2 * math.pi)
                cr.fill()
            else:
                is_sel = (i == self._selected_idx)
                is_hover = (i == self._hover_idx)
                alpha = 1.0 if is_sel else 0.6 if is_hover else 0.35
                cr.set_source_rgba(accent.red, accent.green, accent.blue, alpha)
                r = min(4, bw / 2)
                _rounded_rect_top(cr, bx, by, bw, bh, r)
                cr.fill()

                # Value label above bar
                if bh > 16:
                    txt = _format_duration(val)
                    cr.set_font_size(8)
                    ext = cr.text_extents(txt)
                    tx = bx + bw / 2 - ext.width / 2
                    color = fg if is_sel else dim
                    cr.set_source_rgba(
                        color.red, color.green, color.blue, color.alpha,
                    )
                    cr.move_to(tx, by - 4)
                    cr.show_text(txt)

            # Day label
            cx = ml + i * col_w + col_w / 2
            d = self._dates[i] if i < len(self._dates) else None
            if d:
                day_str = self._DAY_ABBREV[d.weekday()]
                is_sel = (i == self._selected_idx)
                color = fg if is_sel else dim
                cr.set_font_size(10)
                ext = cr.text_extents(day_str)
                cr.set_source_rgba(
                    color.red, color.green, color.blue, color.alpha,
                )
                cr.move_to(cx - ext.width / 2, height - 18)
                cr.show_text(day_str)

                # Day number
                num_str = str(d.day)
                cr.set_font_size(9)
                ext = cr.text_extents(num_str)
                cr.set_source_rgba(dim.red, dim.green, dim.blue, dim.alpha)
                cr.move_to(cx - ext.width / 2, height - 6)
                cr.show_text(num_str)


# ── Hourly Bar Chart ──────────────────────────────────────────


class HourlyBarChart(Gtk.DrawingArea):
    """24-column bar chart showing minutes per hour for one day."""

    def __init__(self) -> None:
        super().__init__()
        self._data: list[int] = [0] * 24
        self._max_val: int = 0
        self._hover_index: int = -1
        self.set_draw_func(self._on_draw)
        self.set_content_height(150)
        self.set_hexpand(True)
        self.set_accessible_role(Gtk.AccessibleRole.IMG)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

    def set_data(self, data: list[int]) -> None:
        """Set hourly data (24 values) and redraw."""
        self._data = data if len(data) == 24 else [0] * 24
        self._max_val = max(self._data) if self._data else 0
        self.queue_draw()

    def _on_motion(
        self, _ctrl: Gtk.EventControllerMotion, x: float, _y: float,
    ) -> None:
        width = self.get_width()
        ml = 4
        chart_w = width - ml - 4
        col_w = chart_w / 24
        idx = int((x - ml) / col_w) if col_w > 0 else -1
        if 0 <= idx < 24 and idx != self._hover_index:
            self._hover_index = idx
            self.set_tooltip_text(f"{idx:02d}:00 — {self._data[idx]} min")
            self.queue_draw()

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        self._hover_index = -1
        self.set_tooltip_text(None)
        self.queue_draw()

    def _on_draw(
        self,
        _area: Gtk.DrawingArea,
        cr: object,
        width: int,
        height: int,
    ) -> None:
        if self._max_val == 0:
            dim = _get_dim_color(self)
            _draw_centered(
                cr, _("No activity on this day"),
                width, height, dim, size=11,
            )
            return

        ml, mr, mt, mb = 4, 4, 22, 20
        chart_w = width - ml - mr
        chart_h = height - mt - mb
        col_w = chart_w / 24
        bar_w = col_w * 0.65
        gap = (col_w - bar_w) / 2

        accent = _get_accent_color(self)
        dim = _get_dim_color(self)

        # Bars + baseline markers for empty hours
        min_bar_h = 2  # thin marker for empty hours
        for hour in range(24):
            value = self._data[hour]
            x = ml + hour * col_w + gap

            if value > 0:
                bar_h = max(min_bar_h, (value / self._max_val) * chart_h)
                y = mt + chart_h - bar_h
                is_hover = (hour == self._hover_index)
                alpha = 0.9 if is_hover else 0.65
                cr.set_source_rgba(
                    accent.red, accent.green, accent.blue, alpha,
                )
                r = min(2, bar_w / 2)
                _rounded_rect_top(cr, x, y, bar_w, bar_h, r)
                cr.fill()

                # Minutes label above bar
                cr.set_font_size(9)
                if value >= 60:
                    txt = f"{value // 60}h{value % 60:02d}"
                else:
                    txt = f"{value}m"
                ext = cr.text_extents(txt)
                lx = x + bar_w / 2 - ext.width / 2
                ly = y - 4
                cr.set_source_rgba(
                    dim.red, dim.green, dim.blue, dim.alpha,
                )
                cr.move_to(lx, ly)
                cr.show_text(txt)
            else:
                # Thin marker line for empty hours
                y = mt + chart_h - min_bar_h
                cr.set_source_rgba(
                    accent.red, accent.green, accent.blue, 0.18,
                )
                cr.rectangle(x, y, bar_w, min_bar_h)
                cr.fill()

        # Hour labels at the bottom — every hour
        cr.set_font_size(8)
        for hour in range(24):
            x = ml + hour * col_w + col_w / 2
            txt = str(hour)
            ext = cr.text_extents(txt)
            cr.set_source_rgba(dim.red, dim.green, dim.blue, dim.alpha)
            cr.move_to(x - ext.width / 2, height - 4)
            cr.show_text(txt)


# ── Shared helpers ────────────────────────────────────────────


def _rounded_rect_top(
    cr: object, x: float, y: float, w: float, h: float, r: float,
) -> None:
    """Draw a rectangle with rounded top corners."""
    if h < r * 2:
        cr.rectangle(x, y, w, h)
        return
    cr.new_path()
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
    cr.line_to(x + w, y + h)
    cr.line_to(x, y + h)
    cr.close_path()


def _draw_centered(
    cr: object, text: str,
    width: float, height: float,
    color: Gdk.RGBA, size: int = 11,
) -> None:
    """Draw centered text."""
    cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
    cr.set_font_size(size)
    ext = cr.text_extents(text)
    cr.move_to((width - ext.width) / 2, (height + ext.height) / 2)
    cr.show_text(text)
