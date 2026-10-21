"""Level 1 Unit Tests for Terminal Rogue 5.4.4 screen parser."""

from __future__ import annotations

import pytest

from rogue_agent.features.terminal_backend.screen_parser import parse_terminal_screen
from rogue_agent.shared.domain import GameState


@pytest.mark.unit
def test_parse_playing_screen() -> None:
    """Verify status bar and map entity extraction on a standard 24x80 Rogue 5.4.4 frame."""
    lines = [""] * 24
    lines[0] = "Hello LeChonk, welcome to the Dungeons of Doom!  --More--"
    lines[5] = "   ---------"
    lines[6] = "   |...@.%B|"
    lines[7] = "   ----+----"
    lines[23] = "Level: 1  Gold: 0      Hp: 12(12)  Str: 16(16)  Arm: 4   Exp: 1/0"

    parsed = parse_terminal_screen(lines, cursor_pos=(6, 7), process_alive=True)
    assert parsed.game_state == GameState.MORE_PROMPT
    assert parsed.visible_status.dungeon_level == 1
    assert parsed.visible_status.hits_current == 12
    assert parsed.visible_status.hits_max == 12
    assert parsed.visible_status.strength_current == 16
    assert parsed.visible_status.armor == 4
    assert parsed.visible_metadata["player_position"] == (6, 7)
    assert parsed.visible_metadata["stairs_positions"] == [(6, 9)]
    assert parsed.visible_metadata["visible_monsters"] == [{"symbol": "B", "row": 6, "col": 10}]


@pytest.mark.unit
def test_parse_tombstone_game_over() -> None:
    """Verify tombstone / RIP screen triggers GAME_OVER."""
    lines = [""] * 24
    lines[10] = "          _______"
    lines[11] = "         /       \\"
    lines[12] = "        /   REST  \\"
    lines[13] = "       /  IN PEACE \\"
    lines[15] = "        killed by a"
    lines[16] = "          hobgoblin"

    parsed = parse_terminal_screen(lines, process_alive=False)
    assert parsed.game_state == GameState.GAME_OVER
