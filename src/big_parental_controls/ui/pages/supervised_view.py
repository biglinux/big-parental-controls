"""Supervised user view — read-only screen showing own usage data and help."""

import locale
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.ui.widgets.activity_block import ActivityBlock
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()

# Help resources per locale prefix (language_COUNTRY or language).
# Each entry: (name, description_key, uri)
# Phone numbers use tel: URI. Websites use https://.
_HELP_RESOURCES: dict[str, list[tuple[str, str, str]]] = {
    "pt_BR": [
        ("CVV 188", "Apoio emocional, 24h", "tel:188"),
        ("SaferNet", "Segurança online para crianças e adolescentes", "https://new.safernet.org.br/denuncie"),
        ("Disque 100", "Violações de direitos humanos", "tel:100"),
    ],
    "pt": [
        ("SOS Criança", "Linha de apoio a crianças e jovens", "tel:116111"),
        ("APAV", "Apoio à vítima", "https://apav.pt"),
    ],
    "es": [
        ("ANAR", "Ayuda a niños y adolescentes", "tel:116111"),
        ("IS4K", "Internet segura para menores", "https://www.is4k.es"),
    ],
    "fr": [
        ("e-Enfance", "Protection des mineurs en ligne", "https://e-enfance.org"),
        ("119 Allô Enfance", "Enfance en danger", "tel:119"),
    ],
    "de": [
        ("Nummer gegen Kummer", "Kinder- und Jugendtelefon", "tel:116111"),
        ("klicksafe", "Sicherheit im Internet", "https://www.klicksafe.de"),
    ],
    "it": [
        ("Telefono Azzurro", "Ascolto bambini e adolescenti", "tel:19696"),
        ("Generazioni Connesse", "Sicurezza in rete", "https://www.generazioniconnesse.it"),
    ],
    "en": [
        ("Childhelp", "Child abuse hotline", "tel:18004224453"),
        ("NCMEC", "Missing & exploited children", "https://www.missingkids.org"),
        ("StopBullying", "Bullying prevention", "https://www.stopbullying.gov"),
    ],
}


def _get_help_resources() -> list[tuple[str, str, str]]:
    """Return help resources matching the current system locale."""
    lang = os.environ.get("LANG", "") or ""
    if not lang:
        try:
            lang = locale.getlocale()[0] or ""
        except ValueError:
            lang = ""

    # Try full match (pt_BR), then language only (pt), fallback to en
    lang_base = lang.split(".")[0]  # e.g. "pt_BR" from "pt_BR.UTF-8"
    if lang_base in _HELP_RESOURCES:
        return _HELP_RESOURCES[lang_base]
    lang_short = lang_base.split("_")[0]  # e.g. "pt"
    if lang_short in _HELP_RESOURCES:
        return _HELP_RESOURCES[lang_short]
    return _HELP_RESOURCES["en"]


class SupervisedView(Gtk.Box):
    """Read-only view for supervised users.

    Shows:
    - Welcome message
    - Own usage charts (screen time, app usage)
    - Help and support links
    Does NOT show:
    - Other users' data
    - Any settings or modification controls
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._accounts = AccountsServiceWrapper()
        self._username = os.environ.get("USER") or os.getlogin()
        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=_("My Screen Time")))
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

        # Welcome
        welcome_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
        )
        welcome_box.set_halign(Gtk.Align.CENTER)
        welcome_box.set_margin_bottom(8)

        icon = Gtk.Image(
            icon_name="preferences-system-parental-controls-symbolic",
        )
        icon.set_pixel_size(48)
        welcome_box.append(icon)

        user = self._accounts.get_current_user()
        display_name = self._username
        if user:
            real = user.get_real_name()
            uname = user.get_user_name()
            if real and real != "None" and real.strip():
                display_name = real
            elif uname and uname != "None" and uname.strip():
                display_name = uname

        welcome_label = Gtk.Label(
            label=_("Hello, %s") % display_name,
        )
        welcome_label.add_css_class("title-2")
        welcome_box.append(welcome_label)

        desc_label = Gtk.Label(
            label=_("Here you can see your screen time and application usage."),
        )
        desc_label.add_css_class("dim-label")
        desc_label.set_wrap(True)
        desc_label.set_justify(Gtk.Justification.CENTER)
        welcome_box.append(desc_label)

        inner.append(welcome_box)

        # Activity block (own data only)
        self._activity_block = ActivityBlock()
        inner.append(self._activity_block)

        # Help group
        help_group = Adw.PreferencesGroup()
        help_group.set_title(_("Help and Support"))
        for name, desc, uri in _get_help_resources():
            row = Adw.ActionRow()
            row.set_title(name)
            row.set_subtitle(desc)
            row.set_activatable(True)
            if uri.startswith("tel:"):
                phone = uri.removeprefix("tel:")
                suffix = Gtk.Label(label=phone)
                suffix.add_css_class("dim-label")
                row.add_suffix(suffix)
            else:
                arrow = Gtk.Image(icon_name="adw-external-link-symbolic")
                arrow.add_css_class("dim-label")
                row.add_suffix(arrow)
            row.connect("activated", self._on_help_row_activated, uri)
            help_group.add(row)
        inner.append(help_group)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)
        self.append(toolbar)

        # Load own data
        self._activity_block.load_user(self._username)

    def _on_help_row_activated(
        self, _row: Adw.ActionRow, uri: str,
    ) -> None:
        """Open the help link in the default handler."""
        launcher = Gtk.UriLauncher(uri=uri)
        launcher.launch(self.get_root(), None, None)
