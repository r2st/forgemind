"""Cross-service Pydantic schemas.

These are the canonical shapes that flow through NATS, REST, and the DB.
Keep them in one place so every service shares a contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ----------------------------------------------------------------------
# Telemetry
# ----------------------------------------------------------------------


class TelemetryReading(BaseModel):
    """A single sensor reading from a factory machine."""

    machine_id: str = Field(..., min_length=1, max_length=100)
    line_id: str = Field(default="line-A", min_length=1, max_length=100)
    plant_id: str = Field(default="plant-01", min_length=1, max_length=100)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Physical sensors - validate reasonable ranges to prevent data injection attacks
    temperature_c: float = Field(..., ge=-50, le=500)  # -50°C to 500°C
    vibration_mm_s: float = Field(..., ge=0, le=100)  # 0 to 100 mm/s
    pressure_bar: float = Field(..., ge=0, le=1000)  # 0 to 1000 bar
    rpm: float = Field(..., ge=0, le=50000)  # 0 to 50000 RPM
    power_kw: float = Field(..., ge=0, le=10000)  # 0 to 10000 kW

    # Operational state
    state: Literal["RUNNING", "IDLE", "DOWN", "MAINTENANCE"] = "RUNNING"
    units_produced: int = Field(default=0, ge=0, le=1000000)
    defects: int = Field(default=0, ge=0, le=1000000)

    # Optional metadata
    operator: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)


# ----------------------------------------------------------------------
# Machines
# ----------------------------------------------------------------------


class Machine(BaseModel):
    machine_id: str
    name: str
    machine_type: Literal["CNC", "PRESS", "ROBOT", "OVEN", "CONVEYOR", "INSPECTION"]
    line_id: str
    plant_id: str
    installed_at: datetime | None = None
    last_maintenance: datetime | None = None
    health_score: float = 1.0


# ----------------------------------------------------------------------
# Incidents
# ----------------------------------------------------------------------


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    SUPPRESSED = "SUPPRESSED"


class Incident(BaseModel):
    """An anomaly or operational event flagged for attention."""

    incident_id: UUID = Field(default_factory=uuid4)
    machine_id: str
    line_id: str = "line-A"
    plant_id: str = "plant-01"

    title: str
    description: str
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    status: IncidentStatus = IncidentStatus.OPEN

    # Detection metadata
    detector: str = "statistical"        # statistical | iforest | llm | manual
    metric: str | None = None             # vibration_mm_s | temperature_c | ...
    score: float | None = None            # detector-specific score
    confidence: float = 0.5
    z_score: float | None = None

    # Lifecycle
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    # Context snapshot used by RCA
    context: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# RCA reports
# ----------------------------------------------------------------------


class RCAFinding(BaseModel):
    category: str          # MECHANICAL | ELECTRICAL | PROCESS | OPERATOR | MATERIAL
    hypothesis: str
    evidence: list[str]
    likelihood: float      # 0..1


class RCAReport(BaseModel):
    report_id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    machine_id: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    summary: str
    findings: list[RCAFinding]
    recommended_actions: list[str]
    confidence: float
    similar_incidents: list[UUID] = Field(default_factory=list)
    model_used: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0


# ----------------------------------------------------------------------
# Predictive maintenance
# ----------------------------------------------------------------------


class MaintenancePrediction(BaseModel):
    machine_id: str
    predicted_at: datetime = Field(default_factory=datetime.utcnow)
    risk_score: float                  # 0..1
    estimated_failure_in_hours: float
    recommended_window_start: datetime
    recommended_window_end: datetime
    rationale: str
    contributing_signals: list[str]


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    session_id: str
    messages: list[ChatMessage]
    stream: bool = True
    model_tier: Literal["fast", "powerful", "fallback"] = "powerful"


class ChatResponse(BaseModel):
    session_id: str
    message: ChatMessage
    model_used: str
    tokens_used: int = 0
    cost_usd: float = 0.0
