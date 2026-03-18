<div align="center">

# BigLinux Parental Controls

A native Linux parental controls suite for supervised accounts, safer browsing, screen time limits, and local-first child protection on BigLinux.

<p>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Linux-2d6cdf">
  <img alt="UI" src="https://img.shields.io/badge/UI-GTK4%20%2B%20libadwaita-4a86cf">
  <img alt="App" src="https://img.shields.io/badge/app-Python-3776AB">
  <img alt="Service" src="https://img.shields.io/badge/service-Rust-000000">
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-2ea043">
</p>

</div>

## Overview

BigLinux Parental Controls is a desktop application that helps parents and guardians create safer Linux accounts for children and teenagers without moving data to the cloud.

The project combines a GTK4 + libadwaita control panel, privileged system helpers, a Rust D-Bus service for ECA Digital age-range signaling, and system integrations such as ACLs, AccountsService, malcontent, PAM time rules, nftables DNS redirection, and polkit authentication.

All enforcement happens locally. No remote account or cloud sync is required.

## What It Does

| Area | What users get |
| --- | --- |
| Supervised accounts | Create a child account or add supervision to an existing account |
| Age profile | Classify supervised users by ECA Digital age range (0–12, 13–15, 16–17, 18+) |
| App restrictions | Allow or block access to selected applications via filesystem ACLs |
| Screen time | Define daily usage limits and allowed time ranges |
| Web filter | Apply family-safe DNS providers or custom DNS servers per user via nftables |
| Activity history | View weekly screen time charts, hourly usage patterns, and login sessions |
| Privacy controls | Delete or export collected activity data (LGPD Art. 18 / GDPR Art. 20) |

## Key Principles

- Local-first: all configuration stays on the machine.
- Native desktop UX: GTK4 + libadwaita, keyboard-friendly, accessible widgets.
- Single `pkexec` per privileged operation: no repeated password prompts.
- Practical enforcement using standard Linux mechanisms (ACL, PAM, nftables).
- ECA Digital age ranges as the classification baseline.

## Architecture

The project has four main parts:

1. **`src/big_parental_controls/`** — Main GTK4 application (Python).
2. **`big-parental-controls/usr/lib/big-parental-controls/group-helper`** — Privileged bash helper run through `pkexec`. All operations that touch protected paths go through this script.
3. **`big-age-signal/`** — Rust D-Bus service (`br.com.biglinux.ParentalDaemon`) that exposes age-range information on the system bus. Other apps on the same device can query `GetAgeGroup(uid)` to get the ECA Digital range for a supervised user.
4. **`big-parental-controls/usr/bin/big-supervised-indicator`** — Lightweight indicator for supervised sessions.

### D-Bus Interface

The Rust daemon exposes two interfaces on `br.com.biglinux.ParentalDaemon`:

- `br.com.biglinux.AgeSignal1.GetAgeGroup(uid: u32) → String` — Returns the ECA Digital range (`"0-12"`, `"13-15"`, `"16-17"`, `"18+"`) stored for the given UID.
- `br.com.biglinux.ParentalMonitor1` — Screen time and session tracking.

### Privileged Operations (group-helper)

All system-level changes go through a single `pkexec group-helper <command>` call:

| Command | Effect |
| --- | --- |
| `create-user USERNAME` | Create supervised account with safe ACL defaults |
| `delete-user USERNAME` | Delete account, home directory, and all data |
| `remove-supervision USERNAME` | Remove from supervised group, restore ACLs |
| `set-age-profile USERNAME RANGE` | Persist ECA Digital age range to `/var/lib/big-parental-controls/user-profiles.json` |
| `dns-set UID JSON` | Write DNS config and apply nftables redirect rules |
| `dns-remove UID` | Remove DNS config and nftables rules |
| `dns-restore` | Restore all nftables DNS rules from saved configs (called at boot) |
| `acl-batch USERNAME BLOCK CSV UNBLOCK CSV` | Apply/remove ACL entries in a single call |
| `time-limit-save JSON` | Write screen time quota config |
| `time-schedule-set/remove USERNAME` | Apply/remove PAM time rules |

### Systemd Services

| Service | Purpose |
| --- | --- |
| `big-parental-daemon.service` | Rust D-Bus daemon |
| `big-parental-dns-restore.service` | Restore nftables DNS rules at boot |
| `big-parental-time-check.timer` | Periodic screen time enforcement |

## User Detail Page Layout

When a parent opens a supervised user, the page shows (in order):

1. **Account summary** — username and account info
2. **Profile** — ECA Digital age group, delete/export data buttons
3. **Web Filter** — link to DNS provider selection
4. **Screen Time** — link to time limits editor
5. **Activity** — weekly chart, hourly chart, login sessions
6. **Account Actions** — remove supervision / delete user

## Default App Blocks

When a supervised account is created, the following binaries are blocked via ACL:

`pacman`, `pamac-manager`, `pamac-installer`, `pamac-daemon`, `yay`, `paru`, `flatpak`, `snap`, `ssh`, `rustdesk`

The parent can adjust this list from the app's filter page.

## Privacy and Security

- No remote account required; no telemetry.
- Age-range data is stored locally in `/var/lib/big-parental-controls/user-profiles.json`, written only by the privileged helper.
- The D-Bus policy allows `GetAgeGroup` queries from all users on the local system bus.

## Dependencies

Runtime:

- Python 3.14+, PyGObject, GTK4, libadwaita
- malcontent, AccountsService, polkit
- nftables, ACL tools (`setfacl`/`getfacl`)
- gettext

Build:

- Rust, Cargo

See `pkgbuild/PKGBUILD` for the full list.

## Build and Install

### Package Build (recommended)

```bash
cd pkgbuild
makepkg -si
```

Several features depend on installed paths, polkit policies, systemd services, and helper scripts — running from source alone is not enough for full functionality.

### Rust Service

```bash
cd big-age-signal
cargo build --release
```

## Testing

```bash
pytest tests
```

The test suite covers:

- i18n configuration and locale sync
- package structure
- DNS service behavior
- age signal D-Bus behavior
- polkit policy presence
- resilience for corrupted configs and subprocess failures

## Localization

The project uses gettext. Editable sources are in `locale/`, compiled catalogs in `big-parental-controls/usr/share/locale/`.

```bash
./update_translations.sh
```

This script extracts strings, updates `.po` files, mirrors catalogs, and rebuilds `.mo` files.

## Compliance Direction

This project references:

- **ECA Digital** (Brazil) — age ranges used for content classification
- **LGPD Art. 18** — data deletion right surfaced in the UI
- **GDPR Art. 20** — data portability surfaced in the UI
- UK Children's Code, EU Digital Services Act

This repository is a technical implementation project, not legal advice.

## Contributing

Contributions are welcome in these areas:

- GTK4/libadwaita UX improvements
- accessibility and Orca review
- new translations
- safer system integration patterns
- tests for real-world Linux edge cases
- distro packaging and deployment polish

Prefer minimal patches, explicit error handling, and native Linux solutions.

## License

GPL-3.0-or-later.

## Maintainer

Bruno Goncalves and the BigLinux team.

---

*This is the hardest program I have ever built — not for technical reasons, but because I realized that the country where I live, and many others, are heading in a direction where I could not have become who I am. I published my first website at 12 and released the BigLinux distribution at 17.*

*Once again, in exchange for an alleged attempt at protection, freedom is being surrendered — and this time it is the freedom to be a true nerd: someone who can study how hardware works, replace the operating system, write their own programs, and compile the kernel with whatever adjustments they see fit. I hope these laws are reformed and that lawmakers come to understand that alongside a genuine attempt to do good, they are harming one of the most peaceful and, at the same time, most important groups for technological development: the nerd. Someone who just wants to live in peace, studying day and night, building technologies that will benefit thousands or even millions of people.*

*I will not be directly affected — it has been a long time since I was a teenager. But from the age of 10, most of my waking hours were spent in front of a computer with internet access, just like thousands of other nerds who are never remembered when laws are written. After all, proportionally to the number of voters, we are an almost insignificant figure. Yet people keep demanding better software, better automation, more comfort in their lives — without having dedicated even one percent of the effort we have spent learning how technology, computers, and the internet actually work. But they are the majority, and the majority decides the laws we are all required to follow.*

*Today is a sad day for humanity. Just because you have no interest in compiling kernels, editing source code, running Docker or Podman containers, spinning up virtual machines, benchmarking DNS to shave a few milliseconds off response times, building your own VPNs, or simply taking apart how things work for the pure joy of learning — that does not mean you should support laws that deny children and teenagers the freedom to do exactly those things. I say this without hypocrisy: I did most of them before I turned 18. So I will say it again — from where I stand, today is a sad day for humanity.*

*And I am publishing this program in an attempt to keep BigLinux alive and out of legal trouble — one of the longest-running free software projects in Brazil, maintained by nerds, voluntarily, and completely free of charge to anyone who wants to use it or learn from it, driven only by our attachment to shared knowledge and our desire to understand how things work.*

— Bruno Goncalves
