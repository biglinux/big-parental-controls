"""Main view — landing screen with supervised users list and help links."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.services.activity_service import ActivityService
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()

SUPPORT_LINKS = [
    ("CVV 188", _("Emotional support, 24h"), "188"),
    ("SaferNet", _("Online safety for children"), "https://www.safernet.org.br"),
    ("Disque 100", _("Human rights violations"), "100"),
]


class MainView(Gtk.Box):
    """Landing screen: app intro + supervised users list + help links."""

    def __init__(self, window: object, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._window = window
        self._accounts = AccountsServiceWrapper()
        self._activity = ActivityService()
        self._user_rows: list[Adw.ActionRow] = []
        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")
        menu_btn.set_tooltip_text(_("Main Menu"))
        menu_btn.set_menu_model(self._build_menu())
        header.pack_end(menu_btn)
        toolbar.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        inner.set_margin_top(32)
        inner.set_margin_bottom(32)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        # App header (compact — no AdwStatusPage to avoid internal scroll)
        header_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8
        )
        header_box.set_halign(Gtk.Align.CENTER)
        header_box.set_margin_bottom(8)

        icon = Gtk.Image(icon_name="big-parental-controls")
        icon.set_pixel_size(64)
        header_box.append(icon)

        desc_label = Gtk.Label(
            label=_("Manage screen time, apps and web filters for supervised users.")
        )
        desc_label.add_css_class("dim-label")
        desc_label.set_wrap(True)
        desc_label.set_justify(Gtk.Justification.CENTER)
        header_box.append(desc_label)

        inner.append(header_box)

        # Users group
        self._users_group = Adw.PreferencesGroup()
        self._users_group.set_title(_("Supervised Users"))
        inner.append(self._users_group)

        # Add user button
        add_btn = Gtk.Button()
        add_btn.set_label(_("Add Supervised User"))
        add_btn.add_css_class("suggested-action")
        add_btn.add_css_class("pill")
        add_btn.set_halign(Gtk.Align.CENTER)
        add_btn.connect("clicked", self._on_add_user)
        inner.append(add_btn)

        # Help group
        help_group = Adw.PreferencesGroup()
        help_group.set_title(_("Help and Support"))
        for name, desc, contact in SUPPORT_LINKS:
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(desc)
            suffix = Gtk.Label(label=contact)
            suffix.add_css_class("dim-label")
            row.add_suffix(suffix)
            help_group.add(row)
        inner.append(help_group)

        # Legal framework group
        inner.append(self._build_legal_group())

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)
        self.append(toolbar)

        self.refresh_users()

    @staticmethod
    def _build_menu() -> Gio.Menu:
        """Build the primary hamburger menu following Adwaita guidelines."""
        menu = Gio.Menu()
        menu.append(_("About Parental Controls"), "app.about")
        return menu

    def refresh_users(self) -> None:
        """Reload the supervised users list."""
        # Clear existing rows
        for row in self._user_rows:
            self._users_group.remove(row)
        self._user_rows.clear()

        def fetch() -> list[dict]:
            users = []
            for user in self._accounts.list_users():
                if self._accounts.is_supervised(user):
                    uname = user.get_user_name()
                    users.append({
                        "user": user,
                        "name": user.get_real_name() or uname,
                        "username": uname,
                    })
            return users

        def on_done(users: list[dict]) -> None:
            if not users:
                row = Adw.ActionRow()
                row.set_title(_("No supervised users yet"))
                row.set_subtitle(
                    _("Create a supervised account to get started.")
                )
                self._users_group.add(row)
                self._user_rows.append(row)
                return

            for info in users:
                row = self._create_user_row(info)
                self._users_group.add(row)
                self._user_rows.append(row)

        run_async(fetch, on_done)

    def _create_user_row(self, info: dict) -> Adw.ActionRow:
        """Create an activatable row for a supervised user."""
        row = Adw.ActionRow()
        row.set_title(info["name"])
        row.set_subtitle(info["username"])
        row.set_activatable(True)

        icon = Gtk.Image(icon_name="avatar-default-symbolic")
        row.add_prefix(icon)

        arrow = Gtk.Image(icon_name="go-next-symbolic")
        row.add_suffix(arrow)

        user = info["user"]
        row.connect("activated", lambda _r: self._window.show_user_detail(user))
        return row

    def _on_add_user(self, _btn: Gtk.Button) -> None:
        """Open the user creation flow via the users page."""
        self._window.show_add_user()

    def _build_legal_group(self) -> Adw.PreferencesGroup:
        """Legal framework references (ECA, LGPD, GDPR, UK Code, DSA)."""
        group = Adw.PreferencesGroup()
        group.set_title(_("Legal Framework"))

        laws = [
            (
                _("ECA Digital — Brazil"),
                _(
                    "Law 15.211/2025 — Safety, Privacy, and Parental "
                    "Control for Children in the Digital Environment. "
                    "This app implements Art. 12 (age verification), "
                    "Art. 13 (data minimization), Art. 17 (protective "
                    "measures), and Art. 18 (activity monitoring)."
                ),
            ),
            (
                _("LGPD — Brazil"),
                _(
                    "Law 13.709/2018 — General Data Protection Law. "
                    "Compliant with Art. 14 (children's data requires "
                    "specific parental consent), Art. 18 (right to "
                    "access and delete data), Art. 46 (security)."
                ),
            ),
            (
                _("GDPR — European Union"),
                _(
                    "Regulation 2016/679 — General Data Protection "
                    "Regulation. Compliant with Art. 8 (child consent "
                    "via parent), Art. 13 (transparent information), "
                    "Art. 17 (right to erasure), Art. 20 (data "
                    "portability), Art. 25 (privacy by design)."
                ),
            ),
            (
                _("UK Children's Code"),
                _(
                    "Age Appropriate Design Code — 15 standards for "
                    "child-safe digital services, including data "
                    "minimization, default protections, and parental "
                    "controls."
                ),
            ),
            (
                _("EU Digital Services Act"),
                _(
                    "Regulation 2022/2065 — Transparency, user safety, "
                    "and minors' protection in digital platforms."
                ),
            ),
        ]

        for title, subtitle in laws:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(subtitle)
            group.add(row)

        return group
