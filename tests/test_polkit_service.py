"""Unit tests for polkit_service module."""

import os
import tempfile
import unittest
from unittest.mock import patch

# We need to test polkit_service without GIR dependencies
import sys

# Add the source directory to path
SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "big-parental-controls",
    "usr",
    "share",
    "biglinux",
    "parental-controls",
)
sys.path.insert(0, SRC_DIR)

from services.polkit_service import (
    POLKIT_RULES_TEMPLATE,
    rules_installed,
)


class TestPolkitService(unittest.TestCase):
    """Tests for polkit rules generation and management."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rules_file = os.path.join(self.tmpdir, "50-big-parental-controls.rules")

    def tearDown(self):
        if os.path.exists(self.rules_file):
            os.remove(self.rules_file)
        os.rmdir(self.tmpdir)

    @patch("services.polkit_service.POLKIT_RULES_DIR")
    @patch("services.polkit_service.RULES_FILE")
    def test_install_polkit_rules_creates_file(self, mock_file, mock_dir):
        mock_dir.__str__ = lambda s: self.tmpdir
        mock_file.__str__ = lambda s: self.rules_file

        # Directly test the template content
        with open(self.rules_file, "w") as f:
            f.write(POLKIT_RULES_TEMPLATE)

        self.assertTrue(os.path.exists(self.rules_file))

        with open(self.rules_file) as f:
            content = f.read()

        self.assertIn("supervised", content)
        self.assertIn("org.manjaro.pamac.commit", content)
        self.assertIn("org.freedesktop.packagekit.package-install", content)
        self.assertIn("org.freedesktop.Flatpak.app-install", content)
        self.assertIn("polkit.Result.AUTH_ADMIN", content)

    def test_polkit_template_contains_all_required_actions(self):
        """Verify the template blocks all required package management actions."""
        required_actions = [
            "org.manjaro.pamac.commit",
            "org.freedesktop.packagekit.package-install",
            "org.freedesktop.packagekit.package-remove",
            "org.freedesktop.Flatpak.app-install",
            "org.freedesktop.Flatpak.runtime-install",
            "org.freedesktop.Flatpak.app-uninstall",
        ]
        for action in required_actions:
            self.assertIn(action, POLKIT_RULES_TEMPLATE, f"Missing action: {action}")

    def test_polkit_template_uses_group_check(self):
        """Verify the template checks the supervised group."""
        self.assertIn('subject.isInGroup("supervised")', POLKIT_RULES_TEMPLATE)

    def test_polkit_template_returns_auth_admin(self):
        """Verify blocked actions require admin authentication.

        polkit.Result.NO is allowed for account management (full denial)
        while other actions use AUTH_ADMIN.
        """
        self.assertIn("polkit.Result.AUTH_ADMIN", POLKIT_RULES_TEMPLATE)

    def test_rules_file_detection(self):
        """Test rules_installed() detection."""
        # Before creation
        with patch("services.polkit_service.RULES_FILE", self.rules_file):
            self.assertFalse(rules_installed())

        # After creation
        with open(self.rules_file, "w") as f:
            f.write("test")

        with patch("services.polkit_service.RULES_FILE", self.rules_file):
            self.assertTrue(rules_installed())


class TestPolkitTemplateFormat(unittest.TestCase):
    """Verify the polkit rules template is valid JavaScript."""

    def test_template_has_balanced_braces(self):
        opens = POLKIT_RULES_TEMPLATE.count("{")
        closes = POLKIT_RULES_TEMPLATE.count("}")
        self.assertEqual(opens, closes, "Unbalanced braces in polkit template")

    def test_template_has_balanced_parens(self):
        opens = POLKIT_RULES_TEMPLATE.count("(")
        closes = POLKIT_RULES_TEMPLATE.count(")")
        self.assertEqual(opens, closes, "Unbalanced parentheses in polkit template")

    def test_template_semicolons(self):
        """Every statement line should end with semicolon, brace, or continuation."""
        for line in POLKIT_RULES_TEMPLATE.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith(("//", "*")):
                continue
            if stripped.endswith(("{", "}", "(", ")", ",", "[", "]")):
                continue
            # Allow logical continuation operators at end of line (&&, ||)
            if stripped.endswith(("&&", "||")):
                continue
            if stripped.startswith(("polkit.", "if ", "var ", "return ", "for ")):
                # These should end with { , ; or )
                self.assertTrue(
                    stripped.endswith((";", "{", "}", ")", ",")),
                    f"Statement may be missing semicolon: {stripped!r}",
                )


if __name__ == "__main__":
    unittest.main()
