"""Integration-style tests that verify the desktop entry and package structure."""

import os
import unittest

# Base directory of the package
PKG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "big-parental-controls",
)


class TestDesktopEntry(unittest.TestCase):
    """Validate the .desktop file."""

    def setUp(self):
        self.desktop_file = os.path.join(
            PKG_DIR, "usr", "share", "applications", "big-parental-controls.desktop"
        )

    def test_desktop_file_exists(self):
        self.assertTrue(os.path.isfile(self.desktop_file))

    def test_desktop_file_has_required_keys(self):
        with open(self.desktop_file) as f:
            content = f.read()

        required_keys = [
            "Type=Application",
            "Name=",
            "Comment=",
            "Exec=big-parental-controls",
            "Icon=big-parental-controls",
            "Categories=",
            "Terminal=false",
        ]
        for key in required_keys:
            self.assertIn(key, content, f"Missing key: {key}")

    def test_desktop_file_has_pt_br_translation(self):
        with open(self.desktop_file) as f:
            content = f.read()

        self.assertIn("Name[pt_BR]=", content)
        self.assertIn("Comment[pt_BR]=", content)

    def test_desktop_file_has_settings_category(self):
        with open(self.desktop_file) as f:
            content = f.read()

        self.assertIn("Settings", content)


class TestPackageStructure(unittest.TestCase):
    """Validate the package directory structure."""

    def test_launcher_exists(self):
        path = os.path.join(PKG_DIR, "usr", "bin", "big-parental-controls")
        self.assertTrue(os.path.isfile(path))

    def test_main_py_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "main.py"
        )
        self.assertTrue(os.path.isfile(path))

    def test_app_py_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "app.py"
        )
        self.assertTrue(os.path.isfile(path))

    def test_window_py_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "window.py"
        )
        self.assertTrue(os.path.isfile(path))

    def test_window_ui_template_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "window.ui"
        )
        self.assertTrue(os.path.isfile(path))

    def test_window_ui_valid_xml(self):
        import xml.etree.ElementTree as ET
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "window.ui"
        )
        tree = ET.parse(path)
        root = tree.getroot()
        self.assertEqual(root.tag, "interface")
        # Must have a template element
        template = root.find("template")
        self.assertIsNotNone(template, "Missing <template> element in window.ui")
        self.assertEqual(template.get("class"), "MainWindow")

    def test_window_ui_has_required_ids(self):
        import xml.etree.ElementTree as ET
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "window.ui"
        )
        tree = ET.parse(path)
        root = tree.getroot()
        all_ids = {obj.get("id") for obj in root.iter("object") if obj.get("id")}
        required_ids = {
            "toast_overlay", "split_view", "sidebar_list",
            "content_page", "content_header", "content_stack",
        }
        missing = required_ids - all_ids
        self.assertFalse(missing, f"Missing widget IDs in window.ui: {missing}")

    def test_style_css_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "style.css"
        )
        self.assertTrue(os.path.isfile(path))

    def test_icon_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "icons", "hicolor", "scalable", "apps",
            "big-parental-controls.svg",
        )
        self.assertTrue(os.path.isfile(path))

    def test_polkit_rules_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "polkit-1", "rules.d",
            "50-big-parental-controls.rules",
        )
        self.assertTrue(os.path.isfile(path))

    def test_dbus_service_file_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "dbus-1", "services",
            "br.com.biglinux.AgeSignal.service",
        )
        self.assertTrue(os.path.isfile(path))

    def test_dbus_interface_xml_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "share", "dbus-1", "interfaces",
            "br.com.biglinux.AgeSignal.xml",
        )
        self.assertTrue(os.path.isfile(path))

    def test_systemd_user_service_exists(self):
        path = os.path.join(
            PKG_DIR, "usr", "lib", "systemd", "user", "big-age-signal.service"
        )
        self.assertTrue(os.path.isfile(path))

    def test_all_pages_exist(self):
        pages_dir = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "pages"
        )
        expected_pages = [
            "__init__.py",
            "users_page.py",
            "app_filter_page.py",
            "time_limits_page.py",
            "dns_page.py",
            "support_page.py",
        ]
        for page in expected_pages:
            path = os.path.join(pages_dir, page)
            self.assertTrue(os.path.isfile(path), f"Missing page: {page}")

    def test_all_services_exist(self):
        services_dir = os.path.join(
            PKG_DIR, "usr", "share", "biglinux", "parental-controls", "services"
        )
        expected_services = [
            "__init__.py",
            "malcontent_service.py",
            "accounts_service.py",
            "polkit_service.py",
            "dns_service.py",
        ]
        for svc in expected_services:
            path = os.path.join(services_dir, svc)
            self.assertTrue(os.path.isfile(path), f"Missing service: {svc}")

    def test_rust_age_signal_source_exists(self):
        age_signal_dir = os.path.join(
            PKG_DIR, "..", "big-age-signal"
        )
        self.assertTrue(
            os.path.isdir(age_signal_dir),
            "Missing big-age-signal Rust source directory",
        )
        cargo_toml = os.path.join(age_signal_dir, "Cargo.toml")
        self.assertTrue(
            os.path.isfile(cargo_toml),
            "Missing big-age-signal/Cargo.toml",
        )


class TestPkgbuild(unittest.TestCase):
    """Validate PKGBUILD structure."""

    def setUp(self):
        self.pkgbuild = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "pkgbuild",
            "PKGBUILD",
        )

    def test_pkgbuild_exists(self):
        self.assertTrue(os.path.isfile(self.pkgbuild))

    def test_pkgbuild_has_pkgname(self):
        with open(self.pkgbuild) as f:
            content = f.read()
        self.assertIn("pkgname=big-parental-controls", content)

    def test_pkgbuild_has_required_depends(self):
        with open(self.pkgbuild) as f:
            content = f.read()
        required_deps = [
            "python",
            "python-gobject",
            "gtk4",
            "libadwaita",
            "malcontent",
            "accountsservice",
            "polkit",
        ]
        for dep in required_deps:
            self.assertIn(dep, content, f"Missing dependency: {dep}")

    def test_install_file_exists(self):
        install_file = os.path.join(
            os.path.dirname(self.pkgbuild), "big-parental-controls.install"
        )
        self.assertTrue(os.path.isfile(install_file))

    def test_install_file_creates_group(self):
        install_file = os.path.join(
            os.path.dirname(self.pkgbuild), "big-parental-controls.install"
        )
        with open(install_file) as f:
            content = f.read()
        self.assertIn("supervised", content)
        self.assertIn("groupadd", content)


class TestDBusServiceFile(unittest.TestCase):
    """Validate D-Bus service file format."""

    def setUp(self):
        self.service_file = os.path.join(
            PKG_DIR, "usr", "share", "dbus-1", "services",
            "br.com.biglinux.AgeSignal.service",
        )

    def test_has_dbus_service_section(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("[D-BUS Service]", content)

    def test_has_bus_name(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("Name=br.com.biglinux.AgeSignal", content)

    def test_has_exec(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("Exec=", content)


class TestSystemdService(unittest.TestCase):
    """Validate systemd user service file."""

    def setUp(self):
        self.service_file = os.path.join(
            PKG_DIR, "usr", "lib", "systemd", "user", "big-age-signal.service"
        )

    def test_has_unit_section(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)

    def test_is_dbus_type(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("Type=dbus", content)

    def test_has_matching_bus_name(self):
        with open(self.service_file) as f:
            content = f.read()
        self.assertIn("BusName=br.com.biglinux.AgeSignal", content)


if __name__ == "__main__":
    unittest.main()
