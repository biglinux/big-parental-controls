"""Service for managing DNS configuration for supervised accounts."""

import ipaddress
import json
import os
import subprocess

from services.acl_service import GROUP_HELPER

CONFIG_DIR = "/etc/big-parental-controls/dns"

DNS_PROVIDERS = {
    "cleanbrowsing": {
        "name": "CleanBrowsing Family Filter",
        "dns1": "185.228.168.168",
        "dns2": "185.228.169.168",
    },
    "opendns": {
        "name": "OpenDNS FamilyShield",
        "dns1": "208.67.222.123",
        "dns2": "208.67.220.123",
    },
    "cloudflare": {
        "name": "Cloudflare for Families",
        "dns1": "1.1.1.3",
        "dns2": "1.0.0.3",
    },
}

SYSTEM_CONFIG_DIR = "/etc/big-parental-controls/dns"


class DnsService:
    """Manage per-user DNS configuration for family-safe filtering."""

    @staticmethod
    def _use_privileged_helper() -> bool:
        """Use pkexec only for the real system config path.

        Tests patch CONFIG_DIR to a temporary directory and should use local writes.
        """
        return os.path.abspath(CONFIG_DIR) == SYSTEM_CONFIG_DIR

    @staticmethod
    def _validate_ip(addr: str) -> bool:
        """Validate that addr is a valid IPv4 or IPv6 address."""
        try:
            ipaddress.ip_address(addr)
            return True
        except ValueError:
            return False

    def get_dns_for_user(self, uid: int) -> dict | None:
        """Get the DNS configuration for a user UID.

        Returns dict with 'provider', 'dns1', 'dns2' or None if not configured.
        """
        config_file = os.path.join(CONFIG_DIR, f"{uid}.json")
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
        """Configure DNS for a user. Pass provider=None to disable.

        Args:
            uid: Target user UID.
            provider: One of 'cleanbrowsing', 'opendns', 'cloudflare', 'custom', or None.
            custom_dns1: Primary DNS if provider='custom'.
            custom_dns2: Secondary DNS if provider='custom'.

        Returns True on success.
        """
        config_file = os.path.join(CONFIG_DIR, f"{uid}.json")

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

        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.chmod(config_file, 0o644)
        return True

    def _apply_dns_reset(self, uid: int) -> None:
        """Remove any DNS overrides for a user."""
        config_file = os.path.join(CONFIG_DIR, f"{uid}.json")
        if self._use_privileged_helper():
            subprocess.run(
                ["pkexec", GROUP_HELPER, "dns-remove", str(uid)],
                check=False,
                capture_output=True,
                timeout=30,
            )
            return

        if os.path.isfile(config_file):
            os.remove(config_file)

    def generate_login_scripts(self) -> None:
        """Generate /etc/profile.d/ scripts for all configured users.

        Each script sets DNS via resolvectl when the user logs in.
        """
        if not os.path.isdir(CONFIG_DIR):
            return

        for filename in os.listdir(CONFIG_DIR):
            if not filename.endswith(".json"):
                continue
            uid = filename.replace(".json", "")
            config_file = os.path.join(CONFIG_DIR, filename)
            with open(config_file) as f:
                config = json.load(f)

            dns1 = config.get("dns1", "")
            dns2 = config.get("dns2", "")

            # Validate IP addresses before writing to shell script
            if not self._validate_ip(dns1):
                continue
            if dns2 and not self._validate_ip(dns2):
                dns2 = ""

            script_content = (
                "#!/bin/bash\n"
                f"# Generated by big-parental-controls — DNS for UID {uid}\n"
                f'if [ "$(id -u)" = "{uid}" ]; then\n'
                "    # Try resolvectl first (systemd-resolved)\n"
                "    if command -v resolvectl &>/dev/null; then\n"
                "        IFACE=$(ip route show default 2>/dev/null | awk '{print $5}' | head -1)\n"
                '        if [ -n "$IFACE" ]; then\n'
                f'            resolvectl dns "$IFACE" {dns1} {dns2} 2>/dev/null\n'
                "        fi\n"
                "    fi\n"
                "fi\n"
            )
            script_path = f"/etc/profile.d/big-dns-{uid}.sh"
            with open(script_path, "w") as f:
                f.write(script_content)
            os.chmod(script_path, 0o755)

    @staticmethod
    def list_providers() -> dict:
        """Return the available DNS providers."""
        return DNS_PROVIDERS
