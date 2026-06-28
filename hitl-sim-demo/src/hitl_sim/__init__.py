"""hitl-sim: a reference per-developer HIL/HITL simulator.

Pure-software, deterministic fin-actuator plant model + bus-level fault injection
+ instrumentation. Runs in CI today; deploys unchanged to a Raspberry Pi bench by
swapping only the :class:`~hitl_sim.transport.Transport`.
"""

from __future__ import annotations

from .actuator import FinActuator, FinActuatorParams
from .controller import Controller, Monitor, ReferenceModelMonitor, SafetyMonitor
from .faults import (
    DelayFault,
    DriftFault,
    Fault,
    FaultInjector,
    GainFault,
    HardOverFault,
    NoiseFault,
    OffsetFault,
    PacketLossFault,
    SpikeFault,
    StuckAtFault,
)
from .instrumentation import Recorder, StepRecord
from .loop import HilLoop
from .messages import ActuatorCommand, ActuatorFeedback, ActuatorStatus
from .scenarios import SCENARIOS, Scenario, multistep_setpoint, step_setpoint
from .simulator import PlantSimulator
from .transport import (
    CanTransport,
    LoopbackTransport,
    Transport,
    decode_command,
    decode_feedback,
    encode_command,
    encode_feedback,
)

__all__ = [
    "FinActuator",
    "FinActuatorParams",
    "Controller",
    "Monitor",
    "SafetyMonitor",
    "ReferenceModelMonitor",
    "Fault",
    "FaultInjector",
    "GainFault",
    "OffsetFault",
    "HardOverFault",
    "StuckAtFault",
    "DelayFault",
    "NoiseFault",
    "PacketLossFault",
    "DriftFault",
    "SpikeFault",
    "Recorder",
    "StepRecord",
    "HilLoop",
    "ActuatorCommand",
    "ActuatorFeedback",
    "ActuatorStatus",
    "SCENARIOS",
    "Scenario",
    "step_setpoint",
    "multistep_setpoint",
    "PlantSimulator",
    "LoopbackTransport",
    "Transport",
    "CanTransport",
    "encode_command",
    "decode_command",
    "encode_feedback",
    "decode_feedback",
]
