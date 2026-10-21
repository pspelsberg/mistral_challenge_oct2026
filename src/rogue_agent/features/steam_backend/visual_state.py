"""Visual state heuristics and 80x25 CP437-to-ASCII grid extraction for Epyx Rogue v1.49 (Section 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image

from rogue_agent.shared.domain import GameState

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

_WALKABLE_ASCII_CHARS = frozenset({".", "+", "#", "%", "*", ":", "?", "M"})


@dataclass(frozen=True)
class VisualScreenAnalysis:
    """Result of lightweight visual inspection and 80x25 grid extraction of a Steam Rogue screenshot."""

    inferred_state: GameState
    uncertainty: float
    metrics: dict[str, Any]
    ascii_grid_text: str | None = None


def extract_dosbox_canvas(image: Image.Image) -> Image.Image:
    """Normalize a captured Steam/DOSBox frame to the exact 640x400 (80x25 cells of 8x16px) canvas."""
    rgb = image.convert("RGB")
    w, h = rgb.size
    if (w, h) == (640, 400):
        return rgb
    if 642 <= w <= 660 and 420 <= h <= 450:
        pad_x = (w - 640) // 2
        pad_bottom = 3
        pad_top = h - 400 - pad_bottom
        if pad_top >= 20:
            return rgb.crop((pad_x, pad_top, pad_x + 640, pad_top + 400))
    return rgb.resize((640, 400), Image.Resampling.NEAREST)


def extract_dosbox_ascii_grid(canvas: Image.Image) -> tuple[str | None, dict[str, Any]]:
    """Reconstruct the 80x25 ASCII dungeon map and entity coordinates from a 640x400 DOSBox frame."""
    if canvas.size != (640, 400):
        canvas = extract_dosbox_canvas(canvas)

    get_pixels = getattr(canvas, "get_flattened_data", canvas.getdata)
    flat_pixels = list(get_pixels())

    grid_rows: list[list[str]] = [[" " for _ in range(80)] for _ in range(25)]
    player_position: tuple[int, int] | None = None
    stairs_positions: list[tuple[int, int]] = []
    door_positions: list[tuple[int, int]] = []
    visible_monsters: list[dict[str, Any]] = []
    visible_entities: list[dict[str, Any]] = []
    row0_active_cells = 0
    dungeon_nonempty_cells = 0

    for r in range(25):
        y_base = r * 16
        for c in range(80):
            x_base = c * 8
            nonblack_count = 0
            yellow_count = 0
            green_count = 0
            brown_count = 0
            gray_count = 0
            red_count = 0
            blue_cyan_count = 0
            touches_top_or_bottom_2 = False

            for dy in range(16):
                row_offset = (y_base + dy) * 640 + x_base
                for dx in range(8):
                    red, green, blue = flat_pixels[row_offset + dx]
                    if red <= 25 and green <= 25 and blue <= 25:
                        continue
                    nonblack_count += 1
                    if dy <= 1 or dy >= 14:
                        touches_top_or_bottom_2 = True
                    if red > 200 and green > 200 and blue < 120:
                        yellow_count += 1
                    elif red < 120 and green > 180 and blue < 120:
                        green_count += 1
                    elif 120 < red < 205 and 45 < green < 125 and blue < 55:
                        brown_count += 1
                    elif 130 < red < 255 and 130 < green < 255 and 130 < blue < 255:
                        gray_count += 1
                    elif red > 130 and green < 60 and blue < 60:
                        red_count += 1
                    elif blue > 130 and red < 120:
                        blue_cyan_count += 1

            if nonblack_count == 0:
                continue

            if r == 0:
                row0_active_cells += 1
                continue
            if r >= 23:
                continue

            dungeon_nonempty_cells += 1

            # 1. Hero ('☺', CP437 char 1) vs Gold ('☼', CP437 char 15) in yellow
            if yellow_count >= 18:
                y2_offset = (y_base + 2) * 640 + x_base
                smiley_forehead = sum(
                    1 for dx in range(1, 7) if flat_pixels[y2_offset + dx][0] > 200
                )
                if smiley_forehead >= 4:
                    grid_rows[r][c] = "@"
                    player_position = (r, c)
                else:
                    grid_rows[r][c] = "*"
                    visible_entities.append(
                        {"symbol": "*", "type": "gold", "row": r, "col": c}
                    )
                continue

            # 2. Room floor dot ('∙') vs Staircase ('≡') in bright green
            if green_count > 0 and nonblack_count <= 6:
                grid_rows[r][c] = "."
                continue
            if green_count >= 10:
                grid_rows[r][c] = "%"
                stairs_positions.append((r, c))
                continue

            # 3. Lit corridor block ('▒') in light gray touching full cell height
            if gray_count >= 20 and touches_top_or_bottom_2:
                grid_rows[r][c] = "#"
                continue

            # 4. Orange/brown double-line walls ('═', '║', '╔', '╗', '╚', '╝') and doors ('╬')
            if brown_count >= 10:
                top_b = sum(
                    1
                    for dx in range(8)
                    if flat_pixels[y_base * 640 + x_base + dx][0] > 100
                )
                bot_b = sum(
                    1
                    for dx in range(8)
                    if flat_pixels[(y_base + 15) * 640 + x_base + dx][0] > 100
                )
                left_b = sum(
                    1
                    for dy in range(16)
                    if flat_pixels[(y_base + dy) * 640 + x_base][0] > 100
                )
                right_b = sum(
                    1
                    for dy in range(16)
                    if flat_pixels[(y_base + dy) * 640 + x_base + 7][0] > 100
                )
                if top_b > 0 and bot_b > 0 and left_b > 0 and right_b > 0:
                    grid_rows[r][c] = "+"
                    door_positions.append((r, c))
                elif top_b > 0 and bot_b > 0:
                    grid_rows[r][c] = "|"
                else:
                    grid_rows[r][c] = "-"
                continue

            # 5. Items & Monsters inside the dungeon
            if red_count >= 8:
                grid_rows[r][c] = ":"
                visible_entities.append(
                    {"symbol": ":", "type": "food_or_trap", "row": r, "col": c}
                )
            elif blue_cyan_count >= 8:
                grid_rows[r][c] = "?"
                visible_entities.append(
                    {"symbol": "?", "type": "item", "row": r, "col": c}
                )
            elif gray_count >= 8 and not touches_top_or_bottom_2:
                grid_rows[r][c] = "M"
                visible_monsters.append({"symbol": "M", "row": r, "col": c})
            else:
                grid_rows[r][c] = "*"
                visible_entities.append(
                    {"symbol": "*", "type": "entity", "row": r, "col": c}
                )

    adjacent_tiles: dict[str, str] = {}
    walkable_directions: list[str] = []
    if player_position is not None:
        pr, pc = player_position
        cardinal_walls = sum(
            1
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            if 1 <= pr + dr <= 22
            and 0 <= pc + dc < 80
            and grid_rows[pr + dr][pc + dc] in ("|", "-")
        )
        in_doorway = cardinal_walls >= 2
        for dir_name, (dr, dc) in _DIRECTION_DELTAS.items():
            nr, nc = pr + dr, pc + dc
            if 1 <= nr <= 22 and 0 <= nc < 80:
                ch = grid_rows[nr][nc]
                adjacent_tiles[dir_name] = ch
                if ch not in _WALKABLE_ASCII_CHARS:
                    continue
                if dir_name in ("NE", "NW", "SE", "SW") and (
                    in_doorway or ch in ("+", "#")
                ):
                    continue
                walkable_directions.append(dir_name)
            else:
                adjacent_tiles[dir_name] = " "

    rendered_lines: list[str] = []
    for r in range(1, 23):
        line_str = "".join(grid_rows[r]).rstrip()
        if line_str.strip():
            rendered_lines.append(f"{r:02d}: {line_str}")

    ascii_grid_text = "\n".join(rendered_lines) if rendered_lines else None
    grid_meta = {
        "player_position": player_position,
        "stairs_positions": stairs_positions,
        "door_positions": door_positions,
        "visible_monsters": visible_monsters,
        "visible_entities": visible_entities,
        "adjacent_tiles": adjacent_tiles,
        "walkable_directions": walkable_directions,
        "row0_active_cells": row0_active_cells,
        "dungeon_nonempty_cells": dungeon_nonempty_cells,
    }
    return ascii_grid_text, grid_meta


def analyze_steam_screenshot(image: Image.Image) -> VisualScreenAnalysis:
    """Inspect CGA/EGA palette distribution and reconstruct 80x25 ASCII dungeon grid."""
    canvas = extract_dosbox_canvas(image)
    small = canvas.resize((160, 100), Image.Resampling.NEAREST)
    get_pixels = getattr(small, "get_flattened_data", small.getdata)
    pixels = list(get_pixels())
    total = len(pixels)

    black_count = 0
    orange_brown_count = 0
    magenta_count = 0
    yellow_curtain_count = 0
    bright_color_count = 0
    top_bar_nonblack = 0
    bottom_bar_nonblack = 0

    for idx, (r, g, b) in enumerate(pixels):
        row = idx // 160
        if r < 20 and g < 20 and b < 20:
            black_count += 1
        elif r > 120 and 40 <= g <= 130 and b < 45:
            # Classic Epyx 1.49 orange/brown double-line room walls & status text
            orange_brown_count += 1
        elif r > 150 and g < 110 and b > 150:
            # CGA magenta used on Epyx Title Screen (~5.9%) and 'Rogue's Name?' Credits (~0.9%)
            magenta_count += 1
            bright_color_count += 1
        elif r > 120 and g > 120 and b < 60:
            # Yellow-green curtain transition / status text
            yellow_curtain_count += 1
            bright_color_count += 1
        elif max(r, g, b) > 140:
            bright_color_count += 1

        if row < 4 and (r > 40 or g > 40 or b > 40):
            top_bar_nonblack += 1
        if row >= 92 and (r > 35 or g > 35 or b > 35):
            bottom_bar_nonblack += 1

    black_ratio = black_count / total
    orange_ratio = orange_brown_count / total
    magenta_ratio = magenta_count / total
    curtain_ratio = yellow_curtain_count / total
    bright_ratio = bright_color_count / total
    top_bar_ratio = top_bar_nonblack / (4 * 160)
    bottom_bar_ratio = bottom_bar_nonblack / (8 * 160)

    metrics: dict[str, Any] = {
        "black_ratio": round(black_ratio, 4),
        "orange_wall_ratio": round(orange_ratio, 4),
        "magenta_ratio": round(magenta_ratio, 4),
        "curtain_ratio": round(curtain_ratio, 4),
        "bright_color_ratio": round(bright_ratio, 4),
        "top_message_bar_activity": round(top_bar_ratio, 4),
        "bottom_bar_activity": round(bottom_bar_ratio, 4),
        "dimensions": image.size,
    }

    if black_ratio > 0.992:
        metrics["needs_screenshot_backup"] = True
        metrics["backup_reason"] = "blank_or_unknown_screen"
        return VisualScreenAnalysis(
            inferred_state=GameState.UNKNOWN,
            uncertainty=0.9,
            metrics=metrics,
        )

    # Epyx title graphic (ROGUE.PIC) has large bright CGA magenta logo (>2.5%)
    if magenta_ratio > 0.025 or (bright_ratio > 0.22 and black_ratio < 0.72):
        metrics["needs_screenshot_backup"] = True
        metrics["backup_reason"] = "start_menu_screen"
        return VisualScreenAnalysis(
            inferred_state=GameState.START_MENU,
            uncertainty=0.1,
            metrics=metrics,
        )

    # Epyx 'Rogue's Name?' screen has magenta credits text (0.2%..2.5%) or yellow curtain (>4%)
    if 0.002 <= magenta_ratio <= 0.025 or curtain_ratio > 0.04:
        metrics["needs_screenshot_backup"] = True
        metrics["backup_reason"] = "character_name_entry_screen"
        return VisualScreenAnalysis(
            inferred_state=GameState.CHARACTER_NAME_ENTRY,
            uncertainty=0.15,
            metrics=metrics,
        )

    ascii_grid_text, grid_meta = extract_dosbox_ascii_grid(canvas)
    metrics.update(grid_meta)

    # Determine whether the screenshot backup is needed alongside the ASCII grid
    backup_reason: str | None = None
    if grid_meta["player_position"] is None:
        backup_reason = "player_symbol_not_found_on_grid"
    elif grid_meta["row0_active_cells"] > 0 or top_bar_ratio > 0.015:
        backup_reason = "top_message_banner_active"
    elif orange_ratio <= 0.003 and bottom_bar_ratio <= 0.04:
        backup_reason = "non_standard_dungeon_overlay"

    metrics["needs_screenshot_backup"] = backup_reason is not None
    metrics["backup_reason"] = backup_reason

    # Active dungeon view has orange double-line room walls or active bottom status bar
    if orange_ratio > 0.003 or bottom_bar_ratio > 0.04:
        return VisualScreenAnalysis(
            inferred_state=GameState.PLAYING,
            uncertainty=0.10 if backup_reason is None else 0.18,
            metrics=metrics,
            ascii_grid_text=ascii_grid_text,
        )

    return VisualScreenAnalysis(
        inferred_state=GameState.PLAYING,
        uncertainty=0.35,
        metrics=metrics,
        ascii_grid_text=ascii_grid_text,
    )
