"""ForgeMind common shared library."""

from .config import Settings, get_settings
from .logging import get_logger, setup_logging
from .llm_gateway import LLMGateway, ModelTier, get_gateway
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
from .runtime_config import (
    KNOWN_AGENTS,
    config_for_admin,
    load_runtime_config,
    resolve_llm_config,
    save_runtime_config,
    update_agent_config,
    update_default_config,
)

__version__ = "0.1.0"

__all__ = [
    "Settings",
    "get_settings",
    "get_logger",
    "setup_logging",
    "LLMGateway",
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
    "KNOWN_AGENTS",
    "config_for_admin",
    "load_runtime_config",
    "resolve_llm_config",
    "save_runtime_config",
    "update_agent_config",
    "update_default_config",
]
