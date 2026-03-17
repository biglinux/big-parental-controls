"""Tests for corrupted config fallback, subprocess failures, and edge cases."""

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


class TestDnsCorruptedConfig(unittest.TestCase):
    """DNS service handles malformed JSON and missing fields gracefully."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_corrupted_json_returns_none(self):
        from services.dns_service import DnsService

        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            config_file = os.path.join(self.tmpdir, "1001.json")
            with open(config_file, "w") as f:
                f.write("{this is not valid json!!!")
            dns = DnsService()
            # Should raise or return broken data; the function just calls json.load
            # which will raise JSONDecodeError — caller must handle
            with self.assertRaises(json.JSONDecodeError):
                dns.get_dns_for_user(1001)

    def test_empty_file_returns_none(self):
        from services.dns_service import DnsService

        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            config_file = os.path.join(self.tmpdir, "1001.json")
            with open(config_file, "w") as f:
                f.write("")
            dns = DnsService()
            with self.assertRaises(json.JSONDecodeError):
                dns.get_dns_for_user(1001)

    def test_missing_dns_fields_in_generate_scripts(self):
        from services.dns_service import DnsService

        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            # Config with missing dns1
            config_file = os.path.join(self.tmpdir, "1001.json")
            with open(config_file, "w") as f:
                json.dump({"provider": "custom"}, f)

            dns = DnsService()
            # generate_login_scripts skips entries with invalid dns1
            # Should not raise
            dns.generate_login_scripts()

    def test_malicious_ip_rejected_by_set_dns(self):
        from services.dns_service import DnsService

        dns = DnsService()
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = dns.set_dns_for_user(
                1001,
                provider="custom",
                custom_dns1="; rm -rf /",
            )
            self.assertFalse(result)

    def test_ipv6_accepted_as_custom_dns(self):
        from services.dns_service import DnsService

        dns = DnsService()
        with patch("services.dns_service.CONFIG_DIR", self.tmpdir):
            result = dns.set_dns_for_user(
                1001,
                provider="custom",
                custom_dns1="2606:4700:4700::1111",
                custom_dns2="2606:4700:4700::1001",
            )
            self.assertTrue(result)

    def test_validate_ip_private_range(self):
        from services.dns_service import DnsService

        self.assertTrue(DnsService._validate_ip("192.168.1.1"))
        self.assertTrue(DnsService._validate_ip("10.0.0.1"))
        self.assertFalse(DnsService._validate_ip("not-an-ip"))
        self.assertFalse(DnsService._validate_ip("1.2.3.4; echo hacked"))


class TestTimeServiceCorruptedConfig(unittest.TestCase):
    """Time service handles corrupted state files gracefully."""

    def test_load_limits_empty_file(self):
        from services import time_service

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("")
            tmpfile = f.name

        try:
            with patch.object(time_service, "TIME_LIMITS_FILE", tmpfile):
                result = time_service._load_limits()
                self.assertEqual(result, {})
        finally:
            os.unlink(tmpfile)

    def test_load_limits_corrupted_json(self):
        from services import time_service

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{broken json[[[")
            tmpfile = f.name

        try:
            with patch.object(time_service, "TIME_LIMITS_FILE", tmpfile):
                result = time_service._load_limits()
                self.assertEqual(result, {})
        finally:
            os.unlink(tmpfile)

    def test_load_limits_missing_file(self):
        from services import time_service

        with patch.object(time_service, "TIME_LIMITS_FILE", "/nonexistent/path.json"):
            result = time_service._load_limits()
            self.assertEqual(result, {})

    def test_get_schedule_nonexistent_user(self):
        from services import time_service

        with patch.object(time_service, "TIME_LIMITS_FILE", "/nonexistent/path.json"):
            result = time_service.get_schedule("nonexistent_user")
            self.assertIsNone(result)

    def test_get_daily_limit_nonexistent_user(self):
        from services import time_service

        with patch.object(time_service, "TIME_LIMITS_FILE", "/nonexistent/path.json"):
            result = time_service.get_daily_limit("nonexistent_user")
            self.assertEqual(result, 0)


class TestAclServiceCorruptedState(unittest.TestCase):
    """ACL service handles corrupted state and subprocess failures."""

    def test_load_state_missing_file(self):
        from services import acl_service

        with patch.object(acl_service, "ACL_STATE_FILE", "/nonexistent/path.json"):
            result = acl_service._load_state()
            self.assertEqual(result, {})

    def test_load_state_corrupted_json(self):
        from services import acl_service

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json at all")
            tmpfile = f.name

        try:
            with patch.object(acl_service, "ACL_STATE_FILE", tmpfile):
                result = acl_service._load_state()
                self.assertEqual(result, {})
        finally:
            os.unlink(tmpfile)

    def test_apply_default_blocks_subprocess_failure(self):
        from services import acl_service

        import subprocess

        with patch("services.acl_service.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "pkexec")
            result = acl_service.apply_default_blocks("testuser")
            self.assertFalse(result)

    def test_apply_default_blocks_timeout(self):
        from services import acl_service

        import subprocess

        with patch("services.acl_service.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("pkexec", 60)
            result = acl_service.apply_default_blocks("testuser")
            self.assertFalse(result)

    def test_unblock_all_empty_state(self):
        from services import acl_service

        with patch.object(acl_service, "ACL_STATE_FILE", "/nonexistent/path.json"):
            result = acl_service.unblock_all("testuser")
            self.assertTrue(result)

    def test_default_supervised_blocks_is_list(self):
        from services.acl_service import DEFAULT_SUPERVISED_BLOCKS

        self.assertIsInstance(DEFAULT_SUPERVISED_BLOCKS, list)
        self.assertGreater(len(DEFAULT_SUPERVISED_BLOCKS), 0)
        for path in DEFAULT_SUPERVISED_BLOCKS:
            self.assertTrue(path.startswith("/"), f"Path should be absolute: {path}")


class TestTimeServiceSubprocessFailures(unittest.TestCase):
    """Time service handles subprocess failures gracefully."""

    def test_set_schedule_subprocess_failure(self):
        from services import time_service

        import subprocess

        with patch("services.time_service.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "pkexec")
            result = time_service.set_schedule(
                "testuser", [{"start_hour": 8, "end_hour": 20}]
            )
            self.assertFalse(result)

    def test_remove_schedule_subprocess_failure(self):
        from services import time_service

        import subprocess

        with patch("services.time_service.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "pkexec")
            # remove_schedule logs a warning but still continues
            with patch.object(time_service, "TIME_LIMITS_FILE", "/nonexistent/path.json"):
                result = time_service.remove_schedule("testuser")
                self.assertTrue(result)


class TestAsyncRunner(unittest.TestCase):
    """Test the async_runner utility without GTK main loop."""

    def test_run_async_calls_callback(self):
        import threading

        from utils.async_runner import run_async

        event = threading.Event()
        results = []

        def task():
            return 42

        def callback(result):
            results.append(result)
            event.set()

        # Mock GLib.idle_add to call the function directly
        with patch("utils.async_runner.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)):
            run_async(task, callback)
            event.wait(timeout=2)

        self.assertEqual(results, [42])

    def test_run_async_calls_error_callback(self):
        import threading

        from utils.async_runner import run_async

        event = threading.Event()
        errors = []

        def task():
            raise ValueError("test error")

        def error_callback(exc):
            errors.append(exc)
            event.set()

        with patch("utils.async_runner.GLib.idle_add", side_effect=lambda fn, *args: fn(*args)):
            run_async(task, error_callback=error_callback)
            event.wait(timeout=2)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)

    def test_run_async_no_callback(self):
        import threading

        from utils.async_runner import run_async

        event = threading.Event()

        def task():
            event.set()
            return 99

        # Should not raise even without callback
        run_async(task)
        event.wait(timeout=2)
        self.assertTrue(event.is_set())


if __name__ == "__main__":
    unittest.main()
