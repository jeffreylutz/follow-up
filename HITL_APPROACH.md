# HITL Bench Access Approach

Options for restricting access to a **hardware-in-the-loop (HIL) test host** so that:

1. **Only one accessor at a time** holds the bench — whether that accessor is an
   **interactive SSH user** or a **CI/CD run** (the two must contend for the *same*
   single slot, not separate ones).
2. Each session has a **hard wall-clock time limit** — when it expires the session is
   **auto-logged-off** and the bench is **released/reset** so the next accessor can run.

The concrete driver (see `README.md`) is "create queue automation for ssh": a single
HIL bench shared by a handful of developers and a **GitHub Actions** pipeline, where a
second accessor should **queue and wait** for the bench rather than be rejected.

_Last updated: June 2026._

---

## TL;DR

- **The chokepoint that matters:** both humans and CI reach the bench **over SSH**, so
  put the lock there — an **`flock` inside an sshd `ForceCommand` wrapper**. One gate
  governs *both* accessor types. CI-native concurrency only serializes CI-vs-CI and
  **cannot** stop a human SSHing in directly, so it's a complement, not the gate.
- **Mutual exclusion + queue/wait:** **blocking `flock -w <queue_timeout>`** on a local
  lockfile. Second accessor blocks ("held by X since Y"), then proceeds when free. The
  **kernel auto-releases** the lock when the holder disconnects or crashes → no stuck
  bench. Sharp edges: `flock` is **not strictly FIFO-fair**, and the lockfile must live
  on a **local** filesystem (unreliable over NFS).
- **Hard time limit (the real requirement):** **`systemd-run --scope -p
  RuntimeMaxSec=<max>`** around the session — systemd kills the scope at the deadline
  regardless of activity, the `flock` releases with it, and the next accessor proceeds.
  Alternatives: `timeout <max> bash` or a backgrounded `at` kill.
- **⚠️ `TMOUT` does NOT meet the requirement.** It's an **idle** timeout that resets on
  every keystroke and is defeated by `vi`/long jobs. Use it only as an *extra* idle
  reaper layered on top of the hard cap, never as the hard cap itself.
- **GitHub Actions side:** a **single self-hosted runner pinned to the bench** (+ a
  `concurrency:` group) so CI runs flow through the *same* SSH lock as humans and queue
  naturally.
- **Graduate when you outgrow one bench:** **Jumpstarter** (a *lease* = time-limited
  exclusive reservation; TTL is the hard limit; native CI **and** interactive) or
  **labgrid** (place reservation + lock). Reach for **Teleport/Boundary** only if you
  need enterprise access *governance* (audit, short-lived certs), not just a lock.

---

## The two requirements are orthogonal

It's worth separating the two jobs, because different mechanisms own each and the common
mistake is to solve one and assume it covers the other:

| Requirement | What it means | Wrong tool people reach for | Right primitive |
|-------------|---------------|------------------------------|-----------------|
| **(A) Mutual exclusion** | One accessor at a time, **interactive or CI**, on one shared slot | CI concurrency alone (ignores humans); `MaxSessions` (limits per-connection channels, not one-user-total) | A **lock at the SSH chokepoint** (`flock` in `ForceCommand`) |
| **(B) Hard time limit** | Wall-clock cap that frees the bench on expiry | `TMOUT` (idle only; resets on activity) | **`systemd RuntimeMaxSec`** / `timeout` / `at` kill |

The unifying realization: an interactive developer and a GitHub Actions job **both arrive
over SSH**. So the cheapest correct design makes the SSH entry the single chokepoint —
acquire the lock there, start the timer there, and *both* accessor types are governed by
one mechanism. Anything that gates only the CI path (or only interactive logins) leaves a
hole.

---

## Option tiers

### Tier 1 — DIY on the host (recommended start)

Everything runs on the bench host itself; no new services.

**Mutual exclusion** — an sshd **`ForceCommand`** wrapper applied to the bench-access
account/group via a `Match Group` block. The wrapper grabs an exclusive `flock` before
doing anything; CI runs (which pass a command in `$SSH_ORIGINAL_COMMAND`) and interactive
logins (no command) both route through it.

| Choice | Behavior | When |
|--------|----------|------|
| `flock -n` (non-blocking) | **Reject** immediately if busy ("bench in use by X until Y") | Simplest; if callers should fail fast |
| **`flock -w <secs>` (blocking, bounded)** | **Queue/wait** up to a cap, then proceed or give up | **Our pick** — matches the "second accessor waits" requirement |

- **Crash-safe:** an `flock(2)` lock is owned by the open file descriptor; the **kernel
  releases it automatically** when the holding process exits or the SSH connection drops.
  No stale locks, no "stuck bench."
- **Sharp edges:** `flock` does **not guarantee FIFO fairness** — a waiter is not
  guaranteed to win in arrival order. And `flock` is **unreliable over NFS**; keep the
  lockfile on a **local** filesystem (e.g. `/run/hil-bench.lock`).

**Hard time limit** — wrap the granted session so wall-clock time is capped:

| Mechanism | How | Notes |
|-----------|-----|-------|
| **`systemd-run --scope -p RuntimeMaxSec=<max>`** | systemd tracks the session as a transient scope and **kills it at the deadline**; the `flock` releases with the process tree → next accessor proceeds | **Preferred** — crash-safe, integrates with login session tracking. Caveats: suspended time isn't counted toward the limit; confirm behavior on the host's systemd version |
| `timeout <max> bash -l` | Wrap the shell directly | Simple, no systemd dependency; less clean for backgrounded children |
| `( sleep <max>; kill … ) &` via `at`/background | Schedule a kill of the session leader | Most manual; easy to leak the killer if the session ends early |
| `TMOUT` (shell) | Idle reaper only | **Not a hard cap.** Optionally layer on top to also reclaim idle holders |

**Verdict:** covers **both** accessor types at one chokepoint, gives **queue/wait**, is
**crash-safe**, and needs **zero new infrastructure**. Best place to start for one bench.

### Tier 2 — GitHub Actions concurrency (complement, CI-only)

Governs the *CI side* so automated runs don't pile onto the bench — but it does **not**
replace Tier 1, because it can't see interactive humans.

- **Single self-hosted runner pinned to the bench** (dedicated label, e.g.
  `runs-on: [self-hosted, hil-bench]`). With one runner, GitHub Actions jobs **queue
  naturally** — a second job waits until the runner is free.
- Add a workflow **`concurrency:`** group to collapse redundant queued runs (note: GitHub
  `concurrency` tends to *cancel*/limit rather than strict FIFO-queue, so rely on the
  single-runner serialization for ordering).
- **Limitation:** serializes **CI vs CI** only. A developer SSHing in directly is invisible
  to it — which is exactly why the **Tier-1 host lock remains the unifying gate**. CI runs
  should still go through the same SSH wrapper so they contend on the one real lock.

### Tier 3 — Purpose-built HIL reservation / lease frameworks (graduation path)

When a second bench appears, or you need fair FIFO, priorities, notifications, or audit:

| Framework | Exclusivity model | Hard time limit | CI + interactive | Weight |
|-----------|-------------------|-----------------|------------------|--------|
| **Jumpstarter** | A **lease** = time-limited reservation with **exclusive** access to an exporter | **Yes — lease TTL is the built-in cap** | Yes — integrates with CI/CD and local/interactive; local mode or K8s/OpenShift controller | Medium; closest off-the-shelf match to *both* requirements |
| **labgrid** (+ coordinator) | **Place reservation + lock**; only the reservation owner can lock the place | Reservation **times out** if not refreshed/used | Yes — designed to share places between developers and CI jobs | Medium; great for embedded board control |
| **LAVA** | Scheduler owns devices; jobs queued and dispatched | Per-job, scheduler-enforced | CI/job-oriented; weaker for interactive dev shells | Heavy; full scheduler + board admin + web UI |

**Verdict:** the "proper" answer at fleet scale. Jumpstarter in particular gives you
exactly *exclusive + TTL + CI + interactive* without hand-rolling the wrapper — adopt it
when the DIY lock's lack of fairness/visibility starts to hurt.

### Tier 4 — Access brokers / bastions (enterprise governance)

| Tool | What it adds | Fit for "one at a time + hard limit" |
|------|--------------|--------------------------------------|
| **Teleport** | Short-lived certs, session recording/audit, RBAC, session TTL | Strong on *governance*; exclusivity-to-one isn't a native primitive — you'd still enforce the single slot via a lock |
| **HashiCorp Boundary** | Brokered access, dynamic creds via Vault, session controls | Same caveat; max-session-limit has historically been a feature request, not a turnkey "only one" |
| **StrongDM** | Managed access plane, audit | Same — access control, not bench mutual-exclusion |

**Verdict:** pick these when you need **access governance** (who/when/audit, short-lived
credentials) as a separate requirement — not as the way to enforce "only one accessor."

---

## Comparison across tiers

| Approach | Covers interactive? | Covers CI? | Queue/wait? | Hard time limit? | Crash-safe / auto-release? | New infra? | Fair FIFO? | Best for |
|----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|----------|
| **T1: flock ForceCommand + systemd RuntimeMaxSec** | ✅ | ✅ (via same SSH) | ✅ (`-w`) | ✅ (systemd) | ✅ | None | ⚠️ no | **One bench, start here** |
| **T2: GitHub single runner + concurrency** | ❌ | ✅ | ✅ (runner busy) | ❌ (job-level only) | ✅ | None | ~ | Serializing CI runs only |
| **T3: Jumpstarter / labgrid** | ✅ | ✅ | ✅ | ✅ (lease TTL) | ✅ | Coordinator/controller | ✅ | Multiple benches, audit, priorities |
| **T3: LAVA** | ~ | ✅ | ✅ | ✅ | ✅ | Server + web UI | ✅ | Board farm / fleet |
| **T4: Teleport / Boundary** | ✅ | ✅ | ❌ (not native) | ✅ (cert/session TTL) | ✅ | Broker + (Vault) | n/a | Enterprise access governance |

---

## Recommendation — what to start with and why

**Start with Tier 1, complemented by the Tier-2 runner setup.**

1. **sshd `ForceCommand` wrapper** on the bench-access group that takes a **blocking
   `flock -w <queue_timeout>`** on a local lockfile — this *is* the "queue automation":
   a second accessor waits (with a "held by *user* since *time*" message), then proceeds
   when the bench frees. It launches the session under **`systemd-run --scope -p
   RuntimeMaxSec=<max>`** so the bench is **hard-released on the deadline regardless of
   activity**, and handles both the interactive shell and the `$SSH_ORIGINAL_COMMAND`
   CI path.
2. **A single self-hosted GitHub Actions runner pinned to the bench** (+ a `concurrency:`
   group) so CI runs flow through the *same* SSH lock as humans and queue naturally.

**Why start here:**

- **One primitive gates both accessor types** at the only shared chokepoint (SSH) —
  the single requirement that CI tools alone can't satisfy.
- **Crash-safe by construction:** the kernel releases the `flock` on disconnect, and
  systemd enforces the timer — the bench resets exactly as required, even if a session
  dies unexpectedly.
- **Zero new infrastructure** for a single host, matching the lightweight reality and the
  style of the sibling Vivado wrapper work.
- It directly delivers the two stated behaviors: **queue/wait** (blocking lock) and a
  **hard auto-logoff that resets the bench** (systemd cap).

**Know the two sharp edges going in:** `flock` is **not strictly FIFO-fair** (if true
arrival-order fairness matters, use a ticket queue or move to Jumpstarter), and the
lockfile **must stay on a local filesystem**.

**Graduate to Jumpstarter** (leases = exclusive + TTL, native CI **and** interactive) the
moment a second bench appears or you need fair FIFO, priorities, notifications, or audit.
Reach for **Teleport/Boundary** only if enterprise access governance becomes a separate
requirement.

### Illustrative wrapper sketch

> Skeleton only — not production-hardened. Validate paths, escaping, and the systemd
> version's `RuntimeMaxSec` behavior on the actual host before relying on it.

`/etc/ssh/sshd_config` (append):

```sshd_config
Match Group hil
    ForceCommand /usr/local/sbin/hil-session
    PermitTTY yes
    X11Forwarding no
    AllowTcpForwarding no
```

`/usr/local/sbin/hil-session`:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOCK=/run/hil-bench.lock          # local fs only — NOT NFS
QUEUE_TIMEOUT=${HIL_QUEUE_TIMEOUT:-1800}   # how long to wait in line (s)
MAX_SESSION=${HIL_MAX_SESSION:-3600}       # hard wall-clock cap (s)

exec 9>"$LOCK"
echo "Waiting for HIL bench (up to ${QUEUE_TIMEOUT}s)..." >&2
if ! flock -w "$QUEUE_TIMEOUT" 9; then
    echo "Bench still busy after ${QUEUE_TIMEOUT}s — giving up." >&2
    exit 75   # EX_TEMPFAIL: tells CI to retry later
fi

# We hold the lock on fd 9. Stamp who/when for the next person's message.
printf '%s since %s\n' "${USER:-unknown}" "$(date -Is)" >"${LOCK}.holder" || true
echo "Bench acquired. Hard limit: ${MAX_SESSION}s." >&2

# Run under a systemd scope so the deadline is enforced regardless of activity.
# When the scope dies, this process exits, fd 9 closes, the kernel frees the lock.
if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
    exec systemd-run --user --scope -p RuntimeMaxSec="$MAX_SESSION" \
        /bin/bash -lc "$SSH_ORIGINAL_COMMAND"        # CI/CD path
else
    exec systemd-run --user --scope -p RuntimeMaxSec="$MAX_SESSION" \
        /bin/bash -l                                  # interactive path
fi
```

**Admin break-lock:** because the lock is just an fd on `/run/hil-bench.lock`, an operator
can inspect holders with `fuser -v /run/hil-bench.lock` (or `lslocks`) and reclaim a wedged
bench by killing the offending session leader — the kernel then frees the lock. Prefer
killing the session over deleting the lockfile.

---

## Sources

**SSH `ForceCommand` / restricted-shell wrappers**
- [The little known SSH ForceCommand (shaner.life)](https://shaner.life/the-little-known-ssh-forcecommand/) ·
  [How to enforce a forced command for SSH users (simplified.guide)](https://www.simplified.guide/ssh/force-command-user) ·
  [Implementing SSH ForceCommand for restricted shells (DoHost)](https://dohost.us/index.php/2025/09/14/implementing-ssh-forcecommand-for-restricted-shells/)

**`flock` (mutual exclusion / queue)**
- [flock(1) — man7](https://www.man7.org/linux/man-pages/man1/flock.1.html) ·
  [flock — systutorials](https://www.systutorials.com/docs/linux/man/1-flock/) ·
  [discoteq/flock](https://github.com/discoteq/flock/blob/master/man/flock.1.ronn)

**SSH timeouts (why `TMOUT`/`ClientAlive` aren't a hard cap)**
- [Increase SSH connection timeout (tecmint)](https://www.tecmint.com/increase-ssh-connection-timeout/) ·
  [Configure SSH session timeouts (serverauth)](https://serverauth.com/posts/how-to-configure-ssh-session-timeouts) ·
  [Prevent SSH session timeouts (simplified.guide)](https://www.simplified.guide/ssh/disable-timeout)

**Hard wall-clock limit via systemd**
- [systemd.service(5) — RuntimeMaxSec (Debian manpages)](https://manpages.debian.org/experimental/systemd/systemd.service.5.en.html) ·
  [systemd #7830 (status should show time remaining)](https://github.com/systemd/systemd/issues/7830) ·
  [systemd #2697 (RuntimeMaxSec semantics)](https://github.com/systemd/systemd/issues/2697)

**CI/CD concurrency (the complement)**
- [GitHub Actions: self-hosted runners + `concurrency`](https://github.blog/changelog/2023-09-18-increased-concurrency-limit-for-github-hosted-runners/) ·
  [GitLab `resource_group` (concurrency 1 per physical device — contrast)](https://docs.gitlab.com/ci/resource_groups/)

**Purpose-built HIL reservation / lease frameworks**
- [Jumpstarter — glossary (lease = time-limited exclusive reservation)](https://jumpstarter.dev/main/glossary.html) ·
  [Hardware in the Loop with Jumpstarter (ajo.es)](https://ajo.es/2025/10/hardware-in-the-loop-with-jumpstarter/) ·
  [labgrid — usage / reservations](https://labgrid.readthedocs.io/en/latest/usage.html) ·
  [LAVA lab CI example (ci-box/lava-lab)](https://github.com/ci-box/lava-lab)

**Access brokers / bastions (governance, not exclusivity)**
- [Teleport vs HashiCorp Boundary](https://goteleport.com/compare/hashicorp-boundary-alternative/) ·
  [Boundary: max session limitation (issue #4096)](https://github.com/hashicorp/boundary/issues/4096) ·
  [Alternatives to HashiCorp Boundary (StrongDM)](https://www.strongdm.com/blog/alternatives-to-hashicorp-boundary)
