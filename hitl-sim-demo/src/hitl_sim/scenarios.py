"""Pre-built demo scenarios.

Each scenario wires a controller + plant + a fault schedule into a ready-to-run
:class:`~hitl_sim.loop.HilLoop`. They double as the fixtures the test suite and
the Robot Framework suite drive, so "the demo" and "the tests" exercise the same
code paths.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .controller import Controller, Monitor, ReferenceModelMonitor
from .faults import (
    DriftFault,
    FaultInjector,
    HardOverFault,
    PacketLossFault,
    StuckAtFault,
)
from .loop import HilLoop
from .simulator import PlantSimulator
from .transport import LoopbackTransport


def step_setpoint(value_deg: float, t_step_s: float = 0.05) -> Callable[[float], float]:
    """A setpoint that steps from 0 to ``value_deg`` at ``t_step_s``."""
    return lambda t: value_deg if t >= t_step_s else 0.0


def multistep_setpoint(steps: list[tuple[float, float]]) -> Callable[[float], float]:
    """A setpoint schedule: a list of ``(time_s, value_deg)``, held until the next.

    Models a real maneuver (e.g. command +20°, then -20°, then 15°) that a naïve
    threshold monitor would false-trip on but the model-based monitor tolerates.
    """
    ordered = sorted(steps)

    def setpoint(t: float) -> float:
        value = 0.0
        for ts, v in ordered:
            if t >= ts:
                value = v
            else:
                break
        return value

    return setpoint


@dataclass
class Scenario:
    name: str
    description: str
    duration_s: float
    build: Callable[[], HilLoop]
    # What we expect, used by tests as oracles:
    expect_safe_state: bool
    # Latest acceptable time to latch safe-state [s]. None when no trip expected.
    # Detection latency is fault-specific — a hard-over is caught fast, drift slow.
    detect_by_s: float | None = None


def _loop(
    setpoint: Callable[[float], float],
    injector: FaultInjector,
    monitor: Monitor | None = None,
) -> HilLoop:
    transport = LoopbackTransport()
    controller = Controller(
        setpoint=setpoint, monitor=monitor or ReferenceModelMonitor()
    )
    simulator = PlantSimulator(transport=transport, injector=injector)
    return HilLoop(transport=transport, controller=controller, simulator=simulator)


# A representative multi-step maneuver used to prove no-false-trip behavior.
MANEUVER_STEPS = [(0.05, 20.0), (0.25, -20.0), (0.45, 15.0)]


def _nominal() -> HilLoop:
    return _loop(step_setpoint(20.0), FaultInjector())


def _maneuver() -> HilLoop:
    # Aggressive setpoint changes, no faults: the model-based monitor must NOT trip.
    return _loop(multistep_setpoint(MANEUVER_STEPS), FaultInjector())


def _hard_over() -> HilLoop:
    # Feedback is forced to the +30° rail at t=0.2s while the command is ~20°.
    return _loop(
        step_setpoint(20.0),
        FaultInjector([HardOverFault(t_start=0.2, value=30.0)]),
    )


def _stuck_at() -> HilLoop:
    # Dead sensor reading a fixed 0 deg from t=0.2s while the fin is held at ~20 deg.
    # (Note: a stuck-at that freezes at the *correct* value under a constant command
    # is genuinely undetectable by an error monitor — a real and useful caveat.)
    return _loop(
        step_setpoint(20.0),
        FaultInjector([StuckAtFault(t_start=0.2, value=0.0)]),
    )


def _packet_loss() -> HilLoop:
    # Total feedback loss after t=0.2s -> safety monitor trips on timeout.
    return _loop(
        step_setpoint(20.0),
        FaultInjector([PacketLossFault(t_start=0.2, drop_prob=1.0, seed=7)]),
    )


def _sensor_drift() -> HilLoop:
    # Slow drift that eventually exceeds the tracking tolerance and trips safe-state.
    return _loop(
        step_setpoint(20.0),
        FaultInjector([DriftFault(t_start=0.2, rate_per_s=40.0)]),
    )


SCENARIOS: dict[str, Scenario] = {
    "nominal": Scenario(
        "nominal", "Step command, no faults; clean tracking, no safe-state.",
        duration_s=0.6, build=_nominal, expect_safe_state=False,
    ),
    "maneuver": Scenario(
        "maneuver", "Aggressive multi-step maneuver, no faults; must NOT false-trip.",
        duration_s=0.7, build=_maneuver, expect_safe_state=False,
    ),
    "hard_over": Scenario(
        "hard_over", "Hard-over feedback fault at 0.2s; fast safe-state.",
        duration_s=0.6, build=_hard_over, expect_safe_state=True, detect_by_s=0.32,
    ),
    "stuck_at": Scenario(
        "stuck_at", "Dead (stuck-at-zero) sensor at 0.2s; safe-state on tracking error.",
        duration_s=0.6, build=_stuck_at, expect_safe_state=True, detect_by_s=0.32,
    ),
    "packet_loss": Scenario(
        "packet_loss", "Total feedback loss at 0.2s; safe-state on feedback timeout.",
        duration_s=0.6, build=_packet_loss, expect_safe_state=True, detect_by_s=0.30,
    ),
    "sensor_drift": Scenario(
        "sensor_drift", "Linear sensor drift from 0.2s; slower safe-state once error exceeds tol.",
        duration_s=0.8, build=_sensor_drift, expect_safe_state=True, detect_by_s=0.46,
    ),
}
