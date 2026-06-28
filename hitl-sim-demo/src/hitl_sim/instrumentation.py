"""Instrumentation / observability.

Because the simulator *is* the plant, it can record every commanded value, every
true plant state, and every faulted feedback sample — a perfect, non-intrusive
observation point real hardware can't match. The recorder produces deterministic,
timestamped, replayable logs (CSV/JSONL) plus behavioral helpers used as
pass/fail oracles in tests and Robot Framework suites.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class StepRecord:
    """One simulation tick of ground truth + observed signals."""

    t: float
    setpoint_deg: float
    commanded_deg: float  # what the controller actually commanded (may be safe-state)
    true_position_deg: float  # ground truth from the plant (pre-fault)
    measured_position_deg: float | None  # what the controller received (post-fault; None=dropped)
    safe_state: bool


@dataclass
class Recorder:
    """Collects :class:`StepRecord`s and exposes export + behavioral queries."""

    records: list[StepRecord] = field(default_factory=list)

    def record(self, rec: StepRecord) -> None:
        self.records.append(rec)

    # --- export ---------------------------------------------------------------
    def to_csv(self, path: str | Path) -> Path:
        path = Path(path)
        with path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[f.name for f in StepRecord.__dataclass_fields__.values()])
            writer.writeheader()
            for rec in self.records:
                writer.writerow(asdict(rec))
        return path

    def to_jsonl(self, path: str | Path) -> Path:
        path = Path(path)
        with path.open("w") as f:
            for rec in self.records:
                f.write(json.dumps(asdict(rec)) + "\n")
        return path

    # --- behavioral oracles ---------------------------------------------------
    def time_to_safe_state(self) -> float | None:
        """Logical time at which the DUT first latched safe-state, or None."""
        for rec in self.records:
            if rec.safe_state:
                return rec.t
        return None

    def max_tracking_error(self, *, ignore_after_safe: bool = True) -> float:
        """Largest |setpoint - true position| (optionally before safe-state)."""
        worst = 0.0
        for rec in self.records:
            if ignore_after_safe and rec.safe_state:
                break
            worst = max(worst, abs(rec.setpoint_deg - rec.true_position_deg))
        return worst

    def dropped_sample_count(self) -> int:
        return sum(1 for rec in self.records if rec.measured_position_deg is None)

    def summary(self) -> dict[str, object]:
        tts = self.time_to_safe_state()
        return {
            "ticks": len(self.records),
            "duration_s": round(self.records[-1].t, 4) if self.records else 0.0,
            "reached_safe_state": tts is not None,
            "time_to_safe_state_s": round(tts, 4) if tts is not None else None,
            "max_tracking_error_deg": round(self.max_tracking_error(), 3),
            "dropped_samples": self.dropped_sample_count(),
        }
