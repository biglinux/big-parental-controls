"""Application class for big-parental-controls."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, Gio, Gtk

from window import MainWindow
from utils.i18n import setup_i18n

_ = setup_i18n()

APP_ID = "br.com.biglinux.parental-controls"
PRIVACY_POLICY_URL = "https://github.com/biglinux/big-parental-controls/blob/main/PRIVACY.md"


class ParentalControlsApp(Adw.Application):
    """Main application for big-parental-controls."""

    def __init__(self):
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )

    def do_startup(self):
        Adw.Application.do_startup(self)
        self._load_css()
        self._setup_actions()

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = MainWindow(application=self)
        window.present()

    def _setup_actions(self):
        """Register application actions."""
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

    def _on_about(self, action, param):
        """Show the About dialog with privacy policy link."""
        about = Adw.AboutDialog()
        about.set_application_name(_("Parental Controls"))
        about.set_application_icon("big-parental-controls")
        about.set_version("1.0")
        about.set_developer_name("BigLinux")
        about.set_website("https://www.biglinux.com.br")
        about.set_issue_url("https://github.com/biglinux/big-parental-controls/issues")
        about.set_license_type(Gtk.License.GPL_3_0)
        about.set_copyright("© 2026 BigLinux")

        # Privacy policy section
        about.add_legal_section(
            _("Privacy Policy"),
            "© 2026 BigLinux",
            Gtk.License.CUSTOM,
            _(
                "This application does not collect, store, or transmit personal data. "
                "All processing happens locally on this device. "
                "No data is shared with third parties.\n\n"
                "Full policy: %s"
            )
            % PRIVACY_POLICY_URL,
        )

        about.present(self.props.active_window)

    def _load_css(self):
        """Load custom CSS stylesheet."""
        css_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
        if not os.path.isfile(css_path):
            return

        provider = Gtk.CssProvider()
        provider.load_from_path(css_path)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
