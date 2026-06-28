"""Robot Framework keyword library wrapping the hitl-sim scenarios.

Lets non-Python stakeholders read/author HIL acceptance tests in Robot's
plain-language syntax — the bridge between requirements and automated tests that
the research highlighted (Renode pairs with Robot Framework the same way).
"""

from __future__ import annotations

from hitl_sim.scenarios import SCENARIOS

ROBOT_AUTO_KEYWORDS = False


class HitlLibrary:
    ROBOT_LIBRARY_SCOPE = "TEST"

    def __init__(self) -> None:
        self._rec = None

    def run_scenario(self, name: str) -> None:
        """Run a named HIL scenario to completion."""
        if name not in SCENARIOS:
            raise AssertionError(f"unknown scenario '{name}'; have {list(SCENARIOS)}")
        sc = SCENARIOS[name]
        self._rec = sc.build().run(sc.duration_s)

    def dut_should_reach_safe_state(self) -> None:
        assert self._rec is not None, "run a scenario first"
        tts = self._rec.time_to_safe_state()
        if tts is None:
            raise AssertionError("DUT did not reach safe-state")

    def dut_should_not_reach_safe_state(self) -> None:
        assert self._rec is not None, "run a scenario first"
        tts = self._rec.time_to_safe_state()
        if tts is not None:
            raise AssertionError(f"DUT unexpectedly tripped safe-state at {tts:.3f}s")

    def safe_state_time_should_be_below(self, deadline_s: float) -> None:
        assert self._rec is not None, "run a scenario first"
        tts = self._rec.time_to_safe_state()
        if tts is None or tts > float(deadline_s):
            raise AssertionError(f"safe-state time {tts} not below {deadline_s}s")

    def dropped_sample_count_should_be_above(self, n: int) -> None:
        assert self._rec is not None, "run a scenario first"
        count = self._rec.dropped_sample_count()
        if count <= int(n):
            raise AssertionError(f"dropped samples {count} not above {n}")
