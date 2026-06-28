"""Plant-model contracts: convergence, position saturation, rate limiting."""

from __future__ import annotations

from hitl_sim.actuator import FinActuator, FinActuatorParams
from hitl_sim.messages import ActuatorStatus

DT = 0.004  # 250 Hz


def _settle(act: FinActuator, cmd: float, ticks: int) -> None:
    for _ in range(ticks):
        act.step(cmd, DT)


def test_converges_to_command_within_travel():
    act = FinActuator()
    _settle(act, 15.0, ticks=500)
    assert abs(act.position_deg - 15.0) < 0.1
    assert abs(act.rate_dps) < 1.0  # settled, not still slewing


def test_position_saturates_at_mechanical_limit():
    act = FinActuator(params=FinActuatorParams(max_position_deg=30.0))
    fb = None
    for _ in range(800):
        fb = act.step(45.0, DT)  # command beyond travel
    assert act.position_deg <= 30.0 + 1e-9
    assert abs(act.position_deg - 30.0) < 0.1
    assert fb is not None and fb.status is ActuatorStatus.SATURATED


def test_rate_limit_is_never_exceeded_on_large_step():
    params = FinActuatorParams(max_rate_dps=400.0)
    act = FinActuator(params=params)
    worst_rate = 0.0
    for _ in range(500):
        fb = act.step(30.0, DT)  # large step demands high slew
        worst_rate = max(worst_rate, abs(fb.measured_rate_dps))
    assert worst_rate <= params.max_rate_dps + 1e-6


def test_neutral_command_holds_zero():
    act = FinActuator()
    _settle(act, 0.0, ticks=100)
    assert abs(act.position_deg) < 1e-6


def test_deterministic_repeatable():
    a, b = FinActuator(), FinActuator()
    for _ in range(300):
        a.step(12.0, DT)
        b.step(12.0, DT)
    assert a.position_deg == b.position_deg
    assert a.rate_dps == b.rate_dps
