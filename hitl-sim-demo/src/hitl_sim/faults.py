"""Bus-level fault injection.

Implements the nine-fault menu documented in the research (MDPI *Sensors* 2024
automotive HIL framework): **gain, offset, hard-over, stuck-at, delay, noise,
packet-loss, drift, spike**. Faults are applied to a scalar signal (here the
measured fin position) at the *bus boundary* between plant and controller —
"injected programmatically, in real time, as a black box, without modifying the
original plant model."

Each fault is windowed by ``[t_start, t_end)`` so a scenario can schedule faults
at specific times. Faults compose: a :class:`FaultInjector` applies a list in
order. Returning ``None`` from ``apply`` means "this sample is dropped" (used by
packet loss) — the transport then delivers nothing for that tick.

Determinism: stochastic faults (noise, packet-loss) take a seed and use a
private RNG, so a failing run replays bit-for-bit.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

# A sample value of ``None`` means "dropped / no update this tick".
Sample = float | None


@dataclass
class Fault:
    """Base class. Subclasses override :meth:`_apply`."""

    t_start: float = 0.0
    t_end: float = math.inf

    def active(self, t: float) -> bool:
        return self.t_start <= t < self.t_end

    def apply(self, t: float, value: Sample) -> Sample:
        if value is None or not self.active(t):
            return value
        return self._apply(t, value)

    def _apply(self, t: float, value: float) -> Sample:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class GainFault(Fault):
    """Scale the signal: ``value * gain`` (sensor scale-factor error)."""

    gain: float = 1.0

    def _apply(self, t: float, value: float) -> Sample:
        return value * self.gain


@dataclass
class OffsetFault(Fault):
    """Add a constant bias (sensor zero/offset error)."""

    offset: float = 0.0

    def _apply(self, t: float, value: float) -> Sample:
        return value + self.offset


@dataclass
class HardOverFault(Fault):
    """Force the signal to an extreme value (runaway feedback)."""

    value: float = 30.0

    def _apply(self, t: float, value: float) -> Sample:
        return self.value


@dataclass
class StuckAtFault(Fault):
    """Freeze the signal. Holds either a fixed ``value`` or the first sample seen.

    A frozen feedback (e.g. jammed/failed sensor) is the classic case the
    controller's safety monitor must catch.
    """

    value: float | None = None  # None => hold the value at first activation
    _held: float | None = field(default=None, init=False, repr=False)

    def _apply(self, t: float, value: float) -> Sample:
        if self.value is not None:
            return self.value
        if self._held is None:
            self._held = value
        return self._held


@dataclass
class DelayFault(Fault):
    """Delay the signal by ``delay_samples`` ticks (transport/processing latency)."""

    delay_samples: int = 1
    _buf: deque[float] = field(default_factory=deque, init=False, repr=False)

    def _apply(self, t: float, value: float) -> Sample:
        self._buf.append(value)
        if len(self._buf) <= self.delay_samples:
            # Buffer not yet full: emit the oldest available sample.
            return self._buf[0]
        return self._buf.popleft()


@dataclass
class NoiseFault(Fault):
    """Add zero-mean Gaussian noise with std ``sigma`` (seeded for determinism)."""

    sigma: float = 0.1
    seed: int = 0
    _rng: random.Random = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _apply(self, t: float, value: float) -> Sample:
        return value + self._rng.gauss(0.0, self.sigma)


@dataclass
class PacketLossFault(Fault):
    """Drop samples with probability ``drop_prob`` (seeded). Dropped => ``None``."""

    drop_prob: float = 0.1
    seed: int = 0
    _rng: random.Random = field(default=None, init=False, repr=False)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def _apply(self, t: float, value: float) -> Sample:
        return None if self._rng.random() < self.drop_prob else value


@dataclass
class DriftFault(Fault):
    """Linear drift: adds ``rate_per_s * (t - t_start)`` (slowly biasing sensor)."""

    rate_per_s: float = 1.0

    def _apply(self, t: float, value: float) -> Sample:
        return value + self.rate_per_s * (t - self.t_start)


@dataclass
class SpikeFault(Fault):
    """Inject periodic transient spikes of ``magnitude`` every ``period_s``."""

    magnitude: float = 10.0
    period_s: float = 0.5
    tol: float = 1e-9
    _last_spike: float = field(default=-math.inf, init=False, repr=False)

    def _apply(self, t: float, value: float) -> Sample:
        if t - self._last_spike >= self.period_s - self.tol:
            self._last_spike = t
            return value + self.magnitude
        return value


@dataclass
class FaultInjector:
    """Applies a list of faults in order to each sample at the bus boundary."""

    faults: list[Fault] = field(default_factory=list)

    def apply(self, t: float, value: Sample) -> Sample:
        for fault in self.faults:
            value = fault.apply(t, value)
            if value is None:
                break  # dropped; later faults can't act on a non-existent sample
        return value
