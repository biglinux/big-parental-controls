"""Unit tests for i18n utilities."""

import os
import sys
from pathlib import Path
import unittest

REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = REPO_ROOT / "big-parental-controls" / "usr" / "share" / "biglinux" / "parental-controls"
ROOT_LOCALE_DIR = REPO_ROOT / "locale"
MIRROR_LOCALE_DIR = SRC_DIR / "locale"
COMPILED_LOCALE_DIR = REPO_ROOT / "big-parental-controls" / "usr" / "share" / "locale"
sys.path.insert(0, str(SRC_DIR))

from utils.i18n import DOMAIN, LOCALE_DIR, setup_i18n


class TestI18n(unittest.TestCase):
    """Test i18n configuration."""

    def test_domain_is_correct(self):
        self.assertEqual(DOMAIN, "big-parental-controls")

    def test_locale_dir_is_standard(self):
        self.assertEqual(LOCALE_DIR, "/usr/share/locale")

    def test_setup_returns_callable(self):
        _ = setup_i18n()
        self.assertTrue(callable(_))

    def test_fallback_returns_original_string(self):
        """When no .mo files exist, gettext should return the original string."""
        _ = setup_i18n()
        # This string won't have a translation, so it should return as-is
        result = _("Test string that has no translation")
        self.assertEqual(result, "Test string that has no translation")

    def test_empty_string(self):
        _ = setup_i18n()
        result = _("")
        self.assertEqual(result, "")

    def test_locale_source_files_are_in_sync(self):
        root_po_files = sorted(ROOT_LOCALE_DIR.glob("*.po"))
        self.assertGreater(len(root_po_files), 0)

        root_pot = (ROOT_LOCALE_DIR / f"{DOMAIN}.pot").read_text(encoding="utf-8")
        mirror_pot = (MIRROR_LOCALE_DIR / f"{DOMAIN}.pot").read_text(encoding="utf-8")
        self.assertEqual(root_pot, mirror_pot)

        for root_po in root_po_files:
            mirror_po = MIRROR_LOCALE_DIR / root_po.name
            self.assertTrue(mirror_po.is_file(), f"Missing mirrored locale file: {mirror_po}")
            self.assertEqual(
                root_po.read_text(encoding="utf-8"),
                mirror_po.read_text(encoding="utf-8"),
                f"Out-of-sync locale file: {root_po.name}",
            )

    def test_compiled_locales_match_source_po_files(self):
        source_langs = {po.stem for po in ROOT_LOCALE_DIR.glob("*.po")}
        compiled_lang_dirs = {lang_dir.name for lang_dir in COMPILED_LOCALE_DIR.iterdir() if lang_dir.is_dir()}
        compiled_langs = {
            lang_dir.name
            for lang_dir in COMPILED_LOCALE_DIR.iterdir()
            if (lang_dir / "LC_MESSAGES" / f"{DOMAIN}.mo").is_file()
        }
        self.assertEqual(source_langs, compiled_lang_dirs)
        self.assertEqual(source_langs, compiled_langs)

    def test_no_stray_root_level_mo_file(self):
        self.assertFalse((REPO_ROOT / "messages.mo").exists())


if __name__ == "__main__":
    unittest.main()
