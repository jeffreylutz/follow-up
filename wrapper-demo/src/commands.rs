//! Build-time recipe manifest, embedded into the binary at compile time.

use serde::Deserialize;

/// The manifest text baked in at build time (validated by build.rs).
pub const MANIFEST_TOML: &str = include_str!("../commands.toml");

#[derive(Debug, Deserialize)]
pub struct Manifest {
    pub wrapped: Wrapped,
    #[serde(rename = "command", default)]
    pub commands: Vec<Recipe>,
}

#[derive(Debug, Deserialize)]
pub struct Wrapped {
    pub name: String,
    /// Local path or https URL of the executable to wrap.
    pub source: String,
    #[serde(default)]
    pub sha256: String,
    pub version: String,
}

#[derive(Debug, Deserialize, Clone)]
pub struct Recipe {
    pub name: String,
    #[serde(default)]
    pub about: String,
    pub args: Vec<String>,
}

impl Manifest {
    /// Parse the embedded manifest. Cannot fail in practice — build.rs already
    /// validated it at compile time.
    pub fn load() -> Self {
        toml::from_str(MANIFEST_TOML)
            .expect("embedded commands.toml is invalid (should have failed at build)")
    }

    pub fn recipe(&self, name: &str) -> Option<&Recipe> {
        self.commands.iter().find(|r| r.name == name)
    }
}
