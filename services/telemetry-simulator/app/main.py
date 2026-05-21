"""ForgeMind telemetry simulator.

Spawns N virtual machines, each producing realistic time-series telemetry
(temperature, vibration, pressure, RPM, power, units produced, defects).

  * Baseline drift via Ornstein-Uhlenbeck process.
  * Random short downtime events.
  * Injectable anomalies (vibration spike, thermal runaway, pressure
    drop, motor stall) via the REST API.
  * Streams to NATS on `forgemind.telemetry`.
  * Optional HTTP push to the anomaly-detection service for direct
    pipelines without NATS.

Run as a FastAPI service so operators can inject anomalies on demand
from the frontend.
"""

from __future__ import annotations

import asyncio
import math
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from forgemind_common import (
    TelemetryReading,
    get_logger,
    get_settings,
    setup_logging,
)
from forgemind_common.messaging import publish
from forgemind_common.observability import install_metrics

setup_logging("telemetry-simulator")
log = get_logger(__name__)
settings = get_settings()


# ----------------------------------------------------------------------
# Machine model
# ----------------------------------------------------------------------


class MachineSim:
    """A virtual factory machine with realistic noise + drift."""

    BASELINES: dict[str, dict[str, float]] = {
        "CNC":         {"temp": 62.0, "vib": 1.8, "press": 4.2, "rpm": 2400, "power": 18.0},
        "PRESS":       {"temp": 71.0, "vib": 2.6, "press": 18.5, "rpm": 0,    "power": 42.0},
        "ROBOT":       {"temp": 48.0, "vib": 0.9, "press": 2.0, "rpm": 0,     "power": 6.0},
        "OVEN":        {"temp": 215.0, "vib": 0.3, "press": 1.1, "rpm": 0,    "power": 55.0},
        "CONVEYOR":    {"temp": 38.0, "vib": 0.6, "press": 0.8, "rpm": 180,   "power": 3.5},
        "INSPECTION":  {"temp": 41.0, "vib": 0.4, "press": 1.0, "rpm": 0,     "power": 2.0},
    }

    def __init__(
        self,
        machine_id: str,
        machine_type: str,
        line_id: str = "line-A",
        plant_id: str = "plant-01",
    ) -> None:
        self.machine_id = machine_id
        self.machine_type = machine_type
        self.line_id = line_id
        self.plant_id = plant_id
        b = self.BASELINES.get(machine_type, self.BASELINES["CNC"])
        self.temp = b["temp"]
        self.vib = b["vib"]
        self.press = b["press"]
        self.rpm = b["rpm"]
        self.power = b["power"]
        self.state: str = "RUNNING"
        self.units = 0
        self.defects = 0
        self.tick = 0
        # Active anomaly injections (key -> ticks remaining)
        self.anomaly_state: dict[str, int] = {}

    def _ou(self, current: float, mean: float, sigma: float, theta: float = 0.15) -> float:
        """Ornstein-Uhlenbeck step (mean-reverting noise)."""
        return current + theta * (mean - current) + sigma * random.gauss(0, 1)

    def inject(self, kind: str, duration_ticks: int = 60) -> None:
        self.anomaly_state[kind] = duration_ticks
        log.info("simulator.inject", machine=self.machine_id, kind=kind, ticks=duration_ticks)

    def _apply_anomalies(self) -> None:
        expired: list[str] = []
        for kind, remaining in self.anomaly_state.items():
            if remaining <= 0:
                expired.append(kind)
                continue
            self.anomaly_state[kind] -= 1
            if kind == "vibration_spike":
                self.vib += random.uniform(2.0, 5.0)
            elif kind == "thermal_runaway":
                self.temp += random.uniform(0.5, 1.4)
            elif kind == "pressure_drop":
                self.press = max(0.1, self.press - random.uniform(0.3, 0.8))
            elif kind == "motor_stall":
                self.rpm = max(0.0, self.rpm * 0.7)
                self.state = "DOWN"
            elif kind == "quality_spike":
                self.defects += random.randint(2, 8)
            elif kind == "power_surge":
                self.power += random.uniform(8.0, 18.0)
        for kind in expired:
            self.anomaly_state.pop(kind, None)
        if "motor_stall" not in self.anomaly_state and self.state == "DOWN":
            # Recover after stall ends.
            if random.random() < 0.2:
                self.state = "RUNNING"

    def step(self) -> TelemetryReading:
        self.tick += 1
        b = self.BASELINES.get(self.machine_type, self.BASELINES["CNC"])

        # Random brief downtime (~0.5% of ticks).
        if self.state == "RUNNING" and random.random() < 0.005:
            self.state = "IDLE"
        elif self.state == "IDLE" and random.random() < 0.1:
            self.state = "RUNNING"

        if self.state == "RUNNING":
            self.temp = self._ou(self.temp, b["temp"], 0.4)
            self.vib = max(0.0, self._ou(self.vib, b["vib"], 0.08))
            self.press = max(0.0, self._ou(self.press, b["press"], 0.15))
            self.rpm = max(0.0, self._ou(self.rpm, b["rpm"], 12.0))
            self.power = max(0.0, self._ou(self.power, b["power"], 0.5))
            self.units += random.randint(0, 3)
            if random.random() < 0.02:
                self.defects += 1
        else:
            self.rpm *= 0.95
            self.power *= 0.9
            self.temp = self._ou(self.temp, b["temp"] * 0.6, 0.2)

        self._apply_anomalies()

        return TelemetryReading(
            machine_id=self.machine_id,
            line_id=self.line_id,
            plant_id=self.plant_id,
            timestamp=datetime.now(timezone.utc),
            temperature_c=round(self.temp, 2),
            vibration_mm_s=round(self.vib, 3),
            pressure_bar=round(self.press, 3),
            rpm=round(self.rpm, 1),
            power_kw=round(self.power, 2),
            state=self.state,  # type: ignore[arg-type]
            units_produced=self.units,
            defects=self.defects,
        )


# ----------------------------------------------------------------------
# Fleet
# ----------------------------------------------------------------------

FLEET: dict[str, MachineSim] = {}


def _build_fleet() -> None:
    spec = [
        ("CNC-101", "CNC", "line-A"),
        ("CNC-102", "CNC", "line-A"),
        ("PRESS-201", "PRESS", "line-A"),
        ("ROBOT-301", "ROBOT", "line-A"),
        ("OVEN-401", "OVEN", "line-B"),
        ("CNC-103", "CNC", "line-B"),
        ("PRESS-202", "PRESS", "line-B"),
        ("CONV-501", "CONVEYOR", "line-B"),
        ("ROBOT-302", "ROBOT", "line-C"),
        ("INSP-601", "INSPECTION", "line-C"),
    ]
    for mid, mtype, line in spec:
        FLEET[mid] = MachineSim(mid, mtype, line_id=line)


# ----------------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------------


class InjectRequest(BaseModel):
    machine_id: str
    kind: Literal[
        "vibration_spike",
        "thermal_runaway",
        "pressure_drop",
        "motor_stall",
        "quality_spike",
        "power_surge",
    ]
    duration_ticks: int = Field(60, ge=1, le=600)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _build_fleet()
    task = asyncio.create_task(_pump_loop())
    log.info("simulator.started", machines=len(FLEET))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="ForgeMind Telemetry Simulator", version="0.1.0", lifespan=lifespan)
install_metrics(app, "telemetry-simulator")


async def _pump_loop() -> None:
    interval = 1.0  # one tick per second
    while True:
        try:
            await asyncio.sleep(interval)
            for sim in FLEET.values():
                reading = sim.step()
                await publish(settings.telemetry_subject, reading.model_dump(mode="json"))
        except asyncio.CancelledError:  # noqa: PERF203
            break
        except Exception:  # noqa: BLE001
            log.exception("simulator.pump_error")


@app.get("/api/v1/machines")
async def list_machines() -> list[dict]:
    return [
        {
            "machine_id": s.machine_id,
            "machine_type": s.machine_type,
            "line_id": s.line_id,
            "plant_id": s.plant_id,
            "state": s.state,
            "active_anomalies": list(s.anomaly_state.keys()),
        }
        for s in FLEET.values()
    ]


@app.get("/api/v1/snapshot")
async def snapshot() -> list[dict]:
    return [sim.step().model_dump(mode="json") for sim in FLEET.values()]


@app.post("/api/v1/inject")
async def inject(req: InjectRequest) -> dict:
    sim = FLEET.get(req.machine_id)
    if not sim:
        raise HTTPException(404, f"Unknown machine: {req.machine_id}")
    sim.inject(req.kind, req.duration_ticks)
    return {"ok": True, "machine_id": req.machine_id, "kind": req.kind}


@app.post("/api/v1/replay-historical")
async def replay() -> dict:
    """Inject a wave of preset anomalies — handy for the demo flow."""
    plan = [
        ("CNC-101", "vibration_spike", 90),
        ("PRESS-201", "thermal_runaway", 120),
        ("OVEN-401", "power_surge", 60),
        ("CONV-501", "motor_stall", 45),
        ("INSP-601", "quality_spike", 80),
    ]
    for mid, kind, dur in plan:
        if mid in FLEET:
            FLEET[mid].inject(kind, dur)
    return {"injected": [{"machine_id": m, "kind": k, "ticks": d} for m, k, d in plan]}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
