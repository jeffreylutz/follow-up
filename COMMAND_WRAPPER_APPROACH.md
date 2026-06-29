# Command Wrapper Approach

Options for building a **wrapper around an external executable** that:

1. Runs the executable.
2. **Downloads / caches** the executable if it's missing or a newer version is available.
3. Runs it with **specific environment variables**.
4. Runs it with **specific configuration** from a config file.
5. Uses a **concurrency limiter** capped at a configurable maximum (e.g. `2`).
6. Installs **in a single command** — and must **not require `uv`** to install.
7. **Checks for updates and self-updates** every time the wrapper runs.

The concrete driver (see `README.md`) is a wrapper around the **Xilinx** toolchain
(Vivado/Vitis): a large vendor binary, **FlexLM-licensed**, where we have a very
limited number of seats (as few as **1**), so we must never launch more runs than
we hold licenses for.

_Last updated: June 2026._

This document is both an **options survey** and the record of the **decision**: the
wrapper is implemented as **a single Rust binary** (see [`wrapper-demo/`](wrapper-demo/)).
The detailed per-requirement sections below survey the option space — much of it in the
Python ecosystem — that informed the choice; the chosen Rust mapping is here.

---

## Decision: one static Rust binary

**Why Rust, not Python.** Every requirement is plain orchestration — spawn a process,
hash + download a file, read TOML, take a file lock, parse `lmstat`, swap-and-re-exec.
None of it needs a Python runtime. Requirement 6 (single-line install, **no
Python/pip/uv on the target**) actively penalises Python: the only way to satisfy it
was to **embed a whole interpreter** (PyApp/Nuitka, ~17 MB) just to remove the Python
dependency we introduced. A compiled language skips that round-trip. Rust gives a
**~2 MB static binary with nothing embedded**, the primitives are all in `std` or small
crates, and `cargo` builds the artifact directly.

**A twist on requirement 4:** the command recipes — *what* the wrapper runs — are
defined in a **build-time** config (`commands.toml`) that `build.rs` validates and
embeds at compile time (a malformed manifest fails the build). Per-machine *ops* settings
(seats, license server, env) stay in a **runtime** `config.toml`.

| # | Requirement | Rust mechanism (in `wrapper-demo/`) |
|---|-------------|-------------------------------------|
| 1,3 | Run the exe + inject env | `std::process::Command` (inherits env, then layers `extra_env`) |
| 2 | Download / cache if missing-or-newer + SHA256 | `ureq` + `sha2`, atomic write into a versioned cache (`binary.rs`) |
| 4 | Config | **build-time** recipes via `build.rs` + `include_str!` (`commands.toml`); **runtime** ops via `figment` (`config.toml` + `XWRAP_*`) |
| 5 | Concurrency cap | `fs2` `flock` over **N seat files**, cross-process, kernel-released on crash (`limiter.rs`) |
| — | License safety net | `lmstat` poll before launch (`license.rs`) |
| 6 | Single-line, zero-dep install | static binary in a **Nexus raw repo** + `curl \| sh` (`install.sh`); needs only `curl`/`sh` |
| 7 | Self-update on run | check Nexus `latest/VERSION` (TTL, fail-open) → verified download → atomic swap → re-exec, with `XWRAP_PIN`/`XWRAP_NO_AUTO_UPDATE` (`update.rs`) |

**Cross-compilation caveat (honest):** unlike Go, Rust here pulls C via `ring`/`rustls`,
so multi-arch isn't one flag — build per OS/arch on **CI runners** (or use `cross`).
That's the same per-target build a PyApp/PyInstaller binary needs, but the Rust artifact
is smaller and carries no runtime.

---

## TL;DR (option survey)

> The bullets below summarise the **options considered** per requirement. The
> **chosen** mapping is Rust (see *Decision* above); the Python-centric picks here are
> the strongest alternatives in each category and explain the trade-offs.

- **Run the executable:** in Python, plain **`subprocess`** is the default; **`plumbum`**
  for cross-platform/SSH, **`invoke`** for interactive prompts. → *Rust: `std::process::Command`.*
- **Download / cache the binary by version:** **`pooch`** natively does
  "download only if missing **or** the hash changed" + **SHA256** + versioned cache.
  Tool-version managers (**mise**, **aqua**, asdf) target *public* releases and can't
  fetch an auth-gated vendor installer. → *Rust: `ureq` + `sha2`.*
- **Env vars + config file:** **`pydantic-settings`** layers *defaults < file < env < CLI*
  with validation; **`dynaconf`** for multi-env + secrets. → *Rust: `figment` (runtime) +
  `build.rs`/`include_str!` (build-time recipes).*
- **Concurrency cap — the part that bites:** in-process limiters
  (`ThreadPoolExecutor`, `asyncio.Semaphore`) only count *within one process*. A FlexLM
  license is shared across **every process and host**, so you need a **cross-process**
  limiter:
  - **One host:** `N` lock files via **`filelock`** (Python) / **`fs2`** (Rust), or GNU
    `sem -j N --id`. Kernel auto-releases on crash — the most robust.
  - **Many hosts:** a **Redis counting semaphore** (per-slot TTL + heartbeat).
  - **On a cluster:** **Slurm `--licenses`** (since 23.02 can sync real usage via `lmstat`).
- **Always gate on the license itself** — a quick `lmutil lmstat` pre-check catches
  seats consumed by other users outside your wrapper.
- **Single-line install, zero dependencies on the target (no Python/pip/`uv`):** ship a
  **standalone binary** via a **`curl … | sh`** installer (rustup/Deno model). A Rust
  binary is natively self-contained; a Python one must **embed the interpreter** (PyApp
  / Nuitka). **Neither Just nor Devbox fits:** Just is a *task runner* (not an installer,
  and itself a prerequisite); Devbox *swaps `uv` for a Nix dependency*. Here we publish to
  a **Nexus raw repo**.
- **Self-update on run — carefully.** Updating on *every* invocation is risky for a
  licensed/regulated flow: **throttled check** (TTL) → **fail-open** → **verified**
  download → **atomic swap** → **re-exec**, gated by **pin / opt-out**. → *Rust: `update.rs`
  against Nexus; **`tufup`** (TUF-signed) if you need cryptographic update signing.*

---

## Option survey by requirement

> The sections below are the **option space considered** for each requirement (much of
> it Python, since that was the starting point). They explain the trade-offs behind the
> Rust mapping in *Decision* above — read them as "alternatives evaluated," not as the
> current recommendation.

### 1 & 3. Running the executable (with specific env vars)

These two go together — env injection is a parameter of how you launch.

| Tool | What it is | Strengths | Weaknesses | Use when |
|------|------------|-----------|------------|----------|
| **`subprocess`** (stdlib) | Built-in process API (`run`, `Popen`, `PIPE`) | Zero deps; full control over fds/pipes/env/timeout; `run(..., capture_output=True, env=..., check=True, timeout=...)` covers most needs | Verbose; manual line-streaming; `shell=True` quoting footguns | **Default.** Driving a long-running vendor CLI with precise control |
| **`plumbum`** | Shell combinators + cross-platform paths/env + local/remote (SSH) exec | Cross-platform incl. Windows; `local.env` / `with local.cwd()`; pipe/redirect operators; SSH to remote tool hosts; actively maintained (v1.10, Py 3.9–3.14) | DSL learning curve; operator-overloading can obscure intent | Cross-platform wrapper, or the tool runs on a remote host over SSH |
| **`invoke`** (pyinvoke) | Task runner with high-level `run()` | `pty=True` fixes child buffering and handles interactive/password prompts; watchers/responders; clean `result.stdout`; doubles as a `tasks.py` CLI | Geared to task orchestration, not library embedding; `pty=True` merges stdout/stderr | The tool prompts interactively, or you also want user-facing tasks |
| **`sh`** | "Programs as functions" (`sh.vivado(...)`) | Very terse; built-in streaming (`_iter`); per-call `_env` | **No Windows**; dynamic-attr magic hurts readability/linting | Quick POSIX-only scripts |
| **`sarge`** | Thin subprocess wrapper with shell-like pipelines | Safe command parsing without `shell=True`; pipelines | Niche, low activity | You want pipeline syntax without `shell=True` risk |

**Recommendation:** `subprocess`. Best per concern — output capture: `capture_output=True`;
live streaming: `Popen` line iteration; **env injection: `env=`**; error handling:
`check=True` (raises `CalledProcessError`); interactive prompts: switch to `invoke`'s
`pty=True`.

**Env-injection best practice (matters more than it looks):**

- **Copy, don't start empty.** Use `env = os.environ.copy()` then override only what
  you need. An empty `env={}` strips essentials (notably `PATH`, and `SystemRoot` on
  Windows) and the child will fail mysteriously. Vivado in particular needs `PATH`,
  `LM_LICENSE_FILE` / `XILINXD_LICENSE_FILE`, and its settings-sourced vars.
- **Merge shorthand (3.9+):** `subprocess.run(cmd, env=os.environ | {"FOO": "bar"})`.
- **`env` values are literal** — no shell expansion. Build the final `PATH` yourself.
- Use a **clean/minimal env** only when you deliberately want isolation (reproducible
  runs, avoiding secret leakage); even then include `PATH` (+ `SystemRoot` on Windows).

### 2. Download / cache the executable (if missing or newer)

| Tool | What it is | DL-if-missing/newer? | Integrity | Local cache | Notes |
|------|------------|----------------------|-----------|-------------|-------|
| **`pooch`** | Scientific file/binary fetcher with a hash registry | **Yes** — fetches only if absent **or hash mismatch**; supports versioned cache dirs | **SHA256**/MD5/SHA1 per file | Yes (OS cache dir via `pooch.os_cache`) | Purpose-built for "fetch a binary by version, verify, cache." Custom downloaders allow **auth headers** for gated URLs. The hash *is* the version check |
| **`requests` + manual hash** | DIY: GET, compare stored version/SHA, atomic write | Yes — you implement it | Whatever you code (`hashlib`) | You implement | Max control over auth/ETag/atomic-write/locking; you own the edge cases |
| **`requests-cache`** | Persistent HTTP **response** cache | Caches responses, not a managed binary store | No content hashing | SQLite/Redis/files | Wrong layer for the binary itself; *fine for caching a version-manifest API call* |
| **`mise`** | Rust polyglot tool/version manager (asdf successor) | Yes, declarative `mise.toml` | Cosign/SLSA/attestation via backends | Shared tool cache | External CLI; **registry/public-release oriented** |
| **`aqua`** | Declarative CLI version manager (Go) | Yes, `aqua.yaml`, lazy install | Strong (`aqua-checksums.json`, Cosign/SLSA) | Yes | External CLI; standard registry = **public** GitHub releases |
| **`asdf`** | Plugin-based version manager (shell) | Yes via plugins | Plugin-dependent (inconsistent) | Yes | Superseded by mise |

**Recommendation:** **`pooch`** for caching a vendor binary by version — it's the only
*library* that natively combines download-if-missing-or-changed + SHA256 + a versioned
cache, embeddable straight into the wrapper.

> ⚠️ **Licensed-installer caveat.** `mise`/`aqua`/`asdf` assume freely downloadable
> artifacts from public registries. A licensed installer (auth-gated, cookie/token,
> EULA, sometimes interactive) generally **cannot** be fetched by them without custom
> plugin work. If you must pull from an authenticated vendor URL, use **`pooch` with a
> custom downloader** or **`requests` + manual hash** so you control the auth headers.
> Reserve mise/aqua for managing *helper* CLIs around the tool. In many shops the
> Vivado installer is placed on a shared mount instead of downloaded — then this step
> is just "verify the cached copy's hash and version," which `pooch` also does.

### 4. Configuration from a file (+ env layering)

| Library | Env vars | Config files | Layering (defaults<file<env<CLI) | Validation/typing | Secrets | Best for |
|---------|----------|--------------|-----------------------------------|-------------------|---------|----------|
| **`pydantic-settings`** | Native | `.env`, TOML (incl. `pyproject.toml`), JSON, YAML (via source classes) | Built-in init>env>dotenv>secrets; reorderable via `settings_customise_sources` | **Strong** (Pydantic types, coercion, clear errors) | `SecretStr`, secrets dir (Docker/k8s mounts) | Type-safe app/CLI config — **the default** |
| **`dynaconf`** | Yes (prefix) | TOML/YAML/JSON/INI/py | Layered across files + named environments + env | Optional validators (weaker typing) | **Strong** — `.secrets.*`, encryption, Vault, Redis | Multi-env services, many formats, secret-heavy |
| **`environs`** | Typed (`env.int/bool/list/...`) | `.env` only | Partial (env + `.env`) | Per-field casting | Basic | Lightweight typed env; you own files/CLI |
| **`Hydra` + `OmegaConf`** | Via interpolation (`${oc.env:VAR}`) | YAML config groups | Defaults-list + powerful CLI overrides + sweeps | OmegaConf typing + optional dataclass schemas | None built-in | ML experiments, hierarchical/composable config |
| stdlib `tomllib` / `configparser` | No | TOML (read-only, 3.11+) / INI | Manual | None | None | Zero-dep loading; legacy INI |

**Recommendation:** **`pydantic-settings`** — one typed `Settings` object gives you
*defaults < config file < env < CLI* with validation, which is exactly the
requirement (configuration via a file **and** specific env vars in one model). Step up
to **`dynaconf`** if dev/stage/prod environment layering or built-in secret backends
matter. **Hydra** is excellent but is overkill outside ML experiment sweeps.

The natural flow for the wrapper: load typed settings (defaults < file < env < CLI) →
derive the subset of vars the child needs → `os.environ.copy()` + apply that subset →
`subprocess.run(..., env=that)`.

### 5. Concurrency limiting (the license cap)

**The core distinction:** in-process limiters count slots inside *one* interpreter; a
shared license needs a limiter whose state lives **outside** any single process — in
the filesystem, the OS kernel, or a network service.

**Tier 1 — In-process (single Python process):**

| Mechanism | Notes |
|-----------|-------|
| `concurrent.futures.ThreadPoolExecutor(max_workers=N)` | Best in-process fit — threads block on `subprocess.run`; GIL irrelevant (work is external) |
| `asyncio.Semaphore(N)` | Clean around `await asyncio.create_subprocess_exec`; counter in-memory |
| `threading.BoundedSemaphore(N)` | Manual version of the executor pattern |
| `multiprocessing.Semaphore(N)` | Only spans processes that **descend from the same parent** — *not* general cross-process |

> ❌ **Every Tier-1 option is useless as a global license cap.** Two independent
> invocations / two cron jobs / two hosts each get their own counter of N → you can
> run 2×N, 3×N… simultaneously and blow past the license.

**Tier 2 — Cross-process / cross-host:**

| Tool | Cross-proc | Cross-host | Configurable max | Auto-release on crash | Verdict |
|------|-----------|-----------|------------------|----------------------|---------|
| **`filelock` / `flock(1)` as a mutex** | Yes | Shared FS only (unreliable over NFS) | N=1 natively | **Yes** — kernel drops the lock when the holder dies | Rock-solid for N=1 on one host |
| **`filelock` as a counting semaphore** | Yes | Shared FS only | Yes — acquire 1 of **N named lock files** (`slot_0.lock`…) | **Yes**, *if* each slot is a real OS lock (not a number in a file) | **Best simple multi-seat cap on one host** |
| **POSIX named semaphore (`posix_ipc`)** | Yes (same host) | **No** (kernel object) | Yes (`initial_value=N`) | **No** — a crashed holder permanently leaks a unit; object lingers in `/dev/shm` | True counter, but crash-leak makes it risky without a watchdog |
| **Redis semaphore** (redis-py + Lua, `redis-semaphore`, Redisson) | Yes | **Yes** | Yes | **Yes via TTL** — orphaned slots expire; **must heartbeat-renew** long jobs | **Standard cross-host answer**; cost = running Redis + renewal |
| **GNU `parallel` / `sem`** | Yes | `sem` same host; `parallel` spans hosts via `--sshlogin` | Yes — `sem -j N --id mylicense 'cmd'` | Mostly — tracks PIDs, reclaims dead slots, `--semaphoretimeout` | Zero-code drop-in when orchestrating from the shell |

**Crash-safety summary** (does a dead holder's slot come back?):
- **Reclaims automatically:** `flock`/`filelock` (kernel release — best, but same-host),
  **Redis** (TTL — set TTL > max runtime *and* heartbeat), **GNU `sem`** (PID tracking).
- **Leaks the slot (stale-risk):** `posix_ipc`, and **any home-grown file-counter**
  (a crash between decrement-on-exit corrupts the count forever — use one-lock-file-
  per-slot so the OS owns release).

**Tier 3 — Let a scheduler/workflow own the license token** (best if you already run one):

| Tool | How you express "1 license" | Truly global? | Fit |
|------|-----------------------------|---------------|-----|
| **Slurm** | `Licenses=vivado:N` in `slurm.conf` (or DB-backed remote licenses via `sacctmgr`); jobs `--licenses=vivado:1` queue until free. **23.02+** can sync real usage from FlexLM via an `lmstat` script | **Yes** — and respects seats taken *outside* the cluster | **Best if already on a cluster** — only option aware of external consumers |
| **Snakemake** | `resources: license=1` per rule; cap run with `--resources license=1` (non-mem/disk resources are global by default) | Yes, across the DAG run | Excellent if work is already a Snakemake DAG; no server |
| **Luigi** | `[resources]` `vivado=1`; task `resources={"vivado":1}`, enforced at the central scheduler | Yes | Same ergonomics as Snakemake; needs the scheduler running |
| **Prefect 3** | Global concurrency limit + `with concurrency("vivado_seats", occupy=1):` around the call | Yes (server-side) | Good if already on Prefect; some high-contention race caveats |
| **Dagster** | Concurrency **pools** (`pool="vivado"` + limit) cap ops across runs | Yes | Good if already on Dagster |
| **Dramatiq** | `ConcurrentRateLimiter(backend, "vivado", limit=N)` — a distributed semaphore as a `with` block | Yes (Redis/Memcached) | Best of Celery/RQ/Dramatiq for this; Celery/RQ only via "dedicated queue + fixed worker count" convention |
| **Nextflow** | `maxForks` (per process, not summed) / `executor.queueSize` (all jobs) | No (not license-specific) | Awkward — prefer its Slurm executor + Slurm licenses |

**Always gate on FlexLM too.** `lmutil lmstat -a -c <port>@<server>` reports issued vs.
in-use per feature. A dead-simple guard: before launching, only spawn if
`issued - in_use >= 1`, else sleep/retry. It's a *snapshot* (TOCTOU race if multiple
launchers poll at once), so for concurrent launchers pair it with a real semaphore — or
let Slurm own the counter. This `lmstat` poll is exactly what Slurm 23.02, LSF
`blcollect`, and SGE load sensors do under the hood.

### 6. Installing the wrapper in one command (zero dependencies on the target)

**The hardened requirement:** a single-line install where the target machine needs
**nothing pre-installed — no Python, no pip, no `uv`, no package manager.** (None of
these methods ship the *licensed executable*; they ship **your wrapper**, and the
vendor binary is fetched/cached separately — requirement 2.)

This rules out a whole class of answers, because the obvious candidates are **three
different categories of tool**, and two of them can't meet the bar:

| Candidate | What it *actually* is | Meets "no Python/pip/uv, single line"? |
|-----------|-----------------------|-----------------------------------------|
| **`uv`** | Python runtime + package manager | ❌ requires `uv` on the target |
| **Just** (`casey/just`) | A **command/task runner** (a `make` replacement that runs `justfile` recipes) | ❌ **wrong category** — it doesn't install/distribute your CLI, and `just` itself must be installed first |
| **Devbox** (Jetify) | A **Nix-based dev-environment manager** | ❌ doesn't remove a dependency — it **swaps `uv` for Nix + the Devbox CLI** (auto-installs Nix, adds a `/nix` store + daemon + shell init) |
| **pipx / pip / condax** | Python CLI installers | ❌ all require Python (+ the installer) present |
| **Homebrew / Nix flake** | System package managers | ❌ require `brew` / Nix (ubiquitous, but still a prerequisite) |
| **Standalone binary + `curl \| sh`** | Self-contained executable (Python baked in) delivered by an installer script | ✅ **only `curl`+`sh` needed** — present on every mac/Linux box |

> **Why Just and Devbox are the wrong answer here.** They feel like alternatives to
> `uv` but they aren't substitutable: `uv`/Devbox are *environment provisioners* (put a
> runtime + your package on the machine), while **Just is a task runner** (it executes
> commands *after* something is installed). None is a zero-dependency *delivery*
> mechanism — each assumes itself as a prerequisite. "Zero dependency on the target"
> forces the runtime to move **into the artifact**: ship a binary with Python already
> embedded, so the machine needs nothing.

**The approach that meets it:** a **prebuilt single binary (Python embedded) delivered
by a `curl … | sh` installer** — exactly how rustup, Deno, and Just itself distribute
*themselves*.

```sh
curl -fsSL https://your.host/install.sh | sh   # detects OS/arch, drops a binary in ~/.local/bin
```

Build the binary with one of:

| Builder | Python on target | Notes |
|---------|------------------|-------|
| **PyApp** (`ofek/pyapp`) ⭐ | **None** (with `PYAPP_DISTRIBUTION_EMBED=1` the interpreter is embedded → offline, zero-dep) | Rust bootstrapper; **built-in `pyapp self update`** — satisfies requirement 7 with no extra framework |
| **Nuitka** `--onefile` | **None** | Compiles to C; best runtime speed and hardest to reverse (a plus for a commercial wrapper); slow builds |
| **PyInstaller** `--onefile` | **None** | Fastest to build; small startup-extraction penalty |

> **shiv / PEX do *not* qualify** — they bundle your *dependencies* but still need a
> Python interpreter on the target.

Binaries are built **per OS/arch in CI** (build on macOS for macOS, Linux for Linux).
**Homebrew tap** and a **Nix flake** make fine *secondary* convenience channels, but
require `brew`/Nix so they aren't the zero-dependency baseline.

**Recommendation:** **PyApp binary (embedded interpreter) + a `curl | sh` installer.**
One line, nothing pre-installed, and `pyapp self update` gives you self-update for free
(see §7). `uv` may still be used *internally* at build time — it never appears in the
install path the user runs. (If your fleet *already* standardizes on Nix, a Devbox/Nix
flake is a legitimate reproducibility choice — but it's a deliberate "we run Nix
everywhere" decision, not a zero-dependency install.)

### 7. Self-updating on every run

Updating on *every* invocation is the requirement, but doing it naively makes the tool
slow, fragile offline, and — worst for a licensed/regulated flow — **non-reproducible**.
The fix is to keep the *trigger* "every run" but make the *work* cheap and safe.

**Version check (cheap, every run):**
- Installed version: `importlib.metadata.version("xwrap")` (stdlib).
- Latest version: `GET https://pypi.org/pypi/xwrap/json` → `info.version` (or a private
  index's PEP 691 Simple-API JSON, which more mirrors implement consistently).
- Compare with `packaging.version.Version` — never string-compare (pre/post/dev tags).
- **Throttle with a TTL cache** (store `{last_check, latest_seen}` in
  `platformdirs.user_cache_dir`): skip the network if checked within, say, 24h. This is
  the single most important mitigation — it decouples *check frequency* from *run
  frequency* while still being "on every run."
- **Fail-open:** wrap the check in a short timeout (~2s); any error ⇒ log at debug and
  run the installed version. A slow/broken check must never block an EDA run.

**Applying the upgrade (depends on install method — detect, don't guess):**
- **pipx:** `subprocess.run(["pipx", "upgrade", "xwrap"])`.
- **pip:** `python -m pip install --upgrade xwrap` — but pip-mutating-the-running-env is
  fragile; do it in a subprocess *before* loading heavy code, then re-exec.
- **Standalone binary:** download new artifact → **verify hash + signature** → write to
  a temp file on the same filesystem → `os.replace()` (atomic) → re-exec.
- **Re-exec after any mid-run update:** `os.execv(sys.executable, [sys.executable,
  *sys.argv])`, with a guard env var (e.g. `XWRAP_REEXECED=1`) so you can't loop.

**Frameworks:** **`tufup`** (built on python-tuf) is the strongest choice for *bundled*
binaries — signed metadata, rollback/freeze-attack protection, binary patches.
**PyUpdater is archived in 2026 — its own site points to tufup.** **PyApp** ships a
built-in `self update` if you also use it for packaging. For PyPI/pipx installs, no
framework is needed — a throttled checker that shells out to the package manager is the
norm.

**The reproducibility caveat (decisive here).** Silently swapping the wrapper under a
licensed/qualified build is dangerous. So:
- Honor a **pin** (`XWRAP_PIN=2.3.1`) and an **opt-out** (`XWRAP_NO_AUTO_UPDATE=1`)
  unconditionally.
- **Log every version transition** (old→new, time, source index) and record the
  wrapper version into build/report artifacts for traceability.
- In **CI / regulated contexts, prefer *notify* over silent auto-apply**; reserve true
  auto-apply for interactive/dev use.
- **Lock the update** (exclusive `filelock`/`flock`) so concurrent invocations don't
  corrupt the install mid-swap — if the lock is held, skip and run.

**Recommended pattern (trigger every run, work gated):**

```
if XWRAP_PIN set            -> ensure that version, else hard error
if XWRAP_NO_AUTO_UPDATE     -> run installed                       # opt-out
if reexec guard set         -> clear guard, run                    # post-update
if now - last_check < TTL   -> run installed                       # throttle
try (timeout, fail-open):
    latest = index JSON version ; persist last_check
    if Version(latest) <= installed: run installed
    else:
        acquire exclusive update lock (skip if busy)
        download -> verify hash+signature -> os.replace()          # verified+atomic
        log old->new ; set guard ; os.execv(...)                   # re-exec
except anything: log debug ; run installed                         # fail-open
```

---

## Chosen stack (Rust)

The implementation in [`wrapper-demo/`](wrapper-demo/). Right column notes the Python
alternative that was surveyed, for context.

| Concern | Chosen (Rust) | Surveyed alternative |
|---------|---------------|----------------------|
| Run the exe + inject env | **`std::process::Command`** (inherit env, layer `extra_env`) | `subprocess` (`os.environ.copy()` + overrides) |
| Download/cache by version | **`ureq` + `sha2`**, atomic write, versioned cache | `pooch` |
| Config — recipes | **build-time `commands.toml`** via `build.rs` + `include_str!` (validated at compile) | (n/a — Python had runtime-only config) |
| Config — ops settings | **`figment`** (`config.toml` + `XWRAP_*`) | `pydantic-settings` |
| Concurrency cap — **1 host** | **`fs2` flock** over N seat files | `filelock` / `sem -j N --id` |
| Concurrency cap — **many hosts** | Redis counting semaphore (TTL + heartbeat) | same |
| Concurrency cap — **on a cluster** | Slurm `--licenses` (+ `lmstat` sync) | same |
| Safety net | **`lmstat` pre-check** before every launch (`license.rs`) | same |
| Single-line, zero-dep install | **static binary in Nexus raw repo + `curl \| sh`** | PyApp binary (embedded Python) + `curl \| sh` |
| Self-update on run | **`update.rs`** vs Nexus `latest/VERSION` | `pyapp self update` / `tufup` |

### Pragmatic default for "wrap Vivado, 1–2 seats, one build server"

**Build:** `cargo build --release` produces a ~2 MB static `xwrap` with the command
recipes baked in from `commands.toml`. Publish it to a **Nexus raw repo** with
`publish-to-nexus.sh`. **Install (zero-dependency):**
`curl -fsSL https://nexus/.../install.sh | sh` drops the binary in `~/.local/bin` —
no Python/pip/uv/cargo on the target. **Each run:** throttled version check (TTL,
fail-open) honoring `XWRAP_PIN` / `XWRAP_NO_AUTO_UPDATE`, self-update + re-exec when a
newer version exists → load `figment` config → `ureq`/`sha2` verify/cache the wrapped
binary → acquire one of `N` `fs2` seat-locks (N = seats) **and** confirm `lmstat` shows
a free seat → `std::process::Command` with a curated env. No broker, no scheduler,
crash-safe, the cap is a single configurable number. Graduate to a Redis semaphore
(multi-host) or Slurm (cluster) when more than one machine launches runs, and to
**`tufup`** if you need cryptographically signed updates.

---

## Sources

**Rust implementation (chosen)**
- [`std::process::Command`](https://doc.rust-lang.org/std/process/struct.Command.html) ·
  [ureq](https://docs.rs/ureq/) · [sha2](https://docs.rs/sha2/) ·
  [fs2 (file locks)](https://docs.rs/fs2/) · [figment (config layering)](https://docs.rs/figment/) ·
  [clap (builder API)](https://docs.rs/clap/) · [semver](https://docs.rs/semver/)
- [Cargo build scripts (`build.rs`)](https://doc.rust-lang.org/cargo/reference/build-scripts.html) ·
  [`include_str!`](https://doc.rust-lang.org/std/macro.include_str.html) ·
  [`cross` (cross-compilation)](https://github.com/cross-rs/cross) ·
  [Sonatype Nexus raw repositories](https://help.sonatype.com/en/raw-repositories.html) ·
  [tufup (signed self-update)](https://github.com/dennisvang/tufup)

**Running executables / env (surveyed)**
- [subprocess docs](https://docs.python.org/3/library/subprocess.html) ·
  [CPython #120836: copy os.environ for subprocess env](https://github.com/python/cpython/issues/120836)
- [plumbum docs](https://plumbum.readthedocs.io/) ·
  [Invoke FAQ (pty/output)](https://www.pyinvoke.org/faq.html) ·
  [sh on PyPI](https://pypi.org/project/sh/) · [sarge](https://sarge.readthedocs.io/)

**Download / cache**
- [pooch](https://pypi.org/project/pooch/) ·
  [pooch hashes](https://www.fatiando.org/pooch/latest/hashes.html) ·
  [requests-cache](https://requests-cache.readthedocs.io/) ·
  [mise dev-tools](https://mise.jdx.dev/dev-tools/) ·
  [aqua checksum verification](https://aquaproj.github.io/docs/reference/security/checksum/) ·
  [asdf](https://asdf-vm.com/guide/getting-started.html)

**Config / env**
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) ·
  [Dynaconf](https://www.dynaconf.com/) · [environs](https://pypi.org/project/environs/) ·
  [python-dotenv](https://pypi.org/project/python-dotenv/) · [Hydra](https://hydra.cc/docs/intro/) ·
  [tomllib](https://docs.python.org/3/library/tomllib.html)

**Concurrency / locks**
- [py-filelock](https://py-filelock.readthedocs.io/) ·
  [GNU Parallel `sem`](https://www.gnu.org/software/parallel/sem.html) ·
  [posix_ipc](https://semanchuk.com/philip/posix_ipc/) ·
  [Redis distributed locks](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/) ·
  [dv/redis-semaphore](https://github.com/dv/redis-semaphore) ·
  [Python threading (BoundedSemaphore)](https://docs.python.org/3/library/threading.html)

**Install / distribution**
- [PyApp (standalone binary + `self update`)](https://ofek.dev/pyapp/latest/) ·
  [PyApp repo](https://github.com/ofek/pyapp) ·
  [rustup `curl|sh` pattern](https://rust-lang.github.io/rustup/installation/other.html) ·
  [Deno install script](https://docs.deno.com/runtime/getting_started/installation/) ·
  [PyInstaller vs Nuitka vs shiv vs PEX](https://pyoxidizer.readthedocs.io/en/stable/pyoxidizer_comparisons.html)
- *Ruled out for zero-dep install:*
  [Just — it's a command runner](https://github.com/casey/just) ·
  [Devbox needs Nix (Jetify FAQ)](https://www.jetify.com/docs/devbox/faq) ·
  [pipx (needs Python)](https://pipx.pypa.io/stable/explanation/comparisons/) ·
  [Homebrew tap (needs brew)](https://docs.brew.sh/How-to-Create-and-Maintain-a-Tap) ·
  [condax (needs conda)](https://github.com/mariusvniekerk/condax)

**Self-update**
- [tufup (TUF-based updater)](https://github.com/dennisvang/tufup) ·
  [python-tuf](https://pypi.org/project/tuf/) ·
  [PyUpdater archived → migrate to tufup](https://www.pyupdater.org/upgrading/) ·
  [PyApp self-update](https://ofek.dev/pyapp/latest/) ·
  [PyPI JSON API](https://docs.pypi.org/api/json/) ·
  [importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html) ·
  [packaging.version](https://packaging.python.org/en/latest/discussions/versioning/) ·
  [pipx upgrade is shallow](https://jamescooke.info/pipxs-upgrade-is-shallow-lets-go-deeper.html)

**License-aware schedulers / workflows**
- [Slurm Licenses (incl. 23.02 FlexLM lmstat sync)](https://slurm.schedmd.com/licenses.html) ·
  [Snakemake resources](https://snakemake.readthedocs.io/en/stable/snakefiles/rules.html) ·
  [Luigi resources](https://luigi.readthedocs.io/en/stable/configuration.html) ·
  [Prefect global concurrency limits](https://docs.prefect.io/v3/how-to-guides/workflows/global-concurrency-limits) ·
  [Dagster concurrency pools](https://docs.dagster.io/guides/operate/managing-concurrency/concurrency-pools) ·
  [Dramatiq rate limiters](https://dramatiq.io/cookbook.html) ·
  [Nextflow process directives](https://www.nextflow.io/docs/latest/reference/process.html) ·
  [LSF License Scheduler](https://www.ibm.com/docs/SSWRJV_10.1.0/lsf_config_ref/lsf.licensescheduler.5.html) ·
  [SGE FLEXlm integration](http://wiki.gridengine.info/wiki/index.php/Olesen-FLEXlm-Integration) ·
  [FlexLM lmstat usage](https://www.ibm.com/support/pages/retrieve-license-information-using-lmstat)
