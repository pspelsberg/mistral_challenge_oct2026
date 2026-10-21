"""Parser for reconstructed 80x24 Terminal Rogue 5.4.4 screens (Section 7)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rogue_agent.shared.domain import GameState, VisibleStatus

# Rogue 5.4.4 status bar format on row 23:
# "Level: 1  Gold: 0      Hp: 12(12)  Str: 16(16)  Arm: 4   Exp: 1/0  Hungry"
_STATUS_REGEX = re.compile(
    r"Level:\s*(?P<level>\d+)\s+"
    r"Gold:\s*(?P<gold>\d+)\s+"
    r"Hp:\s*(?P<hp>\d+)\((?P<hp_max>\d+)\)\s+"
    r"Str:\s*(?P<str>\d+)\((?P<str_max>\d+)\)\s+"
    r"Arm:\s*(?P<arm>-?\d+)\s+"
    r"Exp:\s*(?P<exp_lvl>\d+)/(?P<exp_pts>\d+)"
    r"(?:\s+(?P<hunger>Hungry|Weak|Faint))?"
)

_ITEM_PROMPT_PATTERNS = (
    "drop what",
    "quaff what",
    "read what",
    "eat what",
    "wield what",
    "wear what",
    "put on what",
    "remove which",
    "which direction",
    "throw what",
    "zap with what",
    "what do you want identified",
    "which object do you want to identify",
    "what do you want to call it",
    "call it:",
)

_DIRECTION_DELTAS: dict[str, tuple[int, int]] = {
    "N": (-1, 0),
    "S": (1, 0),
    "E": (0, 1),
    "W": (0, -1),
    "NE": (-1, 1),
    "NW": (-1, -1),
    "SE": (1, 1),
    "SW": (1, -1),
}

_DIAGONAL_DIRS = frozenset({"NE", "NW", "SE", "SW"})
_WALKABLE_CHARS = frozenset(
    {".", "+", "#", "%", ":", "!", "?", "/", ")", "*", "]", "=", ",", "^"}
)


@dataclass(frozen=True)
class ParsedTerminalScreen:
    """Structured result of parsing a 24x80 Terminal Rogue screen."""

    screen_text: str
    game_state: GameState
    visible_status: VisibleStatus
    recent_messages: list[str] = field(default_factory=list)
    visible_metadata: dict[str, Any] = field(default_factory=dict)


def parse_terminal_screen(
    lines: list[str],
    cursor_pos: tuple[int, int] | None = None,
    process_alive: bool = True,
) -> ParsedTerminalScreen:
    """Parse 24 lines of reconstructed terminal output into state and visible status."""
    padded_lines = [line.ljust(80)[:80] for line in lines[:24]]
    while len(padded_lines) < 24:
        padded_lines.append(" " * 80)

    # Render compact numbered map lines so the LLM never miscounts rows
    rendered_lines: list[str] = []
    for idx, raw_line in enumerate(padded_lines):
        stripped = raw_line.rstrip()
        if idx in (0, 23) or stripped:
            rendered_lines.append(f"{idx:02d}: {stripped}")
    screen_text = "\n".join(rendered_lines)
    lower_screen = "\n".join(padded_lines).lower()

    top_line = padded_lines[0].strip()
    status_line = padded_lines[23].strip()
    messages: list[str] = [top_line] if top_line else []

    # Parse status bar if present
    visible_status = VisibleStatus(raw_status_line=status_line)
    match = _STATUS_REGEX.search(status_line)
    if match:
        visible_status = VisibleStatus(
            dungeon_level=int(match.group("level")),
            gold=int(match.group("gold")),
            hits_current=int(match.group("hp")),
            hits_max=int(match.group("hp_max")),
            strength_current=int(match.group("str")),
            strength_max=int(match.group("str_max")),
            armor=int(match.group("arm")),
            exp_level=int(match.group("exp_lvl")),
            exp_points=int(match.group("exp_pts")),
            hunger_state=match.group("hunger"),
            raw_status_line=status_line,
        )

    # Scan dungeon map rows (1..22) for visible entities (@, %, +, monsters A-Z, items)
    player_coords: tuple[int, int] | None = None
    stairs_coords: list[tuple[int, int]] = []
    door_coords: list[tuple[int, int]] = []
    visible_monsters: list[dict[str, Any]] = []
    visible_items: list[dict[str, Any]] = []

    for r in range(1, 23):
        row_str = padded_lines[r]
        for c, ch in enumerate(row_str):
            if ch == "@":
                player_coords = (r, c)
            elif ch == "%":
                stairs_coords.append((r, c))
            elif ch == "+":
                door_coords.append((r, c))
            elif "A" <= ch <= "Z":
                visible_monsters.append({"symbol": ch, "row": r, "col": c})
            elif ch in ":!?/)*]=,^":
                visible_items.append({"symbol": ch, "row": r, "col": c})

    adjacent_tiles: dict[str, str] = {}
    walkable_directions: list[str] = []
    if player_coords is not None:
        pr, pc = player_coords
        # Detect if player is currently in a doorway/corridor where diagonal moves are forbidden.
        # Note: a room corner has 2 perpendicular walls (e.g. N and W) and 2 floor '.' neighbors,
        # which is inside a room and MUST allow diagonal moves. A doorway has 2 opposite walls
        # (N & S, or E & W), and a corridor has '#' neighbors with no room floor '.' neighbors.
        n_ch = padded_lines[pr - 1][pc] if pr > 1 else " "
        s_ch = padded_lines[pr + 1][pc] if pr < 22 else " "
        w_ch = padded_lines[pr][pc - 1] if pc > 0 else " "
        e_ch = padded_lines[pr][pc + 1] if pc < 79 else " "
        on_doorway = (n_ch in ("|", "-") and s_ch in ("|", "-")) or (
            w_ch in ("|", "-") and e_ch in ("|", "-")
        )
        on_corridor = any(c == "#" for c in (n_ch, s_ch, w_ch, e_ch)) and not any(
            c == "." for c in (n_ch, s_ch, w_ch, e_ch)
        )
        in_doorway_or_corridor = on_doorway or on_corridor

        for dir_name, (dr, dc) in _DIRECTION_DELTAS.items():
            nr, nc = pr + dr, pc + dc
            if 1 <= nr <= 22 and 0 <= nc < 80:
                ch = padded_lines[nr][nc]
                adjacent_tiles[dir_name] = ch
                is_walkable_tile = ch in _WALKABLE_CHARS or ("A" <= ch <= "Z")
                if not is_walkable_tile:
                    continue
                # In Rogue 5.4.4, diagonal movement into/out of doorways ('+') or corridors ('#') is blocked
                if dir_name in _DIAGONAL_DIRS and (
                    in_doorway_or_corridor or ch in ("+", "#")
                ):
                    adjacent_tiles[dir_name] = f"{ch} (diagonal blocked; step cardinally first)"
                    continue
                walkable_directions.append(dir_name)
            else:
                adjacent_tiles[dir_name] = " "

    # Determine GameState
    if "total winner" in lower_screen or "congratulations" in lower_screen:
        state = GameState.VICTORY
    elif (
        "rest in peace" in lower_screen
        or "killed by" in lower_screen
        or "top ten" in lower_screen
        or (not process_alive and match is None)
    ):
        state = GameState.GAME_OVER
    elif "--more--" in lower_screen:
        state = GameState.MORE_PROMPT
    elif "--press space to continue--" in lower_screen:
        state = GameState.INVENTORY
    elif any(pat in top_line.lower() for pat in _ITEM_PROMPT_PATTERNS):
        state = GameState.ITEM_SELECTION
    elif match is not None or player_coords is not None:
        state = GameState.PLAYING
    elif not process_alive:
        state = GameState.GAME_OVER
    else:
        state = GameState.UNKNOWN

    visible_metadata: dict[str, Any] = {
        "player_position": player_coords,
        "stairs_positions": stairs_coords,
        "door_positions": door_coords,
        "visible_monsters": visible_monsters,
        "visible_items": visible_items,
        "visible_items_count": len(visible_items),
        "adjacent_tiles": adjacent_tiles,
        "walkable_directions": walkable_directions,
        "cursor_position": cursor_pos,
    }

    return ParsedTerminalScreen(
        screen_text=screen_text,
        game_state=state,
        visible_status=visible_status,
        recent_messages=messages,
        visible_metadata=visible_metadata,
    )
