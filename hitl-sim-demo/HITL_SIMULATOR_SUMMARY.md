# Hardware-in-the-Loop (HIL/HITL) Simulator — Research Summary & Recommendation

**Question:** Does it make sense to build a hardware simulator that every developer can use for
integration testing — providing instrumentation to confirm behavior — so that when we finally test
with the scarce real hardware (e.g., missile guidance fin actuators) in the loop, the embedded
software works without edge-case surprises?

**Short answer: Yes.** This is a mainstream, standards-endorsed practice in aerospace, automotive,
and defense embedded development. Your specific twist — a *cheap, per-developer* simulator (software
running on a Raspberry Pi, wired to the real embedded controller under development) — is not only
sensible, it matches a documented industry pattern and directly attacks the scarce-hardware problem.
Below is what the industry does, what open-source building blocks exist, and a concrete recommended
approach for the Pi-per-developer model.

> Scope note: this report is weighted toward your stated goals — per-developer dev access, CI
> integration testing, a pre-HIL validation rig, behavior instrumentation, and an **open-source-first**
> tooling bias. A "Confidence & caveats" section at the end flags where the evidence is thin.

---

## 1. Your idea, in industry vocabulary

What you're describing is a **signal-level Hardware-in-the-Loop (HIL) bench**, miniaturized to one
unit per developer. It sits on a well-established testing ladder. Each rung trades fidelity for
accessibility, and the whole point is to **catch defects on the cheap rungs before you ever touch the
expensive actuator.** This progression originated with MathWorks' Model-Based Design and is the
backbone of safety-critical software verification:

| Stage | What runs | What it tests | Hardware needed |
|-------|-----------|---------------|-----------------|
| **MIL** (Model-in-the-Loop) | Control model + plant model, both in simulation | Algorithm/requirements logic | None |
| **SIL** (Software-in-the-Loop) | *Generated/compiled control code* on a host PC vs. plant model | Code matches model; logic bugs | None |
| **PIL** (Processor-in-the-Loop) | Object code on the *target processor* vs. plant model | Compiler/target-specific behavior, timing | Target CPU/dev board |
| **HIL** (Hardware-in-the-Loop) | *Real controller hardware* ↔ *simulated plant* over real I/O buses | I/O, timing, integration, fault response | Controller + plant simulator |

> Terminology: you used "HITL." In aerospace usage (e.g., PX4), **HITL** specifically means the
> *normal production firmware runs on the real target controller*, while the plant is simulated —
> which is exactly your goal. **SITL** is the variant where simulation-specific firmware runs on a
> PC. This document uses **HIL** for the general technique and **HITL** for "real controller + sim
> plant," since that is what your Raspberry-Pi-wired-to-the-controller design is.

**Why this ladder matters to you:** the staged progression "catches issues at each abstraction level"
and reduces costly late iterations. By the time software reaches the real fin actuator, the vast
majority of logic, interface, timing, and fault-handling bugs have already been found against the
simulator — which is precisely the "no edge-case surprises in real HIL" outcome you described.

---

## 2. HIL architecture best practices (what good rigs do)

Across the strongest sources — a rocket flight-control HIL stand (ILR-33 AMBER), an automotive
fault-injection HIL (MDPI *Sensors* 2024), and MathWorks' reference guidance — the same architectural
patterns recur:

1. **Simulate the *plant*, run the *real controller*.** The device-under-test (DUT) is the actual
   embedded controller running production firmware. The simulator computes the *plant* it would
   normally drive: actuator dynamics, sensor feedback, vehicle/airframe dynamics, and environment.

2. **Talk over the *real* buses.** Connect the simulator to the DUT using the same physical
   interfaces the real system uses — CAN, Ethernet, serial, and in defense contexts MIL-STD-1553.
   This is what surfaces the communication/interface bugs that pure software simulation misses.

3. **Modular plant model.** Decompose the plant into independent sub-models — e.g., *airframe/body
   dynamics (6-DOF)*, *sensors*, *actuators*, *on-board computer*, *environment* — so pieces can be
   refined or swapped independently. (The AMBER rocket rig used exactly these five modules.)

4. **Fixed-rate, deterministic real-time execution.** The plant runs at a fixed step rate (the AMBER
   rig ran at 250 Hz) on a real-time-capable host so results are repeatable. **Determinism is the
   feature** — it's what makes a failing test reproducible and a passing test trustworthy.

5. **Reuse the production toolchain for the model.** The rocket model was built in the same
   Matlab/Simulink version as the actual vehicle development, so the plant model is shared
   engineering, not throwaway test code. (Your analog: reuse the same actuator math/datasheet the
   firmware team already relies on.)

6. **Signal-level vs. power/electrical-level fidelity — choose to need.** Commercial platforms
   distinguish *signal-level* HIL (functional signals: commanded angle, position feedback, bus
   messages) from *power-level* HIL (real currents, back-EMF, motor loads, electrical faults). Higher
   fidelity costs more. For day-to-day developer integration testing, signal-level is usually the
   right and far cheaper target; power-level fidelity is reserved for the late, scarce real-hardware
   bench.

---

## 3. Your specific design: a cheap, per-developer Raspberry Pi simulator

Your concept — **one inexpensive Pi-based simulator per developer, wired electrically to the embedded
controller they're writing software for** — is a *signal-level HITL bench at developer scale*. The
research supports its feasibility, and there is direct precedent:

- **Documented precedent for the exact topology.** An academic HIL framework (AGH, arXiv 2207.12198)
  connected a PC-based environment simulator to an embedded **Zynq SoC FPGA** dev board running the
  *real* landing-detection algorithm, communicating **over serial USB**. Swap "PC + AirSim" for
  "Raspberry Pi + your actuator model" and "Zynq board" for "your controller" and you have your design.
- **PX4 HITL** is the same idea productized in open source: standard firmware on the real flight
  controller, plant simulated off-board.
- **Low-cost building blocks exist** for the bus layer, including a software-only (Python)
  MIL-STD-1553 simulator — useful if your controller speaks 1553 at the functional/protocol level.

### What the Pi simulates
The Pi runs a software model of everything on the *other side* of the controller's connectors:

```
   ┌─────────────────────────┐         real bus / GPIO / PWM / ADC / DAC        ┌──────────────────────────┐
   │  Embedded Controller     │  ◄──────────────────────────────────────────►   │  Raspberry Pi Simulator   │
   │  (DUT, production f/w)    │     CAN · serial · 1553 · PWM · analog          │                           │
   │                          │                                                  │  • Actuator model (fin    │
   │  - reads "sensor" feedback│  ── commanded fin angle / torque cmd ──►        │    dynamics, rate/position │
   │  - issues actuator cmds   │  ◄── simulated position / current / status ──   │    limits, lag, backlash) │
   │                          │                                                  │  • Sensor models          │
   │                          │                                                  │  • Fault injection        │
   │                          │                                                  │  • Logging/instrumentation│
   └─────────────────────────┘                                                  └──────────────────────────┘
```

### Where the Pi is strong vs. where it falls short
- **Strong:** digital buses (CAN via a HAT/MCP2515, UART/SPI/I²C natively, Ethernet), functional
  signal exchange, fault injection, logging, cost (each unit is tens of dollars), and "every developer
  gets one." Excellent for the **signal-level / functional** tier.
- **Watch out:** a stock Raspberry Pi running Linux is **not hard-real-time** and has limited
  precise-timing analog I/O. For tight, jitter-sensitive control loops you will likely need one or
  more of:
  - the **`PREEMPT_RT`** patched kernel (soft real-time), or pinning the sim to an isolated core;
  - a **microcontroller co-processor** (e.g., Pi Pico / RP2040, STM32, or the Pi's own PIO) to handle
    deterministic PWM/ADC/timing while the Pi handles modeling and logging;
  - external **ADC/DAC** boards if the controller exchanges true analog signals.
- **Cannot replace:** real-world electrical/power-level effects (true motor current, back-EMF,
  thermal, hard-over at the power stage) and mechanical reality. Those stay on the scarce real-hardware
  bench. **This is the consistent, well-evidenced limit:** software/emulation "can replace a
  substantial portion of HIL but may not fully replace physical hardware testing."

### Keep the model honest (the hidden cost)
A simulator is only as good as its plant model. Budget explicitly for **building and validating the
actuator model**, and use your one scarce real actuator to *characterize/validate* the model (step
response, rate/position limits, lag, backlash) so every developer's Pi inherits a trusted model. A
known failure mode is shipping a low-fidelity model and gaining false confidence — validate against
real hardware at least once, then guard the model with regression tests.

---

## 4. Fault injection — the payoff you can't get from real hardware

You can't easily command a real fin actuator to fail a specific way on cycle 10,000. A simulator can —
and fault injection is a *core* reason the industry builds these rigs (it is **explicitly/strongly
recommended by ISO 26262**, and standard in DO-178C/DO-331 flows).

Best practice from the automotive HIL fault-injection work:

- Inject faults **programmatically, in real time, at the bus/signal interface as a black box** — i.e.,
  corrupt the messages/signals between sim and DUT **without modifying the plant model**, preserving
  model integrity.
- A documented framework supports **nine fault categories**, applied singly or simultaneously:
  **gain, offset, hard-over, stuck-at, delay, noise, packet loss, drift, spike.** That list is a
  ready-made test menu for your actuator/sensor channels.
- Caveat: this injects at *sensor/control/communication signals*, not arbitrary internal plant states —
  which is exactly the layer your Pi controls.

For an actuator specifically, the high-value faults to script are: **stuck-at** (jammed fin),
**hard-over** (runaway to limit), **rate/position-limit saturation**, **feedback offset/drift**, and
**bus delay/packet loss**.

---

## 5. Instrumentation & observability (confirming behavior)

You called out instrumentation as a primary goal — correctly. Because the Pi *is* the plant, it sees
every commanded value and every simulated response, giving you a perfect, non-intrusive observation
point the real hardware can't match. Practical patterns:

- **Timestamped logging of every bus transaction and internal plant state** to a structured log
  (CSV/Parquet/MCAP) per test run.
- **Assertions on behavior**, not just signals: e.g., "after a hard-over fault, controller enters
  safe-state within N ms." Turn these into pass/fail oracles.
- **Determinism + seeded scenarios** so a captured failure replays identically for debugging.
- **Robot Framework** test cases (see below) as the human-readable spec ↔ automated-test bridge.

---

## 6. Open-source building blocks (your "open-source-first" bias)

| Tool | Role in your stack | Notes / fit |
|------|--------------------|-------------|
| **Renode** (Antmicro) | Emulate the controller SoC itself — run **unmodified production firmware** on a virtual board; multi-node systems; deterministic | The single most adaptable OSS piece. Lets the **whole team work in parallel with no hardware at all** (pure SIL/emulation tier). Integrates with **Robot Framework** (`renode-test`) and has a **GitHub Action** for CI. Fidelity depends on peripheral-model quality. |
| **QEMU** | Generic CPU/board emulation | Lower-level alternative/complement to Renode when a target isn't modeled. |
| **PX4 SITL/HITL** | Reference design for "real firmware + simulated plant" | Study its HITL architecture even if you don't fly PX4; proven pattern. |
| **Gazebo** | 3D physics/dynamics plant simulation | Useful if you need airframe/aero/6-DOF dynamics with physics realism feeding the actuator model. |
| **FMI / FMU** | Portable plant-model packaging | Export the actuator/dynamics model as an FMU so the *same* validated model runs in MIL, SIL, and on the Pi. Strongly recommended for "build the model once, reuse everywhere." |
| **Python MIL-STD-1553 simulator** (ShubhankarKulkarni/MIL-STD-1553-Simulator) | Software-only 1553 bus (BC + RTs over Ethernet) | **Hobby-grade, functional/protocol level only** — fine for early functional integration, *not* electrical/signal-level 1553 fidelity. |
| **Robot Framework** | Test authoring + CI glue | Pairs with Renode today; can also drive the Pi rig. |
| `PREEMPT_RT`, RP2040/PIO, `python-can`, `pyserial` | Real-time + I/O plumbing on the Pi | The practical glue that makes the Pi bench deterministic enough. |

**Suggested OSS layering:**
- **Tier 0 — Emulation (no hardware, every dev + CI):** Renode/QEMU running production firmware →
  catches logic/integration bugs continuously in CI. This is the cheapest, broadest safety net and
  needs *zero* per-developer hardware.
- **Tier 1 — Your Pi HITL bench (real controller + sim plant):** signal-level integration + fault
  injection per developer.
- **Tier 2 — Scarce real-hardware HIL:** the expensive actuator, used late and sparingly for
  electrical/power-level and final integration.

---

## 7. Commercial landscape (for comparison / "build vs. buy")

You're going open-source, but it helps to know what the cheap Pi rig is standing in for. The
established real-time HIL vendors are **dSPACE** (SCALEXIO, MicroAutoBox — supports both signal-level
*and* power-level HIL), **Speedgoat** (the real-time host in the rocket and MathWorks examples),
**NI / VeriStand** (notably used for *aircraft actuation* test systems), **Typhoon HIL** (power
electronics, with documented CI integration), and **OPAL-RT**. These deliver hard real-time guarantees,
high-fidelity (including power-level) I/O, and vendor/certification support — at a per-seat cost that
makes "one per developer" infeasible, which is exactly the gap your Pi design fills. Treat vendor
"unlimited scalability" marketing with caution (one such claim was refuted in verification). A common
real-world arrangement: **cheap OSS emulation + Pi benches for the team, one commercial-grade HIL rig
shared for final/power-level validation.**

---

## 8. Standards & methodology context

- **V-model:** HIL sits at the **system-integration** phase — verifying integrated software/hardware
  against system requirements.
- **MIL → SIL → PIL → HIL** staged verification (Model-Based Design) is the recommended progression;
  test cases developed at the model level can be *largely* reused downstream (but note: "fully reused
  to satisfy DO-331 integration objectives" was **refuted** — don't assume MIL test cases alone
  satisfy certification integration objectives without analysis).
- **ISO 26262** (automotive functional safety) explicitly/strongly recommends both **HIL simulation**
  and **fault injection** (strongest at ASIL D).
- **DO-178C / DO-331** (airborne software / model-based supplement) frame the model-based verification
  flow your rig fits into.
- **Defense specifics (MIL-STD-1553, ITAR/classification, certification accreditation)** are *inferred*
  here from adjacent aerospace/automotive evidence, not directly sourced — see caveats.

---

## 9. Recommended approach

1. **Adopt the tiered model now.** Stand up **Renode + Robot Framework in CI** immediately (Tier 0) —
   it unblocks the whole team with zero hardware and starts catching integration bugs today.
2. **Prototype the Pi bench (Tier 1)** against the most important interface first (likely the actuator
   command/feedback path over CAN or serial). Start signal-level; add an RP2040/PIO or external
   ADC/DAC co-processor only where timing/analog fidelity demands it.
3. **Build the actuator plant model once, package as an FMU,** and **validate it against the one scarce
   real actuator.** Reuse that exact model in MIL, SIL, and on every Pi.
4. **Make fault injection first-class** from day one — implement the nine-fault menu at the bus
   interface, scripted and repeatable.
5. **Instrument everything** — deterministic, timestamped, replayable logs + behavioral assertions as
   pass/fail oracles.
6. **Reserve the real hardware** for electrical/power-level and final integration only (Tier 2).
7. **Standardize the bench** (same Pi image, same model version, version-controlled) so "works on my
   simulator" means the same thing for everyone and in CI.

---

## 10. Confidence & caveats

- **Domain skew:** strongest evidence is from **automotive** (ISO 26262, dSPACE) and
  **aerospace/UAV/rocket** academic case studies (Speedgoat, PX4, AirSim/Zynq), **not** directly from
  missile fin-actuator programs. Architectural patterns transfer well; **defense-specific constraints
  (ITAR, MIL-STD-1553 *electrical* fidelity, security accreditation) are inferred, not sourced.**
- Several findings rest on **single peer-reviewed papers describing one team's own rig** — reliable as
  feasibility proofs, weaker as broad surveys.
- **MathWorks/dSPACE sources are vendor-originated.** The MIL/SIL/PIL/HIL progression and product
  features survived only because independent sources corroborated them; soft marketing claims
  ("arbitrary scalability," "seamlessly reused," "prevents costly iterations") were **refuted or
  downgraded.**
- The **open-source 1553 simulator is hobby-grade, functional-level only** — not for
  electrical/signal-level fidelity.
- **Emulation/sim cannot fully replace physical hardware testing** for real-world/electrical
  conditions — keep the Tier-2 real-hardware bench.
- A stock **Raspberry Pi is not hard-real-time**; plan for `PREEMPT_RT`, a microcontroller
  co-processor, and/or external I/O for timing-critical or analog signals.
- **Time-sensitivity:** tool versions evolve (e.g., Simulink R2023a in the rocket case; Renode
  capabilities change) — verify current versions.

### Refuted during verification (do *not* rely on these)
- "MIL test cases can be *fully* reused for SIL/HIL and satisfy DO-331 table MB.A-6 integration
  objectives." (1–2)
- "Renode CI adoption hinges *entirely* on peripheral-model accuracy validated against physical
  hardware." (0–3)
- "dSPACE SCALEXIO scales to *arbitrary* computation and I/O." (1–2)

---

## 11. Open questions to resolve next

1. **Electrical/power-level fidelity for the *fin actuator*** (servo current, back-EMF, hard-over at
   the power stage) — which tier/tool covers it, and is a Pi-class rig ever enough, or is that
   strictly Tier-2?
2. **Real-time HIL in CI with determinism guarantees** — the strongest source listed this as *future
   work*; what's the proven path?
3. **Defense constraints** — how do ITAR/classification and high-fidelity (electrical) MIL-STD-1553
   requirements constrain open-source tools (Renode/QEMU/Gazebo), and what hybrid (OSS emulation +
   accredited bench) satisfies auditors?
4. **Model build/validation methodology & cost** — how best to use the single scarce actuator to
   extract and validate a model the whole team can trust?

---

## 12. Sources

**Primary / case studies**
- Renode (Antmicro) — open-source SoC/system emulation, Robot Framework + CI: https://github.com/renode/renode
- Renode GitHub Action for automated testing in simulation: https://antmicro.com/blog/2024/10/renode-github-action-for-automated-testing-in-simulation
- DiVA MSc thesis (nRF5340, ~2024) — Renode replacing portions of HIL, team-parallel development: https://www.diva-portal.org/smash/get/diva2:1900246/FULLTEXT01.pdf
- ILR-33 AMBER rocket HIL test stand (Speedgoat, Simulink, 250 Hz, modular plant): https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12251647/
- Automotive HIL fault-injection framework (MDPI *Sensors* 2024; 3-layer arch, 9 fault types, ISO 26262): https://pmc.ncbi.nlm.nih.gov/articles/PMC11207294/
- HIL fault-injection without modifying the plant model (ISO 26262 fault injection): https://pmc.ncbi.nlm.nih.gov/articles/PMC8963027/
- TU Munich flight-control MBD / DO-178C / DO-331, CI excluding real-time HIL: https://arxiv.org/pdf/2010.06505
- AirSim ↔ Zynq SoC FPGA HIL over serial USB (AGH) — precedent for PC/Pi-to-embedded topology: https://arxiv.org/pdf/2207.12198
- PX4 HITL documentation (real firmware + simulated plant): https://docs.px4.io/main/en/simulation/hitl
- Python MIL-STD-1553 simulator (functional/protocol level only): https://github.com/ShubhankarKulkarni/MIL-STD-1553-Simulator

**Secondary / vendor / methodology**
- MathWorks — MIL/SIL/PIL/HIL and Model-Based Design: https://www.mathworks.com/matlabcentral/answers/440277-what-are-mil-sil-pil-and-hil-and-how-do-they-integrate-with-the-model-based-design-approach
- MathWorks — Model-Based Design for DO-178C/DO-331: https://www.mathworks.com/learn/training/model-based-design-for-do-178c-do-331-compliance.html
- MathWorks — Hardware-in-the-Loop overview: https://www.mathworks.com/discovery/hardware-in-the-loop-hil.html
- dSPACE SCALEXIO (signal-level + power-level HIL): https://www.dspace.com/en/ltd/home/products/hw/simulator_hardware/scalexio.cfm
- NI/VeriStand — aircraft actuation test systems: https://www.ni.com/en/solutions/aerospace-defense/case-studies/test-platform-for-aircraft-actuation-test-systems.html
- Typhoon HIL — CI with HIL for control-software testing: https://www.typhoon-hil.com/blog/continuous-integration-with-hil-fully-automate-power-electronics-control-software-testing/
- EE Power — HIL tools/vendor landscape: https://eepower.com/technical-articles/hardware-in-the-loop-simulation-tools-and-implementation-part-2/
- Golioth — HIL testing in practice: https://blog.golioth.io/golioth-hil-testing-part1/
- ReverseToBuild — firmware HIL CI pipeline: https://reversetobuild.com/firmware-hil-ci-pipeline/

---

*Generated from a fan-out deep-research pass: 5 search angles, 21 sources fetched, 104 claims
extracted, 25 adversarially verified (3-vote; 22 confirmed, 3 refuted), synthesized into 8 findings.*
