"""Tests for login name derivation and the helper's username checks (issue #2)."""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from big_parental_controls.utils.username import LOGIN_RE, to_login  # noqa: E402

HELPER = REPO_ROOT / "big-parental-controls" / "usr" / "lib" / "big-parental-controls" / "group-helper"
TEST_LOCALE = "fr_FR.UTF-8"


def _locale_installed(name: str) -> bool:
    """An unknown LC_ALL silently falls back to C, so check it exists."""
    try:
        out = subprocess.run(["locale", "-a"], capture_output=True, text=True, check=False).stdout
    except OSError:
        return False
    wanted = name.lower().replace("-", "")
    return any(line.strip().lower().replace("-", "") == wanted for line in out.splitlines())


class TestToLogin(unittest.TestCase):
    def test_accents_removed(self):
        self.assertEqual(to_login("Jéçica"), "jecica")
        self.assertEqual(to_login("Ève-Lyne!"), "eve-lyne")
        self.assertEqual(to_login("Zoé_2"), "zoe_2")

    def test_spaces_become_dash(self):
        self.assertEqual(to_login("  Anne   Marie "), "anne-marie")

    def test_already_valid_is_kept(self):
        self.assertEqual(to_login("lana"), "lana")
        self.assertEqual(to_login("mini_bruno"), "mini_bruno")

    def test_leading_digits_and_dashes_dropped(self):
        self.assertEqual(to_login("2Léa"), "lea")
        self.assertEqual(to_login("-x"), "x")

    def test_nothing_usable(self):
        self.assertEqual(to_login("123"), "")
        self.assertEqual(to_login("日本"), "")
        self.assertEqual(to_login(""), "")

    def test_max_length(self):
        self.assertEqual(len(to_login("a" * 50)), 32)

    def test_result_always_valid(self):
        for s in ("Jéçica", "Anne Marie", "Ève-Lyne!", "Œdipe", "user.name", "a/b"):
            login = to_login(s)
            self.assertTrue(login == "" or LOGIN_RE.match(login), (s, login))


@unittest.skipUnless(
    sys.platform.startswith("linux") and shutil.which("bash") and HELPER.exists(),
    "needs Linux bash",
)
@unittest.skipUnless(
    _locale_installed(TEST_LOCALE),
    f"{TEST_LOCALE} not installed: the locale regression would not be exercised",
)
class TestHelperValidation(unittest.TestCase):
    """The helper must reject non-ASCII names whatever the locale."""

    def _check(self, func: str, name: str) -> bool:
        script = (
            f"eval \"$(tr -d '\r' < \"$1\" | sed -n '/^{func}()/,/^}}/p')\"; ( {func} \"$2\" ) 2>/dev/null"
        )
        env = dict(os.environ, LC_ALL=TEST_LOCALE)
        res = subprocess.run(["bash", "-c", script, "bash", str(HELPER), name], env=env)
        return res.returncode == 0

    def test_new_username(self):
        self.assertTrue(self._check("validate_new_username", "jecica"))
        self.assertTrue(self._check("validate_new_username", "anne-marie"))
        self.assertFalse(self._check("validate_new_username", "jéçica"))
        self.assertFalse(self._check("validate_new_username", "Jecica"))
        self.assertFalse(self._check("validate_new_username", "1abc"))

    def test_existing_username(self):
        self.assertTrue(self._check("validate_username", "Bruno"))
        self.assertFalse(self._check("validate_username", "jéçica"))


if __name__ == "__main__":
    unittest.main()
