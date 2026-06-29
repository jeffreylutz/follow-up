//! Self-update from a Nexus raw (hosted) repository.
//!
//! Layout convention in Nexus:
//!   {nexus_url}/latest/VERSION              -> text, e.g. "0.2.0"
//!   {nexus_url}/{version}/xwrap-{os}-{arch} -> the binary
//!   {nexus_url}/{version}/xwrap-{os}-{arch}.sha256
//!
//! On a normal run the check is throttled (TTL), fails open (network error =>
//! run the installed version), and is gated by XWRAP_PIN / XWRAP_NO_AUTO_UPDATE
//! so a licensed/regulated flow can freeze the version.

use anyhow::{bail, Context, Result};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::binary::hex;
use crate::config::Config;

const CURRENT: &str = env!("CARGO_PKG_VERSION");

/// Called on every run before launching the tool. Throttled + fail-open.
pub fn maybe_self_update(cfg: &Config) -> Result<()> {
    if !cfg.update.enabled || cfg.update.nexus_url.is_empty() {
        return Ok(());
    }
    if std::env::var_os("XWRAP_NO_AUTO_UPDATE").is_some() {
        return Ok(());
    }
    if std::env::var_os("XWRAP_REEXECED").is_some() {
        return Ok(()); // we already updated + re-exec'd this run
    }
    if let Ok(pin) = std::env::var("XWRAP_PIN") {
        if pin != CURRENT {
            bail!("XWRAP_PIN={pin} but this binary is {CURRENT}; refusing to run unpinned");
        }
        return Ok(());
    }
    let forced = std::env::var_os("XWRAP_FORCE_UPDATE_CHECK").is_some();
    if !forced && !ttl_expired(cfg) {
        return Ok(());
    }
    // Fail-open: never block a run because the update check failed.
    if let Err(e) = try_update(cfg) {
        eprintln!("[xwrap] update check skipped: {e}");
    }
    Ok(())
}

/// Forced update for the `self-update` subcommand (ignores TTL/opt-out).
pub fn force_update(cfg: &Config) -> Result<()> {
    if cfg.update.nexus_url.is_empty() {
        bail!("[update].nexus_url is not configured");
    }
    try_update(cfg)
}

fn try_update(cfg: &Config) -> Result<()> {
    let base = cfg.update.nexus_url.trim_end_matches('/');
    record_check(cfg);

    let latest = http_get_string(&format!("{base}/latest/VERSION"))?;
    let latest = latest.trim();

    if !is_newer(latest, CURRENT) {
        return Ok(());
    }
    eprintln!("[xwrap] updating {CURRENT} -> {latest}");

    let asset = target_asset();
    let bin_url = format!("{base}/{latest}/{asset}");
    let bytes = http_get_bytes(&bin_url).with_context(|| format!("downloading {bin_url}"))?;

    // Verify against the published checksum (fail-closed if present but mismatched).
    if let Ok(sums) = http_get_string(&format!("{bin_url}.sha256")) {
        let expected = sums.split_whitespace().next().unwrap_or_default();
        let actual = hex(sha2_digest(&bytes).as_slice());
        if !expected.is_empty() && expected != actual {
            bail!("checksum mismatch for {asset}: expected {expected}, got {actual}");
        }
    }

    let current = std::env::current_exe().context("locating current executable")?;
    atomic_replace(&current, &bytes)?;
    eprintln!("[xwrap] updated; re-exec");
    reexec(&current)
}

fn is_newer(latest: &str, current: &str) -> bool {
    match (semver::Version::parse(latest), semver::Version::parse(current)) {
        (Ok(l), Ok(c)) => l > c,
        _ => false, // unparseable -> don't update (fail-safe)
    }
}

fn target_asset() -> String {
    let os = if cfg!(target_os = "macos") { "macos" } else { "linux" };
    let arch = if cfg!(target_arch = "aarch64") {
        "aarch64"
    } else {
        "x86_64"
    };
    format!("xwrap-{os}-{arch}")
}

fn atomic_replace(current: &Path, bytes: &[u8]) -> Result<()> {
    let dir = current.parent().unwrap_or_else(|| Path::new("."));
    let tmp = dir.join(".xwrap.update.tmp");
    fs::write(&tmp, bytes)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&tmp, fs::Permissions::from_mode(0o755))?;
    }
    fs::rename(&tmp, current)?; // atomic; a running exe keeps its old inode
    Ok(())
}

#[cfg(unix)]
fn reexec(current: &Path) -> Result<()> {
    use std::os::unix::process::CommandExt;
    let err = std::process::Command::new(current)
        .args(std::env::args().skip(1))
        .env("XWRAP_REEXECED", "1")
        .exec();
    bail!("re-exec failed: {err}");
}

#[cfg(not(unix))]
fn reexec(current: &Path) -> Result<()> {
    let status = std::process::Command::new(current)
        .args(std::env::args().skip(1))
        .env("XWRAP_REEXECED", "1")
        .status()?;
    std::process::exit(status.code().unwrap_or(0));
}

// --- TTL bookkeeping ---

fn check_stamp(cfg: &Config) -> PathBuf {
    cfg.cache_dir().join(".update_check")
}

fn ttl_expired(cfg: &Config) -> bool {
    let path = check_stamp(cfg);
    let last = fs::read_to_string(&path)
        .ok()
        .and_then(|s| s.trim().parse::<u64>().ok())
        .unwrap_or(0);
    now_secs().saturating_sub(last) >= cfg.update.ttl_secs
}

fn record_check(cfg: &Config) {
    let _ = fs::create_dir_all(cfg.cache_dir());
    let _ = fs::write(check_stamp(cfg), now_secs().to_string());
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

// --- tiny HTTP helpers (ureq, blocking) ---

fn http_get_string(url: &str) -> Result<String> {
    Ok(ureq::get(url).timeout(Duration::from_secs(5)).call()?.into_string()?)
}

fn http_get_bytes(url: &str) -> Result<Vec<u8>> {
    let resp = ureq::get(url).timeout(Duration::from_secs(30)).call()?;
    let mut buf = Vec::new();
    resp.into_reader().read_to_end(&mut buf)?;
    Ok(buf)
}

fn sha2_digest(bytes: &[u8]) -> Vec<u8> {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(bytes);
    h.finalize().to_vec()
}
