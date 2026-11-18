"""Static checks of the DNS filter bypass protection (group-helper, daemon unit).

The nftables behaviour itself needs root and is checked on a real system;
these tests guard the data and wiring that make it work.
"""

import ipaddress
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "big-parental-controls"
HELPER = PKG / "usr/lib/big-parental-controls/group-helper"
DOH_SERVERS = PKG / "usr/share/big-parental-controls/doh-servers.txt"
DAEMON_UNIT = PKG / "usr/lib/systemd/system/big-parental-daemon.service"

# Shared CDN ranges: blocking port 443 there would break ordinary websites.
CDN_RANGES = [
    ipaddress.ip_network(n)
    for n in ("104.16.0.0/13", "172.64.0.0/13", "2606:4700::/44", "2a06:98c0::/29")
]
# Except the Cloudflare resolver addresses, which are inside 2606:4700::/32
RESOLVER_EXCEPTIONS = [ipaddress.ip_network("2606:4700:4700::/48")]


def _entries() -> list[str]:
    lines = DOH_SERVERS.read_text(encoding="utf-8").splitlines()
    return [ln.split("#", 1)[0].strip() for ln in lines if ln.split("#", 1)[0].strip()]


def _helper_regex(name: str) -> re.Pattern:
    """The grep -E pattern group-helper uses to read DOH_SERVERS."""
    text = HELPER.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.lstrip().startswith(f"{name}=$(grep"))
    pattern = re.search(r"'([^']+)'", line).group(1)
    return re.compile(pattern, re.IGNORECASE if "-oiE" in line else 0)


def test_entries_are_valid_networks() -> None:
    entries = _entries()
    assert len(entries) > 20
    for entry in entries:
        ipaddress.ip_network(entry)  # raises on a typo


def test_no_shared_cdn_address() -> None:
    for entry in _entries():
        net = ipaddress.ip_network(entry)
        if any(net.subnet_of(r) for r in RESOLVER_EXCEPTIONS if r.version == net.version):
            continue
        clash = [r for r in CDN_RANGES if r.version == net.version and net.overlaps(r)]
        assert not clash, f"{entry} is in a shared CDN range {clash}"


def test_helper_reads_every_entry() -> None:
    v4, v6 = _helper_regex("v4"), _helper_regex("v6")
    for entry in _entries():
        version = ipaddress.ip_network(entry).version
        pattern = v4 if version == 4 else v6
        match = pattern.match(entry)
        assert match and match.group(0) == entry, f"helper would not read {entry}"
        other = v6 if version == 4 else v4
        assert not other.match(entry), f"{entry} would land in the wrong set"


def test_daemon_restores_dns_rules_at_start() -> None:
    unit = DAEMON_UNIT.read_text(encoding="utf-8")
    assert re.search(
        r"^ExecStartPre=-\+/usr/lib/big-parental-controls/group-helper dns-restore$",
        unit,
        re.M,
    )
    # nftables.service flushes the ruleset when it starts: restore after it.
    assert re.search(r"^After=.*\bnftables\.service\b", unit, re.M)


def test_bypass_rules_cover_dot_doh_and_ipv6() -> None:
    text = HELPER.read_text(encoding="utf-8")
    body = text[text.index("dns_apply() {") : text.index("dns_unapply() {")]
    assert "th dport 853 reject" in body
    assert "ip daddr @doh4" in body and "ip6 daddr @doh6" in body
    # Any port to a public resolver (Quad9 also serves DoH on 5053), but 53:
    # after the DNAT, plain DNS goes to the filter, which may be in the list.
    assert body.count("daddr @doh") == body.count("th dport != 53 reject") == 2
    assert "meta nfproto ipv6" in body and "th dport 53 reject" in body


@pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None, reason="needs Linux bash"
)
def test_helper_syntax() -> None:
    subprocess.run(["bash", "-n", str(HELPER)], check=True)
