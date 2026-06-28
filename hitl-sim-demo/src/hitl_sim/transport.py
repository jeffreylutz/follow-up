"""Transport seam between the controller (DUT) and the plant simulator.

This is the most important abstraction in the demo. Both sides talk only to a
``Transport``; they never know whether bytes move through an in-process queue
(software demo / CI) or a real CAN bus / serial link on a Raspberry Pi bench.
Swapping transports requires zero changes to the actuator model, the fault
injector, the controller, or the tests — which is exactly what lets you "test
cheap in software and deploy unchanged to hardware."

The demo ships :class:`LoopbackTransport`. To run against a real controller from
a Pi, implement the same two methods over python-can or pyserial (sketched in
``CanTransport`` / ``SerialTransport`` below).
"""

from __future__ import annotations

import struct
from collections import deque
from typing import TYPE_CHECKING, Protocol

from .messages import ActuatorCommand, ActuatorFeedback, ActuatorStatus

if TYPE_CHECKING:  # avoid importing python-can unless the CAN transport is used
    import can


class Transport(Protocol):
    """Minimal duplex channel carrying commands one way and feedback the other."""

    def send_command(self, cmd: ActuatorCommand) -> None: ...
    def recv_command(self) -> ActuatorCommand | None: ...
    def send_feedback(self, fb: ActuatorFeedback) -> None: ...
    def recv_feedback(self) -> ActuatorFeedback | None: ...


class LoopbackTransport:
    """In-process transport: two queues, fully deterministic. Used by the demo/CI.

    ``recv_*`` returns ``None`` when nothing is queued, mirroring a non-blocking
    bus read on real hardware (so the controller must tolerate missing feedback —
    which is exactly what the packet-loss fault exercises).
    """

    def __init__(self) -> None:
        self._commands: deque[ActuatorCommand] = deque()
        self._feedback: deque[ActuatorFeedback] = deque()

    def send_command(self, cmd: ActuatorCommand) -> None:
        self._commands.append(cmd)

    def recv_command(self) -> ActuatorCommand | None:
        return self._commands.popleft() if self._commands else None

    def send_feedback(self, fb: ActuatorFeedback) -> None:
        self._feedback.append(fb)

    def recv_feedback(self) -> ActuatorFeedback | None:
        return self._feedback.popleft() if self._feedback else None


# --- CAN wire format -------------------------------------------------------------
#
# Classic CAN frames carry 8 data bytes. We pack into that budget; the 8-byte
# limit is a real constraint worth modelling (it forces the rate/timestamp
# trade-offs below). For richer payloads, CAN FD (64 bytes) would let every field
# travel as a double.
#
#   Command  (cmd_id):  float32 position | uint32 t_ms                 = 8 bytes
#   Feedback (fb_id):   float32 position | int16 rate*50 | uint8 status = 7 bytes
#
# Feedback has no room for a timestamp, so on decode the receiver stamps arrival
# time itself (t=0.0 here) — which is what real nodes do anyway.

_CMD_FMT = "<fI"
_FB_FMT = "<fhB"
_RATE_SCALE = 50.0  # int16 range ±32767 / 50 ≈ ±655 deg/s, covers the actuator
_STATUS_TO_INT = {ActuatorStatus.OK: 0, ActuatorStatus.SATURATED: 1, ActuatorStatus.FAULT: 2}
_INT_TO_STATUS = {v: k for k, v in _STATUS_TO_INT.items()}


def _clamp_i16(x: float) -> int:
    return max(-32768, min(32767, int(round(x))))


def encode_command(cmd: ActuatorCommand) -> bytes:
    return struct.pack(_CMD_FMT, cmd.commanded_position_deg, round(cmd.t * 1000) & 0xFFFFFFFF)


def decode_command(data: bytes) -> ActuatorCommand:
    position, t_ms = struct.unpack(_CMD_FMT, bytes(data[: struct.calcsize(_CMD_FMT)]))
    return ActuatorCommand(t=t_ms / 1000.0, commanded_position_deg=position)


def encode_feedback(fb: ActuatorFeedback) -> bytes:
    return struct.pack(
        _FB_FMT,
        fb.measured_position_deg,
        _clamp_i16(fb.measured_rate_dps * _RATE_SCALE),
        _STATUS_TO_INT[fb.status],
    )


def decode_feedback(data: bytes, *, t: float = 0.0) -> ActuatorFeedback:
    position, rate_scaled, status = struct.unpack(_FB_FMT, bytes(data[: struct.calcsize(_FB_FMT)]))
    return ActuatorFeedback(
        t=t,
        measured_position_deg=position,
        measured_rate_dps=rate_scaled / _RATE_SCALE,
        status=_INT_TO_STATUS.get(status, ActuatorStatus.OK),
    )


class CanTransport:
    """Real-hardware transport over python-can (``pip install hitl-sim[canbus]``).

    Satisfies the same :class:`Transport` interface as :class:`LoopbackTransport`,
    so the simulator/controller/tests are reused verbatim — only construction
    changes. On a Raspberry Pi bench:

        import can
        bus = can.Bus(interface="socketcan", channel="can0")
        sim = PlantSimulator(transport=CanTransport(bus), injector=my_faults)

    Reads are non-blocking (``recv_timeout=0``) to suit the real-time loop. Each
    node only uses the two methods it needs (the simulator: ``recv_command`` +
    ``send_feedback``); the bus's arbitration-ID filtering keeps directions
    separate.
    """

    def __init__(
        self,
        bus: can.BusABC,
        *,
        cmd_id: int = 0x100,
        fb_id: int = 0x101,
        recv_timeout: float = 0.0,
    ) -> None:
        self.bus = bus
        self.cmd_id = cmd_id
        self.fb_id = fb_id
        self.recv_timeout = recv_timeout

    def _send(self, arbitration_id: int, data: bytes) -> None:
        import can

        self.bus.send(can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=False))

    def _recv(self, want_id: int) -> bytes | None:
        while True:
            msg = self.bus.recv(timeout=self.recv_timeout)
            if msg is None:
                return None
            if msg.arbitration_id == want_id:
                return bytes(msg.data)

    def send_command(self, cmd: ActuatorCommand) -> None:
        self._send(self.cmd_id, encode_command(cmd))

    def recv_command(self) -> ActuatorCommand | None:
        data = self._recv(self.cmd_id)
        return decode_command(data) if data is not None else None

    def send_feedback(self, fb: ActuatorFeedback) -> None:
        self._send(self.fb_id, encode_feedback(fb))

    def recv_feedback(self) -> ActuatorFeedback | None:
        data = self._recv(self.fb_id)
        return decode_feedback(data) if data is not None else None


# --- Serial transport (sketch) ---------------------------------------------------
#
# class SerialTransport:
#     """pyserial implementation. `pip install hitl-sim[serial]`.
#
#     Frame the dataclasses (e.g. COBS + the struct formats above) over
#     /dev/serial0. Best paired with an RP2040/STM32 co-processor handling
#     deterministic PWM/ADC while the Pi runs the plant model and logging.
#     """
