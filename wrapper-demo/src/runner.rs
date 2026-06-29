//! Orchestrate: ensure binary -> hold a seat -> confirm a license -> run.

use anyhow::Result;
use std::process::Command;
use std::time::Duration;

use crate::commands::{Manifest, Recipe};
use crate::config::Config;
use crate::{binary, license, limiter};

pub fn run_recipe(
    manifest: &Manifest,
    recipe: &Recipe,
    cfg: &Config,
    extra: &[String],
) -> Result<i32> {
    let exe = binary::ensure_binary(&manifest.wrapped, cfg)?;

    let guard = limiter::acquire_slot(
        &cfg.lock_dir(),
        cfg.max_concurrency,
        Duration::from_secs(cfg.acquire_timeout),
        Duration::from_secs(cfg.poll_interval),
    )?;
    eprintln!(
        "[xwrap] holding seat {}/{}",
        guard.slot + 1,
        cfg.max_concurrency
    );

    license::wait_for_license(cfg)?;

    // Inherit the parent env (PATH etc.), then layer the configured vars on top.
    let mut cmd = Command::new(&exe);
    cmd.args(&recipe.args).args(extra);
    for (key, val) in &cfg.extra_env {
        cmd.env(key, val);
    }

    eprintln!(
        "[xwrap] launching: {} {}",
        exe.display(),
        recipe.args.join(" ")
    );
    let status = cmd.status()?;
    Ok(status.code().unwrap_or(1))
    // `guard` drops here, releasing the seat.
}
