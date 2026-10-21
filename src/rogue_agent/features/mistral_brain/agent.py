"""Mistral Large 4 gameplay agent and dry-run mock agent (Section 9)."""

from __future__ import annotations

import json
import time
from typing import Any

from mistralai.client import Mistral

from rogue_agent.features.mistral_brain.prompts import build_mistral_messages
from rogue_agent.features.mistral_brain.resilience import BudgetAndRateGuard
from rogue_agent.features.mistral_brain.schemas import (
    MistralActionDecision,
    safe_fallback_action,
)
from rogue_agent.shared.config import MANDATORY_GAMEPLAY_MODEL, RogueAgentSettings
from rogue_agent.shared.domain import (
    ActionType,
    Direction,
    GameAction,
    GameObservation,
    GameState,
)


class MistralGameplayAgent:
    """Autonomous Rogue gameplay agent powered exclusively by mistral-large-4."""

    def __init__(
        self,
        settings: RogueAgentSettings | None = None,
        guard: BudgetAndRateGuard | None = None,
        client: Any | None = None,
    ) -> None:
        self.settings = settings or RogueAgentSettings()
        if self.settings.model_id != MANDATORY_GAMEPLAY_MODEL:
            raise ValueError(f"Only {MANDATORY_GAMEPLAY_MODEL} is permitted for gameplay.")

        self.guard = guard or BudgetAndRateGuard(self.settings)
        self._client = client
        self.invalid_responses: int = 0

    @property
    def model_id(self) -> str:
        return self.settings.model_id

    def _get_client(self) -> Mistral:
        if self._client is None:
            if not self.settings.mistral_api_key or self.settings.mistral_api_key == "your_mistral_api_key_here":
                raise RuntimeError(
                    "MISTRAL_API_KEY is not configured. Set MISTRAL_API_KEY in .env or use --dry-run."
                )
            self._client = Mistral(api_key=self.settings.mistral_api_key)
        return self._client

    def decide_action(
        self,
        observation: GameObservation,
        memory_summary: str,
        current_objective: str,
    ) -> GameAction:
        """Send current observation + bounded memory to mistral-large-4 and parse GameAction."""
        client = self._get_client()
        messages = build_mistral_messages(
            observation,
            memory_summary,
            current_objective,
            screenshot_backup_only=self.settings.steam_screenshot_backup_only,
        )
        timeout_ms = int(self.settings.request_timeout_seconds * 1000)

        t0 = time.monotonic()

        def _invoke() -> Any:
            try:
                return client.chat.parse(
                    model=self.model_id,
                    messages=messages,
                    response_format=MistralActionDecision,
                    temperature=0.2,
                    max_tokens=2048,
                    reasoning_effort="none",
                    timeout_ms=timeout_ms,
                )
            except TypeError:
                return client.chat.parse(
                    model=self.model_id,
                    messages=messages,
                    response_format=MistralActionDecision,
                    temperature=0.2,
                    max_tokens=2048,
                    timeout_ms=timeout_ms,
                )

        try:
            response = self.guard.call_with_backoff(_invoke)
            latency_ms = (time.monotonic() - t0) * 1000.0
        except Exception as exc:
            self.invalid_responses += 1
            raise RuntimeError(f"Mistral Large 4 API request failed: {exc}") from exc

        usage = getattr(response, "usage", None)
        p_tok = getattr(usage, "prompt_tokens", None) if usage else None
        c_tok = getattr(usage, "completion_tokens", None) if usage else None
        self.guard.record_api_call(p_tok, c_tok, latency_ms)

        try:
            choice = response.choices[0]
            parsed: MistralActionDecision | None = getattr(choice.message, "parsed", None)
            if parsed is None:
                raw_content = choice.message.content
                if isinstance(raw_content, str):
                    parsed = MistralActionDecision.model_validate(json.loads(raw_content))
            if parsed is None:
                raise ValueError("Empty parsed decision from mistral-large-4")
            return parsed.to_game_action(observation)
        except Exception as exc:
            self.invalid_responses += 1
            return safe_fallback_action(observation, reason=f"Schema fallback ({exc})")

    def get_usage_stats(self) -> dict[str, Any]:
        stats = self.guard.get_stats()
        stats["model_id"] = self.model_id
        stats["invalid_responses"] = self.invalid_responses
        return stats


class DryRunGameplayAgent:
    """Zero-cost local mock agent for verifying harness pipelines (--dry-run)."""

    def __init__(self, settings: RogueAgentSettings | None = None) -> None:
        self.settings = settings or RogueAgentSettings()
        self._turn = 0
        self._directions = [
            Direction.EAST,
            Direction.SOUTH,
            Direction.WEST,
            Direction.NORTH,
        ]

    @property
    def model_id(self) -> str:
        return f"{self.settings.model_id} (dry-run)"

    def decide_action(
        self,
        observation: GameObservation,
        memory_summary: str,
        current_objective: str,
    ) -> GameAction:
        """Select a safe, deterministic verification action without calling the paid API."""
        self._turn += 1
        if observation.game_state in (
            GameState.MORE_PROMPT,
            GameState.START_MENU,
            GameState.INVENTORY,
        ):
            return GameAction(
                action_type=ActionType.ACKNOWLEDGE_PROMPT,
                decision_summary="[DryRun] Clear prompt with Space",
                objective=current_objective,
                confidence=1.0,
            )
        if observation.game_state == GameState.CHARACTER_NAME_ENTRY:
            return GameAction(
                action_type=ActionType.ENTER_NAME,
                text_input=self.settings.player_name,
                decision_summary="[DryRun] Enter character name",
                objective="Start game",
                confidence=1.0,
            )
        if self._turn % 5 == 0:
            return GameAction(
                action_type=ActionType.SEARCH,
                decision_summary="[DryRun] Periodic search for hidden doors",
                objective="Verify search command",
                confidence=0.9,
            )
        direction = self._directions[(self._turn - 1) % len(self._directions)]
        walkable = observation.inferred_metadata.get("walkable_directions")
        if isinstance(walkable, list) and walkable and direction.value not in walkable:
            for cand in self._directions:
                if cand.value in walkable:
                    direction = cand
                    break
        return GameAction(
            action_type=ActionType.MOVE,
            direction=direction,
            steps=3,
            decision_summary=f"[DryRun] Short-horizon move {direction.value} (up to 3 steps)",
            objective="Verify observation-action loop and interrupt guard",
            confidence=0.9,
        )

    def get_usage_stats(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "api_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "budget_limit_usd": self.settings.max_budget_usd,
            "avg_latency_ms": 0.0,
            "invalid_responses": 0,
        }
