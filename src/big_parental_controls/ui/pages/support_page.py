"""Support page — links to help channels and reporting services (Art. 17, IX)."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()

SUPPORT_LINKS = [
    {
        "title": "CVV 188",
        "subtitle": _("Centro de Valorização da Vida — emotional support by phone or chat"),
        "icon": "call-start-symbolic",
        "url": "https://www.cvv.org.br",
    },
    {
        "title": "SaferNet Brasil",
        "subtitle": _("Report and get help with online safety issues"),
        "icon": "security-high-symbolic",
        "url": "https://new.safernet.org.br",
    },
    {
        "title": _("Disque 100"),
        "subtitle": _("Report violations of children's and adolescents' rights"),
        "icon": "dialog-warning-symbolic",
        "url": "https://www.gov.br/mdh/pt-br/acesso-a-informacao/disque-100",
    },
    {
        "title": "CERT.br",
        "subtitle": _("Internet security guides and best practices"),
        "icon": "network-server-symbolic",
        "url": "https://cartilha.cert.br",
    },
]


class SupportPage(Gtk.Box):
    """Page displaying support links and help channels."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._build_ui()

    def _build_ui(self) -> None:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        inner.set_margin_top(0)
        inner.set_margin_bottom(24)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        desc = Gtk.Label(
            label=_(
                "If you or someone you know needs help, you are not alone. "
                "These organizations provide free, confidential support — "
                "no one will judge you."
            )
        )
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        desc.add_css_class("dim-label")
        inner.append(desc)

        # Support links
        group = Adw.PreferencesGroup()

        for link in SUPPORT_LINKS:
            row = Adw.ActionRow()
            row.set_title(link["title"])
            row.set_subtitle(link["subtitle"])
            row.set_activatable(True)
            row.connect("activated", self._on_link_activated, link["url"])

            icon = Gtk.Image(
                icon_name=link["icon"],
                pixel_size=32,
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
            )
            row.add_prefix(icon)

            arrow = Gtk.Image(
                icon_name="go-next-symbolic",
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
            )
            row.add_suffix(arrow)

            group.add(row)

        inner.append(group)

        # Emergency info
        emergency_group = Adw.PreferencesGroup()
        emergency_group.set_title(_("Emergency"))

        emergency_row = Adw.ActionRow()
        emergency_row.set_title(_("In case of immediate danger, call 190 (Police) or 192 (SAMU)"))
        emergency_row.set_subtitle(_("These numbers are free and available 24/7"))

        emergency_icon = Gtk.Image(
            icon_name="emblem-important-symbolic",
            pixel_size=32,
            accessible_role=Gtk.AccessibleRole.PRESENTATION,
        )
        emergency_row.add_prefix(emergency_icon)

        emergency_group.add(emergency_row)
        inner.append(emergency_group)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def _on_link_activated(self, _row: Adw.ActionRow, url: str) -> None:
        """Open a URL in the default browser."""
        launcher = Gtk.UriLauncher.new(url)
        launcher.launch(self.get_root(), None, None)

    def refresh(self) -> None:
        """No-op — support links are static."""
