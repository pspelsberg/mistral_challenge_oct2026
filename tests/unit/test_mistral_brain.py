"""Level 1 Unit Tests for Mistral Brain (Schemas, Prompts, BudgetGuard, and Mock Client)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rogue_agent.features.mistral_brain.agent import MistralGameplayAgent
from rogue_agent.features.mistral_brain.prompts import build_mistral_messages
from rogue_agent.features.mistral_brain.resilience import (
    BudgetAndRateGuard,
    BudgetExceededError,
    SessionLimitReachedError,
)
from rogue_agent.features.mistral_brain.schemas import MistralActionDecision
from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.domain import (
    ActionType,
    BackendId,
    Direction,
    GameObservation,
    GameState,
)


@pytest.mark.unit
def test_mistral_action_decision_repairs_incomplete_actions() -> None:
    """If mistral-large-4 omits direction on a move, fallback safely instead of crashing."""
    obs = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.PLAYING,
    )
    bad_decision = MistralActionDecision(
        observed_state=GameState.PLAYING,
        action=ActionType.MOVE,
        direction=None,
        decision_summary="Move without direction",
    )
    action = bad_decision.to_game_action(obs)
    assert action.action_type == ActionType.SEARCH

    obs_more = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.MORE_PROMPT,
    )
    action_more = bad_decision.to_game_action(obs_more)
    assert action_more.action_type == ActionType.ACKNOWLEDGE_PROMPT


@pytest.mark.unit
def test_multimodal_and_terminal_prompt_builders() -> None:
    """Verify Steam uses ASCII-primary + Screenshot-backup while Terminal uses 80x24 text."""
    # 1. Steam with clean reconstructed 80x25 ASCII grid (no backup needed -> 0 image tokens)
    obs_steam_ascii = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        screen_text="02: |....@......*|",
        screenshot_png_bytes=b"\x89PNG\r\n\x1a\nfake",
        game_state=GameState.PLAYING,
        inferred_metadata={
            "player_position": (2, 58),
            "walkable_directions": ["E", "W", "S"],
            "needs_screenshot_backup": False,
        },
    )
    msgs_steam_ascii = build_mistral_messages(obs_steam_ascii, "Memory summary", "Find stairs")
    assert isinstance(msgs_steam_ascii[1]["content"], str)
    assert "RECONSTRUCTED 80x25 STEAM DOSBOX ASCII GRID" in msgs_steam_ascii[1]["content"]

    # 2. Steam when backup screenshot IS needed (e.g., top banner active or no ASCII grid)
    obs_steam_backup = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        screen_text="02: |....@......*|",
        screenshot_png_bytes=b"\x89PNG\r\n\x1a\nfake",
        game_state=GameState.PLAYING,
        inferred_metadata={
            "needs_screenshot_backup": True,
            "backup_reason": "top_message_banner_active",
        },
    )
    msgs_steam_backup = build_mistral_messages(obs_steam_backup, "Memory summary", "Find stairs")
    user_content = msgs_steam_backup[1]["content"]
    assert isinstance(user_content, list)
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    obs_term = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        screen_text="Level: 1  Gold: 0",
        game_state=GameState.PLAYING,
    )
    msgs_term = build_mistral_messages(obs_term, "Memory summary", "Find stairs")
    assert isinstance(msgs_term[1]["content"], str)
    assert "CURRENT 80x24 TERMINAL SCREEN" in msgs_term[1]["content"]


@pytest.mark.unit
def test_budget_and_rate_guard_limits_and_backoff() -> None:
    """Verify max_turns, max_api_calls, max_budget_usd, and exponential backoff."""
    settings = RogueAgentSettings(
        ROGUE_MAX_TURNS=3,
        ROGUE_MAX_API_CALLS=2,
        ROGUE_MAX_BUDGET_USD=0.01,
    )
    guard = BudgetAndRateGuard(settings)
    guard.check_can_proceed(0)

    with pytest.raises(SessionLimitReachedError):
        guard.check_can_proceed(3)

    # Record a large token call exceeding $0.01 budget
    guard.record_api_call(prompt_tokens=10_000, completion_tokens=2_000, latency_ms=120.0)
    with pytest.raises(BudgetExceededError):
        guard.check_can_proceed(1)

    # Test exponential backoff on rate-limit 429 error
    attempts = 0
    delays: list[float] = []

    def flaky_call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("HTTP 429 rate limit exceeded")
        return "ok"

    res = guard.call_with_backoff(flaky_call, sleep_fn=delays.append)
    assert res == "ok"
    assert attempts == 3
    assert delays == [1.0, 2.0]


@pytest.mark.unit
def test_mistral_gameplay_agent_with_mock_sdk_client() -> None:
    """Verify MistralGameplayAgent calls client.chat.parse with model='mistral-large-4'."""
    parsed_obj = MistralActionDecision(
        observed_state=GameState.PLAYING,
        current_objective="Head east toward door",
        action=ActionType.MOVE,
        direction=Direction.EAST,
        decision_summary="Move east toward visible doorway '+'",
        notable_memory_fact="Room has a doorway on the east wall",
        confidence=0.91,
    )
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed_obj, content=""))],
        usage=SimpleNamespace(prompt_tokens=450, completion_tokens=65),
    )

    called_kwargs: dict = {}

    class FakeChat:
        def parse(self, **kwargs):
            called_kwargs.update(kwargs)
            return fake_response

    fake_client = SimpleNamespace(chat=FakeChat())
    settings = RogueAgentSettings(MISTRAL_API_KEY="test-key")
    agent = MistralGameplayAgent(settings=settings, client=fake_client)

    obs = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        screen_text="@....+",
        game_state=GameState.PLAYING,
    )
    action = agent.decide_action(obs, "No prior turns", "Explore")
    assert called_kwargs["model"] == "mistral-large-4"
    assert action.action_type == ActionType.MOVE
    assert action.direction == Direction.EAST
    assert agent.get_usage_stats()["api_calls"] == 1
    assert agent.get_usage_stats()["total_tokens"] == 515
