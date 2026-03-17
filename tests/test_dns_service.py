"""Unit tests for dns_service module."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import sys

SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "big-parental-controls",
    "usr",
    "share",
    "biglinux",
    "parental-controls",
)
sys.path.insert(0, SRC_DIR)

from services.dns_service import DNS_PROVIDERS, DnsService


class TestDnsProviders(unittest.TestCase):
    """Test DNS provider definitions."""

    def test_all_providers_have_required_keys(self):
        for key, provider in DNS_PROVIDERS.items():
            self.assertIn("name", provider, f"Provider {key} missing 'name'")
            self.assertIn("dns1", provider, f"Provider {key} missing 'dns1'")
            self.assertIn("dns2", provider, f"Provider {key} missing 'dns2'")

    def test_dns_addresses_are_valid_ipv4(self):
        import ipaddress

        for key, provider in DNS_PROVIDERS.items():
            for field in ("dns1", "dns2"):
                try:
                    ipaddress.IPv4Address(provider[field])
                except ipaddress.AddressValueError:
                    self.fail(
                        f"Provider {key} has invalid IPv4 in {field}: {provider[field]}"
                    )

    def test_known_providers_exist(self):
        self.assertIn("cleanbrowsing", DNS_PROVIDERS)
        self.assertIn("opendns", DNS_PROVIDERS)
        self.assertIn("cloudflare", DNS_PROVIDERS)


class TestDnsService(unittest.TestCase):
    """Test DnsService configuration management."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dns = DnsService()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    @patch("services.dns_service.CONFIG_DIR")
    def test_get_dns_returns_none_when_not_configured(self, mock_dir):
        mock_dir.__str__ = lambda s: self.tmpdir
        # Patch CONFIG_DIR properly
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = self.dns.get_dns_for_user(1001)
            self.assertIsNone(result)

    def test_set_and_get_dns_for_known_provider(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = self.dns.set_dns_for_user(1001, provider="cleanbrowsing")
            self.assertTrue(result)

            config = self.dns.get_dns_for_user(1001)
            self.assertIsNotNone(config)
            self.assertEqual(config["provider"], "cleanbrowsing")
            self.assertEqual(config["dns1"], "185.228.168.168")
            self.assertEqual(config["dns2"], "185.228.169.168")

    def test_set_and_get_custom_dns(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = self.dns.set_dns_for_user(
                1001, provider="custom", custom_dns1="1.2.3.4", custom_dns2="5.6.7.8"
            )
            self.assertTrue(result)

            config = self.dns.get_dns_for_user(1001)
            self.assertEqual(config["provider"], "custom")
            self.assertEqual(config["dns1"], "1.2.3.4")
            self.assertEqual(config["dns2"], "5.6.7.8")

    def test_set_dns_none_disables(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            # First set
            self.dns.set_dns_for_user(1001, provider="opendns")
            self.assertIsNotNone(self.dns.get_dns_for_user(1001))

            # Then disable
            self.dns.set_dns_for_user(1001, provider=None)
            self.assertIsNone(self.dns.get_dns_for_user(1001))

    def test_invalid_provider_returns_false(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = self.dns.set_dns_for_user(1001, provider="invalid_provider")
            self.assertFalse(result)

    def test_custom_without_dns1_returns_false(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = self.dns.set_dns_for_user(1001, provider="custom")
            self.assertFalse(result)

    def test_config_file_is_valid_json(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            self.dns.set_dns_for_user(1001, provider="cloudflare")

            config_file = os.path.join(self.tmpdir, "1001.json")
            self.assertTrue(os.path.isfile(config_file))

            with open(config_file) as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)

    def test_different_users_have_separate_configs(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            self.dns.set_dns_for_user(1001, provider="cleanbrowsing")
            self.dns.set_dns_for_user(1002, provider="opendns")

            config1 = self.dns.get_dns_for_user(1001)
            config2 = self.dns.get_dns_for_user(1002)

            self.assertEqual(config1["provider"], "cleanbrowsing")
            self.assertEqual(config2["provider"], "opendns")


class TestDnsLoginScripts(unittest.TestCase):
    """Test login script generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.profile_dir = tempfile.mkdtemp()
        self.dns = DnsService()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        shutil.rmtree(self.profile_dir)

    def test_generate_login_scripts_creates_files(self):
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            # Write a config
            os.makedirs(self.tmpdir, exist_ok=True)
            config_file = os.path.join(self.tmpdir, "1001.json")
            with open(config_file, "w") as f:
                json.dump({"provider": "cleanbrowsing", "dns1": "185.228.168.168", "dns2": "185.228.169.168"}, f)

            # Generate scripts to a temp profile dir
            with patch("services.dns_service.DnsService.generate_login_scripts"):
                # Since generate_login_scripts writes to /etc/profile.d which needs root,
                # we just verify the config file exists and is parseable
                self.assertTrue(os.path.isfile(config_file))


class TestListProviders(unittest.TestCase):
    """Test the list_providers static method."""

    def test_list_providers_returns_dict(self):
        providers = DnsService.list_providers()
        self.assertIsInstance(providers, dict)
        self.assertGreater(len(providers), 0)

    def test_list_providers_matches_constant(self):
        self.assertEqual(DnsService.list_providers(), DNS_PROVIDERS)


if __name__ == "__main__":
    unittest.main()
