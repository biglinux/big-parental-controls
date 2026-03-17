"""DNS configuration page — optional family-safe DNS for supervised accounts."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from services.accounts_service import AccountsServiceWrapper
from services.dns_service import DNS_PROVIDERS, DnsService
from utils.i18n import setup_i18n

_ = setup_i18n()


class DnsPage(Gtk.Box):
    """Page for configuring per-user DNS family-safe filtering."""

    def __init__(self, **kwargs):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)

        self._accounts = AccountsServiceWrapper()
        self._dns = DnsService()
        self._selected_uid = None
        self._selected_username = None

        self._build_ui()

    def _build_ui(self):
        # Warning banner — edge-to-edge, outside scroll
        warning = Adw.Banner()
        warning.set_title(
            _(
                "If the internet stops working after turning this on, "
                "try disabling the web filter — some networks do not allow it."
            )
        )
        warning.set_revealed(True)
        self.append(warning)

        # Scrollable content
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

        # Description
        desc = Gtk.Label(
            label=_(
                "Turn on a web filter to automatically block websites that are not "
                "appropriate for children. Works with any browser."
            )
        )
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        desc.add_css_class("dim-label")
        inner.append(desc)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("network-server-symbolic")
        self._empty_status.set_title(_("No Supervised Accounts"))
        self._empty_status.set_description(
            _("Create one in the Users page first.")
        )
        self._empty_status.set_visible(False)
        inner.append(self._empty_status)

        # Settings
        self._settings_group = Adw.PreferencesGroup()
        self._settings_group.set_title(_("Filter Settings"))

        self._enable_row = Adw.SwitchRow(title=_("Enable web filter"))
        self._enable_row.set_subtitle(_("Automatically block inappropriate websites"))
        self._enable_row.connect("notify::active", self._on_enable_toggled)
        self._settings_group.add(self._enable_row)

        provider_names = [info["name"] for info in DNS_PROVIDERS.values()]
        provider_names.append(_("Custom"))
        self._provider_list = Gtk.StringList.new(provider_names)

        self._provider_row = Adw.ComboRow(title=_("Filter provider"))
        self._provider_row.set_model(self._provider_list)
        self._provider_row.set_sensitive(False)
        self._provider_row.connect("notify::selected", self._on_provider_changed)
        self._settings_group.add(self._provider_row)

        self._custom_dns1 = Adw.EntryRow(title=_("Primary DNS"))
        self._custom_dns1.set_visible(False)
        self._settings_group.add(self._custom_dns1)

        self._custom_dns2 = Adw.EntryRow(title=_("Secondary DNS"))
        self._custom_dns2.set_visible(False)
        self._settings_group.add(self._custom_dns2)

        inner.append(self._settings_group)

        # Apply button
        apply_box = Gtk.Box()
        apply_box.set_halign(Gtk.Align.END)

        self._apply_btn = Gtk.Button(label=_("Apply"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.connect("clicked", self._on_apply)
        apply_box.append(self._apply_btn)
        inner.append(apply_box)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

        # Start with empty state visible
        self._empty_status.set_visible(True)
        self._settings_group.set_visible(False)
        self._apply_btn.get_parent().set_visible(False)

    def set_selected_user(self, user):
        """Called by window when the header dropdown selection changes."""
        if user is None:
            self._selected_uid = None
            self._selected_username = None
            self._empty_status.set_visible(True)
            self._settings_group.set_visible(False)
            self._apply_btn.get_parent().set_visible(False)
            return

        self._selected_uid = user.get_uid()
        self._selected_username = user.get_user_name()
        self._empty_status.set_visible(False)
        self._settings_group.set_visible(True)
        self._apply_btn.get_parent().set_visible(True)
        self._load_current_config()

    def _load_current_config(self):
        if self._selected_uid is None:
            return

        config = self._dns.get_dns_for_user(self._selected_uid)
        if config is None:
            self._enable_row.set_active(False)
        else:
            self._enable_row.set_active(True)
            # Find provider index
            provider_keys = list(DNS_PROVIDERS.keys())
            provider = config.get("provider", "")
            if provider in provider_keys:
                self._provider_row.set_selected(provider_keys.index(provider))
            else:
                # Custom
                self._provider_row.set_selected(len(provider_keys))
                self._custom_dns1.set_text(config.get("dns1", ""))
                self._custom_dns2.set_text(config.get("dns2", ""))

    def _on_enable_toggled(self, row, pspec):
        active = row.get_active()
        if not active and self._selected_uid is not None:
            # Confirm before disabling — neutral wording (G4 anti-nudge)
            dialog = Adw.AlertDialog()
            dialog.set_heading(_("Disable web filter?"))
            dialog.set_body(
                _("Inappropriate websites will no longer be blocked for this account.")
            )
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("disable", _("Disable"))
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", self._on_disable_dns_response)
            dialog.present(self.get_root())
            return

        self._provider_row.set_sensitive(active)
        self._apply_btn.set_sensitive(True)
        if not active:
            self._custom_dns1.set_visible(False)
            self._custom_dns2.set_visible(False)

    def _on_disable_dns_response(self, dialog, response):
        if response == "disable":
            self._provider_row.set_sensitive(False)
            self._custom_dns1.set_visible(False)
            self._custom_dns2.set_visible(False)
            self._apply_btn.set_sensitive(True)
        else:
            # Revert toggle without triggering signal recursion
            self._enable_row.handler_block_by_func(self._on_enable_toggled)
            self._enable_row.set_active(True)
            self._enable_row.handler_unblock_by_func(self._on_enable_toggled)

    def _on_provider_changed(self, row, pspec):
        idx = row.get_selected()
        is_custom = idx >= len(DNS_PROVIDERS)
        self._custom_dns1.set_visible(is_custom)
        self._custom_dns2.set_visible(is_custom)

    def _on_apply(self, button):
        if self._selected_uid is None:
            return

        if not self._enable_row.get_active():
            self._dns.set_dns_for_user(self._selected_uid, provider=None)
            self._show_toast(_("Web filter disabled."))
            return

        idx = self._provider_row.get_selected()
        provider_keys = list(DNS_PROVIDERS.keys())

        if idx < len(provider_keys):
            provider = provider_keys[idx]
            self._dns.set_dns_for_user(self._selected_uid, provider=provider)
            self._show_toast(
                _("Web filter set to %s.") % DNS_PROVIDERS[provider]["name"]
            )
        else:
            dns1 = self._custom_dns1.get_text().strip()
            dns2 = self._custom_dns2.get_text().strip()
            if not dns1:
                self._show_toast(_("Primary DNS is required."))
                return
            self._dns.set_dns_for_user(
                self._selected_uid,
                provider="custom",
                custom_dns1=dns1,
                custom_dns2=dns2,
            )
            self._show_toast(_("Custom web filter configured."))

    def _show_toast(self, message):
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def refresh(self):
        """Refresh current DNS config (called on navigation)."""
        if self._selected_uid is not None:
            self._load_current_config()
