//! Download/cache the wrapped executable if missing or its hash changed.

use anyhow::{bail, Context, Result};
use sha2::{Digest, Sha256};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::commands::Wrapped;
use crate::config::Config;

pub fn ensure_binary(wrapped: &Wrapped, cfg: &Config) -> Result<PathBuf> {
    let cache = cfg.cache_dir().join(&wrapped.version);
    fs::create_dir_all(&cache)?;

    let filename = Path::new(&wrapped.source)
        .file_name()
        .map(|s| s.to_owned())
        .unwrap_or_else(|| std::ffi::OsString::from("executable"));
    let dest = cache.join(&filename);

    let want_hash = !wrapped.sha256.is_empty();
    let stale = !dest.exists() || (want_hash && sha256_file(&dest)? != wrapped.sha256);

    if stale {
        let bytes = if is_url(&wrapped.source) {
            // For an auth-gated vendor URL, add headers on the request here.
            http_get(&wrapped.source).with_context(|| format!("downloading {}", wrapped.source))?
        } else {
            fs::read(&wrapped.source)
                .with_context(|| format!("reading {}", wrapped.source))?
        };
        atomic_write(&dest, &bytes)?;
    }

    if want_hash {
        let got = sha256_file(&dest)?;
        if got != wrapped.sha256 {
            bail!(
                "SHA256 mismatch for {}: expected {}, got {}",
                dest.display(),
                wrapped.sha256,
                got
            );
        }
    }

    make_executable(&dest)?;
    Ok(dest)
}

fn is_url(s: &str) -> bool {
    s.starts_with("http://") || s.starts_with("https://")
}

fn http_get(url: &str) -> Result<Vec<u8>> {
    let resp = ureq::get(url).call()?;
    let mut buf = Vec::new();
    resp.into_reader().read_to_end(&mut buf)?;
    Ok(buf)
}

fn atomic_write(dest: &Path, bytes: &[u8]) -> Result<()> {
    let tmp = dest.with_extension("tmp");
    fs::write(&tmp, bytes)?;
    fs::rename(&tmp, dest)?;
    Ok(())
}

pub fn sha256_file(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex(&hasher.finalize()))
}

pub fn hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

#[cfg(unix)]
fn make_executable(path: &Path) -> Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let mut perms = fs::metadata(path)?.permissions();
    perms.set_mode(0o755);
    fs::set_permissions(path, perms)?;
    Ok(())
}

#[cfg(not(unix))]
fn make_executable(_path: &Path) -> Result<()> {
    Ok(())
}
