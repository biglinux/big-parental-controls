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
INSTALL = REPO / "pkgbuild/big-parental-controls.install"

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


def test_upgrade_restarts_daemon() -> None:
    """Existing installs get the new rules on upgrade, not at the next boot."""
    text = INSTALL.read_text(encoding="utf-8")
    body = text[text.index("post_upgrade() {") :]
    body = body[: body.index("\n}")]
    assert "systemctl try-restart big-parental-daemon.service" in body
    # pacman reloads systemd only after the transaction: reload first, or
    # the restart uses the old unit (without ExecStartPre)
    assert body.index("systemctl daemon-reload") < body.index("systemctl try-restart")


def _helper_case(name: str) -> str:
    text = HELPER.read_text(encoding="utf-8")
    body = text[text.index(f"    {name})\n") :]
    return body[: body.index("\n        ;;")]


def test_removing_supervision_removes_dns_filter() -> None:
    """Otherwise dns-restore brings the filter back at every boot (delete-user
    runs remove-full too)."""
    body = _helper_case("remove-full")
    assert 'rm -f "$DNS_DIR/$USER_UID.json"' in body
    assert 'dns_unapply "$USER_UID"' in body
    assert '"$0" remove-full' in _helper_case("delete-user")


def test_restore_skips_non_supervised_users() -> None:
    """Leftover configs from older versions must not filter anyone."""
    body = _helper_case("dns-restore")
    assert 'grep -qx "$GROUP"' in body
    assert body.index('dns_unapply "$uid"') < body.index('dns_apply "$uid"')


def test_rules_are_rechecked_while_running() -> None:
    """A "flush ruleset" (nftables restart) must not leave a child unfiltered."""
    unit = DAEMON_UNIT.read_text(encoding="utf-8")
    assert re.search(r"^Wants=big-parental-dns-check\.timer$", unit, re.M)
    units = DAEMON_UNIT.parent
    timer = (units / "big-parental-dns-check.timer").read_text(encoding="utf-8")
    assert re.search(r"^OnUnitActiveSec=", timer, re.M)
    service = (units / "big-parental-dns-check.service").read_text(encoding="utf-8")
    assert "group-helper dns-restore --missing" in service
    install = INSTALL.read_text(encoding="utf-8")
    assert "systemctl stop big-parental-dns-check.timer" in install


def test_restore_forgets_confirmed_leftovers_only() -> None:
    """A later account reusing the UID must not inherit the old filter, but a
    directory-service failure must not erase a child's config."""
    body = _helper_case("dns-restore")
    assert "(( rc == 2 ))" in body  # getent: account does not exist
    forget = body.index('rm -f "$cfg" "/etc/profile.d/big-dns-$uid.sh"')
    assert forget < body.index('if [[ -z "$user" ]]; then')


@pytest.mark.parametrize("case", ["dns-set", "dns-remove", "dns-restore", "remove-full"])
def test_dns_changes_are_serialised(case: str) -> None:
    """A restore must not re-apply a config that dns-set/dns-remove changed
    between its read and its write."""
    body = _helper_case(case)
    lock = body.index("dns_lock")
    for access in ('"$DNS_DIR/$2.json"', 'for cfg in "$DNS_DIR"', '"$DNS_DIR/$USER_UID.json"'):
        if access in body:
            assert lock < body.index(access), access


def test_uninstall_stops_a_running_check_first() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    stop = text.index("systemctl stop big-parental-dns-check.service")
    assert stop < text.index("nft delete table inet big_parental_guard")


def test_dns_set_validates_before_writing() -> None:
    body = _helper_case("dns-set")
    assert body.index('valid_ipv4 "$DNS1"') < body.index('> "$DNS_DIR/$2.json"')


LINUX_BASH = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bash") is None, reason="needs Linux bash"
)


@LINUX_BASH
def test_helper_syntax() -> None:
    subprocess.run(["bash", "-n", str(HELPER)], check=True)


@LINUX_BASH
@pytest.mark.parametrize(
    ("addr", "valid"),
    [
        ("86.54.11.12", True),
        ("0.0.0.0", True),
        ("255.255.255.255", True),
        ("256.1.1.1", False),
        ("1.2.3", False),
        ("2001:db8::53", False),
        ("1.2.3.4; nft flush ruleset", False),
        ("08.8.8.8", True),
        ("", False),
    ],
)
def test_valid_ipv4(addr: str, valid: bool) -> None:
    script = 'eval "$(sed -n \'/^valid_ipv4()/,/^}/p\' "$1")"; valid_ipv4 "$2"'
    result = subprocess.run(["bash", "-c", script, "bash", str(HELPER), addr], check=False)
    assert (result.returncode == 0) is valid
