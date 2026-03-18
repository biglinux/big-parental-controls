"""Entry point for big-parental-controls."""

import sys

from big_parental_controls.utils.i18n import setup_i18n

setup_i18n()

from big_parental_controls.app import ParentalControlsApp


def main() -> int:
    app = ParentalControlsApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
