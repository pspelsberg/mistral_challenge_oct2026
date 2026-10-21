"""Slice 5: Telemetry and Performance Evaluation (Section 15)."""

from rogue_agent.features.telemetry_eval.collector import SessionTelemetryCollector
from rogue_agent.features.telemetry_eval.report import (
    aggregate_runs_by_version,
    export_session_gif,
)

__all__ = [
    "SessionTelemetryCollector",
    "aggregate_runs_by_version",
    "export_session_gif",
]
