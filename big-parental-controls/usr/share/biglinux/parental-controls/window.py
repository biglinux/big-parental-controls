"""Main window for big-parental-controls — composite template with sidebar."""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from pages.app_filter_page import AppFilterPage
from pages.dns_page import DnsPage
from pages.support_page import SupportPage
from pages.time_limits_page import TimeLimitsPage
from pages.users_page import UsersPage
from pages.welcome_page import WelcomePage
from services.accounts_service import AccountsServiceWrapper
from utils.i18n import setup_i18n

_ = setup_i18n()

# Section IDs used to map sidebar rows ↔ stack pages
_SECTION_IDS = ("home", "users", "apps", "time", "dns", "support")

# Section labels for content page title (matches row order in .ui)
_SECTION_LABELS = {
    "home": _("Home"),
    "users": _("Users"),
    "apps": _("Allowed Apps"),
    "time": _("Screen Time"),
    "dns": _("Web Filter"),
    "support": _("Help"),
}

# Sections that show the supervised user dropdown in the header bar
_USER_SECTIONS = {"apps", "time", "dns"}

_UI_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window.ui")


@Gtk.Template(filename=_UI_FILE)
class MainWindow(Adw.ApplicationWindow):
    """Main window with sidebar navigation — loaded from window.ui template."""

    __gtype_name__ = "MainWindow"

    # Template children (must match 'id' in window.ui)
    _toast_overlay = Gtk.Template.Child("toast_overlay")
    _split_view = Gtk.Template.Child("split_view")
    _sidebar_list = Gtk.Template.Child("sidebar_list")
    _content_page = Gtk.Template.Child("content_page")
    _content_header = Gtk.Template.Child("content_header")
    _content_stack = Gtk.Template.Child("content_stack")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title(_("Parental Controls"))

        self._accounts = AccountsServiceWrapper()
        self._supervised_users: list = []
        self._current_section: str = "home"
        self._pages = {}

        # Supervised user dropdown (placed as title_widget when needed)
        self._user_dropdown = Gtk.DropDown()
        self._user_dropdown.set_visible(False)

        self._setup_pages()
        self._sidebar_list.connect("row-selected", self._on_section_selected)
        self._user_dropdown.connect("notify::selected", self._on_user_dropdown_changed)

        # "Add Supervised Account" button for Users headerbar
        self._add_user_btn = Gtk.Button(label=_("Add Supervised Account"))
        self._add_user_btn.add_css_class("suggested-action")
        self._add_user_btn.connect("clicked", self._on_add_user_clicked)

        # Initial dropdown population
        self._refresh_supervised_dropdown()

        # Select first section
        first_row = self._sidebar_list.get_row_at_index(0)
        if first_row:
            self._sidebar_list.select_row(first_row)

    def _setup_pages(self):
        """Create page widgets and add them to the content stack."""
        self._pages["home"] = WelcomePage()
        self._pages["users"] = UsersPage()
        self._pages["apps"] = AppFilterPage()
        self._pages["time"] = TimeLimitsPage()
        self._pages["dns"] = DnsPage()
        self._pages["support"] = SupportPage()

        for section_id, page in self._pages.items():
            self._content_stack.add_named(page, section_id)

    # ------------------------------------------------------------------
    # Supervised user dropdown
    # ------------------------------------------------------------------

    def _refresh_supervised_dropdown(self, select_username: str | None = None):
        """Reload the supervised user list in the header dropdown."""
        users = self._accounts.list_users()
        self._supervised_users = [u for u in users if self._accounts.is_supervised(u)]

        if self._supervised_users:
            names = [
                u.get_real_name() or u.get_user_name()
                for u in self._supervised_users
            ]
            self._user_dropdown.set_model(Gtk.StringList.new(names))
            self._user_dropdown.set_sensitive(True)

            # Select requested user or keep current
            idx = 0
            if select_username:
                for i, u in enumerate(self._supervised_users):
                    if u.get_user_name() == select_username:
                        idx = i
                        break
            self._user_dropdown.set_selected(idx)
        else:
            self._user_dropdown.set_model(
                Gtk.StringList.new([_("No supervised accounts")])
            )
            self._user_dropdown.set_sensitive(False)

        # Notify current page
        self._push_selected_user_to_page()

    def refresh_user_dropdown(self, select_username: str | None = None):
        """Public API called by UsersPage after create / remove / supervise."""
        self._refresh_supervised_dropdown(select_username)

    def _get_selected_supervised_user(self):
        """Return the currently selected supervised user object or None."""
        idx = self._user_dropdown.get_selected()
        if 0 <= idx < len(self._supervised_users):
            return self._supervised_users[idx]
        return None

    def _on_user_dropdown_changed(self, dropdown, pspec):
        self._push_selected_user_to_page()

    def _push_selected_user_to_page(self):
        """Send the currently selected user to the active page."""
        page = self._pages.get(self._current_section)
        if page is None or self._current_section not in _USER_SECTIONS:
            return

        user = self._get_selected_supervised_user()
        if hasattr(page, "set_selected_user"):
            page.set_selected_user(user)

    def _on_add_user_clicked(self, button):
        """Delegate to UsersPage._on_add_clicked."""
        page = self._pages.get("users")
        if page:
            page._on_add_clicked(button)

    # ------------------------------------------------------------------
    # Section navigation
    # ------------------------------------------------------------------

    def _on_section_selected(self, listbox, row):
        if row is None:
            return

        section_id = row.get_name()
        self._current_section = section_id
        self._content_stack.set_visible_child_name(section_id)

        # Configure headerbar per section
        label = _SECTION_LABELS.get(section_id, section_id)
        self._content_page.set_title(label)

        if section_id in _USER_SECTIONS:
            # Apps / Time / DNS — dropdown centered
            self._content_header.set_show_title(True)
            self._content_header.set_title_widget(self._user_dropdown)
            self._user_dropdown.set_visible(True)
        elif section_id == "users":
            # Users — "Add Supervised Account" button centered
            self._content_header.set_show_title(True)
            self._content_header.set_title_widget(self._add_user_btn)
        else:
            # Home / Support — hide title in headerbar
            self._content_header.set_show_title(False)
            self._content_header.set_title_widget(None)
            self._user_dropdown.set_visible(False)

        # Refresh the page when navigating to it
        page = self._pages.get(section_id)
        if page and hasattr(page, "refresh"):
            page.refresh()

        # Push user selection to pages that need it
        if section_id in _USER_SECTIONS:
            self._push_selected_user_to_page()

        # Show content on mobile
        self._split_view.set_show_content(True)

    def show_toast(self, message: str):
        """Show a toast notification (for success/info messages)."""
        toast = Adw.Toast.new(message)
        toast.set_timeout(3)
        self._toast_overlay.add_toast(toast)

    def show_error(self, message: str):
        """Show an error dialog (for failures that need attention)."""
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Error"))
        dialog.set_body(message)
        dialog.add_response("ok", _("OK"))
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(self)
