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


@pytest.mark.unit
def test_bounded_memory_adjacent_monster_immediate_attack_doctrine() -> None:
    """Verify adjacent fast fliers (B/K) trigger immediate melee attack and never stale staircase sprints."""
    mem = BoundedAgentMemory()
    # Emulate previously known staircase on level 1
    mem.known_stairs_by_level[1] = [(10, 10)]

    grid_lines = [
        "",
        "   ---------",
        "   |.......|",
        "   |.@B....|",
        "   |.......|",
        "   ---------",
    ]
    screen_text = "\n".join(grid_lines)
    obs = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.PLAYING,
        screen_text=screen_text,
        visible_status=VisibleStatus(dungeon_level=1, hits_current=12, hits_max=12),
        inferred_metadata={
            "player_position": (3, 4),
            "walkable_directions": ["N", "S", "E", "W"],
            "adjacent_tiles": {"N": ".", "S": ".", "E": "B", "W": "."},
            "door_positions": [],
            "stairs_positions": [],  # No stairs visible on current screen
            "visible_items": [],
            "visible_monsters": [{"symbol": "B", "row": 3, "col": 5}],
        },
    )
    summary = mem.build_prompt_summary(obs)
    assert "TACTICAL COMBAT ALERT (IMMEDIATE MELEE ATTACK)" in summary
    assert "Never flee or circle" in summary
    assert "STAIRCASE SPRINT ALERT (HIGHEST PRIORITY)" not in summary
    assert "Step toward the stairs instead of fighting" not in summary


@pytest.mark.unit
def test_mark_segment_visited_traces_curved_corridor() -> None:
    """Multi-bend fast_move corridor paths must mark all intermediate corridor tiles as visited."""
    grid = [
        "00: --------------------------------------------------------------------------------",
        "01: |...................|                                                           ",
        "02: |...................+#####                                                      ",
        "03: |...................|    #                                                      ",
        "04: |...................|    #                                                      ",
        "05: ---------------------    ####+-----------------                                 ",
        "06:                              |................|                                 ",
    ]
    screen_text = "\n".join(grid)
    visited: set[tuple[int, int]] = set()
    p1 = (2, 20)  # Door tile
    p2 = (5, 29)  # Target door in second room
    BoundedAgentMemory._mark_segment_visited(visited, p1, p2, screen_text)

    # Every corridor tile along the bend must be visited
    assert (2, 21) in visited
    assert (2, 25) in visited
    assert (3, 25) in visited
    assert (4, 25) in visited
    assert (5, 25) in visited
    assert (5, 28) in visited
    assert (5, 29) in visited


@pytest.mark.unit
def test_anti_backtracking_prioritizes_unvisited_room_door_over_corridors() -> None:
    """When the hero is inside a room with an unexplored door, topological compass must target the room door, not backtrack into corridors."""
    grid = [
        "00: --------------------------------------------------------------------------------",
        "01:                         |.................|                                     ",
        "02:                         |.................|                                     ",
        "03: #####+------------------+........@........+#####                                ",
        "04:                         |.................|                                     ",
        "05:                         |........+........|                                     ",
        "06:                         ---------+---------                                     ",
    ]
    screen_text = "\n".join(grid)
    visited_level1 = {
        (3, 24),
        (3, 25),
        (3, 26),
        (3, 27),
        (3, 28),
        (3, 29),
        (3, 30),
        (3, 31),
        (3, 32),
        (3, 33),
        (3, 37),
    }

    mem = BoundedAgentMemory()
    mem.visited_by_level[1] = set(visited_level1)
    obs = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.PLAYING,
        screen_text=screen_text,
        visible_status=VisibleStatus(dungeon_level=1, hits_current=12, hits_max=12),
        inferred_metadata={
            "player_position": (3, 37),  # Hero at '@'
            "walkable_directions": ["N", "S", "E", "W"],
            "adjacent_tiles": {"N": ".", "S": ".", "E": ".", "W": "."},
            "door_positions": [(3, 28), (5, 33), (3, 46)],
            "stairs_positions": [],
            "visible_items": [],
            "visible_monsters": [],
        },
    )

    summary = mem.build_prompt_summary(obs)
    # Door (5, 33) is an unexplored room door in the current room
    assert "UNEXPLORED DOOR IN THIS ROOM (TOP PRIORITY)" in summary
    assert "(5, 33)" in summary
    # Compass should direct hero toward south door (5, 33), NOT backtracking into west door/corridor
    assert "TOPOLOGICAL COMPASS HINT: Closest unexplored room door along walkable tiles is (5, 33)" in summary


@pytest.mark.unit
def test_macro_backtracking_alert_emitted_on_revisiting_past_room() -> None:
    """Detect returning to coordinates visited 3-5 turns ago and issue a macro-backtracking warning."""
    mem = BoundedAgentMemory()
    obs_dummy = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.PLAYING,
        visible_status=VisibleStatus(dungeon_level=1),
    )
    act_dummy = GameAction(action_type=ActionType.MOVE, direction=Direction.EAST)
    res_dummy = ActionExecutionResult(
        success=True,
        keys_sent=["l"],
        state_before=GameState.PLAYING,
        state_after=GameState.PLAYING,
    )

    # Simulate path with cycle > 2 steps: (3, 20) -> (3, 25) -> (3, 30) -> (3, 35) -> (3, 40) -> (3, 30)
    positions = [(3, 20), (3, 25), (3, 30), (3, 35), (3, 40), (3, 30)]
    for idx in range(1, len(positions)):
        obs_b = obs_dummy.model_copy(
            update={"inferred_metadata": {"player_position": positions[idx - 1]}}
        )
        obs_a = obs_dummy.model_copy(
            update={"inferred_metadata": {"player_position": positions[idx]}}
        )
        mem.record_turn(idx, obs_b, act_dummy, res_dummy, obs_a)

    failed = list(mem.recent_failed_actions)
    assert any("MACRO-BACKTRACKING DETECTED!" in f for f in failed)


@pytest.mark.unit
def test_compass_prioritizes_never_visited_door_and_items_over_entrance_door() -> None:
    """Verify that when inside a room with entrance door (visited) and exit door (unvisited),

    topological compass targets the unvisited exit door / items, never the entrance door.
    """
    grid = [
        "17:                  #                                                      ",
        "18:  |---------------+-------|                                              ",
        "19:  |...........*..@.....?..+                                              ",
        "20:  |.......................|                                              ",
        "21:  |-----------------------|                                              ",
    ]
    screen_text = "\n".join(grid)
    mem = BoundedAgentMemory()
    # North door (18, 17) has been stepped on:
    mem.visited_by_level[1] = {(18, 17), (19, 17)}
    obs = GameObservation(
        backend=BackendId.STEAM,
        rogue_version="epyx-1.49",
        game_state=GameState.PLAYING,
        screen_text=screen_text,
        visible_status=VisibleStatus(dungeon_level=1),
        inferred_metadata={
            "player_position": (19, 17),
            "walkable_directions": ["N", "S", "E", "W", "SE", "SW"],
            "adjacent_tiles": {"N": "+", "S": ".", "E": ".", "W": "."},
            "door_positions": [(18, 17), (19, 25)],
            "stairs_positions": [],
            "visible_items": [
                {"symbol": "*", "type": "gold", "row": 19, "col": 13},
                {"symbol": "?", "type": "scroll", "row": 19, "col": 22},
            ],
            "visible_monsters": [],
        },
    )

    summary = mem.build_prompt_summary(obs)
    # The compass must target unvisited items in the room first
    assert "TOPOLOGICAL COMPASS HINT: Closest uncollected item in this room is '*' (gold) at (19, 13)" in summary
    # Unvisited exit door (19, 25) must be listed BEFORE already-visited entrance door (18, 17)
    assert summary.index("(19, 25)") < summary.index("(18, 17)")
    # Entrance door (18, 17) to the North must be marked as ALREADY VISITED neighbor
    assert "ALREADY VISITED Walkable Neighbors from (19, 17)" in summary
    assert "N->(18, 17)('+')" in summary




