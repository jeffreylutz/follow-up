# Xilinx Command Wrapper — Implementation Design (Rust)

_Date: 2026-06-28 (revised 2026-06-29 for the Rust implementation)_

The "command wrapper" stack from `COMMAND_WRAPPER_APPROACH.md`, implemented as a
single static **Rust** binary in [`wrapper-demo/`](../../../wrapper-demo/). It wraps a
licensed external executable (the Xilinx toolchain — Vivado/Vitis) and provides:

1. Running the executable (with specific environment variables).
2. Downloading/caching the binary if missing or its hash changed.
3. Configuration from files: **build-time** command recipes + **runtime** ops settings.
4. A configurable concurrency cap (default `2`) that holds **across processes** on one
   host, because a FlexLM license is shared by all processes.
5. A single-command, **zero-dependency** install (no Python/pip/uv/cargo on the target).
6. A **self-update on run** from Nexus, gated for reproducibility.

## Scope decisions

- **Rust only.** No runtime: a ~2 MB static binary, nothing embedded. Primitives come
  from `std` + small crates.
- **Build-time recipes, runtime ops config.** `commands.toml` (what to run) is embedded
  at compile time; `config.toml` + `XWRAP_*` (where/how, per machine) load at runtime.
- **Fully runnable with mocks.** A mock `vivado` and mock `lmstat` let the whole flow
  run end-to-end with no real license; the real binary/server swap in via config.
- **Concurrency: `fs2` flock seat-locks only** (single host, crash-safe). Redis / Slurm
  are out of scope (documented as next steps).
- **Distribution: Nexus raw repo + `curl | sh`.** No automated test suite; verification
  is by running the demo.
- **Targets:** macOS + Linux. Multi-arch builds run per OS/arch in CI (or via `cross`).

## Architecture

```
wrapper-demo/
  Cargo.toml             # crate + deps; release profile (strip, lto, opt-level z)
  commands.toml          # BUILD-TIME recipes (embedded). "what commands to run"
  build.rs               # validates commands.toml at compile time; rerun-if-changed
  config.example.toml    # RUNTIME ops config (copy to config.toml)
  src/
    main.rs              # builds clap CLI from embedded recipes; dispatch
    commands.rs          # include_str!(commands.toml) -> Manifest (Wrapped + Recipe[])
    config.rs            # figment: defaults < config.toml < XWRAP_* env
    binary.rs            # ensure_binary(): download/copy if missing-or-changed + SHA256
    limiter.rs           # SlotLimiter: grab 1 of N fs2 flock seat files; RAII release
    license.rs           # wait_for_license(): poll lmstat, gate on a free seat
    runner.rs            # orchestrates the whole flow
    update.rs            # Nexus self-update: TTL check, verify, atomic swap, re-exec
  mocks/
    mock_vivado.sh       # sleeps + prints, simulates a build
    mock_lmstat.sh       # prints fake FlexLM output; in-use count via env var
  install.sh             # curl|sh installer pulling from Nexus raw
  publish-to-nexus.sh    # PUT binary + .sha256 + latest/VERSION to Nexus (build host)
  README.md              # build, run, ship, self-update instructions
```

**Crates:** `clap` (builder API), `serde` + `toml`, `figment` (config layering),
`ureq` (blocking HTTP, no async runtime), `sha2`, `fs2` (flock), `semver`, `dirs`,
`anyhow`. Build dep: `toml` (manifest validation in `build.rs`).

## Components

### `commands.toml` + `build.rs` + `commands.rs` (build-time config)
The recipe manifest defines the wrapped executable and the named commands:

```toml
[wrapped]                # name, source (path or https URL), sha256, version
[[command]]              # name, about, args[]  (one per recipe)
```

`build.rs` reads and validates it at compile time — a missing `[wrapped]` field or a
recipe without `args` **fails `cargo build`** (correct-by-construction artifact) — and
emits `rerun-if-changed`. `commands.rs` embeds the file with `include_str!` and parses
it into `Manifest { wrapped: Wrapped, commands: Vec<Recipe> }` at startup.

### `config.rs` (runtime ops config)
A `Config` struct loaded via figment with precedence *defaults < `config.toml` <
`XWRAP_*` env* (nested keys via `__`, e.g. `XWRAP_UPDATE__ENABLED`).

| Field | Default | Meaning |
|-------|---------|---------|
| `max_concurrency` | `2` | Number of license seats |
| `acquire_timeout` | `600` | Seconds to wait for a seat + license |
| `poll_interval` | `2` | Seconds between retries |
| `cache_dir` | OS cache dir `/xwrap` | Where the wrapped binary is cached |
| `lock_dir` | `<cache>/locks` | Where seat lock files live |
| `license_server` | `""` | `port@host` for FlexLM (blank disables the gate) |
| `license_feature` | `""` | FlexLM feature name |
| `lmstat_path` | `"lmutil"` | Path to lmstat (mock path for demo) |
| `extra_env` | `{}` | Env vars injected into the child |
| `update` | disabled | `{ enabled, nexus_url, ttl_secs }` |

### `binary.rs`
`ensure_binary(&Wrapped, &Config) -> PathBuf`. Caches under `<cache_dir>/<version>/`.
Re-fetches only if the file is absent or its SHA256 differs (`ureq` for https, file
copy for a local/mock path), writes atomically (tmp + rename), verifies the hash, and
sets the executable bit. A comment marks where auth headers plug in for a gated URL.

### `limiter.rs`
`SlotLimiter::acquire_slot(lock_dir, n, timeout, poll) -> SlotGuard`. Sweeps
`slot_0.lock`…`slot_{n-1}.lock` (start offset = `pid % n` for fairness), taking the
first via `fs2` non-blocking `try_lock_exclusive`; retries until timeout. Each seat is a
real OS lock, so the kernel releases it on crash. `SlotGuard` releases on drop (RAII).

### `license.rs`
`wait_for_license(&Config)`. Runs `lmstat`, parses the two `Total of N license(s)`
values (issued, in-use), returns once `issued - in_use >= 1`, else polls every
`poll_interval` until `acquire_timeout`. Fail-closed (treats unparseable output as 0).

### `runner.rs`
Orchestration: `ensure_binary → acquire_slot → wait_for_license →
Command::new(exe).args(recipe.args).args(extra).envs(extra_env).status()`. Inherits the
parent env, then layers `extra_env`; returns the child's exit code; seat drops on exit.

### `update.rs`
`maybe_self_update(&Config)` (per run) and `force_update` (the `self-update` subcommand).
Throttled by `ttl_secs` (timestamp in cache), **fail-open**, honoring `XWRAP_PIN` /
`XWRAP_NO_AUTO_UPDATE` / `XWRAP_FORCE_UPDATE_CHECK`. Reads `{nexus}/latest/VERSION`,
semver-compares, and if newer: downloads `{nexus}/<ver>/xwrap-<os>-<arch>`, verifies its
`.sha256`, atomically replaces `current_exe()`, then `execv` re-execs (guarded by
`XWRAP_REEXECED`).

### `main.rs`
Loads the embedded `Manifest`, builds the clap `Command` **dynamically** — one
subcommand per recipe, plus `list` and `self-update` — parses `--config`, loads
`Config`, and dispatches. Recipe runs call `maybe_self_update` first (may re-exec), then
`run_recipe`. Anything after `--` is appended to the wrapped tool.

## Data flow

`CLI (recipe) → maybe_self_update (Nexus, TTL/fail-open) → Config (figment) →
ensure_binary (cache + SHA256) → SlotLimiter (fs2 flock) → license gate (lmstat) →
Command::status (curated env) → exit code → seat released on drop`

## Distribution & install

Nexus raw layout: `{nexus}/xwrap/latest/VERSION`, `{nexus}/xwrap/<ver>/xwrap-<os>-<arch>`,
`+ .sha256`. `publish-to-nexus.sh` PUTs these from the build host; `install.sh` (needs
only `curl`/`sh`) reads VERSION, downloads the asset for the host OS/arch, verifies the
checksum, and installs to `~/.local/bin`.

## Error handling

- **Bad recipe manifest:** caught at **compile time** by `build.rs`.
- **Hash mismatch / download failure:** `ensure_binary` returns `Err` with a clear message.
- **No free seat / license within `acquire_timeout`:** error, non-zero exit.
- **Child exits non-zero:** propagated as the wrapper's exit code.
- **Update check failure:** fail-open — logged, run the installed version.
- **Seat release:** RAII (`SlotGuard` drop); on crash, the kernel releases the flock.

## Design rationale

- **Build-time recipes = a compile-time contract:** a malformed `commands.toml` never
  produces a binary, which is stronger than runtime validation.
- **Seat-locks + lmstat gate are belt-and-suspenders:** the limiter caps *our* launches;
  the lmstat poll catches seats consumed by *others* outside the wrapper.
- **One-lock-file-per-seat** (not a counter in a file) is what makes the cap crash-safe —
  the OS owns release.
- **No embedded runtime:** a Rust binary satisfies the zero-dependency install directly,
  unlike a Python binary that must embed an interpreter (~17 MB) to do the same.

## Out of scope (documented next steps)

- Cross-host concurrency (Redis counting semaphore).
- Cluster scheduling (Slurm `--licenses`).
- Automated test suite.
- Real authenticated download of the licensed installer.
- Cryptographically signed updates (`tufup`/TUF) instead of plain checksum verification.
