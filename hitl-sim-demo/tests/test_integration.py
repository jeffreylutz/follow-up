"""Closed-loop / scenario contracts — the behavioral oracles that make fault
injection meaningful: a healthy loop tracks and never trips; each fault drives
the DUT into safe-state within a deadline."""

from __future__ import annotations

import pytest

from hitl_sim.scenarios import SCENARIOS


def test_nominal_tracks_and_never_trips():
    sc = SCENARIOS["nominal"]
    rec = sc.build().run(sc.duration_s)
    assert rec.time_to_safe_state() is None
    # Tracks the 20 deg setpoint closely after settling.
    assert rec.records[-1].true_position_deg == pytest.approx(20.0, abs=0.5)


@pytest.mark.parametrize("name", ["hard_over", "stuck_at", "packet_loss", "sensor_drift"])
def test_fault_drives_safe_state(name: str):
    sc = SCENARIOS[name]
    rec = sc.build().run(sc.duration_s)
    tts = rec.time_to_safe_state()
    assert tts is not None, f"{name}: DUT never reached safe-state"
    # Each fault has its own detection-latency budget (hard-over fast, drift slow).
    assert tts <= sc.detect_by_s, f"{name}: safe-state too slow ({tts:.3f}s > {sc.detect_by_s}s)"


def test_packet_loss_actually_drops_samples():
    sc = SCENARIOS["packet_loss"]
    rec = sc.build().run(sc.duration_s)
    assert rec.dropped_sample_count() > 0


def test_runs_are_deterministic():
    sc = SCENARIOS["sensor_drift"]
    a = sc.build().run(sc.duration_s).summary()
    b = sc.build().run(sc.duration_s).summary()
    assert a == b


def test_every_scenario_matches_its_expectation():
    for name, sc in SCENARIOS.items():
        rec = sc.build().run(sc.duration_s)
        assert (rec.time_to_safe_state() is not None) == sc.expect_safe_state, name
