"""CanTransport round-trip over a python-can loopback bus.

Uses python-can's cross-platform in-memory ``virtual`` interface so the test runs
anywhere (the Linux ``vcan0`` socketcan device is the real-hardware equivalent).
Skips cleanly when python-can is not installed (it's the optional [canbus] extra).
"""

from __future__ import annotations

import pytest

can = pytest.importorskip("can")

from hitl_sim.messages import ActuatorCommand, ActuatorFeedback, ActuatorStatus
from hitl_sim.transport import (
    CanTransport,
    decode_command,
    decode_feedback,
    encode_command,
    encode_feedback,
)


def test_command_codec_roundtrip():
    cmd = ActuatorCommand(t=0.123, commanded_position_deg=12.5)
    got = decode_command(encode_command(cmd))
    assert got.commanded_position_deg == pytest.approx(12.5, abs=1e-3)
    assert got.t == pytest.approx(0.123, abs=1e-3)
    assert len(encode_command(cmd)) <= 8  # fits a classic CAN frame


def test_feedback_codec_roundtrip():
    fb = ActuatorFeedback(
        t=0.2, measured_position_deg=-7.25, measured_rate_dps=123.0,
        status=ActuatorStatus.SATURATED,
    )
    got = decode_feedback(encode_feedback(fb))
    assert got.measured_position_deg == pytest.approx(-7.25, abs=1e-3)
    assert got.measured_rate_dps == pytest.approx(123.0, abs=0.02)  # int16 quantization
    assert got.status is ActuatorStatus.SATURATED
    assert len(encode_feedback(fb)) <= 8


@pytest.fixture()
def virtual_bus_pair():
    channel = "hitl-sim-test"
    a = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    b = can.Bus(interface="virtual", channel=channel, receive_own_messages=False)
    try:
        yield a, b
    finally:
        a.shutdown()
        b.shutdown()


def test_can_loopback_command_and_feedback(virtual_bus_pair):
    sim_bus, ctrl_bus = virtual_bus_pair
    # Two nodes sharing the bus: the simulator and the (emulated) controller.
    sim = CanTransport(sim_bus, recv_timeout=1.0)
    ctrl = CanTransport(ctrl_bus, recv_timeout=1.0)

    # Controller -> simulator (command frame).
    ctrl.send_command(ActuatorCommand(t=0.05, commanded_position_deg=18.0))
    got_cmd = sim.recv_command()
    assert got_cmd is not None
    assert got_cmd.commanded_position_deg == pytest.approx(18.0, abs=1e-3)

    # Simulator -> controller (feedback frame).
    sim.send_feedback(
        ActuatorFeedback(t=0.05, measured_position_deg=17.3, measured_rate_dps=-50.0)
    )
    got_fb = ctrl.recv_feedback()
    assert got_fb is not None
    assert got_fb.measured_position_deg == pytest.approx(17.3, abs=1e-3)
    assert got_fb.measured_rate_dps == pytest.approx(-50.0, abs=0.02)


def test_recv_returns_none_when_idle(virtual_bus_pair):
    sim_bus, _ = virtual_bus_pair
    sim = CanTransport(sim_bus, recv_timeout=0.0)
    assert sim.recv_command() is None  # nothing queued -> non-blocking None
