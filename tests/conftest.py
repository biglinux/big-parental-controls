"""Shared test setup."""

import locale

# The C gettext bindings (locale.bindtextdomain/textdomain) only exist on
# Linux; utils.i18n calls them at import. Let the tests run elsewhere too.
for _name in ("bindtextdomain", "textdomain"):
    if not hasattr(locale, _name):
        setattr(locale, _name, lambda *_args: None)
