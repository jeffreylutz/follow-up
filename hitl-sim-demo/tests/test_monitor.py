"""Monitor contracts, and the headline result: the model-based monitor tolerates
an aggressive maneuver that false-trips the naïve threshold monitor."""

from __future__ import annotations

import pytest

from hitl_sim.controller import Controller, ReferenceModelMonitor, SafetyMonitor
from hitl_sim.faults import FaultInjector, HardOverFault
from hitl_sim.loop import HilLoop
from hitl_sim.scenarios import MANEUVER_STEPS, multistep_setpoint
from hitl_sim.simulator import PlantSimulator
from hitl_sim.transport import LoopbackTransport


def _run(monitor, setpoint, injector=None, duration=0.7):
    transport = LoopbackTransport()
    controller = Controller(setpoint=setpoint, monitor=monitor)
    simulator = PlantSimulator(transport=transport, injector=injector or FaultInjector())
    return HilLoop(transport=transport, controller=controller, simulator=simulator).run(duration)


def test_reference_monitor_survives_aggressive_maneuver():
    rec = _run(ReferenceModelMonitor(), multistep_setpoint(MANEUVER_STEPS))
    assert rec.time_to_safe_state() is None, "model-based monitor false-tripped on a maneuver"


def test_threshold_monitor_false_trips_on_same_maneuver():
    # Demonstrates the problem the reference model solves: the naïve monitor cannot
    # distinguish a legitimate slew from a fault and trips on the maneuver.
    rec = _run(SafetyMonitor(), multistep_setpoint(MANEUVER_STEPS))
    assert rec.time_to_safe_state() is not None, (
        "expected the threshold monitor to false-trip on the maneuver"
    )


def test_reference_monitor_still_catches_real_fault_during_maneuver():
    # A hard-over injected mid-maneuver must still be caught by the model-based monitor.
    rec = _run(
        ReferenceModelMonitor(),
        multistep_setpoint(MANEUVER_STEPS),
        injector=FaultInjector([HardOverFault(t_start=0.3, value=30.0)]),
    )
    tts = rec.time_to_safe_state()
    assert tts is not None and tts == pytest.approx(0.3, abs=0.06)
