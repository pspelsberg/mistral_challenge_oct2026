"""Level 1 Unit Tests for Bounded Agent Memory and Version-Segregated Telemetry."""

from __future__ import annotations

from pathlib import Path

import pytest

from rogue_agent.features.memory import BoundedAgentMemory, CrossSessionPlaybookManager
from rogue_agent.features.telemetry_eval import (
    SessionTelemetryCollector,
    aggregate_runs_by_version,
    export_session_gif,
)
from rogue_agent.shared.domain import (
    ActionExecutionResult,
    ActionType,
    BackendId,
    Direction,
    GameAction,
    GameObservation,
    GameState,
    VisibleStatus,
)


@pytest.mark.unit
def test_bounded_memory_separates_facts_and_hypotheses_and_detects_blocked_moves() -> None:
    """Verify BoundedAgentMemory tracks blocked moves, stairs, and model hypotheses separately."""
    mem = BoundedAgentMemory(max_recent_turns=4)
    obs1 = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.PLAYING,
        visible_status=VisibleStatus(dungeon_level=1, hits_current=12, hits_max=12),
        inferred_metadata={
            "player_position": (5, 5),
            "stairs_positions": [(5, 8)],
            "visible_monsters": [{"symbol": "K", "row": 5, "col": 7}],
        },
    )
    # Same player_position after MOVE -> blocked!
    obs2 = obs1.model_copy()
    action = GameAction(
        action_type=ActionType.MOVE,
        direction=Direction.NORTH,
        decision_summary="Try north wall",
        objective="Reach stairs at (5,8)",
        notable_memory_fact="Kestrel at (5,7) might wake up",
    )
    result = ActionExecutionResult(
        success=True,
        keys_sent=["k"],
        state_before=GameState.PLAYING,
        state_after=GameState.PLAYING,
    )

    mem.record_turn(1, obs1, action, result, obs2)
    summary = mem.build_prompt_summary()
    assert "Reach stairs at (5,8)" in summary
    assert "Staircase '%' observed on Level 1" in summary
    assert "Kestrel at (5,7) might wake up" in summary
    assert "did not change position" in summary


@pytest.mark.unit
def test_telemetry_never_mixes_epyx_149_and_rogue_544_scores(tmp_path: Path) -> None:
    """Competition rule (Section 15): never combine scores across different Rogue versions."""
    obs_term = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.PLAYING,
        screen_text="@...",
        visible_status=VisibleStatus(dungeon_level=2, gold=35),
    )
    obs_steam = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.PLAYING,
        screenshot_png_bytes=b"\x89PNG\r\n\x1a\nfake",
        visible_status=VisibleStatus(dungeon_level=1, gold=10),
    )
    act = GameAction(action_type=ActionType.SEARCH, decision_summary="Search")
    res = ActionExecutionResult(
        success=True,
        keys_sent=["s"],
        state_before=GameState.PLAYING,
        state_after=GameState.PLAYING,
    )

    c1 = SessionTelemetryCollector(base_runs_dir=tmp_path)
    c1.start_session("terminal", "rogue-5.4.4", "mistral-large-4", dry_run=True)
    c1.log_turn(1, obs_term, act, res, {"api_calls": 1, "total_tokens": 100}, 50.0)
    c1.finish_session(obs_term, "completed", {"api_calls": 1, "total_tokens": 100})

    c2 = SessionTelemetryCollector(base_runs_dir=tmp_path)
    c2.start_session("steam", "epyx-1.49", "mistral-large-4", dry_run=True)
    c2.log_turn(1, obs_steam, act, res, {"api_calls": 1, "total_tokens": 120}, 60.0)
    c2.finish_session(obs_steam, "completed", {"api_calls": 1, "total_tokens": 120})

    agg = aggregate_runs_by_version(tmp_path)
    assert "terminal:rogue-5.4.4" in agg
    assert "steam:epyx-1.49" in agg
    assert agg["terminal:rogue-5.4.4"]["max_depth_reached"] == 2
    assert agg["steam:epyx-1.49"]["max_depth_reached"] == 1
    assert agg["terminal:rogue-5.4.4"]["max_rooms_discovered"] >= 1
    assert "total_monsters_defeated" in agg["terminal:rogue-5.4.4"]

    # Verify <2 min competition GIF exporter works on recorded ASCII frames
    assert c1.session_dir is not None
    gif_path = export_session_gif(c1.session_dir)
    assert gif_path.is_file()
    assert gif_path.stat().st_size > 100


@pytest.mark.unit
def test_bounded_memory_detects_cleared_room_and_unexplored_corridor_branches() -> None:
    """Verify cleared rooms auto-mark floor tiles visited while preserving unexplored corridor doors."""
    mem = BoundedAgentMemory()
    grid_lines = [
        "",
        "   ---------",
        "   |.......|",
        "  #+@......|",
        "   |.......|",
        "   ---------",
    ]
    screen_text = "\n".join(grid_lines)
    obs = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.PLAYING,
        screen_text=screen_text,
        visible_status=VisibleStatus(dungeon_level=1, hits_current=12, hits_max=12),
        inferred_metadata={
            "player_position": (3, 4),
            "door_positions": [(3, 3)],
            "stairs_positions": [],
            "visible_items": [],
            "visible_monsters": [],
            "adjacent_walkable_directions": ["W:(3,3)='+'", "E:(3,5)='.'"],
        },
    )
    # Even if door (3, 3) was stepped on once, corridor (3, 2) is unvisited:
    mem.visited_by_level[1] = {(3, 3), (3, 4)}
    summary = mem.build_prompt_summary(obs)
    assert "(3, 3)" in summary
    assert "UNVISITED Doors '+' on Screen" in summary
    assert "UNEXPLORED Corridor Branches '#' on Screen" in summary
    assert "(3, 2)" in summary


@pytest.mark.unit
def test_cross_session_playbook_learns_bestiary_and_writes_markdown(tmp_path: Path) -> None:
    """Verify CrossSessionPlaybookManager extracts monster stats, lessons, JSON, and Markdown."""
    c = SessionTelemetryCollector(base_runs_dir=tmp_path)
    c.start_session("terminal", "rogue-5.4.4", "mistral-large-4", dry_run=False)
    obs1 = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.PLAYING,
        screen_text="01: @HE",
        visible_status=VisibleStatus(dungeon_level=1, hits_current=12, hits_max=12),
        recent_messages=["You now have a red potion (f)"],
    )
    obs2 = GameObservation(
        backend=BackendId.TERMINAL,
        rogue_version="rogue-5.4.4",
        game_state=GameState.GAME_OVER,
        screen_text="01: @HE",
        visible_status=VisibleStatus(dungeon_level=1, hits_current=7, hits_max=12),
        recent_messages=[
            "The hobgoblin scored an excellent hit on you",
            "The emu has injured you",
            "You have defeated the emu",
        ],
    )
    act = GameAction(action_type=ActionType.MOVE, direction=Direction.EAST, decision_summary="Fight")
    res = ActionExecutionResult(
        success=True,
        keys_sent=["l"],
        state_before=GameState.PLAYING,
        state_after=GameState.GAME_OVER,
    )
    c.log_turn(1, obs1, act, res, {"api_calls": 1, "total_tokens": 100}, 40.0)
    c.log_turn(2, obs2, act, res, {"api_calls": 2, "total_tokens": 200}, 40.0)
    c.finish_session(obs2, "terminal_state:GAME_OVER", {"api_calls": 2, "total_tokens": 200})

    mgr = CrossSessionPlaybookManager(runs_dir=tmp_path)
    data = mgr.load_or_bootstrap("rogue-5.4.4")
    assert data.sessions_analyzed == 1
    assert "H:hobgoblin" in data.bestiary
    assert "E:emu" in data.bestiary
    assert data.bestiary["E:emu"].kills_by_player == 1
    assert any("CHOKEPOINT RULE" in r for r in data.tactical_lessons)
    assert any("EMERGENCY CONSUMABLE RULE" in r for r in data.tactical_lessons)
    assert mgr.markdown_path.is_file()
    snippet = mgr.build_prompt_snippet("rogue-5.4.4", ["H"])
    assert "CROSS-SESSION PLAYBOOK" in snippet
    assert "hobgoblin" in snippet


