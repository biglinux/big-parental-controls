"""GTK Application class for Big Parental Controls."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from big_parental_controls.core.constants import (
    APP_DEVELOPER,
    APP_ID,
    APP_NAME,
    APP_VERSION,
    APP_WEBSITE,
    APP_ISSUE_URL,
    RESOURCE_BASE,
)
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class ParentalControlsApp(Adw.Application):
    """Main application class — single-instance GTK4 + libadwaita app."""

    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self._setup_actions()

    def _setup_actions(self) -> None:
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def do_activate(self) -> None:
        from big_parental_controls.window import MainWindow

        win = self.props.active_window
        if not win:
            win = MainWindow(application=self)
        win.present()

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        self._register_icon_theme()
        self._load_css()

    def _register_icon_theme(self) -> None:
        """Add project icon path for development mode."""
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        if not display:
            return
        icon_theme = Gtk.IconTheme.get_for_display(display)
        dev_icons = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "big-parental-controls", "usr", "share", "icons",
        )
        if os.path.isdir(dev_icons):
            icon_theme.add_search_path(os.path.realpath(dev_icons))

    def _load_css(self) -> None:
        css_path = os.path.join(RESOURCE_BASE, "style.css")
        if os.path.isfile(css_path):
            provider = Gtk.CssProvider()
            provider.load_from_path(css_path)
            from gi.repository import Gdk

            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )

    def _on_about(self, _action: Gio.SimpleAction, _param: object) -> None:
        dialog = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon="big-parental-controls",
            developer_name=APP_DEVELOPER,
            version=APP_VERSION,
            website=APP_WEBSITE,
            issue_url=APP_ISSUE_URL,
            license_type=Gtk.License.GPL_3_0,
            developers=[APP_DEVELOPER],
            copyright=f"© 2024-2025 {APP_DEVELOPER}",
            comments=_(
                "Keep children safe on this computer.\n"
                "Compliant with ECA Digital (Lei 15.211/2025), LGPD, and GDPR."
            ),
        )
        dialog.present(self.props.active_window)
