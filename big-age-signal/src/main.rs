//! D-Bus session service: br.com.biglinux.AgeSignal
//!
//! Exposes a minimal interface so applications can query whether the
//! current user is a child or adult, following data minimisation
//! (Art. 13 ECA Digital) — only the age *range* is exposed, never
//! the exact age.

use std::ffi::CString;

use nix::unistd::User;
use zbus::{interface, Connection, Result};

const SUPERVISED_GROUP: &str = "supervised";
const VERSION: &str = "1.0";

struct AgeSignal;

/// Check if the current user belongs to `supervised`.
fn is_supervised() -> bool {
    let uid = nix::unistd::getuid();
    let user = match User::from_uid(uid) {
        Ok(Some(u)) => u,
        _ => return false,
    };

    let gid = match nix::unistd::Group::from_name(SUPERVISED_GROUP) {
        Ok(Some(g)) => g.gid,
        _ => return false,
    };

    // Check primary group
    if user.gid == gid {
        return true;
    }

    // Check supplementary groups
    let cname = match CString::new(user.name.as_str()) {
        Ok(c) => c,
        Err(_) => return false,
    };
    match nix::unistd::getgrouplist(&cname, user.gid) {
        Ok(groups) => groups.contains(&gid),
        Err(_) => false,
    }
}

fn get_age_range() -> &'static str {
    if is_supervised() {
        "child"
    } else {
        "adult"
    }
}

#[interface(name = "br.com.biglinux.AgeSignal1")]
impl AgeSignal {
    /// Returns "child", "teen", or "adult".
    fn get_age_range(&self) -> &str {
        get_age_range()
    }

    /// Returns true if the user is under 18 (supervised).
    fn is_minor(&self) -> bool {
        get_age_range() != "adult"
    }

    /// Interface version.
    #[zbus(property)]
    fn version(&self) -> &str {
        VERSION
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let connection = Connection::session().await?;

    connection
        .object_server()
        .at("/br/com/biglinux/AgeSignal", AgeSignal)
        .await?;

    connection
        .request_name("br.com.biglinux.AgeSignal")
        .await?;

    // Run forever — D-Bus messages handled in background.
    std::future::pending::<()>().await;

    Ok(())
}
