"""The plant simulator — the code that runs on the Raspberry Pi.

It owns the logical clock, reads commands off the transport, steps the actuator
plant model, applies bus-level fault injection to the feedback, and sends the
(possibly faulted, possibly dropped) feedback back to the controller.

On real hardware this same class runs on the Pi; only the ``Transport`` swaps
from loopback to CAN/serial.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .actuator import FinActuator
from .faults import FaultInjector
from .messages import ActuatorCommand, ActuatorFeedback
from .transport import Transport


@dataclass
class PlantSimulator:
    """Reads commands, advances the plant, emits fault-injected feedback."""

    transport: Transport
    actuator: FinActuator = field(default_factory=FinActuator)
    injector: FaultInjector = field(default_factory=FaultInjector)
    dt: float = 0.004  # 250 Hz, matching the AMBER rocket HIL reference
    _last_command_deg: float = 0.0

    def step(self, t: float) -> ActuatorFeedback | None:
        """Advance one tick at logical time ``t``.

        Returns the feedback actually transmitted (post-fault), or ``None`` if
        the sample was dropped by a packet-loss fault.
        """
        # Use the freshest command available; hold last command if none arrived
        # (a real controller commands faster than once per plant tick, but this
        # also models command-side dropouts gracefully).
        cmd: ActuatorCommand | None = None
        while (c := self.transport.recv_command()) is not None:
            cmd = c
        if cmd is not None:
            self._last_command_deg = cmd.commanded_position_deg

        feedback = self.actuator.step(self._last_command_deg, self.dt)

        # Bus-level fault injection on the measured position only. A dropped
        # sample (None) means we send nothing this tick (packet loss).
        faulted_pos = self.injector.apply(t, feedback.measured_position_deg)
        if faulted_pos is None:
            return None

        sent = replace(feedback, t=t, measured_position_deg=faulted_pos)
        self.transport.send_feedback(sent)
        return sent
