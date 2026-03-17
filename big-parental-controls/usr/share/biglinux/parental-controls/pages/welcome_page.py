"""Welcome page — explains what the app does, why and how."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from utils.i18n import setup_i18n

_ = setup_i18n()

# Feature items: (icon, title, description)
_FEATURES = [
    (
        "system-users-symbolic",
        _("Users"),
        _("Manage supervised accounts for children"),
    ),
    (
        "application-x-executable-symbolic",
        _("Allowed Apps"),
        _("Choose which programs are available"),
    ),
    (
        "preferences-system-time-symbolic",
        _("Screen Time"),
        _("Set daily usage limits"),
    ),
    (
        "network-workgroup-symbolic",
        _("Web Filter"),
        _("Block harmful websites automatically"),
    ),
    (
        "help-browser-symbolic",
        _("Help"),
        _("Find support contacts and resources"),
    ),
]


class WelcomePage(Gtk.Box):
    """Landing page shown when the application starts."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        self.append(scroll)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)
        scroll.set_child(clamp)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        outer.set_margin_top(0)
        outer.set_margin_bottom(48)
        outer.set_margin_start(16)
        outer.set_margin_end(16)
        clamp.set_child(outer)

        # --- Title row: icon + title inline ---
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        title_box.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image(icon_name="big-parental-controls", pixel_size=48,
                       accessible_role=Gtk.AccessibleRole.PRESENTATION)
        title_box.append(icon)

        title = Gtk.Label(label=_("Parental Controls"))
        title.add_css_class("title-1")
        title_box.append(title)

        outer.append(title_box)

        # --- Subtitle ---
        subtitle = Gtk.Label(
            label=_(
                "Keep children safe on this computer. "
                "Everything works locally — age range data is shared with "
                "other apps on this device via D-Bus to adjust content, "
                "but nothing is sent to the internet."
            )
        )
        subtitle.set_wrap(True)
        subtitle.set_justify(Gtk.Justification.CENTER)
        subtitle.add_css_class("dim-label")
        subtitle.set_halign(Gtk.Align.CENTER)
        outer.append(subtitle)

        # --- Features group ---
        features_group = Adw.PreferencesGroup()
        features_group.set_title(_("Features"))
        features_group.set_margin_top(16)

        for icon_name, feat_title, feat_desc in _FEATURES:
            row = Adw.ActionRow()
            row.set_title(feat_title)
            row.set_subtitle(feat_desc)
            row.set_activatable(False)

            row_icon = Gtk.Image(icon_name=icon_name, pixel_size=24,
                                accessible_role=Gtk.AccessibleRole.PRESENTATION)
            row.add_prefix(row_icon)

            features_group.add(row)

        outer.append(features_group)

        # --- Privacy group ---
        privacy_group = Adw.PreferencesGroup()
        privacy_group.set_title(_("Your Privacy"))
        privacy_group.set_description(
            _(
                "This application does not collect, store, or transmit "
                "personal data. All settings stay on this device. "
                "You can read the full privacy policy in the About menu."
            )
        )

        compliance_row = Adw.ActionRow()
        compliance_row.set_title(_("Compliance"))
        compliance_row.set_subtitle(
            _(
                "Follows ECA Digital (Law 15.211/2025), "
                "UK Children's Code and EU Digital Services Act"
            )
        )
        compliance_row.set_activatable(False)

        shield_icon = Gtk.Image(icon_name="channel-secure-symbolic", pixel_size=24,
                                accessible_role=Gtk.AccessibleRole.PRESENTATION)
        compliance_row.add_prefix(shield_icon)

        privacy_group.add(compliance_row)
        outer.append(privacy_group)
