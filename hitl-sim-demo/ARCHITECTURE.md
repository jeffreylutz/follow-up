# Tier-1 Raspberry Pi HIL Bench — Reference Architecture

This document describes how the software demo in this repo maps onto a real,
cheap, **per-developer** Hardware-in-the-Loop bench. It complements the strategy
in [`HITL_SIMULATOR_SUMMARY.md`](./HITL_SIMULATOR_SUMMARY.md).

## The transport seam (why this works)

Every module talks only to a `Transport` interface. The plant model, fault
injector, controller logic, instrumentation, and the entire test suite are
**transport-agnostic**. Moving from software to hardware changes exactly one
class.

```
            SOFTWARE (CI / laptop)                         HARDWARE (Pi bench)
   ┌────────────┐   LoopbackTransport   ┌────────────┐    CanTransport /
   │ Controller │◄────(in-process)─────►│  Plant     │    SerialTransport
   │  (stand-in)│                       │  Simulator │  ┌──────────────┐  CAN/UART  ┌─────────────┐
   └────────────┘                       └────────────┘  │ PlantSimulator│◄─────────►│ Real DUT    │
        ▲   same hitl_sim package, unchanged   ▲         │  on Pi        │  bus      │ controller  │
        └──────────────────────────────────────┘        └──────────────┘           └─────────────┘
```

## Tiering (recap)

| Tier | Where | What | Hardware |
|------|-------|------|----------|
| 0 — Emulation/SIL | Every dev + CI | Renode/QEMU run production firmware; this demo's software plant | none |
| **1 — Pi HITL bench** | **Every dev** | **Real controller ↔ Pi plant over real bus; signal-level + fault injection** | **Pi + controller** |
| 2 — Real-hardware HIL | Shared, late | Scarce actuator; electrical/power-level + final integration | the expensive actuator |

This repo is the reference for **Tier 1**.

## Hardware topology

```
   ┌──────────────────────────┐        commanded fin angle (CAN / serial / PWM)        ┌───────────────────────────┐
   │  Embedded Controller      │  ───────────────────────────────────────────────►     │  Raspberry Pi              │
   │  (Device Under Test)      │                                                        │  + CAN HAT (MCP2515)       │
   │  production firmware       │  ◄───────────────────────────────────────────────     │  + optional RP2040 / ADC/DAC│
   │                          │        simulated position / rate / status               │                           │
   └──────────────────────────┘                                                        │  runs: PlantSimulator      │
                                                                                        │         FaultInjector      │
                                                                                        │         Recorder           │
                                                                                        └───────────────────────────┘
```

## Bill of materials (per developer, indicative)

| Item | Purpose | Approx cost |
|------|---------|-------------|
| Raspberry Pi 4/5 (4 GB) | runs the plant model, faults, logging | $55–80 |
| CAN HAT (MCP2515 / MCP2518FD) **or** USB-CAN adapter | real CAN bus to the DUT | $15–30 |
| RP2040 board (e.g. Pico) *(optional)* | deterministic PWM/ADC/timing co-processor | $4–6 |
| MCP4728 DAC / ADS1115 ADC *(optional)* | true analog feedback/command signals | $5–10 each |
| Logic level shifters, wiring, connectors | interfacing | $10 |
| **Total** | | **~$90–140** |

Compare to a commercial signal-level HIL seat (dSPACE/Speedgoat/NI/Typhoon):
typically **5–6 figures**, which is why those are shared, not per-developer.

## Real-time considerations

A stock Pi running Linux is **not hard real-time**. Mitigations, in order of need:

1. **`PREEMPT_RT` kernel** + pin the plant loop to an isolated core
   (`isolcpus`, `SCHED_FIFO`) — soft real-time, good to ~1 kHz for this model.
2. **RP2040 / STM32 co-processor** for the truly timing-critical edge: generate
   PWM, sample ADC, and timestamp at deterministic intervals; the Pi runs the
   model + logging and exchanges setpoints with the co-processor.
3. **External ADC/DAC** if the controller exchanges real analog signals rather
   than bus messages.

The fixed step rate in the demo (`dt = 0.004 s`, 250 Hz) matches the ILR-33
AMBER rocket HIL stand from the research; raise/lower to match your control loop.

## Model fidelity & validation (the hidden cost)

The simulator is only as trustworthy as its plant model. Recommended workflow:

1. Characterize the **one** scarce real actuator: step response, rate limit,
   position limit, lag, backlash.
2. Fit `FinActuatorParams` (and extend the model if needed) to that data.
3. **Pin** the validated parameters in version control so every developer's bench
   inherits the same trusted model.
4. Guard the model with regression tests; re-validate against hardware periodically.

> The research explicitly bounds this: software/emulation "can replace a
> substantial portion of HIL but may not fully replace physical hardware
> testing" for real-world/electrical conditions. Keep Tier 2.

## Implementing a hardware transport

A CAN implementation **ships in `transport.py`** (`CanTransport`), satisfying the
same `Transport` interface as the loopback used by the demo/CI. Classic-CAN
encode/decode helpers (`encode_command`/`decode_feedback`, etc.) pack the
messages into 8-byte frames. Install the extra with `pip install hitl-sim[canbus]`.

On the Pi (real socketcan device, or a `vcan0` virtual device for bring-up):

```python
import can
from hitl_sim import CanTransport, PlantSimulator

bus = can.Bus(interface="socketcan", channel="can0")   # or vcan0
sim = PlantSimulator(transport=CanTransport(bus), injector=my_faults)
while True:
    sim.step(now())   # driven by a real-time tick instead of a logical clock
```

Bring up a Linux virtual CAN device for testing without hardware:

```bash
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan && sudo ip link set up vcan0
```

The cross-platform `tests/test_can_transport.py` exercises the same code over
python-can's in-memory `virtual` interface. Nothing else in `hitl_sim` changes —
the actuator model, fault injector, controller, monitor, and tests are reused
verbatim. A `SerialTransport` (pyserial) follows the same pattern.

## Defense / certification caveats (unresolved)

For missile/defense use, the research flagged (but could not source) constraints
that must be resolved before relying on open-source tooling: ITAR/classification
handling, high-fidelity **electrical-level** MIL-STD-1553 (the open-source 1553
simulators are functional-level only), and DO-178C/MIL certification evidence.
Expect a hybrid: open-source emulation + this Pi bench for development, with an
accredited Tier-2 bench for certification credit.
