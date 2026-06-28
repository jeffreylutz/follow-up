"""Fin-actuator plant model.

A second-order electromechanical servo with rate and position saturation — the
standard functional-fidelity model for a control-surface/fin actuator. This is
the *plant*: pure physics, no faults, no I/O. Faults live at the bus boundary
(see :mod:`hitl_sim.faults`) so the model stays a trustworthy black box.

The discrete update uses semi-implicit (symplectic) Euler, which is stable for
the stiff servo dynamics at the fixed step rates used here (e.g. 250 Hz, the
rate used on the ILR-33 AMBER rocket HIL stand referenced in the research).

Validate-against-real-hardware note: the parameters below are placeholders. The
intended workflow is to characterize the *one* scarce real actuator (step
response, rate/position limits), fit these parameters, and pin them so every
developer's bench inherits the same validated model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .messages import ActuatorFeedback, ActuatorStatus


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass
class FinActuatorParams:
    """Physical parameters of the fin servo. Fit these to real hardware."""

    max_position_deg: float = 30.0  # mechanical travel limit (±)
    max_rate_dps: float = 400.0  # slew-rate limit
    natural_freq_rps: float = 60.0  # servo bandwidth wn [rad/s]
    damping_ratio: float = 0.7  # zeta


@dataclass
class FinActuator:
    """Stateful second-order fin actuator with rate/position limits."""

    params: FinActuatorParams = field(default_factory=FinActuatorParams)
    position_deg: float = 0.0
    rate_dps: float = 0.0

    def step(self, commanded_position_deg: float, dt: float) -> ActuatorFeedback:
        """Advance the plant one timestep and return measured feedback.

        Args:
            commanded_position_deg: desired fin angle from the controller.
            dt: timestep [s]. Must match the rig's fixed real-time rate.
        """
        p = self.params

        # Command is physically clamped to mechanical travel; report saturation.
        cmd = _clamp(commanded_position_deg, -p.max_position_deg, p.max_position_deg)
        saturated = cmd != commanded_position_deg

        # Second-order servo: accel = wn^2 * error - 2*zeta*wn * velocity.
        error = cmd - self.position_deg
        accel = p.natural_freq_rps**2 * error - 2 * p.damping_ratio * p.natural_freq_rps * self.rate_dps

        # Semi-implicit Euler: update velocity first, clamp slew rate, then position.
        self.rate_dps = _clamp(self.rate_dps + accel * dt, -p.max_rate_dps, p.max_rate_dps)
        self.position_deg = _clamp(
            self.position_deg + self.rate_dps * dt, -p.max_position_deg, p.max_position_deg
        )

        return ActuatorFeedback(
            t=0.0,  # stamped by the simulator, which owns the logical clock
            measured_position_deg=self.position_deg,
            measured_rate_dps=self.rate_dps,
            status=ActuatorStatus.SATURATED if saturated else ActuatorStatus.OK,
        )
