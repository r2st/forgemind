"""ForgeMind common shared library."""

from .config import Settings, get_settings
from .logging import get_logger, setup_logging
from .tfy_gateway import TrueFoundryGateway, ModelTier, get_gateway
from .schemas import (
    TelemetryReading,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    Machine,
    RCAReport,
    MaintenancePrediction,
    ChatMessage,
)
from .hermes_runtime import (
    HermesAgentRuntime,
    ToolRegistry,
    Tool,
    AgentActivity,
    ActivityLedger,
    get_activity_ledger,
    new_runtime,
    HERMES_AVAILABLE,
)

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "get_settings",
    "get_logger",
    "setup_logging",
    "TrueFoundryGateway",
    "ModelTier",
    "get_gateway",
    "TelemetryReading",
    "Incident",
    "IncidentSeverity",
    "IncidentStatus",
    "Machine",
    "RCAReport",
    "MaintenancePrediction",
    "ChatMessage",
    "HermesAgentRuntime",
    "ToolRegistry",
    "Tool",
    "AgentActivity",
    "ActivityLedger",
    "get_activity_ledger",
    "new_runtime",
    "HERMES_AVAILABLE",
]
