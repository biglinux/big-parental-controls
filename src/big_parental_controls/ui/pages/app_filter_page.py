"""App filter page — manage per-user app access."""

from __future__ import annotations

import json
import os
import shutil
from typing import TYPE_CHECKING, Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from big_parental_controls.core.constants import (
    ACL_STATE_FILE,
    GROUP_HELPER,
    WEBAPP_BLOCKS_FILE,
)
from big_parental_controls.services import desktop_hide_service
from big_parental_controls.services.accounts_service import AccountsServiceWrapper
from big_parental_controls.services.malcontent_service import MalcontentService
from big_parental_controls.utils.async_runner import run_async
from big_parental_controls.utils.i18n import setup_i18n

if TYPE_CHECKING:
    pass

_ = setup_i18n()

CATEGORY_KEYS = [
    ("ALL", _("All Categories")),
    ("INTERNET", _("Internet & Browsers")),
    ("GAMES", _("Games")),
    ("MULTIMEDIA", _("Audio & Video")),
    ("OFFICE", _("Office & Productivity")),
    ("DEVELOPMENT", _("Development")),
    ("SYSTEM", _("System & Settings")),
    ("UTILITIES", _("Utilities")),
    ("OTHERS", _("Others")),
]

STATUS_KEYS = [
    ("ALL", _("All Statuses")),
    ("ALLOWED", _("Allowed Only")),
    ("BLOCKED", _("Blocked Only")),
]

PROTECTED_BASENAMES: set[str] = {
    "browser-tweaks-chromium-base",
    "big-webapps-exec",
    "env",
    "sh",
    "bash",
    "zsh",
    "dash",
    "pkexec",
    "sudo",
    "xdg-open",
    "python",
    "python3",
    "systemctl",
    "systemd",
    "kbuildsycoca6",
    "update-desktop-database",
}

PROTECTED_BINARIES: set[str] = {
    "/usr/local/bin/browser-tweaks-chromium-base",
    "/usr/bin/big-webapps-exec",
    "/usr/sbin/big-webapps-exec",
    "/usr/bin/env",
    "/usr/sbin/env",
    "/bin/env",
    "/usr/bin/sh",
    "/bin/sh",
    "/usr/bin/bash",
    "/bin/bash",
    "/usr/bin/pkexec",
    "/usr/bin/sudo",
    "/usr/bin/xdg-open",
    "/usr/sbin/xdg-open",
}


def is_protected_binary(path: str) -> bool:
    """Check whether a path points to a protected system binary that must never have ACLs."""
    if not path or path == "/dev/null":
        return True
    if path in PROTECTED_BINARIES:
        return True
    base = os.path.basename(path)
    if base in PROTECTED_BASENAMES or any(base.startswith(f"{p}.") for p in PROTECTED_BASENAMES):
        return True
    try:
        real = os.path.realpath(path)
        if real in PROTECTED_BINARIES:
            return True
        real_base = os.path.basename(real)
        if real_base in PROTECTED_BASENAMES or any(real_base.startswith(f"{p}.") for p in PROTECTED_BASENAMES):
            return True
    except Exception:
        pass
    return False


def extract_real_executable(app_info: object) -> str:
    """Extract the actual target binary from an AppInfo, unwrapping env, pkexec, etc."""
    cmd = ""
    if hasattr(app_info, "get_commandline"):
        try:
            cmd = app_info.get_commandline() or ""
        except Exception:
            cmd = ""

    if cmd:
        import shlex
        try:
            tokens = shlex.split(cmd)
        except Exception:
            tokens = cmd.split()

        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            base = os.path.basename(token)
            if base in ("env", "pkexec", "sudo", "prime-run"):
                idx += 1
                while idx < len(tokens):
                    t = tokens[idx]
                    if t.startswith("-") or ("=" in t and not t.startswith("/")):
                        idx += 1
                    else:
                        break
                continue
            break

        if idx < len(tokens):
            candidate = tokens[idx]
            if candidate.startswith("/"):
                return candidate
            which_cand = shutil.which(candidate)
            if which_cand:
                return which_cand

    exe = ""
    if hasattr(app_info, "get_executable"):
        try:
            exe = app_info.get_executable() or ""
        except Exception:
            exe = ""

    if exe:
        return exe if exe.startswith("/") else (shutil.which(exe) or exe)
    return ""


def is_webapp_or_pwa(app_info: object) -> bool:
    """Check if an app is a PWA, WebApp, or web shortcut.

    PWAs and web shortcuts share browsers/utilities and must be blocked via desktop
    hiding, never by modifying filesystem ACLs on the engine or shared tool.
    """
    cmd = ""
    if hasattr(app_info, "get_commandline"):
        try:
            cmd = app_info.get_commandline() or ""
        except Exception:
            cmd = ""

    if "--app=" in cmd or "--app-id=" in cmd:
        return True

    exe = ""
    if hasattr(app_info, "get_executable"):
        try:
            exe = app_info.get_executable() or ""
        except Exception:
            exe = ""
    if "big-webapps-exec" in exe or "big-webapps-exec" in cmd:
        return True

    if "xdg-open" in exe or "xdg-open" in cmd:
        return True

    app_id = ""
    if hasattr(app_info, "get_id"):
        try:
            app_id = app_info.get_id() or ""
        except Exception:
            app_id = ""

    if app_id.startswith(("brave-", "chrome-", "chromium-")):
        if app_id not in ("brave-browser.desktop", "google-chrome.desktop", "chromium.desktop"):
            return True

    return False


def resolve_all_related_binaries(exe_path: str) -> list[str]:
    """Resolve an executable and all its wrapper/underlying binaries.

    Handles BigLinux /usr/local/bin wrappers and package backend binaries
    (e.g., /usr/local/bin/brave, /usr/bin/brave, /usr/lib/brave-browser/brave).
    """
    resolved_paths: set[str] = set()
    if not exe_path or exe_path == "/dev/null":
        return []

    resolved_paths.add(exe_path)
    if os.path.exists(exe_path):
        real = os.path.realpath(exe_path)
        if real != "/dev/null":
            resolved_paths.add(real)

    basename = os.path.basename(exe_path)
    candidates = [
        f"/usr/local/bin/{basename}",
        f"/usr/bin/{basename}",
        f"/usr/sbin/{basename}",
    ]
    if "brave" in basename:
        candidates.extend([
            "/usr/lib/brave-browser/brave",
            "/usr/lib/brave-browser/brave-browser",
            "/usr/bin/brave",
            "/usr/local/bin/brave",
        ])
    elif "chrome" in basename:
        candidates.extend([
            "/opt/google/chrome/chrome",
            "/opt/google/chrome/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/local/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
        ])
    elif "chromium" in basename:
        candidates.extend([
            "/usr/lib/chromium/chromium",
            "/usr/bin/chromium",
        ])
    elif "libreoffice" in basename or "soffice" in basename:
        candidates.extend([
            "/usr/local/bin/libreoffice",
            "/usr/bin/libreoffice",
            "/usr/lib/libreoffice/program/soffice.bin",
        ])

    for c in candidates:
        if os.path.exists(c) and c != "/dev/null":
            resolved_paths.add(c)
            real_c = os.path.realpath(c)
            if real_c != "/dev/null":
                resolved_paths.add(real_c)

    for p in list(resolved_paths):
        try:
            if os.path.isfile(p) and os.access(p, os.R_OK):
                with open(p, "rb") as f:
                    first_line = f.readline()
                    if first_line.startswith(b"#!"):
                        content = f.read().decode("utf-8", errors="ignore")
                        for line in content.splitlines():
                            line = line.strip()
                            if line.startswith("exec ") or "exec " in line:
                                for token in line.split():
                                    if (
                                        token.startswith("/")
                                        and os.path.exists(token)
                                        and token != "/dev/null"
                                    ):
                                        if os.path.isfile(token) and os.access(token, os.X_OK):
                                            resolved_paths.add(token)
                                            real_t = os.path.realpath(token)
                                            if real_t != "/dev/null":
                                                resolved_paths.add(real_t)
        except Exception:
            pass

    return sorted(
        p for p in resolved_paths
        if os.path.exists(p) and p != "/dev/null" and not is_protected_binary(p)
    )


def categorize_app_info(app_info: object) -> str:
    """Return standard category key for an AppInfo."""
    raw_cats = ""
    if hasattr(app_info, "get_categories"):
        try:
            raw_cats = app_info.get_categories() or ""
        except Exception:
            raw_cats = ""

    raw_cats_lower = raw_cats.lower()
    if "game" in raw_cats_lower:
        return "GAMES"
    if any(k in raw_cats_lower for k in ["webbrowser", "network", "chat", "email", "instantmessaging"]):
        return "INTERNET"
    if any(k in raw_cats_lower for k in ["audiovideo", "audio", "video", "player", "recorder", "music"]):
        return "MULTIMEDIA"
    if any(k in raw_cats_lower for k in ["office", "wordprocessor", "spreadsheet"]):
        return "OFFICE"
    if any(k in raw_cats_lower for k in ["development", "ide", "debugger"]):
        return "DEVELOPMENT"
    if any(k in raw_cats_lower for k in ["system", "settings", "packagemanager", "terminalemulator"]):
        return "SYSTEM"
    if any(k in raw_cats_lower for k in ["utility", "archiving", "calculator", "texteditor"]):
        return "UTILITIES"
    return "OTHERS"


class AppFilterPage(Gtk.Box):
    """Page for managing per-user app access control."""

    def __init__(self, user: object | None = None, **kwargs: object) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0, **kwargs)
        self._accounts = AccountsServiceWrapper()
        try:
            self._malcontent = MalcontentService()
        except GLib.Error:
            self._malcontent = None
        self._initial_user = user
        self._selected_uid: int | None = None
        self._selected_username: str | None = None
        self._pending_changes: dict[str, bool] = {}
        self._app_rows: dict[str, Adw.SwitchRow] = {}
        self._app_metadata: dict[str, dict[str, Any]] = {}
        self._filter_text: str = ""
        self._selected_category: str = "ALL"
        self._selected_status: str = "ALL"
        self._supervised_users: list[Any] = []
        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(680)

        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        inner.set_margin_top(20)
        inner.set_margin_bottom(24)
        inner.set_margin_start(20)
        inner.set_margin_end(20)

        # User selector
        selector_group = Adw.PreferencesGroup()
        self._user_combo = Adw.ComboRow()
        self._user_combo.set_title(_("User"))
        self._user_model = Gtk.StringList()
        self._user_combo.set_model(self._user_model)
        self._user_combo.connect("notify::selected", self._on_user_changed)
        selector_group.add(self._user_combo)
        inner.append(selector_group)

        # Empty state
        self._empty_status = Adw.StatusPage()
        self._empty_status.set_icon_name("application-x-executable-symbolic")
        self._empty_status.set_title(_("Select a User"))
        self._empty_status.set_description(_("Choose a supervised user to manage app access."))
        inner.append(self._empty_status)

        # Container for controls (hidden until user is chosen)
        self._controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self._controls_box.set_visible(False)

        # Search bar
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text(_("Filter apps by name or command…"))
        self._search_entry.connect("search-changed", self._on_search_changed)
        self._controls_box.append(self._search_entry)

        # Category and status filters
        filter_group = Adw.PreferencesGroup()
        filter_group.set_title(_("Filters"))

        # Category combo
        self._category_combo = Adw.ComboRow()
        self._category_combo.set_title(_("Category"))
        self._category_model = Gtk.StringList.new([name for _, name in CATEGORY_KEYS])
        self._category_combo.set_model(self._category_model)
        self._category_combo.connect("notify::selected", self._on_category_changed)
        filter_group.add(self._category_combo)

        # Status combo
        self._status_combo = Adw.ComboRow()
        self._status_combo.set_title(_("Status"))
        self._status_model = Gtk.StringList.new([name for _, name in STATUS_KEYS])
        self._status_combo.set_model(self._status_model)
        self._status_combo.connect("notify::selected", self._on_status_filter_changed)
        filter_group.add(self._status_combo)
        self._controls_box.append(filter_group)

        # Batch actions and counter bar
        batch_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        batch_bar.set_margin_top(4)

        self._counter_label = Gtk.Label(label="", xalign=0.0)
        self._counter_label.set_hexpand(True)
        self._counter_label.add_css_class("dim-label")
        batch_bar.append(self._counter_label)

        self._allow_all_btn = Gtk.Button(label=_("Allow Visible"))
        self._allow_all_btn.set_icon_name("emblem-ok-symbolic")
        self._allow_all_btn.set_tooltip_text(_("Allow all currently visible applications"))
        self._allow_all_btn.connect("clicked", self._on_allow_visible_clicked)
        batch_bar.append(self._allow_all_btn)

        self._block_all_btn = Gtk.Button(label=_("Block Visible"))
        self._block_all_btn.set_icon_name("action-unavailable-symbolic")
        self._block_all_btn.set_tooltip_text(_("Block all currently visible applications"))
        self._block_all_btn.connect("clicked", self._on_block_visible_clicked)
        batch_bar.append(self._block_all_btn)

        self._controls_box.append(batch_bar)

        # Apps list group
        self._apps_group = Adw.PreferencesGroup()
        self._apps_group.set_title(_("Installed Applications"))
        self._controls_box.append(self._apps_group)

        # Apply button
        self._apply_btn = Gtk.Button(label=_("Apply Changes"))
        self._apply_btn.add_css_class("suggested-action")
        self._apply_btn.set_sensitive(False)
        self._apply_btn.set_halign(Gtk.Align.END)
        self._apply_btn.connect("clicked", self._on_apply)
        self._controls_box.append(self._apply_btn)

        inner.append(self._controls_box)

        clamp.set_child(inner)
        scrolled.set_child(clamp)
        toolbar.set_content(scrolled)
        self.append(toolbar)

        self._populate_user_combo()

    def _populate_user_combo(self) -> None:
        """Populate user dropdown with supervised users."""
        self._supervised_users = []
        self._user_model.splice(0, self._user_model.get_n_items(), [])

        preselect_idx = 0
        for user in self._accounts.list_users():
            if self._accounts.is_supervised(user):
                if (
                    self._initial_user is not None
                    and user.get_uid() == self._initial_user.get_uid()
                ):
                    preselect_idx = len(self._supervised_users)
                self._supervised_users.append(user)
                label = user.get_real_name() or user.get_user_name()
                self._user_model.append(label)

        if self._supervised_users:
            self._user_combo.set_selected(preselect_idx)

    def _on_user_changed(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self._supervised_users):
            return

        user = self._supervised_users[idx]
        self._selected_uid = user.get_uid()
        self._selected_username = user.get_user_name()
        self._empty_status.set_visible(False)
        self._controls_box.set_visible(True)
        self._pending_changes.clear()
        self._apply_btn.set_sensitive(False)
        self._filter_text = ""
        self._selected_category = "ALL"
        self._selected_status = "ALL"
        self._search_entry.set_text("")
        self._category_combo.set_selected(0)
        self._status_combo.set_selected(0)
        self._load_apps()

    def _load_apps(self) -> None:
        """Load installed apps and their blocked status."""
        while True:
            child = self._apps_group.get_first_child()
            if child is None:
                break
            if not isinstance(child, Adw.SwitchRow):
                child = child.get_next_sibling()
                if child is None:
                    break
                continue
            self._apps_group.remove(child)

        self._app_rows.clear()
        self._app_metadata.clear()

        if self._selected_uid is None:
            return

        # Read ACL state so filesystem-blocked apps show correctly
        acl_blocked: set[str] = set()
        try:
            with open(ACL_STATE_FILE) as _f:
                _state = json.load(_f)
            acl_blocked = set(_state.get(self._selected_username or "", []))
        except (OSError, json.JSONDecodeError):
            pass

        # Read WebApp blocks state
        webapp_blocked: set[str] = set()
        try:
            with open(WEBAPP_BLOCKS_FILE) as _f:
                _wstate = json.load(_f)
            webapp_blocked = set(_wstate.get(self._selected_username or "", []))
        except (OSError, json.JSONDecodeError):
            pass

        shown_paths: set[str] = set()

        for app_info in Gio.AppInfo.get_all():
            if not app_info.should_show():
                continue
            abs_exe = extract_real_executable(app_info)
            if not abs_exe:
                continue

            name = app_info.get_display_name()
            app_id = app_info.get_id() or abs_exe
            category = categorize_app_info(app_info)
            is_webapp = is_webapp_or_pwa(app_info)

            if is_webapp:
                # WebApps are blocked via desktop hiding, NOT filesystem ACLs on shared browser
                allowed = app_id not in webapp_blocked
                bin_chain: list[str] = []
            else:
                bin_chain = resolve_all_related_binaries(abs_exe)
                if any(b in acl_blocked for b in bin_chain):
                    allowed = False
                elif self._malcontent:
                    try:
                        allowed = self._malcontent.is_appinfo_allowed(self._selected_uid, app_info)
                    except Exception:
                        allowed = True
                else:
                    allowed = True

            row = Adw.SwitchRow()
            row.set_title(name)
            subtitle = _("Web Application") if is_webapp else abs_exe
            row.set_subtitle(subtitle)
            row.set_active(allowed)
            row.connect("notify::active", self._on_app_toggled, app_id)

            icon = app_info.get_icon()
            if icon:
                img = Gtk.Image.new_from_gicon(icon)
                img.set_pixel_size(32)
                row.add_prefix(img)

            self._apps_group.add(row)
            self._app_rows[app_id] = row
            self._app_metadata[app_id] = {
                "name": name,
                "path": abs_exe,
                "app_id": app_id,
                "category": category,
                "is_webapp": is_webapp,
                "binary_chain": bin_chain,
                "row": row,
                "initial_allowed": allowed,
            }
            if not is_webapp:
                shown_paths.update(bin_chain)

        # Show ACL-blocked apps that have no visible .desktop entry
        for blocked_path in sorted(acl_blocked - shown_paths):
            if is_protected_binary(blocked_path):
                continue
            name = shutil.which(blocked_path) and blocked_path.split("/")[-1] or blocked_path
            app_id = blocked_path
            category = "OTHERS"
            row = Adw.SwitchRow()
            row.set_title(name)
            row.set_subtitle(blocked_path)
            row.set_active(False)
            row.connect("notify::active", self._on_app_toggled, app_id)
            img = Gtk.Image.new_from_icon_name("application-x-executable-symbolic")
            img.set_pixel_size(32)
            row.add_prefix(img)

            self._apps_group.add(row)
            self._app_rows[app_id] = row
            self._app_metadata[app_id] = {
                "name": name,
                "path": blocked_path,
                "app_id": app_id,
                "category": category,
                "is_webapp": False,
                "binary_chain": [blocked_path],
                "row": row,
                "initial_allowed": False,
            }

        self._filter_and_update_view()

    def _matches_filter(self, meta: dict[str, Any]) -> bool:
        """Check if an app matches current search, category, and status filters."""
        name = meta["name"]
        path = meta["path"]
        category = meta["category"]
        row: Adw.SwitchRow = meta["row"]
        active = row.get_active()

        # Text filter
        if self._filter_text:
            needle = self._filter_text.lower()
            if needle not in name.lower() and needle not in path.lower():
                return False

        # Category filter
        if self._selected_category != "ALL" and category != self._selected_category:
            return False

        # Status filter
        if self._selected_status == "ALLOWED" and not active:
            return False
        if self._selected_status == "BLOCKED" and active:
            return False

        return True

    def _filter_and_update_view(self) -> None:
        """Apply filters and update counters."""
        total = len(self._app_metadata)
        allowed_count = 0
        blocked_count = 0
        visible_count = 0

        for meta in self._app_metadata.values():
            row: Adw.SwitchRow = meta["row"]
            is_active = row.get_active()
            if is_active:
                allowed_count += 1
            else:
                blocked_count += 1

            visible = self._matches_filter(meta)
            row.set_visible(visible)
            if visible:
                visible_count += 1

        self._counter_label.set_label(
            _("Showing {visible} of {total} • {allowed} allowed, {blocked} blocked").format(
                visible=visible_count,
                total=total,
                allowed=allowed_count,
                blocked=blocked_count,
            )
        )
        self._allow_all_btn.set_sensitive(visible_count > 0)
        self._block_all_btn.set_sensitive(visible_count > 0)

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._filter_text = entry.get_text().strip()
        self._filter_and_update_view()

    def _on_category_changed(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(CATEGORY_KEYS):
            self._selected_category = CATEGORY_KEYS[idx][0]
            self._filter_and_update_view()

    def _on_status_filter_changed(self, combo: Adw.ComboRow, _pspec: object) -> None:
        idx = combo.get_selected()
        if 0 <= idx < len(STATUS_KEYS):
            self._selected_status = STATUS_KEYS[idx][0]
            self._filter_and_update_view()

    def _on_allow_visible_clicked(self, _button: Gtk.Button) -> None:
        """Allow all currently visible apps."""
        for meta in self._app_metadata.values():
            row: Adw.SwitchRow = meta["row"]
            if row.get_visible() and not row.get_active():
                row.set_active(True)
        self._filter_and_update_view()

    def _on_block_visible_clicked(self, _button: Gtk.Button) -> None:
        """Block all currently visible apps."""
        for meta in self._app_metadata.values():
            row: Adw.SwitchRow = meta["row"]
            if row.get_visible() and row.get_active():
                row.set_active(False)
        self._filter_and_update_view()

    def _on_app_toggled(
        self, row: Adw.SwitchRow, _pspec: object, app_id: str
    ) -> None:
        new_active = row.get_active()
        self._pending_changes[app_id] = new_active

        # Check if pending changes actually differ from initial
        has_real_changes = False
        for aid, pending_state in self._pending_changes.items():
            meta = self._app_metadata.get(aid)
            if meta and meta["initial_allowed"] != pending_state:
                has_real_changes = True
                break

        self._apply_btn.set_sensitive(has_real_changes)
        self._filter_and_update_view()

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply pending changes via ACL batch and Desktop Hiding."""
        if not self._selected_username or not self._pending_changes:
            return

        username = self._selected_username

        block_binaries: set[str] = set()
        unblock_binaries: set[str] = set()
        block_desktops: set[str] = set()
        unblock_desktops: set[str] = set()

        for app_id, allowed in self._pending_changes.items():
            meta = self._app_metadata.get(app_id)
            if not meta:
                continue

            if allowed:
                unblock_desktops.add(app_id)
                if not meta["is_webapp"]:
                    chains = meta["binary_chain"] or [meta["path"]]
                    for b in chains:
                        if not is_protected_binary(b):
                            unblock_binaries.add(b)
            else:
                block_desktops.add(app_id)
                if not meta["is_webapp"]:
                    chains = meta["binary_chain"] or [meta["path"]]
                    for b in chains:
                        if not is_protected_binary(b):
                            block_binaries.add(b)

        block_csv = ",".join(sorted(block_binaries))
        unblock_csv = ",".join(sorted(unblock_binaries))
        block_desktop_csv = ",".join(sorted(block_desktops))
        unblock_desktop_csv = ",".join(sorted(unblock_desktops))

        def do_apply() -> None:
            import subprocess

            subprocess.run(
                [
                    "pkexec",
                    GROUP_HELPER,
                    "acl-batch",
                    username,
                    block_csv,
                    unblock_csv,
                    block_desktop_csv,
                    unblock_desktop_csv,
                ],
                check=True,
                timeout=60,
            )

        def on_done(_result: object) -> None:
            # Sync initial states to new values
            for app_id, allowed in self._pending_changes.items():
                meta = self._app_metadata.get(app_id)
                if meta:
                    meta["initial_allowed"] = allowed
            self._pending_changes.clear()
            self._apply_btn.set_sensitive(False)
            self._filter_and_update_view()
            self._show_success(_("App access updated."))

        def on_error(exc: Exception) -> None:
            self._show_error(str(exc))

        run_async(do_apply, on_done, on_error)

    def _show_success(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_toast"):
            window.show_toast(message)

    def _show_error(self, message: str) -> None:
        window = self.get_root()
        if hasattr(window, "show_error"):
            window.show_error(message)

    def refresh(self) -> None:
        """Refresh user list and app list."""
        self._populate_user_combo()
