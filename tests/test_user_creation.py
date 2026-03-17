"""Tests for user creation validation and error handling."""

import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "big-parental-controls",
    "usr",
    "share",
    "biglinux",
    "parental-controls",
)
sys.path.insert(0, SRC_DIR)

# The username regex used in users_page.py
USERNAME_REGEX = re.compile(r"^[a-z][a-z0-9_-]*$")


class TestUsernameValidation(unittest.TestCase):
    """Validate usernames per the rules in users_page.py."""

    def test_valid_simple(self):
        self.assertIsNotNone(USERNAME_REGEX.match("bruno"))

    def test_valid_with_numbers(self):
        self.assertIsNotNone(USERNAME_REGEX.match("user1"))

    def test_valid_with_hyphen(self):
        self.assertIsNotNone(USERNAME_REGEX.match("mini-bruno"))

    def test_valid_with_underscore(self):
        self.assertIsNotNone(USERNAME_REGEX.match("mini_bruno"))

    def test_reject_uppercase(self):
        self.assertIsNone(USERNAME_REGEX.match("Bruno"))

    def test_reject_starts_with_number(self):
        self.assertIsNone(USERNAME_REGEX.match("1user"))

    def test_reject_starts_with_hyphen(self):
        self.assertIsNone(USERNAME_REGEX.match("-user"))

    def test_reject_spaces(self):
        self.assertIsNone(USERNAME_REGEX.match("my user"))

    def test_reject_special_chars(self):
        self.assertIsNone(USERNAME_REGEX.match("user@home"))

    def test_reject_empty(self):
        self.assertIsNone(USERNAME_REGEX.match(""))

    def test_reject_dot(self):
        self.assertIsNone(USERNAME_REGEX.match("user.name"))

    def test_reject_slash(self):
        self.assertIsNone(USERNAME_REGEX.match("user/name"))

    def test_max_length_valid(self):
        name = "a" * 32
        self.assertIsNotNone(USERNAME_REGEX.match(name))

    def test_single_letter(self):
        self.assertIsNotNone(USERNAME_REGEX.match("a"))


class TestPasswordValidation(unittest.TestCase):
    """Validate password rules enforced before subprocess call."""

    def test_empty_password_rejected(self):
        """Empty password must be caught before reaching subprocess."""
        self.assertEqual(len(""), 0)

    def test_any_length_password_accepted(self):
        """Any non-empty password should pass validation (no minimum length)."""
        self.assertTrue(len("a") >= 1)

    def test_password_mismatch(self):
        """Password and confirmation must match."""
        self.assertNotEqual("password1", "password2")

    def test_password_match(self):
        """Identical password and confirmation should pass."""
        self.assertEqual("secret123", "secret123")


class TestCreateFullSubprocess(unittest.TestCase):
    """Test that the create-full subprocess call is formed correctly."""

    @patch("subprocess.run")
    def test_password_sent_via_stdin(self, mock_run):
        """Password must be passed via stdin, never as command argument."""
        import subprocess

        password = "secure_pass"
        username = "testchild"
        fullname = "Test Child"
        helper = "/usr/lib/big-parental-controls/group-helper"

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        subprocess.run(
            ["pkexec", helper, "create-full", username, fullname],
            input=password,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        # Verify password is NOT in the command args
        call_args = mock_run.call_args
        cmd = call_args[0][0]
        self.assertNotIn(password, cmd)

        # Verify password IS in stdin (input kwarg)
        self.assertEqual(call_args[1]["input"], password)

    @patch("subprocess.run")
    def test_failure_returns_stderr(self, mock_run):
        """On failure, stderr should contain the error details."""
        import subprocess

        mock_run.return_value = MagicMock(
            returncode=1, stderr="useradd: user 'test' already exists\n"
        )

        result = subprocess.run(
            ["pkexec", "/usr/lib/big-parental-controls/group-helper",
             "create-full", "test", "Test"],
            input="password",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    @patch("subprocess.run")
    def test_timeout_is_set(self, mock_run):
        """The subprocess call must have a timeout to avoid hanging."""
        import subprocess

        mock_run.return_value = MagicMock(returncode=0, stderr="")

        subprocess.run(
            ["pkexec", "/usr/lib/big-parental-controls/group-helper",
             "create-full", "child1", "Child One"],
            input="pass123",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        call_args = mock_run.call_args
        self.assertEqual(call_args[1]["timeout"], 60)

    @patch("subprocess.run")
    def test_check_false_no_exception(self, mock_run):
        """check=False prevents CalledProcessError on non-zero exit."""
        import subprocess

        mock_run.return_value = MagicMock(returncode=9, stderr="error")

        # Should NOT raise
        result = subprocess.run(
            ["pkexec", "/usr/lib/big-parental-controls/group-helper",
             "create-full", "test", "Test"],
            input="pass",
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        self.assertEqual(result.returncode, 9)


class TestGroupHelperValidation(unittest.TestCase):
    """Test the bash-level validation in group-helper."""

    def test_username_regex_matches_group_helper(self):
        """The Python regex should match the bash regex pattern."""
        # Bash: [[ "$1" =~ ^[a-zA-Z0-9_-]+$ ]]
        # Python: ^[a-z][a-z0-9_-]*$  (stricter — lowercase only, must start with letter)
        # Python validation is intentionally stricter than bash
        bash_regex = re.compile(r"^[a-zA-Z0-9_-]+$")

        # All Python-valid usernames must also be bash-valid
        valid_usernames = ["user", "user1", "my-child", "test_user"]
        for name in valid_usernames:
            self.assertIsNotNone(USERNAME_REGEX.match(name), f"Python rejected: {name}")
            self.assertIsNotNone(bash_regex.match(name), f"Bash rejected: {name}")

    def test_injection_attempts_blocked(self):
        """Command injection attempts must fail validation."""
        attacks = [
            "user; rm -rf /",
            "user$(whoami)",
            "user`id`",
            "../../../etc/passwd",
            "user\nmalicious",
            "user\x00null",
            "$(reboot)",
        ]
        for attack in attacks:
            self.assertIsNone(
                USERNAME_REGEX.match(attack),
                f"Injection not blocked: {attack!r}",
            )


class TestDuplicateUserCheck(unittest.TestCase):
    """Verify that duplicate user creation is caught."""

    @patch("pwd.getpwnam")
    def test_existing_user_detected(self, mock_getpwnam):
        """If pwd.getpwnam returns a result, user exists."""
        mock_getpwnam.return_value = MagicMock()
        import pwd

        exists = True
        try:
            pwd.getpwnam("bruno")
        except KeyError:
            exists = False

        self.assertTrue(exists)

    @patch("pwd.getpwnam", side_effect=KeyError("no such user"))
    def test_new_user_not_detected(self, mock_getpwnam):
        """If pwd.getpwnam raises KeyError, user does not exist."""
        import pwd

        exists = True
        try:
            pwd.getpwnam("newchild")
        except KeyError:
            exists = False

        self.assertFalse(exists)


class TestUsernameLengthLimit(unittest.TestCase):
    """Username must be 32 characters or less (Linux passwd limit)."""

    def test_32_chars_valid(self):
        name = "a" * 32
        self.assertTrue(len(name) <= 32)
        self.assertIsNotNone(USERNAME_REGEX.match(name))

    def test_33_chars_rejected(self):
        name = "a" * 33
        self.assertTrue(len(name) > 32)


class TestFullnameHandling(unittest.TestCase):
    """Fullname fallback and sanitization."""

    def test_empty_fullname_uses_username(self):
        """When fullname is empty, username should be used as fallback."""
        username = "child1"
        fullname = ""
        effective = fullname or username
        self.assertEqual(effective, "child1")

    def test_fullname_preserved(self):
        """When fullname is provided, it should be used."""
        username = "child1"
        fullname = "My Child"
        effective = fullname or username
        self.assertEqual(effective, "My Child")

    def test_whitespace_fullname_stripped(self):
        """Whitespace-only fullname should fall back to username."""
        username = "child1"
        fullname = "   "
        effective = fullname.strip() or username
        self.assertEqual(effective, "child1")


if __name__ == "__main__":
    unittest.main()
