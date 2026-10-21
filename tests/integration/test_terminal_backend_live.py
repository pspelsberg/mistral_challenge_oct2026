"""Level 2 Integration Test: Real Terminal Rogue 5.4.4 PTY startup, observation, and action."""

from __future__ import annotations

import pytest

from rogue_agent.features.terminal_backend.adapter import TerminalGameAdapter
from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState


@pytest.mark.integration
def test_terminal_rogue_live_pty_mvp() -> None:
    """Milestone 2 MVP: Start real Rogue 5.4.4 in PTY, observe map, execute actions, re-observe."""
    settings = RogueAgentSettings()
    assert settings.terminal_binary.is_file(), (
        f"Expected compiled binary at {settings.terminal_binary}"
    )

    adapter = TerminalGameAdapter(settings=settings)
    try:
        obs_initial = adapter.start()
        assert obs_initial.rogue_version == "rogue-5.4.4"
        assert obs_initial.game_state in (GameState.PLAYING, GameState.MORE_PROMPT)
        assert obs_initial.visible_status.dungeon_level == 1
        assert obs_initial.visible_status.hits_current == 12
        assert obs_initial.visible_status.hits_max == 12
        assert obs_initial.screen_text is not None
        assert "@" in obs_initial.screen_text

        # Execute a search action and verify state remains valid
        res_search = adapter.execute_action(
            GameAction(action_type=ActionType.SEARCH, decision_summary="Search room")
        )
        assert res_search.success is True

        # Try moving in all 4 cardinal directions with a 5-step short horizon;
        # verify movement occurs and wall-block interrupt triggers when hitting a wall
        initial_pos = obs_initial.inferred_metadata.get("player_position")
        moved = False
        interrupted_at_wall = False
        for direction in (Direction.EAST, Direction.WEST, Direction.SOUTH, Direction.NORTH):
            res_move = adapter.execute_action(
                GameAction(
                    action_type=ActionType.MOVE,
                    direction=direction,
                    steps=5,
                    decision_summary=f"Try 5-step horizon {direction.value}",
                )
            )
            assert res_move.success is True
            if res_move.interrupted_early:
                interrupted_at_wall = True
            obs_after = adapter.observe()
            new_pos = obs_after.inferred_metadata.get("player_position")
            if new_pos is not None and new_pos != initial_pos:
                moved = True

        assert moved is True, "Player '@' should have changed position after trying 4 directions"
        assert interrupted_at_wall is True, "5-step horizon should interrupt early when hitting a room wall"
    finally:
        adapter.close()
        assert adapter.get_diagnostics()["process_alive"] is False
