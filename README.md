# follow-up

Work Items
- UV vs Poetry: Document why UV is better than Poetry
- Wrapper: Find best option for wrapper around Xilinx with cache and limited concurrency usage (1 license)
- HITL queue: Create queue automation for ssh for HITL testing bench.
- HITL sim: Developers need a hardware simulatior for fin controller with instrumentation

Each work item below has a short summary and a link to its full write-up or runnable
reference implementation.

---

## 1. Python tooling — package & environment managers

A survey of Python package/environment managers (Astral **uv**, **Poetry**, PDM, Hatch,
Pipenv, Rye, Conda/Mamba, pip) covering dependency resolution, lockfiles, interpreter
version management, and build/publish. **Bottom line: use `uv` for new work in 2026** —
it's 10–100× faster than the alternatives and replaces a half-dozen tools (pip, pip-tools,
pipx, pyenv, virtualenv, build, twine) with one Rust binary. Poetry remains a fine choice
for teams already on it; migration to uv is straightforward via `pyproject.toml`. The doc
also gives per-use-case picks (new app, PyPI library, data-science/GPU, monorepo, test
matrices) and a feature comparison table.

Full survey: **[`PYTHON_TOOLING.md`](PYTHON_TOOLING.md)**

Related design docs:
- **[`COMMAND_WRAPPER_APPROACH.md`](COMMAND_WRAPPER_APPROACH.md)** — survey of options for
  wrapping a licensed executable and the **Rust-only** decision.
- **[`docs/superpowers/specs/2026-06-28-xilinx-command-wrapper-design.md`](docs/superpowers/specs/2026-06-28-xilinx-command-wrapper-design.md)**
  — design of the Rust wrapper implementation.

---

## 2. `wrapper-demo` — `xwrap`, a command wrapper for a licensed tool

A runnable Rust reference implementation that wraps a licensed CLI (e.g. Xilinx
Vivado/Vitis) as a single **~2 MB static binary with no Python/pip/uv at build or run
time**. Command *recipes* are baked into the binary at compile time (`commands.toml`,
validated by `build.rs`); per-machine ops settings load at runtime (`config.toml` +
`XWRAP_*`). It covers every requirement from the work item:

- **Cached + verified download** of the wrapped tool (SHA256, cached per version).
- **Cross-process concurrency cap** sized to your license seats — N `flock` lock-files,
  crash-safe (the kernel frees a seat if a holder dies).
- **`lmstat` license gate** — catches seats consumed by others outside the wrapper.
- **Self-update on run** from a **Nexus raw repo**, plus a `curl | sh` one-liner install
  that needs only `curl`/`sh` on the target.

Summary of the install flow and how to swap in the real toolchain (edit `commands.toml` +
`config.toml`, then rebuild) is in the demo's README.

Full details + quick start: **[`wrapper-demo/README.md`](wrapper-demo/README.md)**

```bash
cd wrapper-demo
cargo build --release                              # -> target/release/xwrap (~2 MB, no interpreter)
cp config.example.toml config.toml && chmod +x mocks/*.sh
./target/release/xwrap list                        # baked-in recipes (subcommands)
./target/release/xwrap synth --config config.toml -- --extra-flag
```

---

## 3. `hitl-access-demo` — SSH queue/access control for a HIL bench

A runnable demo of the **Tier 1** SSH-access solution from
[`HITL_APPROACH.md`](HITL_APPROACH.md): restrict an SSH-accessed hardware-in-the-loop
bench so that **only one accessor (interactive user *or* CI/CD run) holds it at a time**,
with a **hard wall-clock time limit** that auto-logs-off and frees the bench for the next
in line. It's a single SSH-server container where every login is forced through a wrapper
that:

- takes a **blocking `flock`** for mutual exclusion — a second accessor **queues and
  waits**;
- runs the session under a **hard wall-clock cap** (kills even *busy* commands, unlike
  `TMOUT`), auto-logging-off at the deadline;
- **releases automatically** when the session ends or crashes (the kernel drops the lock).

The same lock/cap handles the **CI / non-interactive path** (`$SSH_ORIGINAL_COMMAND`),
exiting `75` (`EX_TEMPFAIL`) on queue timeout so a pipeline can retry. The README includes
a hands-on walkthrough (mutual exclusion, hard cap, CI path, crash-safe release) and a
mapping from the demo to a real systemd-based bench.

Full details + quick start: **[`hitl-access-demo/README.md`](hitl-access-demo/README.md)**

---

## 4. `hitl-sim-demo` — per-developer fin-controller simulator

A runnable reference implementation of a cheap, per-developer **Hardware-in-the-Loop
simulator** for a fin actuator, so embedded software can be integration-tested — with
fault injection and full instrumentation — *before* the scarce, expensive real actuator is
touched. It runs today as **pure software** (stdlib only, deterministic, CI-friendly) and
is structured so the **same code deploys to a Raspberry Pi bench unchanged** by swapping
only the transport layer. It demonstrates:

- a **fin-actuator plant model** (second-order servo with rate/position limits);
- a **nine-fault injection menu** (gain, offset, hard-over, stuck-at, delay, noise,
  packet-loss, drift, spike) applied at the bus boundary;
- a **DUT controller stand-in** with a model-based safety monitor, so each fault must drive
  the controller to a safe state within a deadline;
- **deterministic instrumentation** (CSV/JSONL traces + behavioral oracles like
  time-to-safe-state) and a **MIL/SIL → CI → Pi** tiering (pytest + Robot Framework).

Full details + quick start: **[`hitl-sim-demo/README.md`](hitl-sim-demo/README.md)**

```bash
cd hitl-sim-demo
uv run hitl-sim list
uv run hitl-sim run hard_over --log hard_over.csv
uv run pytest -q
```
