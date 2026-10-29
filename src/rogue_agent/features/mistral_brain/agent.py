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

_REDIRECT_PRIORITY: tuple[Direction, ...] = (
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
    Direction.NORTH,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
    Direction.NORTHEAST,
    Direction.NORTHWEST,
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
            if (
                not self.settings.mistral_api_key
                or self.settings.mistral_api_key == "your_mistral_api_key_here"
            ):
                raise RuntimeError(
                    "MISTRAL_API_KEY is not configured. Set MISTRAL_API_KEY in .env or use --dry-run."
                )
            self._client = Mistral(api_key=self.settings.mistral_api_key)
        return self._client

    @staticmethod
    def _parse_forbidden_direction(memory_summary: str) -> Direction | None:
        """Extract the forbidden reverse direction from an oscillation alert in memory."""
        if "FORBIDDEN OSCILLATION DIRECTION: direction='" in memory_summary:
            try:
                f_val = (
                    memory_summary.split("FORBIDDEN OSCILLATION DIRECTION: direction='", 1)[1]
                    .split("'", 1)[0]
                    .lower()
                )
                return Direction(f_val)
            except Exception:
                return None

        if "Bounced (" in memory_summary:
            try:
                part = memory_summary.split("Bounced (", 1)[1]
                p2_str, rest = part.split(") -> (", 1)
                p1_str = rest.split(")", 1)[0]
                r2, c2 = (int(x.strip()) for x in p2_str.split(","))
                r1, c1 = (int(x.strip()) for x in p1_str.split(","))
                return Direction.from_delta(r1 - r2, c1 - c2)
            except Exception:
                return None

        return None

    @classmethod
    def _apply_anti_oscillation_guard(
        cls,
        action: GameAction,
        observation: GameObservation,
        memory_summary: str,
    ) -> GameAction:
        """Redirect movement only if the model chose a forbidden reverse or unwalkable move during oscillation."""
        if action.action_type not in (ActionType.MOVE, ActionType.FAST_MOVE) or not action.direction:
            return action

        has_oscillation_alert = any(
            marker in memory_summary
            for marker in (
                "OSCILLATION ALERT",
                "MACRO-BACKTRACKING",
                "FORBIDDEN OSCILLATION DIRECTION",
            )
        )
        if not has_oscillation_alert:
            return action

        walkable_dirs = [
            str(d).upper()
            for d in (observation.inferred_metadata.get("walkable_directions") or [])
        ]
        forbidden_dir = cls._parse_forbidden_direction(memory_summary)
        is_forbidden = bool(forbidden_dir and action.direction == forbidden_dir)
        is_unwalkable = bool(walkable_dirs and not action.direction.matches_walkable(walkable_dirs))

        if not (is_forbidden or is_unwalkable):
            return action

        redirect_dir: Direction | None = None
        if "TOPOLOGICAL COMPASS HINT:" in memory_summary and "direction='" in memory_summary:
            try:
                raw_compass_d = (
                    memory_summary.split("TOPOLOGICAL COMPASS HINT:", 1)[1]
                    .split("direction='", 1)[1]
                    .split("'", 1)[0]
                    .lower()
                )
                c_dir = Direction(raw_compass_d)
                if c_dir.matches_walkable(walkable_dirs) and c_dir != forbidden_dir:
                    redirect_dir = c_dir
            except Exception:
                pass

        if redirect_dir is None:
            for d_cand in _REDIRECT_PRIORITY:
                if d_cand.matches_walkable(walkable_dirs) and d_cand != forbidden_dir:
                    redirect_dir = d_cand
                    break

        if redirect_dir is None:
            return action

        reason = (
            f"forbidden reverse move {action.direction.value} (would continue oscillation)"
            if is_forbidden
            else f"unwalkable/wall-collision move {action.direction.value}"
        )
        return action.model_copy(
            update={
                "direction": redirect_dir,
                "steps": 1,
                "decision_summary": (
                    f"[Anti-Oscillation Guard] Intercepted {reason}; redirected to {redirect_dir.value}"
                ),
            }
        )

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
                    max_tokens=1024,
                    reasoning_effort="low",
                    timeout_ms=timeout_ms,
                )
            except TypeError:
                return client.chat.parse(
                    model=self.model_id,
                    messages=messages,
                    response_format=MistralActionDecision,
                    temperature=0.2,
                    max_tokens=1024,
                    timeout_ms=timeout_ms,
                )

        try:
            response = self.guard.call_with_backoff(_invoke)
            latency_ms = (time.monotonic() - t0) * 1000.0
        except Exception as exc:
            self.invalid_responses += 1
            exc_str = str(exc)
            if any(term in exc_str for term in ("delimiter", "JSON", "Expecting", "Unterminated")):
                return safe_fallback_action(
                    observation,
                    reason=f"LLM output JSON format error ({exc})",
                    player_name=self.settings.player_name,
                )
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
                raise ValueError("Empty parsed decision from Mistral API response")
            action = parsed.to_game_action(observation)
            return self._apply_anti_oscillation_guard(action, observation, memory_summary)
        except Exception as exc:
            self.invalid_responses += 1
            return safe_fallback_action(
                observation,
                reason=f"Schema fallback ({exc})",
                player_name=self.settings.player_name,
            )

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
        if isinstance(walkable, list) and walkable and not direction.matches_walkable(walkable):
            for cand in self._directions:
                if cand.matches_walkable(walkable):
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
