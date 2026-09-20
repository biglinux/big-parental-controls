"""Unit tests for app filter page categorization and filtering logic."""

import unittest
from unittest.mock import MagicMock

from big_parental_controls.ui.pages.app_filter_page import (
    CATEGORY_KEYS,
    STATUS_KEYS,
    categorize_app_info,
)


class TestAppCategorization(unittest.TestCase):
    """Test XDG categorization mapping."""

    def test_games_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "Game;ActionGame;"
        self.assertEqual(categorize_app_info(mock_app), "GAMES")

    def test_internet_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "Network;WebBrowser;"
        self.assertEqual(categorize_app_info(mock_app), "INTERNET")

    def test_multimedia_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "AudioVideo;Player;Audio;"
        self.assertEqual(categorize_app_info(mock_app), "MULTIMEDIA")

    def test_office_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "Office;WordProcessor;"
        self.assertEqual(categorize_app_info(mock_app), "OFFICE")

    def test_development_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "Development;IDE;"
        self.assertEqual(categorize_app_info(mock_app), "DEVELOPMENT")

    def test_system_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "System;Settings;"
        self.assertEqual(categorize_app_info(mock_app), "SYSTEM")

    def test_utilities_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = "Utility;Calculator;"
        self.assertEqual(categorize_app_info(mock_app), "UTILITIES")

    def test_fallback_category(self):
        mock_app = MagicMock()
        mock_app.get_categories.return_value = ""
        self.assertEqual(categorize_app_info(mock_app), "OTHERS")

    def test_no_categories_method(self):
        mock_app = object()
        self.assertEqual(categorize_app_info(mock_app), "OTHERS")


class TestFilterConstants(unittest.TestCase):
    """Ensure categories and status keys are defined."""

    def test_category_keys_structure(self):
        self.assertTrue(len(CATEGORY_KEYS) >= 8)
        keys = [k for k, _ in CATEGORY_KEYS]
        self.assertIn("ALL", keys)
        self.assertIn("GAMES", keys)
        self.assertIn("INTERNET", keys)

    def test_status_keys_structure(self):
        self.assertEqual(len(STATUS_KEYS), 3)
        keys = [k for k, _ in STATUS_KEYS]
        self.assertEqual(keys, ["ALL", "ALLOWED", "BLOCKED"])


class TestWebappAndBinaryResolution(unittest.TestCase):
    """Ensure PWAs and binary wrappers are correctly detected and resolved."""

    def test_pwa_detected_via_commandline(self):
        from big_parental_controls.ui.pages.app_filter_page import is_webapp_or_pwa
        mock_pwa = MagicMock()
        mock_pwa.get_commandline.return_value = "/usr/lib/brave-browser/brave --app-id=xyz123"
        mock_pwa.get_executable.return_value = "/usr/lib/brave-browser/brave"
        mock_pwa.get_id.return_value = "brave-xyz123-Default.desktop"
        self.assertTrue(is_webapp_or_pwa(mock_pwa))

    def test_pwa_detected_via_big_webapps_exec(self):
        from big_parental_controls.ui.pages.app_filter_page import is_webapp_or_pwa
        mock_pwa = MagicMock()
        mock_pwa.get_commandline.return_value = "big-webapps-exec filename=test.desktop brave"
        mock_pwa.get_executable.return_value = "/usr/bin/big-webapps-exec"
        mock_pwa.get_id.return_value = "brave-whatsapp.desktop"
        self.assertTrue(is_webapp_or_pwa(mock_pwa))

    def test_browser_not_classified_as_pwa(self):
        from big_parental_controls.ui.pages.app_filter_page import is_webapp_or_pwa
        mock_browser = MagicMock()
        mock_browser.get_commandline.return_value = "brave %U"
        mock_browser.get_executable.return_value = "brave"
        mock_browser.get_id.return_value = "brave-browser.desktop"
        self.assertFalse(is_webapp_or_pwa(mock_browser))

    def test_binary_chain_resolution(self):
        from big_parental_controls.ui.pages.app_filter_page import (
            PROTECTED_BINARIES,
            resolve_all_related_binaries,
        )
        chain = resolve_all_related_binaries("/usr/local/bin/brave")
        self.assertIn("/usr/bin/brave", chain)
        self.assertIn("/usr/lib/brave-browser/brave", chain)
        for protected in PROTECTED_BINARIES:
            self.assertNotIn(protected, chain)

    def test_protected_binaries_defense(self):
        from big_parental_controls.ui.pages.app_filter_page import is_protected_binary
        self.assertTrue(is_protected_binary("/usr/bin/env"))
        self.assertTrue(is_protected_binary("/usr/sbin/env"))
        self.assertTrue(is_protected_binary("/bin/bash"))
        self.assertTrue(is_protected_binary("/usr/bin/pkexec"))
        self.assertTrue(is_protected_binary("/usr/bin/sudo"))
        self.assertTrue(is_protected_binary("/usr/bin/xdg-open"))
        self.assertTrue(is_protected_binary("/usr/sbin/xdg-open"))
        self.assertFalse(is_protected_binary("/usr/bin/brave"))
        self.assertFalse(is_protected_binary("/usr/bin/vlc"))

    def test_extract_real_executable_from_env_wrapper(self):
        from big_parental_controls.ui.pages.app_filter_page import extract_real_executable
        mock_app = MagicMock()
        mock_app.get_commandline.return_value = "env TMPDIR=/tmp/test /opt/VSCode/code --launch %F"
        mock_app.get_executable.return_value = "env"
        self.assertEqual(extract_real_executable(mock_app), "/opt/VSCode/code")

    def test_extract_real_executable_from_pkexec_wrapper(self):
        from big_parental_controls.ui.pages.app_filter_page import extract_real_executable
        mock_app = MagicMock()
        mock_app.get_commandline.return_value = "pkexec /usr/local/bin/biglinux-snapshot-restore"
        mock_app.get_executable.return_value = "pkexec"
        self.assertEqual(extract_real_executable(mock_app), "/usr/local/bin/biglinux-snapshot-restore")

    def test_xdg_open_shortcut_classified_as_webapp_or_pwa(self):
        from big_parental_controls.ui.pages.app_filter_page import is_webapp_or_pwa
        mock_app = MagicMock()
        mock_app.get_commandline.return_value = "xdg-open http://localhost:631/"
        mock_app.get_executable.return_value = "xdg-open"
        mock_app.get_id.return_value = "bigcontrolcenter-cups.desktop"
        self.assertTrue(is_webapp_or_pwa(mock_app))


if __name__ == "__main__":
    unittest.main()
