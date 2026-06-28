"""Fixed-step HIL loop that wires the controller (DUT) to the plant simulator.

This is the deterministic test harness. It advances a logical clock at the rig's
fixed rate, exchanges messages over the transport, and records ground truth vs.
observed signals every tick. No wall-clock is used, so runs are perfectly
reproducible — the property that makes a captured failure replayable.

Feedback reaches the controller one tick after it is produced (the feedback
queued by ``simulator.step`` is read by the controller on the next iteration),
modelling realistic loop latency.
"""

from __future__ import annotations

from dataclasses import dataclass

from .controller import Controller
from .instrumentation import Recorder, StepRecord
from .simulator import PlantSimulator
from .transport import Transport


@dataclass
class HilLoop:
    transport: Transport
    controller: Controller
    simulator: PlantSimulator

    def run(self, duration_s: float) -> Recorder:
        """Run the closed loop for ``duration_s`` and return the recorder."""
        rec = Recorder()
        dt = self.simulator.dt
        n_ticks = int(round(duration_s / dt))

        for i in range(n_ticks):
            t = i * dt

            # 1. Controller consumes feedback produced on the previous tick.
            fb_in = self.transport.recv_feedback()
            cmd = self.controller.update(t, fb_in)
            self.transport.send_command(cmd)

            # 2. Plant advances and emits this tick's (fault-injected) feedback.
            sent_fb = self.simulator.step(t)

            # 3. Record ground truth (pre-fault plant state) vs. what was sent.
            rec.record(
                StepRecord(
                    t=t,
                    setpoint_deg=self.controller.setpoint(t),
                    commanded_deg=self.controller.last_command_deg,
                    true_position_deg=self.simulator.actuator.position_deg,
                    measured_position_deg=(
                        sent_fb.measured_position_deg if sent_fb is not None else None
                    ),
                    safe_state=self.controller.monitor.tripped,
                )
            )

        return rec
