"""Compliance actions — consent, data deletion, data export (LGPD/GDPR)."""

import json

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from big_parental_controls.services.activity_service import ActivityService
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


def show_consent_dialog(
    window: object,
    user: object,
    on_accepted: callable,
    on_rejected: callable,
) -> None:
    """Show informed consent dialog before enabling monitoring."""
    display_name = user.get_real_name() or user.get_user_name()
    dialog = Adw.AlertDialog()
    dialog.set_content_width(520)
    dialog.set_heading(_("Enable Activity Monitoring"))
    dialog.set_body(
        _(
            "By enabling monitoring for %(user)s, the following "
            "data will be collected and stored exclusively on "
            "this device:\n\n"
            "Data collected:\n"
            "• Names of applications used "
            "(checked every 60 seconds)\n"
            "• Duration of use per application\n"
            "• Login and logout times\n\n"
            "Data controller: You (the device administrator).\n"
            "Purpose: Child safety monitoring.\n"
            "Legal basis: Parental consent (LGPD Art. 14, "
            "GDPR Art. 8, ECA Digital Art. 18).\n"
            "Retention: 30 days, then automatically deleted.\n"
            "Access: Only you can view detailed reports.\n"
            "Storage: Local only — no data is transmitted.\n\n"
            "Rights: You can disable monitoring, export data, "
            "or delete all data at any time. The supervised "
            "user will be informed that monitoring is active "
            "via the system tray indicator."
        )
        % {"user": display_name}
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("consent", _("I Understand and Consent"))
    dialog.set_response_appearance(
        "consent", Adw.ResponseAppearance.SUGGESTED
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(
        _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response == "consent":
            on_accepted()
        else:
            on_rejected()

    dialog.connect("response", on_response)
    dialog.present(window)


def confirm_delete_data(
    window: object, username: str
) -> None:
    """Confirm and delete all activity data (LGPD Art. 18, VI)."""
    dialog = Adw.AlertDialog()
    dialog.set_heading(_("Delete Activity Data"))
    dialog.set_body(
        _(
            "All activity data for %(user)s will be permanently "
            "deleted.\nThis includes app usage history and "
            "session records.\n\nThis action cannot be undone."
        )
        % {"user": username}
    )
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("delete", _("Delete All Data"))
    dialog.set_response_appearance(
        "delete", Adw.ResponseAppearance.DESTRUCTIVE
    )
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def on_response(
        _dialog: Adw.AlertDialog, response: str
    ) -> None:
        if response != "delete":
            return
        import subprocess

        data_dir = (
            f"/var/lib/big-parental-controls/activity/{username}"
        )

        def do_delete() -> bool:
            subprocess.run(
                ["pkexec", "rm", "-rf", data_dir],
                timeout=10,
                check=False,
            )
            return True

        def on_done(_ok: bool) -> None:
            window.show_toast(
                _("Activity data deleted for %s") % username
            )

        run_async(do_delete, on_done)

    dialog.connect("response", on_response)
    dialog.present(window)


def start_export_data(
    window: object, username: str
) -> None:
    """Export activity data as JSON (GDPR Art. 20)."""
    file_dialog = Gtk.FileDialog()
    file_dialog.set_title(_("Export Activity Data"))
    file_dialog.set_initial_name(f"{username}_activity.json")

    def on_save(
        dlg: Gtk.FileDialog, result: Gio.AsyncResult
    ) -> None:
        import contextlib

        with contextlib.suppress(Exception):
            gfile = dlg.save_finish(result)
            if not gfile:
                return
            path = gfile.get_path()
            activity = ActivityService()

            def do_export() -> str:
                summary = activity.get_summary(username, days=30)
                data = {
                    "username": username,
                    "period_days": 30,
                    "daily_totals": summary.daily_totals,
                    "hourly_distribution": (
                        summary.hourly_distribution
                    ),
                    "sessions": [
                        {
                            "start": s.start.isoformat(),
                            "end": (
                                s.end.isoformat()
                                if s.end
                                else None
                            ),
                            "duration_minutes": (
                                s.duration_minutes
                            ),
                            "tty": s.tty,
                            "session_type": s.session_type,
                        }
                        for s in summary.sessions
                    ],
                }
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(
                        data, f, ensure_ascii=False, indent=2
                    )
                return path

            def on_done(saved_path: str) -> None:
                window.show_toast(
                    _("Data exported to %s") % saved_path
                )

            run_async(do_export, on_done)

    file_dialog.save(window, None, on_save)
