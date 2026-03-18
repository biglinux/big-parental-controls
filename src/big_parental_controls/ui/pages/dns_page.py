"""DNS filtering page — manage per-user web content filtering.

Redesigned with:
  - Contextual explanation of DNS for non-technical users
  - Radio-style provider selection with descriptions and links
  - Custom DNS option
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.services.dns_service import DnsService
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()

# Provider metadata with descriptions and URLs
_PROVIDERS = [
    {
        "key": "cleanbrowsing",
        "name": "CleanBrowsing Family Filter",
        "dns1": "185.228.168.168",
        "dns2": "185.228.169.168",
        "url": "https://cleanbrowsing.org",
        "description": _(
            "Blocks adult content, gambling, and phishing websites. "
            "One of the most widely used free family filters."
        ),
    },
    {
        "key": "opendns",
        "name": "OpenDNS FamilyShield",
        "dns1": "208.67.222.123",
        "dns2": "208.67.220.123",
        "url": "https://www.opendns.com/setupguide/#familyshield",
        "description": _(
            "By Cisco. Automatically blocks adult content on all devices. "
            "No account or configuration needed."
        ),
    },
    {
        "key": "cloudflare",
        "name": "Cloudflare for Families",
        "dns1": "1.1.1.3",
        "dns2": "1.0.0.3",
        "url": "https://one.one.one.one/family/",
        "description": _(
            "By Cloudflare (1.1.1.3). Blocks malware and adult content. "
            "Very fast and privacy-focused."
        ),
    },
]


class DnsPage(Gtk.Box):
    """Page for managing family-safe DNS filtering."""

    def __init__(self, user: object, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._dns = DnsService()
        self._selected_uid: int = user.get_uid()
        self._selected_username: str = user.get_user_name()
        self._provider_checks: list[Gtk.CheckButton] = []
        self._loading: bool = False
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

        # ── What is DNS filtering ─────────────────────────────
        explain_group = Adw.PreferencesGroup()
        explain_group.set_title(_("What is web filtering?"))
        explain_group.set_description(
            _(
                "Web filtering uses special DNS servers to block "
                "access to inappropriate websites such as adult "
                "content, gambling, and known malicious pages. "
                "It works transparently — no software is installed "
                "on the child's session; the system's firewall "
                "redirects their internet lookups to a protective "
                "server."
            )
        )
        inner.append(explain_group)

        # ── Enable / disable ──────────────────────────────────
        toggle_group = Adw.PreferencesGroup()
        toggle_group.set_title(
            _("Filtering for %s") % self._selected_username
        )

        self._enable_row = Adw.SwitchRow()
        self._enable_row.set_title(_("Enable web filtering"))
        self._enable_row.set_subtitle(
            _(
                "When enabled, all web requests from this user "
                "are redirected through the chosen DNS provider."
            )
        )
        self._enable_row.connect("notify::active", self._on_enable_toggled)
        toggle_group.add(self._enable_row)
        inner.append(toggle_group)

        # ── Provider selection (radio style) ──────────────────
        self._providers_group = Adw.PreferencesGroup()
        self._providers_group.set_title(_("Choose a provider"))
        self._providers_group.set_description(
            _(
                "Each provider maintains a list of blocked sites. "
                "All options below are free and privacy-respecting."
            )
        )
        self._providers_group.set_sensitive(False)

        radio_group_btn: Gtk.CheckButton | None = None
        for prov in _PROVIDERS:
            row = Adw.ActionRow()
            row.set_title(prov["name"])
            row.set_subtitle(prov["description"])
            row.set_subtitle_lines(3)

            # Radio button
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            if radio_group_btn is not None:
                check.set_group(radio_group_btn)
            else:
                radio_group_btn = check
            check.connect("toggled", self._on_radio_toggled)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self._provider_checks.append(check)

            # Link button
            link = Gtk.Button(label=_("Learn more"))
            link.add_css_class("flat")
            link.set_valign(Gtk.Align.CENTER)
            url = prov["url"]
            link.connect("clicked", lambda _b, u=url: self._open_url(u))
            row.add_suffix(link)

            self._providers_group.add(row)

        # Custom option
        custom_row = Adw.ActionRow()
        custom_row.set_title(_("Custom DNS server"))
        custom_row.set_subtitle(
            _("Enter your own DNS addresses for advanced setups.")
        )
        self._custom_check = Gtk.CheckButton()
        self._custom_check.set_valign(Gtk.Align.CENTER)
        if radio_group_btn is not None:
            self._custom_check.set_group(radio_group_btn)
        self._custom_check.connect("toggled", self._on_radio_toggled)
        custom_row.add_prefix(self._custom_check)
        custom_row.set_activatable_widget(self._custom_check)
        self._providers_group.add(custom_row)

        inner.append(self._providers_group)

        # ── Custom DNS entries ────────────────────────────────
        self._custom_group = Adw.PreferencesGroup()
        self._custom_group.set_title(_("Custom DNS Addresses"))
        self._custom_group.set_visible(False)

        self._dns1_row = Adw.EntryRow()
        self._dns1_row.set_title(_("Primary DNS"))
        self._custom_group.add(self._dns1_row)

        self._dns2_row = Adw.EntryRow()
        self._dns2_row.set_title(_("Secondary DNS (optional)"))
        self._custom_group.add(self._dns2_row)

        inner.append(self._custom_group)

        # ── Apply ─────────────────────────────────────────────
        self._apply_btn = Gtk.Button(label=_("Apply"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.add_css_class("pill")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.set_halign(Gtk.Align.CENTER)
        self._apply_btn.connect("clicked", self._on_apply)
        inner.append(self._apply_btn)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)
        self.append(toolbar)

        self._load_config()

    # ── Load / save ───────────────────────────────────────────

    def _load_config(self) -> None:
        """Load current DNS config for the user."""
        self._loading = True
        config = self._dns.get_dns_for_user(self._selected_uid)
        if config:
            self._enable_row.set_active(True)
            self._providers_group.set_sensitive(True)
            provider = config.get("provider", "")
            keys = [p["key"] for p in _PROVIDERS]
            if provider in keys:
                idx = keys.index(provider)
                self._provider_checks[idx].set_active(True)
                self._custom_group.set_visible(False)
            elif provider == "custom":
                self._custom_check.set_active(True)
                self._dns1_row.set_text(config.get("dns1", ""))
                self._dns2_row.set_text(config.get("dns2", ""))
                self._custom_group.set_visible(True)
        else:
            self._enable_row.set_active(False)
            self._providers_group.set_sensitive(False)
        self._loading = False
        self._apply_btn.set_sensitive(False)

    # ── UI handlers ───────────────────────────────────────────

    def _on_enable_toggled(self, row: Adw.SwitchRow, _pspec: object) -> None:
        active = row.get_active()
        self._providers_group.set_sensitive(active)
        if not active:
            self._custom_group.set_visible(False)
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _on_radio_toggled(self, _check: Gtk.CheckButton) -> None:
        self._custom_group.set_visible(self._custom_check.get_active())
        if not self._loading:
            self._apply_btn.set_sensitive(True)

    def _open_url(self, url: str) -> None:
        launcher = Gtk.UriLauncher(uri=url)
        launcher.launch(self.get_root(), None, None, None)

    def _get_selected_provider(self) -> str | None:
        """Return the key of the selected provider or 'custom'."""
        for i, check in enumerate(self._provider_checks):
            if check.get_active():
                return _PROVIDERS[i]["key"]
        if self._custom_check.get_active():
            return "custom"
        return None

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply DNS configuration."""
        uid = self._selected_uid

        if not self._enable_row.get_active():
            def do_disable() -> bool:
                return self._dns.set_dns_for_user(uid, provider=None)

            def on_done(_result: object) -> None:
                self._apply_btn.set_sensitive(False)
                self._show_success(_("Web filtering disabled."))

            run_async(do_disable, on_done, lambda e: self._show_error(str(e)))
            return

        provider = self._get_selected_provider()
        if provider is None:
            self._show_error(_("Please select a DNS provider."))
            return

        if provider == "custom":
            dns1 = self._dns1_row.get_text().strip()
            dns2 = self._dns2_row.get_text().strip()
            if not dns1:
                self._show_error(_("Primary DNS address is required."))
                return

            def do_set_custom() -> bool:
                return self._dns.set_dns_for_user(
                    uid, provider="custom",
                    custom_dns1=dns1, custom_dns2=dns2,
                )

            def on_done(_result: object) -> None:
                self._apply_btn.set_sensitive(False)
                self._show_success(_("Custom DNS applied."))

            run_async(
                do_set_custom, on_done, lambda e: self._show_error(str(e)),
            )
        else:
            def do_set() -> bool:
                return self._dns.set_dns_for_user(uid, provider=provider)

            def on_done(_result: object) -> None:
                self._apply_btn.set_sensitive(False)
                self._show_success(_("Web filtering enabled."))

            run_async(do_set, on_done, lambda e: self._show_error(str(e)))

    def _show_success(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def refresh(self) -> None:
        """Refresh config."""
        self._load_config()
