#!/usr/bin/env python3
"""Entry point for big-parental-controls."""

import sys
import os

# Add our package directory to Python path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from utils.i18n import setup_i18n

_ = setup_i18n()

from app import ParentalControlsApp


def main():
    app = ParentalControlsApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
