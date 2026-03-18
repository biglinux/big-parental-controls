"""Internationalization helpers for big-parental-controls."""

import gettext
import locale
from typing import Callable

from big_parental_controls.core.constants import GETTEXT_DOMAIN, LOCALE_DIR

_gettext_func: Callable[[str], str] | None = None


def setup_i18n() -> Callable[[str], str]:
    """Configure gettext once and return the cached translation function.

    Safe to call multiple times — locale setup runs only on first call.
    """
    global _gettext_func
    if _gettext_func is not None:
        return _gettext_func

    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass

    locale.bindtextdomain(GETTEXT_DOMAIN, LOCALE_DIR)
    locale.textdomain(GETTEXT_DOMAIN)
    gettext.bindtextdomain(GETTEXT_DOMAIN, LOCALE_DIR)
    gettext.textdomain(GETTEXT_DOMAIN)

    translation = gettext.translation(GETTEXT_DOMAIN, localedir=LOCALE_DIR, fallback=True)
    _gettext_func = translation.gettext
    return _gettext_func
