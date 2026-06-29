//! FlexLM license pre-check: gate a launch on a free seat via lmstat.

use anyhow::{bail, Result};
use std::process::Command;
use std::time::{Duration, Instant};

use crate::config::Config;

pub fn wait_for_license(cfg: &Config) -> Result<()> {
    if cfg.license_server.is_empty() || cfg.license_feature.is_empty() {
        return Ok(()); // gate disabled
    }
    let deadline = Instant::now() + Duration::from_secs(cfg.acquire_timeout);
    loop {
        if free_seats(cfg) >= 1 {
            return Ok(());
        }
        if Instant::now() >= deadline {
            bail!(
                "no free '{}' license seat within {}s",
                cfg.license_feature,
                cfg.acquire_timeout
            );
        }
        std::thread::sleep(Duration::from_secs(cfg.poll_interval));
    }
}

/// issued-minus-in-use for the configured feature; 0 (fail-closed) if unparseable.
fn free_seats(cfg: &Config) -> i64 {
    let output = Command::new(&cfg.lmstat_path)
        .args(["lmstat", "-f", &cfg.license_feature, "-c", &cfg.license_server])
        .output();
    let output = match output {
        Ok(o) => o,
        Err(_) => return 0,
    };
    let text = String::from_utf8_lossy(&output.stdout);

    // Real lmstat prints: "...Total of N license(s) issued; Total of M license(s) in use".
    // Pull the integer following each "Total of": first = issued, second = in use.
    let nums: Vec<i64> = text
        .split("Total of")
        .skip(1)
        .filter_map(|seg| seg.trim_start().split_whitespace().next())
        .filter_map(|tok| tok.parse::<i64>().ok())
        .collect();

    if nums.len() < 2 {
        return 0;
    }
    nums[0] - nums[1]
}
