# xwrap (Rust) — command wrapper for a licensed executable

A single ~2 MB static binary that wraps a licensed CLI (e.g. Xilinx Vivado/Vitis) and
adds: a cached/verified download of the tool, injected env vars, a **cross-process
concurrency cap** sized to your license seats, an **lmstat** pre-check, and
**self-update on run**. The command *recipes* are baked into the binary at build time;
per-machine settings load at runtime. **No Python/pip/uv anywhere** — at build or run
time; the released artifact is self-contained.

---

## Quick start

### Install (end users) — one line, zero dependencies

The binary lives in a **Nexus raw repo**. On any macOS/Linux box (needs only `curl`/`sh`
— no Python, pip, uv, or cargo):

```bash
curl -fsSL https://nexus.example.com/repository/raw-hosted/xwrap/install.sh | sh
```

This downloads the binary for your OS/arch, verifies its SHA256, and drops it in
`~/.local/bin`. Then:

```bash
xwrap list                              # show the built-in recipes
xwrap synth --config /etc/xwrap.toml    # run a recipe
```

### Build & try from source (developers)

```bash
cd wrapper-demo
cargo build --release                   # -> target/release/xwrap (~2 MB, no interpreter)
cp config.example.toml config.toml
chmod +x mocks/*.sh                      # the demo wraps a mock "vivado" + mock "lmstat"

./target/release/xwrap list
./target/release/xwrap synth --config config.toml -- --extra-flag
#   runs <wrapped> -mode batch -source synth.tcl --extra-flag

# Prove the cap (max_concurrency=2): two run, the third waits for a seat.
for t in A B C; do MOCK_VIVADO_SECONDS=3 ./target/release/xwrap synth & done; wait
```

Recipes are real subcommands built from the embedded manifest; anything after `--` is
appended to the wrapped tool.

---

## How the wrapper works

Two configs, by design:

- **Build-time recipes — `commands.toml`** (the *what*). Defines the wrapped executable
  and the named commands. `build.rs` validates it **at compile time** (a malformed
  manifest fails `cargo build`) and `include_str!` embeds it. Change it and rebuild to
  specialize the binary for another tool or site.
- **Runtime ops config — `config.toml` + `XWRAP_*` env** (the *how/where*). Per-machine
  settings — seat count, license server, env vars, Nexus URL — layered via figment as
  *defaults < file < env*.

Each recipe run is a short pipeline:

```
xwrap synth
  │
  1. parse CLI ........ recipe subcommands are built from the embedded commands.toml
  2. self-update ...... check Nexus latest/VERSION (throttled by TTL, fail-open);
  │                     if newer: verify → atomic swap → re-exec  (skipped if pinned/opted out)
  3. load config ...... figment: defaults < config.toml < XWRAP_*
  4. ensure binary .... download/copy the wrapped exe only if missing or its SHA256
  │                     changed; cache under <cache_dir>/<version>/
  5. acquire a seat ... take 1 of N flock lock-files (N = max_concurrency). If all are
  │                     held, wait (poll) up to acquire_timeout. Kernel frees a seat
  │                     automatically if a holder crashes.
  6. license gate ..... poll lmstat; proceed only when issued - in_use >= 1
  7. run .............. spawn <exe> <recipe args> <extra args> with inherited env +
  │                     config extra_env; return its exit code
  8. release .......... the seat is released on exit (RAII), even on crash
```

Why two independent guards in steps 5–6? The **flock seat-cap** limits *our* concurrent
launches across every process on the host; the **lmstat check** catches seats consumed
by *other* people outside the wrapper. Neither alone is sufficient. Using one lock-file
per seat (not a counter in a file) is what makes the cap crash-safe — the OS owns
release.

### Layout

```
wrapper-demo/
  commands.toml          # BUILD-TIME recipes (embedded). "what commands to run"
  build.rs               # validates commands.toml at compile time
  config.example.toml    # RUNTIME ops config
  src/
    main.rs              # builds the clap CLI from the embedded recipes; dispatch
    commands.rs          # parse the embedded commands.toml
    config.rs            # figment: defaults < config.toml < XWRAP_*
    binary.rs            # download/cache the wrapped exe + SHA256
    limiter.rs           # N flock seats; cross-process, crash-safe
    license.rs           # poll lmstat, gate on a free seat
    runner.rs            # orchestrates the pipeline above
    update.rs            # Nexus self-update: check, verify, swap, re-exec
  mocks/                 # mock_vivado.sh, mock_lmstat.sh (for the demo)
  install.sh             # curl|sh installer pulling from Nexus raw
  publish-to-nexus.sh    # PUT binary + .sha256 + latest/VERSION to Nexus (build host)
```

---

## The one-liner install, end to end

**1. Build per OS/arch** (on a native runner — see cross-compilation below):

```bash
cargo build --release      # -> target/release/xwrap
```

**2. Publish to Nexus** from the build host. The raw repo uses this layout:

```
{nexus}/xwrap/latest/VERSION                 # text, e.g. 0.2.0
{nexus}/xwrap/<ver>/xwrap-<os>-<arch>        # the binary
{nexus}/xwrap/<ver>/xwrap-<os>-<arch>.sha256
```

```bash
NEXUS_URL=https://nexus.example.com/repository/raw-hosted/xwrap \
NEXUS_USER=svc-ci NEXUS_PASS=*** \
  ./publish-to-nexus.sh target/release/xwrap
```

(`publish-to-nexus.sh` reads the version from `Cargo.toml`, computes the checksum, and
uploads the binary, its `.sha256`, and `latest/VERSION`.)

**3. Install anywhere** — the single line end users run (only `curl`/`sh` required):

```bash
curl -fsSL https://nexus.example.com/repository/raw-hosted/xwrap/install.sh | sh
```

`install.sh` detects OS/arch, reads `latest/VERSION`, downloads the matching binary,
verifies the checksum, and installs to `~/.local/bin`. Point `XWRAP_BASE_URL` /
`XWRAP_INSTALL_DIR` at your instance to override the defaults.

---

## Self-update

With `[update].enabled = true` and `nexus_url` set in `config.toml`, every run does a
throttled (`ttl_secs`) check of `latest/VERSION`; if newer it does a verified download →
atomic swap of the running binary → re-exec. Controls:

- `XWRAP_PIN=<ver>` — refuse to run anything but this version (reproducible builds).
- `XWRAP_NO_AUTO_UPDATE=1` — opt out of the on-run check.
- `XWRAP_FORCE_UPDATE_CHECK=1` — ignore the TTL for this run; or run `xwrap self-update`.

It is **fail-open**: a slow or unreachable Nexus never blocks a run — the installed
version is used.

---

## Cross-compilation (the honest version)

Unlike Go, Rust cross-compiling isn't a single flag here — `ring`/`rustls` pull in C, so
you need the target std and a cross linker. Practical options:

- **CI matrix** (recommended): build on a native runner per OS/arch (macOS arm64 +
  x86_64, Linux x86_64 + aarch64), then `publish-to-nexus.sh` each. This is the same
  per-target build PyInstaller/Nuitka/PyApp require — but the Rust artifact is smaller
  and has no embedded runtime.
- **`cross`** (`cargo install cross`) — Docker-based cross builds to Linux targets.
- **rustup targets** — `rustup target add <triple>` works for same-OS targets
  (e.g. `x86_64-apple-darwin` from arm64 macOS). A Homebrew `cargo` ships only the host
  target, so use rustup if you need others.
