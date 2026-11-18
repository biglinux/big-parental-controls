"""Family DNS providers and their filtering levels, read from data files.

The distribution ships /usr/share/big-parental-controls/dns-providers.json;
/etc/big-parental-controls/dns-providers.json adds providers or replaces
them by id (same format, untouched by package updates):

    {"dns4eu": {"name": "DNS4EU", "url": "https://...", "regions": ["eu"],
                "levels": {"strict": ["86.54.11.12", "86.54.11.212"]}}}

"regions" lists where the provider is meant to be used: "global", "eu" or
ISO 3166 country codes ("br"). Providers of the system's region come first.
A filter is designated as "provider:level" (age-defaults.json, user config).
"""

import ipaddress
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from big_parental_controls.utils.i18n import setup_i18n

_ = setup_i18n()
log = logging.getLogger(__name__)

SHIPPED_FILE = Path("/usr/share/big-parental-controls/dns-providers.json")
LOCAL_FILE = Path("/etc/big-parental-controls/dns-providers.json")

# From the strictest to the most permissive.
LEVELS = ("strict", "adult", "security")

EU_COUNTRIES = frozenset(
    {
        "at",
        "be",
        "bg",
        "cy",
        "cz",
        "de",
        "dk",
        "ee",
        "es",
        "fi",
        "fr",
        "gr",
        "hr",
        "hu",
        "ie",
        "it",
        "lt",
        "lu",
        "lv",
        "mt",
        "nl",
        "pl",
        "pt",
        "ro",
        "se",
        "si",
        "sk",
    }
)


def level_label(level: str) -> str:
    return {
        "strict": _("Strict"),
        "adult": _("Adult content blocked"),
        "security": _("Security only"),
    }.get(level, level)


def level_description(level: str) -> str:
    return {
        "strict": _("For young children: adult content, and more where the provider offers it."),
        "adult": _("Blocks adult content; most other sites stay open."),
        "security": _("Blocks malware and phishing only."),
    }.get(level, "")


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    url: str
    regions: tuple[str, ...]
    levels: dict[str, tuple[str, str]]  # level -> (dns1, dns2), strictest first


def _ipv4(value: object) -> str | None:
    try:
        return str(ipaddress.IPv4Address(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def _provider(pid: str, raw: object) -> Provider | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("levels"), dict):
        return None
    levels = {}
    for level in LEVELS:  # keeps the strictest-first order
        addrs = raw["levels"].get(level)
        if isinstance(addrs, list) and addrs:
            dns1 = _ipv4(addrs[0])
            dns2 = _ipv4(addrs[1]) if len(addrs) > 1 else dns1
            if dns1 and dns2:
                levels[level] = (dns1, dns2)
    if not levels:
        return None
    regions = raw.get("regions") or ["global"]
    return Provider(
        id=pid,
        name=str(raw.get("name") or pid),
        url=str(raw.get("url") or ""),
        regions=tuple(str(r).lower() for r in regions if isinstance(r, str)),
        levels=levels,
    )


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("Ignoring %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def load(shipped: Path = SHIPPED_FILE, local: Path = LOCAL_FILE) -> dict[str, Provider]:
    """Valid providers by id; an id in *local* replaces the shipped one."""
    merged = {**_read(shipped), **_read(local)}
    providers = {}
    for pid, raw in merged.items():
        provider = _provider(str(pid), raw)
        if provider:
            providers[provider.id] = provider
        else:
            log.warning("Ignoring invalid DNS provider %r", pid)
    return providers


def system_region(environ: dict | None = None) -> str | None:
    """Country code from the locale ("fr_FR.UTF-8" -> "fr"), or None."""
    env = os.environ if environ is None else environ
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var, "")
        lang = value.split(".")[0].split("@")[0]
        if "_" in lang:
            return lang.split("_")[1].lower()
    return None


def sort_for_region(providers: dict[str, Provider], region: str | None) -> list[Provider]:
    """Providers of *region* first, then global ones, then the others."""

    def rank(p: Provider) -> int:
        if region and (region in p.regions or ("eu" in p.regions and region in EU_COUNTRIES)):
            return 0
        return 1 if "global" in p.regions else 2

    return sorted(providers.values(), key=rank)  # stable: keeps the file order


def resolve(spec: object, providers: dict[str, Provider]) -> dict | None:
    """User DNS config for *spec*, None if it designates nothing valid.

    spec: "provider:level", "provider" (its strictest level), or
    {"dns1": "...", "dns2": "..."} for custom servers.
    """
    if isinstance(spec, dict):
        dns1, dns2 = _ipv4(spec.get("dns1")), _ipv4(spec.get("dns2", spec.get("dns1")))
        return {"provider": "custom", "dns1": dns1, "dns2": dns2} if dns1 and dns2 else None
    if not isinstance(spec, str):
        return None
    pid, _sep, level = spec.partition(":")
    provider = providers.get(pid)
    if provider is None:
        return None
    level = level or next(iter(provider.levels))
    if level not in provider.levels:
        return None
    dns1, dns2 = provider.levels[level]
    return {"provider": pid, "level": level, "dns1": dns1, "dns2": dns2}


def find_level(provider: Provider, dns1: str | None) -> str:
    """Level of a stored config (older configs have no "level" key)."""
    for level, (addr, _addr2) in provider.levels.items():
        if addr == dns1:
            return level
    return next(iter(provider.levels))


def describe(config: dict, providers: dict[str, Provider]) -> str:
    """Short text for a resolved config, e.g. "CleanBrowsing (Strict)"."""
    provider = providers.get(config.get("provider", ""))
    if provider is None:
        return _("Custom DNS (%s)") % config.get("dns1", "?")
    return f"{provider.name} ({level_label(config.get('level', ''))})"
