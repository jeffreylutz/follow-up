"""Demo controller — stand-in for the embedded firmware Device-Under-Test (DUT).

In a real HITL setup this code is replaced by the actual controller hardware
running production firmware; the simulator and transport stay identical. Here it
is software so the demo is self-contained.

It does two jobs:

1. **Track a setpoint schedule** by commanding the fin toward a target angle.
2. **Monitor for faults** — the part that makes fault injection meaningful. When
   the monitor latches a safe-state, the controller commands the fin to neutral
   (0°). This yields a crisp behavioral oracle: "after a hard-over/stuck-at fault,
   the DUT reaches safe-state within N ms."

Two monitor strategies are provided:

* :class:`SafetyMonitor` — naïve command-vs-measured threshold. Simple, but must
  use a generous hold window or it false-trips during normal large maneuvers
  (the measured value legitimately lags the command mid-slew).
* :class:`ReferenceModelMonitor` — *model-based* detection (analytical
  redundancy). It runs a shadow plant model fed the same commands and watches the
  residual ``|measured - model|``. The residual is ~0 in healthy steady *and*
  transient regimes, so it tolerates arbitrary maneuvers without false-tripping
  and detects faults with a tight threshold. This is the default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from .actuator import FinActuator, FinActuatorParams
from .messages import ActuatorCommand, ActuatorFeedback


class Monitor(Protocol):
    """A fault monitor that latches a safe-state. ``update`` is called each tick."""

    tripped: bool
    trip_time_s: float | None

    def update(
        self, t: float, commanded_deg: float, feedback: ActuatorFeedback | None
    ) -> None: ...


@dataclass
class SafetyMonitor:
    """Naïve threshold monitor: trips on sustained |command - measured| error.

    Kept for comparison — it demonstrates *why* the model-based monitor is needed:
    its hold window must exceed the actuator's worst-case slew time, and even then
    a sufficiently large/fast maneuver can false-trip it.
    """

    error_tol_deg: float = 5.0
    error_hold_s: float = 0.08  # must exceed worst-case slew time
    feedback_timeout_s: float = 0.05

    tripped: bool = False
    trip_time_s: float | None = None
    _error_since: float | None = field(default=None, init=False, repr=False)
    _last_feedback_t: float | None = field(default=None, init=False, repr=False)

    def update(
        self, t: float, commanded_deg: float, feedback: ActuatorFeedback | None
    ) -> None:
        if self.tripped:
            return

        if feedback is None:
            if self._last_feedback_t is None:
                self._last_feedback_t = t
            if t - self._last_feedback_t >= self.feedback_timeout_s:
                self._trip(t)
            return
        self._last_feedback_t = t

        if abs(commanded_deg - feedback.measured_position_deg) > self.error_tol_deg:
            if self._error_since is None:
                self._error_since = t
            elif t - self._error_since >= self.error_hold_s:
                self._trip(t)
        else:
            self._error_since = None

    def _trip(self, t: float) -> None:
        self.tripped = True
        self.trip_time_s = t


@dataclass
class ReferenceModelMonitor:
    """Model-based monitor (analytical redundancy). Default for the demo.

    Maintains a shadow :class:`~hitl_sim.actuator.FinActuator` driven by the same
    commands as the real plant and trips when the measured feedback diverges from
    the model's predicted position (the *residual*) beyond ``residual_tol_deg``
    for ``residual_hold_s``. Because the shadow model lags exactly like the real
    actuator, normal maneuvers produce a near-zero residual — so the threshold can
    be tight and the hold short without false-tripping.

    The shadow model must use the *same validated parameters* as the real
    actuator; pass ``params`` fitted to hardware. ``dt`` must match the rig rate.
    """

    residual_tol_deg: float = 5.0
    residual_hold_s: float = 0.024  # short: maneuvers don't create residual
    feedback_timeout_s: float = 0.05
    dt: float = 0.004
    params: FinActuatorParams = field(default_factory=FinActuatorParams)

    tripped: bool = False
    trip_time_s: float | None = None
    _reference: FinActuator = field(default=None, init=False, repr=False)  # type: ignore[assignment]
    _residual_since: float | None = field(default=None, init=False, repr=False)
    _last_feedback_t: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._reference = FinActuator(params=self.params)

    def update(
        self, t: float, commanded_deg: float, feedback: ActuatorFeedback | None
    ) -> None:
        # Advance the shadow model every tick so it tracks the real plant.
        self._reference.step(commanded_deg, self.dt)
        if self.tripped:
            return

        if feedback is None:
            if self._last_feedback_t is None:
                self._last_feedback_t = t
            if t - self._last_feedback_t >= self.feedback_timeout_s:
                self._trip(t)
            return
        self._last_feedback_t = t

        residual = abs(feedback.measured_position_deg - self._reference.position_deg)
        if residual > self.residual_tol_deg:
            if self._residual_since is None:
                self._residual_since = t
            elif t - self._residual_since >= self.residual_hold_s:
                self._trip(t)
        else:
            self._residual_since = None

    def _trip(self, t: float) -> None:
        self.tripped = True
        self.trip_time_s = t


@dataclass
class Controller:
    """Commands the fin to a scheduled setpoint, with a fault monitor."""

    # setpoint(t) -> desired fin angle [deg]
    setpoint: Callable[[float], float]
    monitor: Monitor = field(default_factory=ReferenceModelMonitor)
    safe_state_deg: float = 0.0
    last_command_deg: float = 0.0

    def update(self, t: float, feedback: ActuatorFeedback | None) -> ActuatorCommand:
        """Produce the next command given the latest feedback (may be ``None``)."""
        commanded = self.setpoint(t)
        # Monitor judges health against what we intended to command.
        self.monitor.update(t, commanded, feedback)
        if self.monitor.tripped:
            commanded = self.safe_state_deg
        self.last_command_deg = commanded
        return ActuatorCommand(t=t, commanded_position_deg=commanded)
