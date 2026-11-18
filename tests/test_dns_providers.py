"""Tests for dns_providers: data file, /etc override, levels, region order."""

import ipaddress
import json
import locale
from pathlib import Path

import pytest

# The C gettext bindings only exist on Linux; let the tests run elsewhere.
for _name in ("bindtextdomain", "textdomain"):
    if not hasattr(locale, _name):
        setattr(locale, _name, lambda *_args: None)

from big_parental_controls.services import dns_providers as dp  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHARE = REPO / "big-parental-controls/usr/share/big-parental-controls"
SHIPPED = SHARE / "dns-providers.json"
DOH_SERVERS = SHARE / "doh-servers.txt"
NONE = Path("/nonexistent.json")


@pytest.fixture
def shipped() -> dict[str, dp.Provider]:
    return dp.load(SHIPPED, NONE)


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_shipped_file_loads_completely(shipped) -> None:
    raw = json.loads(SHIPPED.read_text(encoding="utf-8"))
    assert set(shipped) == set(raw)
    for pid, provider in shipped.items():
        assert set(provider.levels) == set(raw[pid]["levels"]), pid
        assert provider.url.startswith("https://")


@pytest.mark.skipif(not DOH_SERVERS.exists(), reason="doh-servers.txt not in this tree")
def test_shipped_addresses_are_blocked_for_doh(shipped) -> None:
    """Every filter address is in doh-servers.txt: its port 53 stays open
    after the DNAT, every other port (DoH) is closed for supervised users."""
    nets = [
        ipaddress.ip_network(ln.split("#")[0].strip())
        for ln in DOH_SERVERS.read_text(encoding="utf-8").splitlines()
        if ln.split("#")[0].strip()
    ]
    for provider in shipped.values():
        for dns1, dns2 in provider.levels.values():
            for addr in (dns1, dns2):
                ip = ipaddress.ip_address(addr)
                assert any(ip in n for n in nets), f"{provider.id} {addr}"


def test_levels_are_strictest_first(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "p.json",
        {"x": {"levels": {"security": ["9.9.9.9"], "strict": ["1.2.3.4", "1.2.3.5"]}}},
    )
    provider = dp.load(path, NONE)["x"]
    assert list(provider.levels) == ["strict", "security"]
    assert provider.levels["security"] == ("9.9.9.9", "9.9.9.9")  # dns2 defaults to dns1
    assert provider.regions == ("global",)


@pytest.mark.parametrize(
    "raw",
    [
        {"levels": {}},
        {"levels": {"strict": ["not-an-ip"]}},
        {"levels": {"strict": ["2001:db8::1"]}},  # the DNAT is IPv4 only
        {"levels": {"unknown-level": ["1.2.3.4"]}},
        {"name": "no levels"},
        "not a dict",
    ],
)
def test_invalid_providers_are_dropped(tmp_path: Path, raw: object) -> None:
    assert dp.load(_write(tmp_path / "p.json", {"x": raw}), NONE) == {}


def test_local_file_adds_and_replaces(tmp_path: Path) -> None:
    local = _write(
        tmp_path / "l.json",
        {
            "cleanbrowsing": {"name": "Mine", "levels": {"adult": ["185.228.168.10"]}},
            "isp": {"name": "My ISP", "regions": ["fr"], "levels": {"strict": ["10.0.0.53"]}},
        },
    )
    providers = dp.load(SHIPPED, local)
    assert providers["cleanbrowsing"].name == "Mine"
    assert list(providers["cleanbrowsing"].levels) == ["adult"]
    assert providers["isp"].regions == ("fr",)
    assert "dns4eu" in providers  # untouched


@pytest.mark.parametrize(
    ("env", "region"),
    [
        ({"LANG": "fr_FR.UTF-8"}, "fr"),
        ({"LC_ALL": "pt_BR.UTF-8", "LANG": "fr_FR.UTF-8"}, "br"),
        ({"LANG": "de_DE@euro"}, "de"),
        ({"LANG": "C.UTF-8"}, None),
        ({}, None),
    ],
)
def test_system_region(env: dict, region: str | None) -> None:
    assert dp.system_region(env) == region


def test_eu_provider_first_in_europe(shipped) -> None:
    assert dp.sort_for_region(shipped, "fr")[0].id == "dns4eu"
    assert dp.sort_for_region(shipped, "br")[0].id != "dns4eu"
    # outside its region a provider is still offered, after the global ones
    assert dp.sort_for_region(shipped, "br")[-1].id == "dns4eu"
    assert dp.sort_for_region(shipped, None)[0].id == "cleanbrowsing"


def test_country_provider_first_in_its_country(tmp_path: Path) -> None:
    local = _write(
        tmp_path / "l.json", {"br-isp": {"regions": ["br"], "levels": {"strict": ["10.0.0.1"]}}}
    )
    providers = dp.load(SHIPPED, local)
    assert dp.sort_for_region(providers, "br")[0].id == "br-isp"
    assert dp.sort_for_region(providers, "fr")[-1].id == "br-isp"


def test_resolve(shipped) -> None:
    assert dp.resolve("dns4eu:strict", shipped) == {
        "provider": "dns4eu",
        "level": "strict",
        "dns1": "86.54.11.12",
        "dns2": "86.54.11.212",
    }
    assert dp.resolve("cleanbrowsing", shipped)["level"] == "strict"  # strictest
    assert dp.resolve("cloudflare", shipped)["level"] == "adult"  # has no strict
    assert dp.resolve({"dns1": "86.54.11.12", "dns2": "86.54.11.212"}, shipped) == {
        "provider": "custom",
        "dns1": "86.54.11.12",
        "dns2": "86.54.11.212",
    }
    assert dp.resolve({"dns1": "10.0.0.1"}, shipped)["dns2"] == "10.0.0.1"


@pytest.mark.parametrize(
    "spec", ["unknown", "cloudflare:strict", "dns4eu:bogus", {"dns1": "x"}, {}, None, 42]
)
def test_resolve_invalid(shipped, spec: object) -> None:
    assert dp.resolve(spec, shipped) is None


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        # written by earlier versions (no "level"): the three original providers
        (
            {"provider": "cleanbrowsing", "dns1": "185.228.168.168", "dns2": "185.228.169.168"},
            ("cleanbrowsing", "strict"),
        ),
        (
            {"provider": "opendns", "dns1": "208.67.222.123", "dns2": "208.67.220.123"},
            ("opendns", "adult"),
        ),
        ({"provider": "cloudflare", "dns1": "1.1.1.3", "dns2": "1.0.0.3"}, ("cloudflare", "adult")),
        # a known provider typed by hand as custom (a real config, DNS4EU child)
        (
            {"provider": "custom", "dns1": "86.54.11.12", "dns2": "86.54.11.212"},
            ("dns4eu", "strict"),
        ),
        # current format
        (
            {"provider": "adguard", "level": "security", "dns1": "94.140.14.14"},
            ("adguard", "security"),
        ),
        # really custom, removed provider, provider whose address changed
        ({"provider": "custom", "dns1": "10.0.0.53", "dns2": "10.0.0.54"}, None),
        ({"provider": "gone", "dns1": "10.9.9.9"}, None),
        ({"provider": "cleanbrowsing", "level": "strict", "dns1": "6.6.6.6"}, None),
        ({}, None),
    ],
)
def test_identify_existing_configs(shipped, config: dict, expected) -> None:
    assert dp.identify(config, shipped) == expected


def test_identify_prefers_the_stored_provider(tmp_path: Path) -> None:
    both = {"levels": {"strict": ["10.0.0.1"]}}
    providers = dp.load(_write(tmp_path / "p.json", {"a": both, "b": both}), NONE)
    assert dp.identify({"provider": "b", "dns1": "10.0.0.1"}, providers) == ("b", "strict")
    assert dp.identify({"provider": "custom", "dns1": "10.0.0.1"}, providers) == ("a", "strict")


def test_describe(shipped) -> None:
    assert dp.describe(dp.resolve("dns4eu:strict", shipped), shipped) == "DNS4EU (Strict)"
    assert "10.0.0.1" in dp.describe({"provider": "custom", "dns1": "10.0.0.1"}, shipped)
