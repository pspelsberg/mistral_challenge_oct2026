"""Hexagonal Ports (Protocol interfaces) decoupling slices from concrete implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rogue_agent.shared.domain import (
    ActionExecutionResult,
    GameAction,
    GameObservation,
    GameState,
)


@runtime_checkable
class ControlProfilePort(Protocol):
    """Version-specific translation of GameAction into raw key sequences (Section 8)."""

    @property
    def version_name(self) -> str:
        """Identifier of the Rogue version this control profile targets."""
        ...

    def translate_action(self, action: GameAction, current_state: GameState) -> list[str]:
        """Translate a high-level GameAction into an ordered list of key tokens."""
        ...


@runtime_checkable
class GameBackendPort(Protocol):
    """Common backend-neutral game environment interface (Section 5)."""

    @property
    def rogue_version(self) -> str:
        """Concrete Rogue version string (e.g., 'epyx-1.49' or 'rogue-5.4.4')."""
        ...

    def start(self) -> GameObservation:
        """Start or connect to the game and return the initial observation."""
        ...

    def observe(self) -> GameObservation:
        """Capture and parse the current visible game state."""
        ...

    def execute_action(self, action: GameAction) -> ActionExecutionResult:
        """Translate and inject a validated GameAction into the running game."""
        ...

    def detect_game_state(self) -> GameState:
        """Return the current UI / gameplay state."""
        ...

    def reset(self) -> GameObservation:
        """Reset the game session where supported, or restart cleanly."""
        ...

    def close(self) -> None:
        """Gracefully terminate or detach from the game process/window."""
        ...

    def get_diagnostics(self) -> dict[str, Any]:
        """Return backend health and runtime diagnostic metadata."""
        ...


@runtime_checkable
class GameplayAgentPort(Protocol):
    """Interface for the Mistral Large 4 autonomous gameplay agent (Section 9)."""

    @property
    def model_id(self) -> str:
        """Return the configured model identifier (must be 'mistral-large-4')."""
        ...

    def decide_action(
        self,
        observation: GameObservation,
        memory_summary: str,
        current_objective: str,
    ) -> GameAction:
        """Perceive the game observation and return a validated GameAction."""
        ...

    def get_usage_stats(self) -> dict[str, Any]:
        """Return cumulative API calls, token usage, latency, and estimated USD cost."""
        ...


@runtime_checkable
class MemoryPort(Protocol):
    """Bounded agent memory interface separating facts from hypotheses (Section 11)."""

    def record_turn(
        self,
        turn_index: int,
        obs_before: GameObservation,
        action: GameAction,
        result: ActionExecutionResult,
        obs_after: GameObservation,
    ) -> None:
        """Update bounded memory with turn outcome."""
        ...

    def build_prompt_summary(self, observation: GameObservation | None = None) -> str:
        """Render a compact, token-bounded memory summary for the model prompt."""
        ...

    def reset(self) -> None:
        """Clear memory for a new game run."""
        ...

    def get_snapshot(self) -> dict[str, Any]:
        """Return structured memory state for telemetry/debugging."""
        ...


@runtime_checkable
class TelemetryPort(Protocol):
    """Telemetry and session evaluation logger interface (Section 15)."""

    def start_session(self, backend: str, rogue_version: str, model_id: str, dry_run: bool) -> str:
        """Initialize a run directory and return its path."""
        ...

    def log_turn(
        self,
        turn_index: int,
        observation: GameObservation,
        action: GameAction,
        execution_result: ActionExecutionResult,
        agent_stats: dict[str, Any],
        latency_ms: float,
    ) -> None:
        """Record a single turn's observation, action, and metrics."""
        ...

    def finish_session(
        self,
        final_observation: GameObservation | None,
        termination_reason: str,
        agent_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Write final session summary and return aggregated metrics."""
        ...
