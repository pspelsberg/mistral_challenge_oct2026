"""Level 1 Unit Tests for Steam Backend window verification and visual state detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageDraw

from rogue_agent.features.steam_backend.adapter import SteamGameAdapter
from rogue_agent.features.steam_backend.capture import strip_wine_dosbox_chrome
from rogue_agent.features.steam_backend.visual_state import analyze_steam_screenshot
from rogue_agent.features.steam_backend.window_manager import (
    STEAM_ROGUE_APP_ID,
    WindowInfo,
    is_verified_rogue_window,
)
from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState


@pytest.mark.unit
def test_window_identity_guard_rejects_ide_and_terminals() -> None:
    """Ensure workspaces named 'Rogue Oktober 2026' in IDEs/terminals are never matched."""
    assert not is_verified_rogue_window(
        title="Idea.sh - Rogue Oktober 2026 - Antigravity",
        wm_class=("antigravity", "Antigravity"),
        steam_app_id=None,
    )
    assert not is_verified_rogue_window(
        title="peppi@cachyos: ~/coding/challenges/Rogue Oktober 2026",
        wm_class=("kgx", "Kgx"),
        steam_app_id=None,
    )
    assert not is_verified_rogue_window(
        title="Rogue on Steam - Mozilla Firefox",
        wm_class=("Navigator", "firefox"),
        steam_app_id=None,
    )


@pytest.mark.unit
def test_window_identity_guard_accepts_dosbox_and_steam_app_1443430() -> None:
    """Verify genuine DOSBox and Steam App ID 1443430 windows are accepted."""
    assert is_verified_rogue_window(
        title="DOSBox 0.74, Cpu speed: 3000 cycles, Frameskip 0, Program:     ROGUE",
        wm_class=("dosbox", "DOSBox"),
        steam_app_id=STEAM_ROGUE_APP_ID,
    )
    assert is_verified_rogue_window(
        title="Rogue",
        wm_class=("steam_app_1443430", "steam_app_1443430"),
        steam_app_id=STEAM_ROGUE_APP_ID,
    )


@pytest.mark.unit
def test_visual_state_analyzer_distinguishes_blank_title_and_dungeon() -> None:
    """Verify visual heuristics on synthetic Epyx 1.49 frames."""
    # 1. All-black frame -> UNKNOWN with high uncertainty
    blank = Image.new("RGB", (640, 400), (0, 0, 0))
    res_blank = analyze_steam_screenshot(blank)
    assert res_blank.inferred_state == GameState.UNKNOWN
    assert res_blank.uncertainty >= 0.8

    # 2. Dungeon frame with orange walls and bottom status line -> PLAYING
    dungeon = Image.new("RGB", (640, 400), (0, 0, 0))
    draw = ImageDraw.Draw(dungeon)
    draw.rectangle((80, 60, 260, 180), outline=(170, 85, 0), width=3)
    draw.rectangle((10, 380, 500, 395), fill=(170, 85, 0))
    res_dungeon = analyze_steam_screenshot(dungeon)
    assert res_dungeon.inferred_state == GameState.PLAYING
    assert res_dungeon.uncertainty <= 0.25

    # 3. High-color density title screen -> START_MENU
    title = Image.new("RGB", (640, 400), (180, 40, 200))
    res_title = analyze_steam_screenshot(title)
    assert res_title.inferred_state == GameState.START_MENU


@pytest.mark.unit
def test_strip_wine_dosbox_chrome_removes_titlebar_and_borders() -> None:
    """Verify 646x432 Wine/DOSBox window frame is cropped down to the exact 640x400 DOS canvas."""
    framed = Image.new("RGB", (646, 432), (58, 149, 255))
    cropped = strip_wine_dosbox_chrome(framed)
    assert cropped.size == (640, 400)


@pytest.mark.unit
def test_dosbox_ascii_grid_extraction_and_backup_flag() -> None:
    """Verify 80x25 CP437 cell grid reconstructs '@', '.', '+', '-', '|' and sets backup flag."""
    canvas = Image.new("RGB", (640, 400), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Draw orange walls in row 2..4, col 10..14
    for c in range(10, 15):
        draw.rectangle((c * 8, 2 * 16 + 6, c * 8 + 7, 2 * 16 + 9), fill=(170, 85, 0))
        draw.rectangle((c * 8, 4 * 16 + 6, c * 8 + 7, 4 * 16 + 9), fill=(170, 85, 0))
    # Vertical wall at (row=3, col=10)
    draw.rectangle((10 * 8 + 3, 3 * 16, 10 * 8 + 4, 3 * 16 + 15), fill=(170, 85, 0))
    # Door '+' at (row=3, col=14) touching all 4 edges of the 8x16 cell
    draw.rectangle((14 * 8 + 3, 3 * 16, 14 * 8 + 4, 3 * 16 + 15), fill=(170, 85, 0))
    draw.rectangle((14 * 8, 3 * 16 + 7, 14 * 8 + 7, 3 * 16 + 8), fill=(170, 85, 0))
    # Green floor dot '.' at (row=3, col=11) and (row=3, col=13)
    for c in (11, 13):
        draw.rectangle((c * 8 + 3, 3 * 16 + 7, c * 8 + 4, 3 * 16 + 8), fill=(85, 255, 85))
    # Yellow Hero smiley '☺' at (row=3, col=12)
    draw.rectangle((12 * 8 + 1, 3 * 16 + 2, 12 * 8 + 6, 3 * 16 + 11), fill=(255, 255, 85))
    # Bottom status bar activity so orange/status threshold is met
    draw.rectangle((10, 23 * 16 + 2, 400, 23 * 16 + 12), fill=(255, 255, 85))

    res = analyze_steam_screenshot(canvas)
    assert res.inferred_state == GameState.PLAYING
    assert res.ascii_grid_text is not None
    assert "|.@.+|" not in res.ascii_grid_text  # col 14 is '+' door
    assert "|.@.+" in res.ascii_grid_text
    assert res.metrics["player_position"] == (3, 12)
    assert (3, 14) in res.metrics["door_positions"]
    assert "E" in res.metrics["walkable_directions"]
    assert "W" in res.metrics["walkable_directions"]
    assert "N" not in res.metrics["walkable_directions"]
    assert res.metrics["needs_screenshot_backup"] is False

    # Now add a message in Row 0 -> backup screenshot must be triggered
    draw.rectangle((8, 4, 120, 12), fill=(170, 170, 170))
    res_with_msg = analyze_steam_screenshot(canvas)
    assert res_with_msg.metrics["needs_screenshot_backup"] is True
    assert res_with_msg.metrics["backup_reason"] == "top_message_banner_active"


@pytest.mark.unit
def test_steam_adapter_pauses_and_captures_for_menu_actions() -> None:
    """Verify that selection menu actions (e.g. throw_item) inject prompt keys, sleep 1.5s, capture intermediate frame, and inject item key."""
    adapter = SteamGameAdapter()
    fake_win = WindowInfo(
        window_id=12345,
        title="DOSBox",
        wm_class=("dosbox", "DOSBox"),
        steam_app_id=STEAM_ROGUE_APP_ID,
        x=0,
        y=0,
        width=640,
        height=400,
        is_viewable=True,
        has_focus=True,
    )
    adapter.window_manager = MagicMock()
    adapter.window_manager.find_game_window.return_value = fake_win
    adapter.injector = MagicMock()

    mock_obs = MagicMock()
    mock_obs.game_state = GameState.PLAYING
    mock_obs.inferred_metadata = {"frame_hash": "abc"}
    adapter.observe = MagicMock(return_value=mock_obs)

    action = GameAction(
        action_type=ActionType.THROW_ITEM,
        direction=Direction.NORTH,
        item_key="e",
        decision_summary="Throw arrow north",
    )

    fake_menu_png = b"FAKE_PNG_MENU"
    with (
        patch(
            "rogue_agent.features.steam_backend.adapter.capture_window_client_area",
            return_value=(None, fake_menu_png),
        ),
        patch("time.sleep") as mock_sleep,
    ):
        res = adapter.execute_action(action)

        # Should inject prompt keys first, then selection key
        assert adapter.injector.send_key_sequence.call_count == 2
        first_call = adapter.injector.send_key_sequence.call_args_list[0]
        second_call = adapter.injector.send_key_sequence.call_args_list[1]
        assert first_call[0][1] == ["t", "Up"]
        assert second_call[0][1] == ["e"]

        # Should sleep 1.5s for menu visibility
        mock_sleep.assert_any_call(1.5)

        # Intermediate menu screenshot should be preserved
        assert res.intermediate_screenshot_bytes == fake_menu_png


@pytest.mark.unit
def test_visual_state_detects_more_prompt_on_row0() -> None:
    """Verify that inverse video banner ' More ' on row 0 triggers GameState.MORE_PROMPT."""
    canvas = Image.new("RGB", (640, 400), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Draw regular text on row 0: 'You hit the monster' (normal nonblack)
    for c in range(10):
        draw.rectangle((c * 8 + 1, 3, c * 8 + 6, 12), fill=(170, 170, 170))
    # Draw inverse video ' More ' banner at cols 30..35 (nonblack >= 85)
    for c in range(30, 36):
        draw.rectangle((c * 8, 0, c * 8 + 7, 15), fill=(170, 170, 170))
    # Bottom status bar activity
    draw.rectangle((10, 23 * 16 + 2, 400, 23 * 16 + 12), fill=(255, 255, 85))

    analysis = analyze_steam_screenshot(canvas)
    assert analysis.inferred_state == GameState.MORE_PROMPT
    assert analysis.metrics.get("has_more_prompt") is True
