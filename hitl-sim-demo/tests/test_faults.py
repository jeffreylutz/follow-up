"""Fault-menu contracts: each of the nine faults behaves as specified, and is
windowed (inactive outside [t_start, t_end))."""

from __future__ import annotations

from hitl_sim.faults import (
    DelayFault,
    DriftFault,
    FaultInjector,
    GainFault,
    HardOverFault,
    NoiseFault,
    OffsetFault,
    PacketLossFault,
    SpikeFault,
    StuckAtFault,
)


def test_gain_scales_within_window_only():
    f = GainFault(t_start=1.0, t_end=2.0, gain=2.0)
    assert f.apply(0.5, 10.0) == 10.0  # before window
    assert f.apply(1.5, 10.0) == 20.0  # inside
    assert f.apply(2.5, 10.0) == 10.0  # after window


def test_offset_adds_constant():
    f = OffsetFault(offset=3.0)
    assert f.apply(0.0, 10.0) == 13.0


def test_hard_over_forces_extreme():
    f = HardOverFault(value=30.0)
    assert f.apply(0.0, 5.0) == 30.0


def test_stuck_at_holds_first_sample():
    f = StuckAtFault(t_start=0.0)
    assert f.apply(0.0, 7.0) == 7.0
    assert f.apply(0.1, 12.0) == 7.0  # frozen at first value
    assert f.apply(0.2, 99.0) == 7.0


def test_stuck_at_fixed_value():
    f = StuckAtFault(value=2.0)
    assert f.apply(0.0, 7.0) == 2.0


def test_delay_shifts_by_n_samples():
    f = DelayFault(delay_samples=2)
    # buffer fills; output lags input by 2 samples once full
    assert f.apply(0.0, 1.0) == 1.0
    assert f.apply(0.1, 2.0) == 1.0
    assert f.apply(0.2, 3.0) == 1.0
    assert f.apply(0.3, 4.0) == 2.0


def test_noise_is_seeded_and_deterministic():
    a = NoiseFault(sigma=0.5, seed=42)
    b = NoiseFault(sigma=0.5, seed=42)
    seq_a = [a.apply(t / 10, 0.0) for t in range(10)]
    seq_b = [b.apply(t / 10, 0.0) for t in range(10)]
    assert seq_a == seq_b
    assert any(v != 0.0 for v in seq_a)  # actually perturbs


def test_packet_loss_drops_deterministically():
    f = PacketLossFault(drop_prob=1.0, seed=1)
    assert f.apply(0.0, 5.0) is None  # always drops at prob 1.0
    keep = PacketLossFault(drop_prob=0.0, seed=1)
    assert keep.apply(0.0, 5.0) == 5.0


def test_drift_grows_linearly_from_start():
    f = DriftFault(t_start=1.0, rate_per_s=2.0)
    assert f.apply(1.0, 0.0) == 0.0
    assert f.apply(2.0, 0.0) == 2.0
    assert f.apply(3.5, 0.0) == 5.0


def test_spike_is_periodic():
    f = SpikeFault(magnitude=10.0, period_s=0.5)
    assert f.apply(0.0, 1.0) == 11.0  # first spike
    assert f.apply(0.1, 1.0) == 1.0  # within period -> no spike
    assert f.apply(0.5, 1.0) == 11.0  # next period -> spike


def test_injector_composes_and_short_circuits_on_drop():
    inj = FaultInjector([OffsetFault(offset=1.0), PacketLossFault(drop_prob=1.0, seed=0)])
    assert inj.apply(0.0, 10.0) is None  # dropped despite earlier offset

    inj2 = FaultInjector([GainFault(gain=2.0), OffsetFault(offset=1.0)])
    assert inj2.apply(0.0, 10.0) == 21.0  # (10*2)+1, applied in order
