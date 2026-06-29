# HITL Bench Access — Tier 1 Demo

A runnable demo of the **Tier 1** solution from [`../HITL_APPROACH.md`](../HITL_APPROACH.md):
restrict an SSH-accessed hardware-in-the-loop (HIL) bench so that **only one accessor
(interactive user *or* CI/CD run) holds it at a time**, with a **hard wall-clock time
limit** that auto-logs-off and frees the bench for the next in line.

It is a single SSH-server container where every login is forced through a wrapper that:

1. takes a **blocking `flock`** on a local lockfile — mutual exclusion, second accessor
   **queues and waits**;
2. runs the session under a **hard cap** — auto-logoff + bench release at the deadline;
3. **releases automatically** when the session ends *or crashes* (kernel drops the lock).

> **Fidelity note.** On a real systemd host the wrapper uses
> `systemd-run --scope -p RuntimeMaxSec` (as in the doc). Inside this container there is
> no systemd, so it transparently falls back to GNU `timeout` — the alternative the doc
> lists. The wrapper auto-detects which to use, so the *behavior* is identical.

---

## Prerequisites

- Docker with Compose v2 (`docker compose`)
- An `ssh` client (built in on macOS/Linux)

## Quick start

From this directory:

```bash
docker compose up --build -d      # build + start the bench
docker compose logs -f bench      # (optional) watch sshd / acquire-release events
```

The demo user is **`dev`** / password **`dev`**, on port **2222**.

To avoid `known_hosts` churn (host keys are regenerated each rebuild), use this form —
the rest of the tutorial assumes it:

```bash
alias benchssh='ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null dev@localhost'
```

Then:

```bash
benchssh        # enter password: dev
```

You should see `=== HIL bench ACQUIRED by dev from ... ===`. You now hold the bench.

When you're done, `exit` (or just wait for the time limit). Tear everything down with:

```bash
docker compose down
```

---

## Walkthrough

### 1. Mutual exclusion + queue/wait (one accessor at a time)

- **Terminal A:** `benchssh` → you get the bench.
- **Terminal B:** `benchssh` → instead of a second shell you see:

  ```
  HIL bench is BUSY — held by: dev from 172.x.x.x since 2026-06-28T...
  Waiting up to 120s for your turn...
  ```

  Terminal B is now **queued**, blocked on the lock.
- Back in **Terminal A**, type `exit`. Within a moment **Terminal B acquires the bench**
  and gets its shell.

This is the core guarantee: only one session is ever *inside* the bench; everyone else
waits in line (up to `HIL_QUEUE_TIMEOUT`).

### 2. Hard time limit (auto-logoff, not idle-based)

The cap is **wall-clock**, not an idle timeout — it fires even while you're busy.

- `benchssh`, then run something that keeps the shell busy:

  ```bash
  sleep 999
  ```

- Do nothing else. About **30s** after login (`HIL_MAX_SESSION`) you are forcibly
  dropped back to your local prompt, and the server log shows
  `>>> Time limit reached — session terminated.` followed by `=== HIL bench released. ===`.

Because a *busy* command is killed too, this proves it is a true hard cap — unlike
`TMOUT`, which only counts idle time and would never fire here.

### 3. CI / non-interactive path (same lock)

A CI job doesn't open a shell — it runs a command. The wrapper handles
`$SSH_ORIGINAL_COMMAND` through the **same** lock and cap:

```bash
benchssh 'echo "hello from CI"; hostname; id'
```

If the bench is free it runs immediately; if busy it queues just like an interactive
user. If it waits longer than `HIL_QUEUE_TIMEOUT` it exits **75** (`EX_TEMPFAIL`) so a
CI pipeline can retry. This is exactly how a GitHub Actions step would invoke the bench
(see [`../HITL_APPROACH.md`](../HITL_APPROACH.md) Tier 2 for the runner side).

Try the contention: hold the bench in Terminal A, then run the CI command in Terminal B
and watch it queue, then run the instant A exits.

### 4. Crash-safe release

The lock is owned by an open file descriptor, so a disconnect frees it — no stale lock,
no stuck bench. Release happens when the **server-side** session exits, so sshd must
notice the client is gone.

- **Terminal A:** `benchssh` → acquire the bench, then start something long: `sleep 999`.
- **Terminal B:** `benchssh` → it starts waiting.
- Close Terminal A's window (or kill its `ssh` process) instead of typing `exit`.
- **Terminal B acquires the bench** the moment A's session is reaped: the interactive
  (PTY) session receives a hangup on window close and dies immediately, the kernel drops
  the `flock`, and B proceeds in ~0s.

How each disconnect type is handled:

| Disconnect | How the session is reaped | Speed |
|------------|---------------------------|-------|
| Clean close of an interactive (PTY) session | PTY hangup → `SIGHUP` (propagated by `timeout --foreground`) | Immediate |
| Crash / `kill -9` / dead network | sshd `ClientAlive` probes go unanswered → connection torn down | ~10-15s (real host) |
| Anything sshd fails to detect | **The hard time cap** terminates the session | ≤ `HIL_MAX_SESSION` |

The hard cap is the universal backstop: even if a disconnect is never detected, the bench
*always* frees within `HIL_MAX_SESSION`. That layered guarantee is the point.

> **Docker Desktop (macOS/Windows) caveat.** Its VM network proxy can keep a dead TCP
> connection looking alive, so the crash/`kill -9` case may not be detected by
> `ClientAlive` and instead falls back to the hard-cap backstop. On a native Linux host
> (where a real bench runs) the FIN/RST and `ClientAlive` reaping work as described. The
> interactive clean-close path and the hard cap work everywhere.

---

## Inspect & administer

```bash
# Who currently holds the bench?
docker compose exec bench cat /run/hil/holder

# What process is holding the lock (admin break-lock view)?
docker compose exec bench fuser -v /run/hil/bench.lock

# A shell on the host side (bypasses the wrapper) for troubleshooting:
docker compose exec bench bash
```

To reclaim a wedged bench in production you kill the holding **session** (the kernel then
frees the lock) rather than deleting the lockfile.

## Tuning

Edit `compose.yaml` and re-apply:

```yaml
environment:
  HIL_QUEUE_TIMEOUT: "120"   # how long a waiter stays in line (seconds)
  HIL_MAX_SESSION: "30"      # hard cap per session (seconds)
```

```bash
docker compose up -d         # recreate with new values
```

## How this maps to a real bench

| Demo | Production (real HIL host) |
|------|----------------------------|
| `timeout` enforces the cap | `systemd-run --scope -p RuntimeMaxSec` (auto-detected when systemd is present) |
| Password `dev`/`dev` | SSH **keys**; real users added to the `hil` group |
| Lock at `/run/hil/bench.lock` (container tmpfs) | Lock on a **local** filesystem (never NFS) |
| One container = one bench | One host per bench; pin one GitHub Actions self-hosted runner to it |

The wrapper (`hil-session`), the sshd drop-in (`hil.conf`), and the `Match Group hil` /
`ForceCommand` pattern transfer directly to a real host — that is the whole point of
Tier 1: **no new infrastructure**.

## Files

| File | Role |
|------|------|
| `Dockerfile` | SSH server image with `flock`/`timeout`, the `hil` group, and demo user |
| `compose.yaml` | Builds the image, maps port 2222, sets the two tunables |
| `hil.conf` | sshd drop-in: `Match Group hil` → `ForceCommand` wrapper |
| `hil-session` | The wrapper: blocking `flock` + hard cap, interactive & CI paths |
| `entrypoint.sh` | Prepares `/run`, host keys, tunables; launches `sshd` |

## Cleanup

```bash
docker compose down
```
