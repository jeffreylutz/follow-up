"""Wire messages exchanged between the controller (DUT) and the plant simulator.

These are deliberately plain dataclasses. On real hardware they would be
serialized onto a CAN frame / serial packet / 1553 word; in the software demo
they travel through a :class:`~hitl_sim.transport.LoopbackTransport` unchanged.
Keeping the message schema transport-independent is what lets the same DUT and
plant code run in software, on a Pi bench, and (conceptually) on the final rig.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActuatorStatus(str, Enum):
    """Health word the plant reports alongside its measured state."""

    OK = "ok"
    SATURATED = "saturated"  # commanded beyond travel limit
    FAULT = "fault"  # plant-side fault flag (reserved; faults are bus-side here)


@dataclass(frozen=True)
class ActuatorCommand:
    """Command from the controller to the fin actuator."""

    t: float  # logical simulation time [s]
    commanded_position_deg: float


@dataclass(frozen=True)
class ActuatorFeedback:
    """Sensor feedback from the actuator back to the controller."""

    t: float  # logical simulation time [s]
    measured_position_deg: float
    measured_rate_dps: float
    status: ActuatorStatus = ActuatorStatus.OK
