"""Service for managing DNS configuration for supervised accounts."""

import ipaddress
import json
import os
import subprocess

from big_parental_controls.core.constants import DNS_CONFIG_DIR, DNS_PROVIDERS, GROUP_HELPER

_SYSTEM_CONFIG_DIR = "/etc/big-parental-controls/dns"


class DnsService:
    """Manage per-user DNS configuration for family-safe filtering."""

    @staticmethod
    def _use_privileged_helper() -> bool:
        """Use pkexec only for the real system config path."""
        return os.path.abspath(DNS_CONFIG_DIR) == _SYSTEM_CONFIG_DIR

    @staticmethod
    def _validate_ip(addr: str) -> bool:
        """Validate that addr is a valid IPv4 or IPv6 address."""
        try:
            ipaddress.ip_address(addr)
            return True
        except ValueError:
            return False

    def get_dns_for_user(self, uid: int) -> dict | None:
        """Get the DNS configuration for a user UID."""
        config_file = os.path.join(DNS_CONFIG_DIR, f"{uid}.json")
        if not os.path.isfile(config_file):
            return None
        with open(config_file) as f:
            return json.load(f)

    def set_dns_for_user(
        self,
        uid: int,
        provider: str | None = None,
        custom_dns1: str | None = None,
        custom_dns2: str | None = None,
    ) -> bool:
        """Configure DNS for a user. Pass provider=None to disable."""
        config_file = os.path.join(DNS_CONFIG_DIR, f"{uid}.json")

        if provider is None:
            if self._use_privileged_helper():
                subprocess.run(
                    ["pkexec", GROUP_HELPER, "dns-remove", str(uid)],
                    check=False,
                    capture_output=True,
                    timeout=30,
                )
            else:
                if os.path.isfile(config_file):
                    os.remove(config_file)
            return True

        if provider == "custom":
            if not custom_dns1:
                return False
            if not self._validate_ip(custom_dns1):
                return False
            if custom_dns2 and not self._validate_ip(custom_dns2):
                return False
            config = {
                "provider": "custom",
                "dns1": custom_dns1,
                "dns2": custom_dns2 or custom_dns1,
            }
        elif provider in DNS_PROVIDERS:
            info = DNS_PROVIDERS[provider]
            config = {
                "provider": provider,
                "dns1": info["dns1"],
                "dns2": info["dns2"],
            }
        else:
            return False

        if self._use_privileged_helper():
            json_data = json.dumps(config)
            result = subprocess.run(
                ["pkexec", GROUP_HELPER, "dns-set", str(uid), json_data],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0

        os.makedirs(DNS_CONFIG_DIR, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.chmod(config_file, 0o644)
        return True

    def _apply_dns_reset(self, uid: int) -> None:
        """Remove any DNS overrides for a user."""
        config_file = os.path.join(DNS_CONFIG_DIR, f"{uid}.json")
        if self._use_privileged_helper():
            subprocess.run(
                ["pkexec", GROUP_HELPER, "dns-remove", str(uid)],
                check=False,
                capture_output=True,
                timeout=30,
            )
        elif os.path.isfile(config_file):
            os.remove(config_file)

    @staticmethod
    def list_providers() -> dict:
        """Return the available DNS providers."""
        return DNS_PROVIDERS
