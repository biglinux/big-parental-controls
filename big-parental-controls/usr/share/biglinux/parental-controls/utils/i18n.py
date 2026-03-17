"""Internationalization helpers for big-parental-controls."""

import gettext
import locale
import os

DOMAIN = "big-parental-controls"
LOCALE_DIR = "/usr/share/locale"


def setup_i18n():
    """Configure gettext for the application."""
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    locale.bindtextdomain(DOMAIN, LOCALE_DIR)
    locale.textdomain(DOMAIN)
    gettext.bindtextdomain(DOMAIN, LOCALE_DIR)
    gettext.textdomain(DOMAIN)

    translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, fallback=True)
    return translation.gettext
