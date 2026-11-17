//! Unified D-Bus system daemon: `br.com.biglinux.ParentalDaemon`
//!
//! Combines two interfaces:
//! - `br.com.biglinux.AgeSignal1`    — age range of the calling user
//! - `br.com.biglinux.ParentalMonitor1` — process monitoring for supervised users
//! - `br.com.biglinux.TimeExtra1`    — extra minutes approved by a parent (PIN)
//!
//! Runs on the **system bus** so it can read /proc for any UID.
//! Write methods (EnableUser/DisableUser) restricted to `wheel` group via D-Bus policy.

use std::collections::HashMap;
use std::ffi::CString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;

use chrono::{Local, Datelike, Timelike};
use nix::sys::signal::{kill, Signal};
use nix::unistd::{Group, Pid, Uid, User};
use serde::{Deserialize, Serialize};
use tokio::sync::Mutex;
use tokio::time::{interval, Duration};
use zbus::{interface, message::Header, Connection, Result};

const SUPERVISED_GROUP: &str = "supervised";
const VERSION: &str = "1.0";
const DATA_DIR: &str = "/var/lib/big-parental-controls";
const ACTIVITY_DIR: &str = "/var/lib/big-parental-controls/activity";
const MONITORED_FILE: &str = "/var/lib/big-parental-controls/monitored-users.json";
const TIME_LIMITS_FILE: &str = "/var/lib/big-parental-controls/time-limits.json";
const TIME_USAGE_FILE: &str = "/var/lib/big-parental-controls/time-state.json";
const TIME_CONF_FILE: &str = "/etc/security/time.conf";
const POLL_INTERVAL_SECS: u64 = 60;

/// Processes to ignore (system daemons, not user-facing apps).
const IGNORED_PROCESSES: &[&str] = &[
    "systemd",
    "dbus-broker",
    "dbus-daemon",
    "pipewire",
    "pipewire-pulse",
    "wireplumber",
    "kwin_wayland",
    "ksmserver",
    "plasmashell",
    "kded6",
    "xdg-desktop-portal",
    "xdg-document-portal",
    "xdg-permission-store",
    "gvfsd",
    "gvfsd-fuse",
    "at-spi-bus-launcher",
    "at-spi2-registryd",
    "ssh-agent",
    "gpg-agent",
    "polkitd",
    "Xwayland",
    "fcitx5",
    "kglobalaccel6",
    "kactivitymanagerd",
    "baloo_file",
    "kscreen_backend_launcher",
    "big-parental-daemon",
];

// ── Data types ───────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
struct MonitoredUser {
    username: String,
    uid: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Snapshot {
    t: String,         // "HH:MM"
    p: Vec<String>,    // process names
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DailyLog {
    date: String,
    snapshots: Vec<Snapshot>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct MonitoredUsersFile {
    monitored: Vec<MonitoredUser>,
}

#[derive(Debug)]
struct MonitorState {
    monitored_users: Vec<MonitoredUser>,
}

impl MonitorState {
    fn new() -> Self {
        let monitored_users = load_monitored_users();
        Self { monitored_users }
    }
}

// ── AgeSignal interface ──────────────────────────────────────

struct AgeSignal {
    connection: Connection,
}

/// Check if a given UID belongs to the `supervised` group.
fn is_uid_supervised(uid: Uid) -> bool {
    uid_in_group(uid, SUPERVISED_GROUP)
}

/// Check if a given UID belongs to `group` (primary or supplementary).
fn uid_in_group(uid: Uid, group: &str) -> bool {
    let user = match User::from_uid(uid) {
        Ok(Some(u)) => u,
        _ => return false,
    };

    let gid = match Group::from_name(group) {
        Ok(Some(g)) => g.gid,
        _ => return false,
    };

    if user.gid == gid {
        return true;
    }

    let cname = match CString::new(user.name.as_str()) {
        Ok(c) => c,
        Err(_) => return false,
    };
    match nix::unistd::getgrouplist(&cname, user.gid) {
        Ok(groups) => groups.contains(&gid),
        Err(_) => false,
    }
}

/// Get the UID of the D-Bus caller via GetConnectionUnixUser.
async fn get_caller_uid(conn: &Connection, header: &Header<'_>) -> Option<Uid> {
    let sender = header.sender()?.to_owned();
    let proxy = zbus::fdo::DBusProxy::new(conn).await.ok()?;
    let uid = proxy.get_connection_unix_user(sender.into()).await.ok()?;
    Some(Uid::from_raw(uid))
}

const USER_PROFILES_FILE: &str = "/var/lib/big-parental-controls/user-profiles.json";

/// Read the ECA Digital age range for a given username from user-profiles.json.
/// Returns "18+" when there is no profile entry for that user.
fn get_stored_age_range(username: &str) -> String {
    let data = match fs::read_to_string(USER_PROFILES_FILE) {
        Ok(d) => d,
        Err(_) => return "18+".into(),
    };
    let map: serde_json::Value = match serde_json::from_str(&data) {
        Ok(v) => v,
        Err(_) => return "18+".into(),
    };
    map.get(username)
        .and_then(|entry| entry.get("age_range"))
        .and_then(|v| v.as_str())
        .map(|s| match s {
            "0-12" | "13-15" | "16-17" | "18+" => s.to_string(),
            _ => "18+".to_string(),
        })
        .unwrap_or_else(|| "18+".into())
}

#[interface(name = "br.com.biglinux.AgeSignal1")]
impl AgeSignal {
    /// Returns "child" or "adult" based on the calling process user.
    async fn get_age_range(&self, #[zbus(header)] header: Header<'_>) -> String {
        match get_caller_uid(&self.connection, &header).await {
            Some(uid) if is_uid_supervised(uid) => "child".into(),
            _ => "adult".into(),
        }
    }

    /// Returns true if the calling user is supervised (under 18).
    async fn is_minor(&self, #[zbus(header)] header: Header<'_>) -> bool {
        match get_caller_uid(&self.connection, &header).await {
            Some(uid) => is_uid_supervised(uid),
            None => false,
        }
    }

    /// Returns the ECA Digital age range for a given UID:
    /// "0-12", "13-15", "16-17", or "18+" (default when not configured).
    async fn get_age_group(&self, uid: u32) -> String {
        let user = match User::from_uid(Uid::from_raw(uid)) {
            Ok(Some(u)) => u,
            _ => return "18+".into(),
        };
        get_stored_age_range(&user.name)
    }

    #[zbus(property)]
    fn version(&self) -> &str {
        VERSION
    }
}

// ── TimeExtra interface (extra minutes approved by a parent) ──

const TIME_EXTRA_FILE: &str = "/var/lib/big-parental-controls/time-extra.json";
const PARENT_PIN_FILE: &str = "/var/lib/big-parental-controls/parent-pin";
const EXTRA_STEP_MIN: u32 = 15;
const EXTRA_MAX_REQUESTS: u32 = 3;
const EXTRA_MAX_GRANT_MIN: u32 = 240;
const PIN_MAX_FAILS: u32 = 3;
const PIN_LOCK_SECS: u64 = 15 * 60;
const PIN_HASH_ROUNDS: u32 = 20_000;

/// Today's extra time per user: (granted minutes, child requests accepted).
fn load_time_extra(today: &str) -> HashMap<String, (u32, u32)> {
    let mut out = HashMap::new();
    let Ok(data) = fs::read_to_string(TIME_EXTRA_FILE) else {
        return out;
    };
    let Ok(val) = serde_json::from_str::<serde_json::Value>(&data) else {
        return out;
    };
    if val["_date"].as_str() != Some(today) {
        return out;
    }
    if let Some(obj) = val.as_object() {
        for (k, v) in obj {
            if k == "_date" {
                continue;
            }
            let get = |f: &str| v.get(f).and_then(|n| n.as_u64()).unwrap_or(0) as u32;
            out.insert(k.clone(), (get("minutes"), get("requests")));
        }
    }
    out
}

fn save_time_extra(today: &str, extra: &HashMap<String, (u32, u32)>) {
    let mut obj = serde_json::Map::new();
    obj.insert("_date".into(), serde_json::Value::String(today.into()));
    for (k, (minutes, requests)) in extra {
        obj.insert(k.clone(), serde_json::json!({ "minutes": minutes, "requests": requests }));
    }
    if let Ok(json) = serde_json::to_string_pretty(&serde_json::Value::Object(obj)) {
        atomic_write(Path::new(TIME_EXTRA_FILE), json.as_bytes());
    }
}

fn to_hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Iterated, salted SHA-256 of the PIN (hex).
fn hash_pin(salt: &str, pin: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new().chain_update(salt).chain_update(pin).finalize();
    for _ in 0..PIN_HASH_ROUNDS {
        h = Sha256::new().chain_update(h).chain_update(salt).finalize();
    }
    to_hex(&h)
}

fn valid_pin_format(pin: &str) -> bool {
    (4..=8).contains(&pin.len()) && pin.chars().all(|c| c.is_ascii_digit())
}

/// `Some(true/false)` = PIN checked; `None` = no parent PIN configured.
fn check_pin(pin: &str) -> Option<bool> {
    let stored = fs::read_to_string(PARENT_PIN_FILE).ok()?;
    let (salt, hash) = stored.trim().split_once(':')?;
    let candidate = hash_pin(salt, pin);
    // Constant-time comparison.
    let diff = candidate
        .bytes()
        .zip(hash.bytes())
        .fold(candidate.len() ^ hash.len(), |acc, (a, b)| acc | usize::from(a ^ b));
    Some(diff == 0)
}

fn store_pin(pin: &str) -> bool {
    let mut salt = [0u8; 16];
    let Ok(mut f) = fs::File::open("/dev/urandom") else {
        return false;
    };
    if std::io::Read::read_exact(&mut f, &mut salt).is_err() {
        return false;
    }
    let salt = to_hex(&salt);
    let line = format!("{salt}:{}\n", hash_pin(&salt, pin));
    let tmp = Path::new(PARENT_PIN_FILE).with_extension("tmp");
    {
        use std::os::unix::fs::OpenOptionsExt;
        let Ok(mut out) = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&tmp)
        else {
            return false;
        };
        if std::io::Write::write_all(&mut out, line.as_bytes()).is_err() {
            return false;
        }
    }
    fs::rename(&tmp, PARENT_PIN_FILE).is_ok()
}

/// Daily quota of `username` in minutes (0 = none).
fn daily_quota(username: &str) -> u32 {
    load_time_limits()
        .get(username)
        .and_then(|c| c.get("daily_minutes"))
        .and_then(|v| v.as_u64())
        .unwrap_or(0) as u32
}

/// Per-child "extra time" settings, set by the parent in the app
/// (`time-limits.json` → `<user>.extra`). Defaults keep the original behaviour.
struct ExtraSettings {
    /// Minutes granted per accepted request.
    step: u32,
    /// Child requests allowed per day (0 = feature disabled).
    max_requests: u32,
    /// The extra minutes also push the end of the allowed period.
    extend_schedule: bool,
}

fn extra_settings_of(cfg: Option<&serde_json::Value>) -> ExtraSettings {
    let e = cfg.and_then(|c| c.get("extra"));
    let num = |k: &str, def: u64| e.and_then(|x| x.get(k)).and_then(|v| v.as_u64()).unwrap_or(def);
    ExtraSettings {
        step: (num("step", u64::from(EXTRA_STEP_MIN)) as u32).clamp(5, 120),
        max_requests: (num("max_requests", u64::from(EXTRA_MAX_REQUESTS)) as u32).min(10),
        extend_schedule: e
            .and_then(|x| x.get("extend_schedule"))
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
    }
}

fn extra_settings(username: &str) -> ExtraSettings {
    extra_settings_of(load_time_limits().get(username))
}

/// Extra minutes are useful for `username`: a daily quota, or a schedule
/// that the parent allows to be pushed.
fn extra_applies(username: &str, s: &ExtraSettings) -> bool {
    daily_quota(username) > 0 || (s.extend_schedule && schedule_remaining(username, 0).is_some())
}

/// Schedule status (see `schedule_remaining`), with the end of the allowed
/// period pushed by today's extra minutes when the parent enabled it.
fn schedule_with_extra(
    username: &str,
    limits: &HashMap<String, serde_json::Value>,
    extra: &HashMap<String, (u32, u32)>,
) -> Option<Option<u32>> {
    let base = schedule_remaining(username, 0)?;
    let bonus = extra.get(username).map_or(0, |e| e.0);
    if bonus == 0 || !extra_settings_of(limits.get(username)).extend_schedule {
        return Some(base);
    }
    let pushed = schedule_remaining(username, bonus).flatten();
    Some(match (base, pushed) {
        (Some(a), Some(b)) => Some(a.max(b)),
        (a, b) => a.or(b),
    })
}

fn today_str() -> String {
    Local::now().format("%Y-%m-%d").to_string()
}

/// Adds `minutes` of extra quota for today; `child` counts as a request.
fn add_extra(username: &str, minutes: u32, child: bool) {
    let today = today_str();
    let mut extra = load_time_extra(&today);
    let e = extra.entry(username.to_string()).or_insert((0, 0));
    e.0 += minutes;
    if child {
        e.1 += 1;
    }
    save_time_extra(&today, &extra);
}

/// Caller is root or an administrator (`wheel`).
async fn caller_is_admin(conn: &Connection, header: &Header<'_>) -> bool {
    match get_caller_uid(conn, header).await {
        Some(uid) => uid.is_root() || uid_in_group(uid, "wheel"),
        None => false,
    }
}

struct TimeExtra {
    connection: Connection,
    /// Failed PIN attempts per user: (count, locked until).
    fails: Mutex<HashMap<String, (u32, Option<std::time::Instant>)>>,
}

#[interface(name = "br.com.biglinux.TimeExtra1")]
impl TimeExtra {
    /// Called by a supervised user: asks for more minutes (per-child setting,
    /// 15 by default), validated by the parent PIN typed on the spot.
    /// Returns "ok:<minutes>", "bad_pin", "locked:<minutes>", "max",
    /// "disabled", "no_pin", "no_limit" or "denied".
    async fn request_extra(&self, pin: String, #[zbus(header)] header: Header<'_>) -> String {
        let Some(uid) = get_caller_uid(&self.connection, &header).await else {
            return "denied".into();
        };
        if !is_uid_supervised(uid) {
            return "denied".into();
        }
        let Ok(Some(user)) = User::from_uid(uid) else {
            return "denied".into();
        };
        let name = user.name;
        let settings = extra_settings(&name);
        if settings.max_requests == 0 {
            return "disabled".into();
        }
        if !extra_applies(&name, &settings) {
            return "no_limit".into();
        }
        let today = today_str();
        if load_time_extra(&today).get(&name).map_or(0, |e| e.1) >= settings.max_requests {
            return "max".into();
        }
        let mut fails = self.fails.lock().await;
        let entry = fails.entry(name.clone()).or_insert((0, None));
        if let Some(until) = entry.1 {
            let now = std::time::Instant::now();
            if now < until {
                let left = (until - now).as_secs().div_ceil(60);
                return format!("locked:{left}");
            }
            *entry = (0, None);
        }
        match check_pin(&pin) {
            None => "no_pin".into(),
            Some(false) => {
                entry.0 += 1;
                eprintln!("Extra time for {name}: wrong PIN ({}/{PIN_MAX_FAILS})", entry.0);
                if entry.0 >= PIN_MAX_FAILS {
                    entry.1 = Some(
                        std::time::Instant::now() + Duration::from_secs(PIN_LOCK_SECS),
                    );
                    return format!("locked:{}", PIN_LOCK_SECS / 60);
                }
                "bad_pin".into()
            }
            Some(true) => {
                *entry = (0, None);
                add_extra(&name, settings.step, true);
                eprintln!("Extra time for {name}: +{} min (parent PIN)", settings.step);
                format!("ok:{}", settings.step)
            }
        }
    }

    /// Parent side (wheel only): grants `minutes` extra minutes today.
    async fn grant_extra(
        &self,
        username: String,
        minutes: u32,
        #[zbus(header)] header: Header<'_>,
    ) -> String {
        if !caller_is_admin(&self.connection, &header).await {
            return "denied".into();
        }
        if minutes == 0 || minutes > EXTRA_MAX_GRANT_MIN {
            return "invalid".into();
        }
        if !extra_applies(&username, &extra_settings(&username)) {
            return "no_limit".into();
        }
        add_extra(&username, minutes, false);
        eprintln!("Extra time for {username}: +{minutes} min (granted by a parent)");
        "ok".into()
    }

    /// True when a parent PIN is configured (never reveals anything else).
    async fn has_parent_pin(&self) -> bool {
        Path::new(PARENT_PIN_FILE).exists()
    }

    /// Parent side (wheel only): sets the parent PIN (4 to 8 digits).
    async fn set_parent_pin(&self, pin: String, #[zbus(header)] header: Header<'_>) -> bool {
        if !caller_is_admin(&self.connection, &header).await || !valid_pin_format(&pin) {
            return false;
        }
        store_pin(&pin)
    }
}

// ── ParentalMonitor interface ────────────────────────────────

struct ParentalMonitor {
    state: Arc<Mutex<MonitorState>>,
}

#[interface(name = "br.com.biglinux.ParentalMonitor1")]
impl ParentalMonitor {
    /// Enable monitoring for a supervised user (wheel-only via D-Bus policy).
    async fn enable_user(&self, username: String, uid: u32) -> bool {
        let mut state = self.state.lock().await;
        if state.monitored_users.iter().any(|u| u.username == username) {
            return true; // already monitored
        }

        // Ensure activity directory exists
        let user_dir = Path::new(ACTIVITY_DIR).join(&username);
        if let Err(e) = fs::create_dir_all(&user_dir) {
            eprintln!("Failed to create activity dir for {username}: {e}");
            return false;
        }

        state.monitored_users.push(MonitoredUser {
            username,
            uid,
        });
        save_monitored_users(&state.monitored_users);
        true
    }

    /// Disable monitoring for a user.
    async fn disable_user(&self, username: String) -> bool {
        let mut state = self.state.lock().await;
        let before = state.monitored_users.len();
        state.monitored_users.retain(|u| u.username != username);
        let removed = state.monitored_users.len() < before;
        if removed {
            save_monitored_users(&state.monitored_users);
        }
        removed
    }

    /// Get list of currently monitored usernames.
    async fn get_monitored_users(&self) -> Vec<String> {
        let state = self.state.lock().await;
        state.monitored_users.iter().map(|u| u.username.clone()).collect()
    }

    /// Get app usage summary for a user (last N days). Returns JSON array.
    fn get_app_usage(&self, username: &str, days: u32) -> String {
        let logs = load_daily_logs(username, days);
        let mut usage: HashMap<String, u64> = HashMap::new();

        for log in &logs {
            for snap in &log.snapshots {
                for proc in &snap.p {
                    *usage.entry(proc.clone()).or_default() += 1;
                }
            }
        }

        let mut apps: Vec<serde_json::Value> = usage
            .into_iter()
            .map(|(app, minutes)| {
                serde_json::json!({
                    "app": app,
                    "display_name": prettify_app_name(&app),
                    "minutes": minutes,
                })
            })
            .collect();
        apps.sort_by(|a, b| {
            b["minutes"].as_u64().unwrap_or(0).cmp(&a["minutes"].as_u64().unwrap_or(0))
        });

        serde_json::to_string(&apps).unwrap_or_else(|_| "[]".into())
    }

    /// Get daily usage totals (minutes per day). Returns JSON object.
    fn get_daily_totals(&self, username: &str, days: u32) -> String {
        let logs = load_daily_logs(username, days);
        let totals: HashMap<String, usize> = logs
            .iter()
            .map(|log| (log.date.clone(), log.snapshots.len()))
            .collect();
        serde_json::to_string(&totals).unwrap_or_else(|_| "{}".into())
    }

    /// Get hourly distribution (24 slots). Returns JSON array.
    fn get_hourly_distribution(&self, username: &str, days: u32) -> String {
        let logs = load_daily_logs(username, days);
        let mut hours = [0u64; 24];

        for log in &logs {
            for snap in &log.snapshots {
                if let Some(hour) = snap.t.split(':').next().and_then(|h| h.parse::<usize>().ok()) {
                    if hour < 24 {
                        hours[hour] += 1;
                    }
                }
            }
        }

        serde_json::to_string(&hours.to_vec()).unwrap_or_else(|_| "[]".into())
    }

    /// Get recent sessions from the last log. Returns JSON array.
    fn get_recent_sessions(&self, username: &str, limit: u32) -> String {
        let logs = load_daily_logs(username, 7);
        let mut sessions: Vec<serde_json::Value> = Vec::new();

        // Group consecutive snapshots into sessions (gap > 5 minutes = new session)
        for log in logs.iter().rev() {
            let mut prev_time: Option<(u8, u8)> = None;
            let mut session_start: Option<String> = None;
            let mut session_end: Option<String> = None;
            let mut session_minutes = 0u32;

            for snap in &log.snapshots {
                let parts: Vec<&str> = snap.t.split(':').collect();
                let cur = if parts.len() == 2 {
                    (
                        parts[0].parse::<u8>().unwrap_or(0),
                        parts[1].parse::<u8>().unwrap_or(0),
                    )
                } else {
                    continue;
                };

                let gap = if let Some((ph, pm)) = prev_time {
                    (cur.0 as i16 - ph as i16) * 60 + (cur.1 as i16 - pm as i16)
                } else {
                    0
                };

                if gap > 5 || prev_time.is_none() {
                    // Flush previous session
                    if let (Some(start), Some(end)) = (&session_start, &session_end) {
                        sessions.push(serde_json::json!({
                            "date": log.date,
                            "start": start,
                            "end": end,
                            "minutes": session_minutes,
                        }));
                    }
                    session_start = Some(snap.t.clone());
                    session_minutes = 0;
                }

                session_end = Some(snap.t.clone());
                session_minutes += 1;
                prev_time = Some(cur);
            }

            // Flush last session
            if let (Some(start), Some(end)) = (&session_start, &session_end) {
                sessions.push(serde_json::json!({
                    "date": log.date,
                    "start": start,
                    "end": end,
                    "minutes": session_minutes,
                }));
            }
        }

        sessions.truncate(limit as usize);
        serde_json::to_string(&sessions).unwrap_or_else(|_| "[]".into())
    }

    #[zbus(property)]
    fn version(&self) -> &str {
        VERSION
    }
}

// ── Process scanner ──────────────────────────────────────────

fn scan_user_processes(uid: u32) -> Vec<String> {
    let mut apps = Vec::new();
    let Ok(entries) = fs::read_dir("/proc") else {
        return apps;
    };

    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if !name_str.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }

        let pid_path = entry.path();
        let status_path = pid_path.join("status");
        let Ok(status) = fs::read_to_string(&status_path) else {
            continue;
        };

        let mut proc_uid = u32::MAX;
        for line in status.lines() {
            if let Some(rest) = line.strip_prefix("Uid:\t") {
                if let Some(first) = rest.split_whitespace().next() {
                    proc_uid = first.parse().unwrap_or(u32::MAX);
                }
                break;
            }
        }
        if proc_uid != uid {
            continue;
        }

        let comm_path = pid_path.join("comm");
        let Ok(comm) = fs::read_to_string(&comm_path) else {
            continue;
        };
        let comm = comm.trim();

        if IGNORED_PROCESSES.contains(&comm) {
            continue;
        }
        if !apps.contains(&comm.to_string()) {
            apps.push(comm.to_string());
        }
    }
    apps
}

// ── Storage ──────────────────────────────────────────────────

fn load_monitored_users() -> Vec<MonitoredUser> {
    let path = Path::new(MONITORED_FILE);
    if !path.exists() {
        return Vec::new();
    }
    let Ok(data) = fs::read_to_string(path) else {
        return Vec::new();
    };
    let Ok(file): std::result::Result<MonitoredUsersFile, _> = serde_json::from_str(&data) else {
        return Vec::new();
    };
    file.monitored
}

fn save_monitored_users(users: &[MonitoredUser]) {
    let file = MonitoredUsersFile {
        monitored: users.to_vec(),
    };
    let Ok(json) = serde_json::to_string_pretty(&file) else {
        return;
    };
    let path = Path::new(MONITORED_FILE);
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    atomic_write(path, json.as_bytes());
}

fn load_daily_logs(username: &str, days: u32) -> Vec<DailyLog> {
    let base = PathBuf::from(ACTIVITY_DIR).join(username);
    let mut logs = Vec::new();
    let today = Local::now().date_naive();

    for i in 0..days {
        let date = today - chrono::Duration::days(i as i64);
        let date_str = date.format("%Y-%m-%d").to_string();
        let path = base.join(format!("{date_str}.json"));

        if let Ok(data) = fs::read_to_string(&path) {
            if let Ok(log) = serde_json::from_str::<DailyLog>(&data) {
                logs.push(log);
            }
        }
    }
    logs
}

fn append_snapshot(username: &str, processes: &[String]) {
    let now = Local::now();
    let date_str = now.format("%Y-%m-%d").to_string();
    let time_str = now.format("%H:%M").to_string();

    let user_dir = PathBuf::from(ACTIVITY_DIR).join(username);
    let _ = fs::create_dir_all(&user_dir);
    let path = user_dir.join(format!("{date_str}.json"));

    let mut log = if let Ok(data) = fs::read_to_string(&path) {
        serde_json::from_str::<DailyLog>(&data).unwrap_or(DailyLog {
            date: date_str.clone(),
            snapshots: Vec::new(),
        })
    } else {
        DailyLog {
            date: date_str,
            snapshots: Vec::new(),
        }
    };

    log.snapshots.push(Snapshot {
        t: time_str,
        p: processes.to_vec(),
    });

    if let Ok(json) = serde_json::to_string(&log) {
        atomic_write(&path, json.as_bytes());
    }
}

/// Write atomically: temp file → rename.
fn atomic_write(path: &Path, content: &[u8]) {
    let tmp = path.with_extension("tmp");
    if fs::write(&tmp, content).is_ok() {
        let _ = fs::rename(&tmp, path);
    }
}

fn prettify_app_name(comm: &str) -> String {
    // Capitalize first letter, common substitutions
    let mut name = comm.replace(['-', '_'], " ");
    if let Some(first) = name.get_mut(..1) {
        first.make_ascii_uppercase();
    }
    name
}

// ── Time enforcement ─────────────────────────────────────────

fn get_supervised_users() -> Vec<String> {
    match Group::from_name(SUPERVISED_GROUP) {
        Ok(Some(g)) => g.mem,
        _ => Vec::new(),
    }
}

fn get_active_graphical_session(username: &str) -> Option<String> {
    let state_out = Command::new("loginctl")
        .args(["show-user", username, "--property=State", "--value"])
        .output()
        .ok()?;
    if state_out.stdout.trim_ascii() != b"active" {
        return None;
    }
    let sessions_out = Command::new("loginctl")
        .args(["show-user", username, "--property=Sessions", "--value"])
        .output()
        .ok()?;
    let sessions = String::from_utf8_lossy(&sessions_out.stdout);
    for sid in sessions.split_whitespace() {
        let typ_out = Command::new("loginctl")
            .args(["show-session", sid, "--property=Type", "--value"])
            .output()
            .ok()?;
        let typ = typ_out.stdout.trim_ascii();
        if typ == b"x11" || typ == b"wayland" || typ == b"mir" {
            return Some(sid.to_string());
        }
    }
    None
}

fn terminate_session(username: &str, session_id: &str, reason: &str) {
    eprintln!("Terminating {} session {}: {}", username, session_id, reason);
    let leader_out = Command::new("loginctl")
        .args(["show-session", session_id, "--property=Leader", "--value"])
        .output();
    if let Ok(out) = leader_out {
        let pid_str = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if let Ok(pid) = pid_str.parse::<i32>() {
            let _ = kill(Pid::from_raw(pid), Signal::SIGTERM);
            return;
        }
    }
    // Fallback: let loginctl handle it
    let _ = Command::new("loginctl")
        .args(["terminate-session", session_id])
        .output();
}

/// Runs `program args` as `username` inside their graphical session.
///
/// The child gets the user's identity (setgroups + setgid + setuid, which
/// needs only CAP_SETUID/CAP_SETGID — no `sudo`), their session bus (which a
/// process spawned by the daemon would otherwise not find) and their locale.
/// Fire-and-forget: a reaper thread waits on the child so it never lingers.
fn spawn_as_user(username: &str, program: &str, args: &[&str]) {
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;

    let Ok(Some(user)) = User::from_name(username) else {
        return;
    };
    let Ok(cname) = CString::new(username) else {
        return;
    };
    let (uid, gid) = (user.uid, user.gid);
    let runtime_dir = format!("/run/user/{}", uid.as_raw());

    let mut cmd = Command::new(program);
    cmd.args(args)
        .env_clear()
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", &user.dir)
        .env("USER", username)
        .env("XDG_RUNTIME_DIR", &runtime_dir)
        .env("DBUS_SESSION_BUS_ADDRESS", format!("unix:path={runtime_dir}/bus"))
        .current_dir("/")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(lang) = user_locale(username) {
        cmd.env("LANG", lang);
    }

    // Resolve groups *before* fork (NSS lookups are not fork-safe).
    let groups = nix::unistd::getgrouplist(&cname, gid).unwrap_or_else(|_| vec![gid]);

    // SAFETY: only raw syscalls (setgroups/setgid/setuid) run between fork and exec.
    unsafe {
        cmd.pre_exec(move || {
            nix::unistd::setgroups(&groups)?;
            nix::unistd::setgid(gid)?;
            nix::unistd::setuid(uid)?;
            Ok(())
        });
    }

    match cmd.spawn() {
        Ok(mut child) => {
            std::thread::spawn(move || {
                let _ = child.wait();
            });
        }
        Err(e) => eprintln!("{program} for {username} failed: {e}"),
    }
}

/// Locale of `username` (AccountsService `Language=`, else the system
/// `LANG`), so the alert is shown in the user's language.
fn user_locale(username: &str) -> Option<String> {
    let value_of = |path: &str, key: &str| -> Option<String> {
        fs::read_to_string(path).ok()?.lines().find_map(|l| {
            l.strip_prefix(key)
                .map(|v| v.trim().trim_matches('"').to_string())
                .filter(|v| !v.is_empty())
        })
    };
    value_of(&format!("/var/lib/AccountsService/users/{username}"), "Language=")
        .or_else(|| value_of("/etc/locale.conf", "LANG="))
}

/// Alerts shown to the supervised user.
enum Msg {
    /// Daily quota: N minutes left.
    DailyWarn(u32),
    /// Daily quota (N min) reached.
    DailyDone(u32),
    /// Allowed period ends in N minutes.
    ScheduleWarn(u32),
    /// Allowed period is over.
    ScheduleEnd,
}

/// Translated alerts are rendered by `big-time-left --alert` (gettext, same
/// catalogue as the application); English is only a fallback when it is
/// missing.
const ALERT_HELPER: &str = "/usr/bin/big-time-left";

fn notify_msg(username: &str, m: Msg) {
    let (kind, n) = match m {
        Msg::DailyWarn(n) => ("daily-warn", n),
        Msg::DailyDone(n) => ("daily-done", n),
        Msg::ScheduleWarn(n) => ("schedule-warn", n),
        Msg::ScheduleEnd => ("schedule-end", 0),
    };
    let n_str = n.to_string();
    if Path::new(ALERT_HELPER).exists() {
        spawn_as_user(username, ALERT_HELPER, &["--alert", kind, &n_str]);
        return;
    }
    let (summary, body) = match kind {
        "daily-warn" => (
            format!("{n} min left"),
            format!("Your screen time for today ends in {n} min."),
        ),
        "daily-done" => (
            "Screen time is up".to_string(),
            format!("Your daily screen time of {n} min has been reached."),
        ),
        "schedule-warn" => (
            format!("{n} min left"),
            format!("The allowed hours end in {n} min."),
        ),
        _ => (
            "Allowed hours are over".to_string(),
            "The allowed usage period has ended.".to_string(),
        ),
    };
    spawn_as_user(
        username,
        "notify-send",
        &["--urgency=critical", "--icon=dialog-warning", &summary, &body],
    );
}

fn day_code_applies(code: &str, current_wday: u8) -> bool {
    if code.is_empty() || code.contains("Al") {
        return true;
    }
    if code.contains("Wk") && current_wday < 5 {
        return true;
    }
    if code.contains("Wd") && current_wday >= 5 {
        return true;
    }
    const NAMED: &[(&str, u8)] = &[
        ("Mo", 0), ("Tu", 1), ("We", 2), ("Th", 3), ("Fr", 4), ("Sa", 5), ("Su", 6),
    ];
    for (name, day) in NAMED {
        if code.contains(name) && *day == current_wday {
            return true;
        }
    }
    false
}

/// Schedule status of `username`:
/// - `None`          — no rule (no schedule restriction),
/// - `Some(None)`    — a rule exists and we are outside every allowed range,
/// - `Some(Some(n))` — inside an allowed range that ends in `n` minutes.
///
/// `shift` evaluates the rule `shift` minutes earlier (used to push the end of
/// the allowed period by the parent-approved extra minutes): the returned
/// remaining time is then counted from the pushed end.
fn schedule_remaining(username: &str, shift: u32) -> Option<Option<u32>> {
    let conf = Path::new(TIME_CONF_FILE);
    let content = fs::read_to_string(conf).ok()?;

    let now = Local::now();
    let wday = now.weekday().num_days_from_monday() as u8;
    let Some(now_min) = (now.hour() * 60 + now.minute()).checked_sub(shift) else {
        // Shifted back to the previous day: the extension never crosses midnight.
        return Some(None);
    };

    let rule: Option<String> = content
        .lines()
        .filter(|l| !l.trim_start().starts_with('#') && !l.trim().is_empty())
        .filter_map(|l| {
            let mut parts = l.splitn(4, ';');
            let _ = parts.next()?;
            let _ = parts.next()?;
            let users = parts.next()?;
            let times = parts.next()?.trim().to_string();
            if users == username { Some(times) } else { None }
        })
        .next_back();

    let rule = rule?;

    // Latest end among the allowed ranges that contain "now".
    let mut latest_end: Option<u32> = None;

    // Each segment: DAYSPEC + HHMM-HHMM (time part is always last 9 chars)
    for seg in rule.split('|') {
        let seg = seg.trim();
        if seg.len() < 9 {
            continue;
        }
        let time_part = &seg[seg.len() - 9..];
        // Validate: 8 digits and a '-' at position 4
        if time_part.len() == 9
            && time_part.as_bytes()[4] == b'-'
            && time_part[..4].chars().all(|c| c.is_ascii_digit())
            && time_part[5..].chars().all(|c| c.is_ascii_digit())
        {
            let start_min = time_part[..2].parse::<u32>().unwrap_or(0) * 60
                + time_part[2..4].parse::<u32>().unwrap_or(0);
            let end_min = time_part[5..7].parse::<u32>().unwrap_or(0) * 60
                + time_part[7..9].parse::<u32>().unwrap_or(0);
            let day_code = &seg[..seg.len() - 9];
            if day_code_applies(day_code, wday) && now_min >= start_min && now_min < end_min {
                latest_end = Some(latest_end.map_or(end_min, |e| e.max(end_min)));
            }
        }
    }
    Some(latest_end.map(|end| end - now_min))
}

fn load_time_limits() -> HashMap<String, serde_json::Value> {
    let Ok(data) = fs::read_to_string(TIME_LIMITS_FILE) else {
        return HashMap::new();
    };
    serde_json::from_str(&data).unwrap_or_default()
}

fn load_time_state() -> (String, HashMap<String, u32>) {
    let Ok(data) = fs::read_to_string(TIME_USAGE_FILE) else {
        return (String::new(), HashMap::new());
    };
    let Ok(val) = serde_json::from_str::<serde_json::Value>(&data) else {
        return (String::new(), HashMap::new());
    };
    let date = val["_date"].as_str().unwrap_or("").to_string();
    let mut usage = HashMap::new();
    if let Some(obj) = val.as_object() {
        for (k, v) in obj {
            if k != "_date" {
                if let Some(n) = v.as_u64() {
                    usage.insert(k.clone(), n as u32);
                }
            }
        }
    }
    (date, usage)
}

fn save_time_state(today: &str, usage: &HashMap<String, u32>) {
    let mut obj = serde_json::Map::new();
    obj.insert("_date".to_string(), serde_json::Value::String(today.to_string()));
    for (k, v) in usage {
        obj.insert(k.clone(), serde_json::Value::Number((*v).into()));
    }
    let Ok(json) = serde_json::to_string_pretty(&serde_json::Value::Object(obj)) else {
        return;
    };
    atomic_write(Path::new(TIME_USAGE_FILE), json.as_bytes());
}

fn enforce_time_limits() {
    let today = Local::now().format("%Y-%m-%d").to_string();
    let limits = load_time_limits();
    let (state_date, mut usage) = load_time_state();
    if state_date != today {
        usage = HashMap::new();
    }
    let mut changed = false;
    let extra = load_time_extra(&today);

    // Daily minute limit (plus today's parent-approved extra minutes)
    for (username, cfg) in &limits {
        let base = cfg
            .get("daily_minutes")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as u32;
        if base == 0 {
            continue;
        }
        let daily_minutes = base + extra.get(username).map_or(0, |e| e.0);
        let Some(session_id) = get_active_graphical_session(username) else {
            continue;
        };
        let prev = usage.get(username).copied().unwrap_or(0);
        let total = prev + 1;
        usage.insert(username.clone(), total);
        changed = true;

        if total >= daily_minutes {
            notify_msg(username, Msg::DailyDone(daily_minutes));
            if total > daily_minutes {
                terminate_session(
                    username,
                    &session_id,
                    &format!("daily limit {total}/{daily_minutes} min"),
                );
            }
        } else {
            let remaining = daily_minutes - total;
            if remaining == 5 || remaining == 1 {
                notify_msg(username, Msg::DailyWarn(remaining));
            }
        }
    }

    // Schedule enforcement
    for username in get_supervised_users() {
        match schedule_with_extra(&username, &limits, &extra) {
            None => continue,
            Some(Some(left)) => {
                // Warn shortly before the allowed period ends (needs a live session).
                if (left == 5 || left == 1) && get_active_graphical_session(&username).is_some() {
                    notify_msg(&username, Msg::ScheduleWarn(left));
                }
                continue;
            }
            Some(None) => {}
        }
        let Some(session_id) = get_active_graphical_session(&username) else {
            continue;
        };
        notify_msg(&username, Msg::ScheduleEnd);
        terminate_session(&username, &session_id, "outside allowed schedule");
    }

    if changed {
        save_time_state(&today, &usage);
    }
}

// ── Monitor loop ─────────────────────────────────────────────

async fn monitor_loop(state: Arc<Mutex<MonitorState>>) {
    let mut tick = interval(Duration::from_secs(POLL_INTERVAL_SECS));

    loop {
        tick.tick().await;

        let monitored = {
            let state = state.lock().await;
            state.monitored_users.clone()
        };

        for user in &monitored {
            let processes = scan_user_processes(user.uid);
            if !processes.is_empty() {
                append_snapshot(&user.username, &processes);
            }
        }

        enforce_time_limits();
    }
}

// ── Main ─────────────────────────────────────────────────────

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    // Ensure data directories exist
    let _ = fs::create_dir_all(DATA_DIR);
    let _ = fs::create_dir_all(ACTIVITY_DIR);

    let connection = Connection::system().await?;

    let state = Arc::new(Mutex::new(MonitorState::new()));

    // Register AgeSignal interface
    let age_signal = AgeSignal {
        connection: connection.clone(),
    };
    connection
        .object_server()
        .at("/br/com/biglinux/ParentalDaemon", age_signal)
        .await?;

    // Register ParentalMonitor interface
    let monitor = ParentalMonitor {
        state: state.clone(),
    };
    connection
        .object_server()
        .at("/br/com/biglinux/ParentalDaemon", monitor)
        .await?;

    // Register TimeExtra interface
    let time_extra = TimeExtra {
        connection: connection.clone(),
        fails: Mutex::new(HashMap::new()),
    };
    connection
        .object_server()
        .at("/br/com/biglinux/ParentalDaemon", time_extra)
        .await?;

    // Request bus name
    connection
        .request_name("br.com.biglinux.ParentalDaemon")
        .await?;

    // Spawn the monitoring loop
    let monitor_state = state.clone();
    tokio::spawn(async move {
        monitor_loop(monitor_state).await;
    });

    // Run forever — D-Bus messages handled by zbus in the background.
    std::future::pending::<()>().await;

    Ok(())
}
