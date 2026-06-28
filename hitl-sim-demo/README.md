# hitl-sim — per-developer HIL/HITL simulator (reference demo)

A runnable reference implementation of the **Tier-1 simulator** described in
[`HITL_SIMULATOR_SUMMARY.md`](./HITL_SIMULATOR_SUMMARY.md): a cheap, per-developer
Hardware-in-the-Loop bench that lets embedded software be integration-tested
against a simulated fin actuator — with fault injection and full instrumentation —
*before* the scarce, expensive real actuator is ever touched.

It runs today as **pure software** (stdlib only, deterministic, CI-friendly) and
is structured so the **same code deploys to a Raspberry Pi bench unchanged** by
swapping only the transport layer. See [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## What it demonstrates

- A **fin-actuator plant model** (second-order servo with rate/position limits).
- The **nine-fault injection menu** (gain, offset, hard-over, stuck-at, delay,
  noise, packet-loss, drift, spike) applied at the *bus boundary*, never touching
  the plant model.
- A **DUT controller stand-in** with a safety monitor — so faults are *meaningful*:
  each fault must drive the controller into safe-state within a deadline. Two
  monitors are included: a naïve `SafetyMonitor` (command-vs-measured threshold)
  and a **model-based `ReferenceModelMonitor`** (default) that compares feedback
  against a shadow plant model, so it tolerates aggressive maneuvers without
  false-tripping yet still catches faults (see the `maneuver` scenario).
- **Deterministic instrumentation**: every run logs ground truth vs. observed
  signals to CSV/JSONL and computes behavioral oracles (time-to-safe-state, etc.).
- The **MIL/SIL → CI → Pi** tiering: the same scenarios run as pytest, as a Robot
  Framework acceptance suite, and (on a Pi) over a real bus.

## Quick start

```bash
cd hitl-sim-demo

# List scenarios
uv run hitl-sim list

# Run one scenario, write a CSV trace
uv run hitl-sim run hard_over --log hard_over.csv

# Run everything, archive per-scenario CSV+JSONL logs (exit!=0 if any misbehaves)
uv run hitl-sim run all --outdir scenario_logs

# Unit + integration tests
uv run pytest -q

# Robot Framework HIL acceptance suite (plain-language tests)
uv run python -m robot --pythonpath robot --outputdir robot_out robot/actuator_hitl.robot

# CAN-transport round-trip test (optional extra; uses python-can's virtual bus)
uv run --with python-can pytest -q tests/test_can_transport.py
```

## Scenarios

| Scenario | Fault | Expected behavior |
|----------|-------|-------------------|
| `nominal` | none | tracks command, never trips |
| `maneuver` | none, aggressive multi-step setpoint | **never trips** (model-based monitor tolerates slews) |
| `hard_over` | feedback forced to +30° rail @0.2s | safe-state < 0.32s |
| `stuck_at` | dead sensor reads 0° @0.2s | safe-state < 0.32s |
| `packet_loss` | total feedback loss @0.2s | safe-state on timeout < 0.30s |
| `sensor_drift` | linear drift @0.2s | safe-state < 0.46s (slower to detect) |

## Layout

```
src/hitl_sim/
  messages.py        transport-independent wire messages
  actuator.py        fin-actuator plant model (pure physics)
  faults.py          nine-fault injection menu (bus boundary)
  transport.py       Transport seam: LoopbackTransport (+ CAN/serial stubs)
  simulator.py       the plant process (runs on the Pi)
  controller.py      DUT stand-in with safety monitor
  loop.py            deterministic fixed-step HIL loop
  instrumentation.py recorder + behavioral oracles + CSV/JSONL export
  scenarios.py       pre-built fault scenarios (shared by CLI + tests)
  cli.py             `hitl-sim` entry point
tests/               pytest unit + integration suite
robot/               Robot Framework acceptance suite + keyword library
ci/                  example GitHub Actions pipeline
```

## From demo to real hardware

This software demo is the **Tier-1** functional simulator. To put it on a real
controller you implement `Transport` over CAN/serial (`pip install
hitl-sim[canbus]` / `[serial]`) and run `PlantSimulator` on the Pi — every other
module is reused verbatim. `ARCHITECTURE.md` has the bill of materials, wiring,
and real-time notes (`PREEMPT_RT`, RP2040 co-processor, external ADC/DAC).

> Scope: this is a **functional / signal-level** model. It does **not** simulate
> electrical/power-level effects (real current, back-EMF, hard-over at the power
> stage) — those remain on the scarce Tier-2 real-hardware bench.
