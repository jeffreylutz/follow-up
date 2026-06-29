//! Cross-process concurrency cap: N file locks = N license seats.
//!
//! Each seat is a real OS lock (via `flock`) on its own file. A non-blocking
//! `try_lock_exclusive` that fails means that seat is held right now by some
//! process (possibly another invocation), so we try the next one. The kernel
//! releases the lock when the holder's file descriptor closes — including on
//! crash — so seats are never leaked.

use anyhow::{bail, Result};
use fs2::FileExt;
use std::fs::{File, OpenOptions};
use std::path::Path;
use std::time::{Duration, Instant};

/// Holds an acquired seat. The lock is released when this is dropped (the file
/// closes), or by the kernel if the process dies.
pub struct SlotGuard {
    _file: File,
    pub slot: u32,
}

pub fn acquire_slot(
    lock_dir: &Path,
    n: u32,
    timeout: Duration,
    poll: Duration,
) -> Result<SlotGuard> {
    std::fs::create_dir_all(lock_dir)?;
    let n = n.max(1);
    // Stagger which seat each process tries first, to spread contention.
    let start = std::process::id() % n;
    let deadline = Instant::now() + timeout;

    loop {
        for i in 0..n {
            let idx = (start + i) % n;
            let path = lock_dir.join(format!("slot_{idx}.lock"));
            let file = OpenOptions::new().create(true).write(true).open(&path)?;
            if file.try_lock_exclusive().is_ok() {
                return Ok(SlotGuard {
                    _file: file,
                    slot: idx,
                });
            }
        }
        if Instant::now() >= deadline {
            bail!("no free seat among {n} within {timeout:?}");
        }
        std::thread::sleep(poll);
    }
}
