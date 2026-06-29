//! Runtime ops config: defaults < config.toml < XWRAP_* env vars.

use anyhow::Result;
use figment::{
    providers::{Env, Format, Serialized, Toml},
    Figment,
};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Config {
    pub max_concurrency: u32,
    pub acquire_timeout: u64,
    pub poll_interval: u64,
    pub cache_dir: Option<PathBuf>,
    pub lock_dir: Option<PathBuf>,
    pub license_server: String,
    pub license_feature: String,
    pub lmstat_path: String,
    pub extra_env: BTreeMap<String, String>,
    pub update: UpdateConfig,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct UpdateConfig {
    pub enabled: bool,
    pub nexus_url: String,
    pub ttl_secs: u64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            max_concurrency: 2,
            acquire_timeout: 600,
            poll_interval: 2,
            cache_dir: None,
            lock_dir: None,
            license_server: String::new(),
            license_feature: String::new(),
            lmstat_path: "lmutil".into(),
            extra_env: BTreeMap::new(),
            update: UpdateConfig {
                enabled: false,
                nexus_url: String::new(),
                ttl_secs: 86_400,
            },
        }
    }
}

impl Config {
    pub fn load(path: Option<&Path>) -> Result<Self> {
        let file = path.map(PathBuf::from).unwrap_or_else(|| PathBuf::from("config.toml"));
        let cfg: Config = Figment::from(Serialized::defaults(Config::default()))
            .merge(Toml::file(file))
            // XWRAP_MAX_CONCURRENCY -> max_concurrency; nested via "__":
            // XWRAP_UPDATE__ENABLED -> update.enabled
            .merge(Env::prefixed("XWRAP_").split("__"))
            .extract()?;
        Ok(cfg)
    }

    pub fn cache_dir(&self) -> PathBuf {
        self.cache_dir.clone().unwrap_or_else(|| {
            dirs::cache_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join("xwrap")
        })
    }

    pub fn lock_dir(&self) -> PathBuf {
        self.lock_dir
            .clone()
            .unwrap_or_else(|| self.cache_dir().join("locks"))
    }
}
