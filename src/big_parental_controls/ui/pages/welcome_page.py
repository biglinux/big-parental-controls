"""Welcome page — first screen with features overview and privacy info."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()


class WelcomePage(Gtk.Box):
    """Landing page displaying feature summary and privacy commitment."""

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
        inner.set_margin_top(24)
        inner.set_margin_bottom(24)
        inner.set_margin_start(24)
        inner.set_margin_end(24)

        # Status page header
        status = Adw.StatusPage()
        status.set_icon_name("preferences-system-parental-controls-symbolic")
        status.set_title(_("Parental Controls"))
        status.set_description(
            _("Protect children online — manage apps, screen time, and web filtering.")
        )
        inner.append(status)

        # Features group
        features_group = Adw.PreferencesGroup()
        features_group.set_title(_("Features"))

        features = [
            ("system-users-symbolic", _("Supervised Accounts"), _("Create protected user profiles")),
            (
                "application-x-executable-symbolic",
                _("App Access"),
                _("Control which apps each child can use"),
            ),
            (
                "preferences-system-time-symbolic",
                _("Screen Time"),
                _("Set allowed hours and daily usage limits"),
            ),
            ("network-workgroup-symbolic", _("Web Filter"), _("Block inappropriate web content via DNS")),
        ]
        for icon, title, subtitle in features:
            row = Adw.ActionRow()
            row.set_title(title)
            row.set_subtitle(subtitle)
            img = Gtk.Image(
                icon_name=icon,
                pixel_size=32,
                accessible_role=Gtk.AccessibleRole.PRESENTATION,
            )
            row.add_prefix(img)
            features_group.add(row)

        inner.append(features_group)

        # Privacy group
        privacy_group = Adw.PreferencesGroup()
        privacy_group.set_title(_("Privacy"))

        privacy_row = Adw.ActionRow()
        privacy_row.set_title(_("Data stays on this computer"))
        privacy_row.set_subtitle(
            _("Compliant with ECA Digital, LGPD, and GDPR — no data leaves this device.")
        )
        privacy_icon = Gtk.Image(
            icon_name="security-high-symbolic",
            pixel_size=32,
            accessible_role=Gtk.AccessibleRole.PRESENTATION,
        )
        privacy_row.add_prefix(privacy_icon)
        privacy_group.add(privacy_row)

        inner.append(privacy_group)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        self.append(scrolled)

    def refresh(self) -> None:
        """No-op — static page."""
