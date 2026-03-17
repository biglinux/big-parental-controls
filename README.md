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

BigLinux Parental Controls is a desktop application designed to help parents and guardians create safer Linux accounts for children and teenagers without moving data to the cloud.

The project combines a GTK4 + libadwaita control panel, privileged system helpers, a Rust D-Bus service for age-range signaling, and system integrations such as ACLs, AccountsService, malcontent, PAM time rules, and DNS-based web filtering.

This is a native Linux-first project. It is intended to feel like part of the operating system, not a web wrapper.

## What It Does

| Area | What users get |
| --- | --- |
| Supervised accounts | Create a child account or add supervision to an existing account |
| App restrictions | Allow or block access to selected applications with filesystem ACLs |
| Screen time | Define daily usage limits and allowed time ranges |
| Web filter | Apply family-safe DNS providers or custom DNS servers per supervised user |
| Guidance | Show clear help resources and emergency contacts |
| Privacy | Keep configuration and processing on the device |

## Key Principles

- Local-first: settings stay on the machine.
- Native desktop UX: GTK4 + libadwaita, keyboard-friendly, accessible widgets.
- Practical enforcement: uses system features that Linux already provides.
- Didactic interface: the app tries to explain outcomes in plain language.
- Packaging-ready: designed to ship as a real distro package, not just a dev script.

## Architecture

The project is split into four main parts:

1. `big-parental-controls/usr/share/biglinux/parental-controls/`
   The main GTK4 application written in Python.
2. `big-parental-controls/usr/lib/big-parental-controls/group-helper`
   A privileged helper executed through `pkexec` for operations that must touch protected system paths.
3. `big-age-signal/`
   A Rust D-Bus service that exposes age-range information locally so other apps can adapt content on the same device.
4. `big-parental-controls/usr/bin/big-supervised-indicator`
   A lightweight indicator for supervised sessions.

## Project Layout

```text
big-parental-controls/
├── README.md
├── update_translations.sh
├── locale/
├── tests/
├── pkgbuild/
├── big-age-signal/
└── big-parental-controls/
    ├── usr/
    │   ├── bin/
    │   ├── lib/
    │   └── share/
    └── etc/
```

## Features in More Detail

### Supervised Accounts

- Create a new supervised account with safe defaults.
- Apply supervision to an existing standard account.
- Remove restrictions or fully delete an account with confirmation.
- Integrate with AccountsService and malcontent.

### Allowed Apps

- Restrict execution of selected applications using ACLs.
- Hide blocked launchers from application menus where possible.
- Batch system changes in a single privileged operation.

### Screen Time

- Define daily time quotas.
- Define one or more allowed time ranges.
- Apply PAM time rules and timer-based enforcement.

### Web Filter

- Use trusted family-safe DNS providers.
- Accept custom DNS configuration when needed.
- Store per-user settings and generate system login hooks.

### Safety and Help

- Show guidance for children in supervised sessions.
- Provide emergency and digital safety contacts.
- Surface clear errors instead of silent failures.

## Privacy and Security

This project is intentionally conservative about user data.

- No remote account is required.
- No telemetry or cloud sync is built into the app.
- Most decisions are enforced with local OS mechanisms.
- Privileged operations are isolated in a helper script run through `pkexec`.
- Sensitive actions are kept off the UI thread.

The app may expose local age-range information through D-Bus so other applications on the same device can adapt content appropriately. That information is not sent to the internet by this project.

## Dependencies

Runtime dependencies are defined in `pkgbuild/PKGBUILD` and currently include:

- Python
- PyGObject
- GTK4
- libadwaita
- malcontent
- AccountsService
- polkit
- gettext
- libappindicator-gtk3
- ACL tools

Build dependencies include:

- Rust
- Cargo

## Build and Install

### Package Build

The recommended way to build is through the package recipe:

```bash
cd pkgbuild
makepkg -si
```

This is the most realistic path because several features depend on installed paths, polkit policy files, locale files, system services, and helper scripts.

### Development Run

For UI work and fast iteration, you can run the app directly from the source tree after dependencies are installed:

```bash
python3 big-parental-controls/usr/share/biglinux/parental-controls/main.py
```

For full end-to-end validation, install the package and test on a real system session, because features such as `pkexec`, AccountsService, ACLs, PAM time rules, and `/etc` writes require system integration.

### Rust Service

The D-Bus age signal service is built separately:

```bash
cd big-age-signal
cargo build --release
```

## Testing

Run the Python test suite with:

```bash
pytest tests
```

The project includes tests for:

- i18n configuration and locale sync
- package structure
- DNS service behavior
- age signal behavior
- polkit policy presence
- resilience for corrupted configs and subprocess failures

## Localization

The project uses gettext.

### Source of Truth

- Editable translation sources live in `locale/`
- Mirrored source copies are kept in `big-parental-controls/usr/share/biglinux/parental-controls/locale/`
- Compiled runtime catalogs are written to `big-parental-controls/usr/share/locale/<lang>/LC_MESSAGES/`

### Update Translation Files

```bash
./update_translations.sh
```

This script:

1. Extracts strings from Python files and `.ui` templates.
2. Updates `.po` files with `msgmerge`.
3. Mirrors the catalogs into the app tree.
4. Rebuilds the compiled `.mo` files.

### Current Status

- `pt_BR` is currently maintained in this repository.
- The app is prepared for more languages through gettext.
- Adding a new language means creating a new `locale/<lang>.po` file and rerunning the translation script.

## Compliance Direction

The project is built around child-safety and age-appropriate design goals and references work in this direction such as:

- Brazil's ECA Digital
- UK Children's Code
- EU Digital Services Act

This repository is a technical implementation project, not legal advice.

## Roadmap and Internal Notes

Planning files currently tracked in the repository:

- `PLANNING.md`
- `NEW_PLANNING.md`

They are useful if you want to understand current engineering priorities and review history.

## Contributing

Contributions are welcome in these areas:

- GTK4/libadwaita UX improvements
- accessibility and Orca review
- new translations
- safer system integration patterns
- tests for real-world Linux edge cases
- distro packaging and deployment polish

When contributing, prefer minimal patches, explicit error handling, and native Linux solutions over adding heavy dependencies.

## License

GPL-3.0-or-later.

## Maintainer

Bruno Goncalves and the BigLinux team.
