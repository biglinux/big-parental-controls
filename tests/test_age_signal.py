"""Unit tests for the D-Bus age_signal module."""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "big-parental-controls",
    "usr",
    "share",
    "biglinux",
    "parental-controls",
)
sys.path.insert(0, SRC_DIR)

from dbus.age_signal import (
    _is_supervised,
    _get_age_range,
    BUS_NAME,
    OBJECT_PATH,
    INTERFACE_NAME,
    INTROSPECTION_XML,
)


class TestIsSupervisedFunction(unittest.TestCase):
    """Test the _is_supervised helper."""

    @patch("grp.getgrnam")
    @patch.dict(os.environ, {"USER": "testchild"})
    def test_supervised_user_returns_true(self, mock_getgrnam):
        mock_group = MagicMock()
        mock_group.gr_mem = ["testchild", "anotheruser"]
        mock_getgrnam.return_value = mock_group
        self.assertTrue(_is_supervised())

    @patch("grp.getgrnam")
    @patch.dict(os.environ, {"USER": "admin"})
    def test_non_supervised_user_returns_false(self, mock_getgrnam):
        mock_group = MagicMock()
        mock_group.gr_mem = ["testchild"]
        mock_getgrnam.return_value = mock_group
        self.assertFalse(_is_supervised())

    @patch("grp.getgrnam")
    def test_no_group_returns_false(self, mock_getgrnam):
        mock_getgrnam.side_effect = KeyError("group not found")
        self.assertFalse(_is_supervised())


class TestGetAgeRange(unittest.TestCase):
    """Test the _get_age_range function."""

    @patch("dbus.age_signal._is_supervised", return_value=True)
    def test_supervised_returns_child(self, mock_sup):
        self.assertEqual(_get_age_range(), "child")

    @patch("dbus.age_signal._is_supervised", return_value=False)
    def test_non_supervised_returns_adult(self, mock_sup):
        self.assertEqual(_get_age_range(), "adult")


class TestDBusConstants(unittest.TestCase):
    """Test D-Bus service constants."""

    def test_bus_name_format(self):
        self.assertTrue(BUS_NAME.startswith("br.com.biglinux."))
        # D-Bus names must have at least 2 elements separated by dots
        parts = BUS_NAME.split(".")
        self.assertGreaterEqual(len(parts), 3)

    def test_object_path_format(self):
        self.assertTrue(OBJECT_PATH.startswith("/"))
        # Object paths use / as separator
        self.assertNotIn(".", OBJECT_PATH)

    def test_interface_name_matches_bus(self):
        # Interface should be related to bus name
        self.assertTrue(INTERFACE_NAME.startswith("br.com.biglinux."))

    def test_introspection_xml_is_valid(self):
        self.assertIn("<interface", INTROSPECTION_XML)
        self.assertIn("GetAgeRange", INTROSPECTION_XML)
        self.assertIn("IsMinor", INTROSPECTION_XML)
        self.assertIn("Version", INTROSPECTION_XML)

    def test_introspection_xml_arg_types(self):
        # GetAgeRange returns string
        self.assertIn('type="s"', INTROSPECTION_XML)
        # IsMinor returns boolean
        self.assertIn('type="b"', INTROSPECTION_XML)


class TestAgeSignalService(unittest.TestCase):
    """Test AgeSignalService method handling (without running D-Bus)."""

    def setUp(self):
        # We need GIR mocked for this
        self.gi_available = True
        try:
            import gi
            gi.require_version("Gio", "2.0")
        except (ImportError, ValueError):
            self.gi_available = False

    @unittest.skipUnless(
        os.environ.get("TEST_WITH_GIR"),
        "GIR tests require TEST_WITH_GIR=1 and a running D-Bus session"
    )
    def test_service_instantiation(self):
        from dbus.age_signal import AgeSignalService
        service = AgeSignalService()
        self.assertIsNotNone(service)


if __name__ == "__main__":
    unittest.main()
