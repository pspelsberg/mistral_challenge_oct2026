"""Visual state heuristics and 80x25 CP437-to-ASCII grid extraction for Epyx Rogue v1.49 (Section 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PIL import Image

from rogue_agent.features.steam_backend.capture import strip_wine_dosbox_chrome
from rogue_agent.shared.domain import DIRECTION_DELTAS_BY_CODE, GameState

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
    rgb = strip_wine_dosbox_chrome(image.convert("RGB"))
    if rgb.size == (640, 400):
        return rgb
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
    wall_candidates: set[tuple[int, int]] = set()
    top_b_cells: set[tuple[int, int]] = set()
    bot_b_cells: set[tuple[int, int]] = set()
    left_b_cells: set[tuple[int, int]] = set()
    right_b_cells: set[tuple[int, int]] = set()
    row0_active_cells = 0
    row0_inverse_cells: set[int] = set()
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
            touches_top = False
            touches_bottom = False
            yellow_rows_count = 0
            top3_yellow_count = 0

            for dy in range(16):
                row_offset = (y_base + dy) * 640 + x_base
                has_yellow_on_row = False
                for dx in range(8):
                    red, green, blue = flat_pixels[row_offset + dx]
                    if red <= 25 and green <= 25 and blue <= 25:
                        continue
                    nonblack_count += 1
                    if dy <= 1:
                        touches_top = True
                    if dy >= 14:
                        touches_bottom = True
                    if (red > 120 and green > 120 and blue < 110) or (
                        red > 50 and green > 50 and blue < red * 0.5 and abs(red - green) < 20
                    ):
                        yellow_count += 1
                        has_yellow_on_row = True
                        if dy <= 2:
                            top3_yellow_count += 1
                    elif green > 80 and green > red * 1.25 and green > blue * 1.25:
                        green_count += 1
                    elif 35 <= red <= 210 and 15 <= green <= 130 and blue < 65 and red > green:
                        brown_count += 1
                    elif abs(red - green) <= 15 and abs(green - blue) <= 15 and red >= 50:
                        gray_count += 1
                    elif red > 130 and green < 60 and blue < 60:
                        red_count += 1
                    elif blue > 130 and red < 120:
                        blue_cyan_count += 1
                if has_yellow_on_row:
                    yellow_rows_count += 1

            if nonblack_count == 0:
                continue

            if r == 0:
                row0_active_cells += 1
                if nonblack_count >= 85:
                    row0_inverse_cells.add(c)
                continue
            if r >= 23:
                continue

            dungeon_nonempty_cells += 1

            # 1. Hero ('☺', CP437 char 1) vs Gold ('☼', CP437 char 15) in yellow:
            # Hero glyph has an upper cap/head touching rows 0-2 (rows 0-2 >= 3 yellow px).
            # Gold is a vertically centered 8-pointed star starting only at row 3 (rows 0-2 have 0 px).
            is_hero_glyph = (
                yellow_count >= 15
                and yellow_rows_count >= 7
                and top3_yellow_count >= 3
            )
            if is_hero_glyph:
                if player_position is not None:
                    pr, pc = player_position
                    grid_rows[pr][pc] = "."
                grid_rows[r][c] = "@"
                player_position = (r, c)
                continue
            if yellow_count >= 10:
                grid_rows[r][c] = "*"
                visible_entities.append(
                    {"symbol": "*", "type": "gold", "row": r, "col": c}
                )
                continue

            # 2. Lit corridor block ('▒') in light gray touching full cell height
            if gray_count >= 40 and touches_top and touches_bottom:
                grid_rows[r][c] = "#"
                continue

            # 3. Room floor dot ('∙') vs Staircase ('≡') in bright green
            if green_count > 0 and nonblack_count <= 8:
                grid_rows[r][c] = "."
                continue
            if green_count >= 10:
                grid_rows[r][c] = "%"
                stairs_positions.append((r, c))
                continue

            # 4. Orange/brown double-line walls & doors candidate
            if brown_count >= 8:
                wall_candidates.add((r, c))
                top_b = sum(
                    1 for dx in range(8) if flat_pixels[y_base * 640 + x_base + dx][0] > 35
                )
                bot_b = sum(
                    1 for dx in range(8) if flat_pixels[(y_base + 15) * 640 + x_base + dx][0] > 35
                )
                left_b = sum(
                    1 for dy in range(16) if flat_pixels[(y_base + dy) * 640 + x_base][0] > 35
                )
                right_b = sum(
                    1 for dy in range(16) if flat_pixels[(y_base + dy) * 640 + x_base + 7][0] > 35
                )
                if top_b >= 2:
                    top_b_cells.add((r, c))
                if bot_b >= 2:
                    bot_b_cells.add((r, c))
                if left_b >= 2:
                    left_b_cells.add((r, c))
                if right_b >= 2:
                    right_b_cells.add((r, c))
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
            elif gray_count >= 15:
                grid_rows[r][c] = "M"
                visible_monsters.append({"symbol": "M", "row": r, "col": c})
            elif nonblack_count >= 24:
                grid_rows[r][c] = "*"
                visible_entities.append(
                    {"symbol": "*", "type": "entity", "row": r, "col": c}
                )

    # Resolve walls and doors from candidates
    for r, c in wall_candidates:
        has_l = (r, c - 1) in wall_candidates
        has_r = (r, c + 1) in wall_candidates
        has_u = (r - 1, c) in wall_candidates
        has_d = (r + 1, c) in wall_candidates
        has_tb = (r, c) in top_b_cells and (r, c) in bot_b_cells
        has_lr = (r, c) in left_b_cells and (r, c) in right_b_cells

        is_door = (
            (has_l and has_r and has_tb)
            or (has_u and has_d and has_lr)
            or (has_tb and has_lr)
        )
        if is_door:
            grid_rows[r][c] = "+"
            door_positions.append((r, c))
        elif has_u and has_d and not (has_l and has_r):
            grid_rows[r][c] = "|"
        elif has_l and has_r:
            grid_rows[r][c] = "-"
        elif has_u or has_d:
            grid_rows[r][c] = "|"
        else:
            grid_rows[r][c] = "-"

    # Filter phantom entities floating in black space outside the dungeon in a single pass
    removed_coords: set[tuple[int, int]] = set()
    for r in range(1, 23):
        for c in range(80):
            if grid_rows[r][c] in ("*", ":", "?"):
                has_adj_dungeon = any(
                    1 <= r + dr <= 22
                    and 0 <= c + dc < 80
                    and grid_rows[r + dr][c + dc] in (".", "#", "+", "-", "|", "@", "%")
                    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                )
                if not has_adj_dungeon:
                    grid_rows[r][c] = " "
                    removed_coords.add((r, c))

    if removed_coords:
        visible_entities = [
            e
            for e in visible_entities
            if (e.get("row"), e.get("col")) not in removed_coords
        ]

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
        for dir_name, (dr, dc) in DIRECTION_DELTAS_BY_CODE.items():
            nr, nc = pr + dr, pc + dc
            if 1 <= nr <= 22 and 0 <= nc < 80:
                ch = grid_rows[nr][nc]
                adjacent_tiles[dir_name] = ch
                if ch not in _WALKABLE_ASCII_CHARS and not (
                    len(ch) == 1 and ch.isalpha() and ch.isupper()
                ):
                    continue
                if dir_name in ("NE", "NW", "SE", "SW") and (
                    in_doorway or ch in ("+", "#")
                ):
                    continue
                walkable_directions.append(dir_name)
            else:
                adjacent_tiles[dir_name] = " "

    room_bbox: tuple[int, int, int, int] | None = None
    if player_position is not None:
        pr, pc = player_position
        top_w = next((r for r in range(pr - 1, 0, -1) if grid_rows[r][pc] in ("-", "|", "+")), None)
        bot_w = next((r for r in range(pr + 1, 23) if grid_rows[r][pc] in ("-", "|", "+")), None)
        left_w = next((c for c in range(pc - 1, -1, -1) if grid_rows[pr][c] in ("-", "|", "+")), None)
        right_w = next((c for c in range(pc + 1, 80) if grid_rows[pr][c] in ("-", "|", "+")), None)
        if top_w is not None and bot_w is not None and left_w is not None and right_w is not None:
            room_bbox = (top_w, left_w, bot_w, right_w)

    rendered_lines: list[str] = []
    for r in range(1, 23):
        line_str = "".join(grid_rows[r]).rstrip()
        if line_str.strip():
            rendered_lines.append(f"{r:02d}: {line_str}")

    has_more_prompt = any(
        all((c + i) in row0_inverse_cells for i in range(4))
        for c in range(77)
    )

    ascii_grid_text = "\n".join(rendered_lines) if rendered_lines else None
    grid_meta = {
        "player_position": player_position,
        "stairs_positions": stairs_positions,
        "door_positions": door_positions,
        "visible_monsters": visible_monsters,
        "visible_entities": visible_entities,
        "visible_items": visible_entities,
        "adjacent_tiles": adjacent_tiles,
        "walkable_directions": walkable_directions,
        "row0_active_cells": row0_active_cells,
        "has_more_prompt": has_more_prompt,
        "dungeon_nonempty_cells": dungeon_nonempty_cells,
        "room_bbox": room_bbox,
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

    # Epyx 'Rogue's Name?' screen has magenta credits text (~0.1%..2.5%) or yellow curtain (>4%)
    if 0.0008 <= magenta_ratio <= 0.025 or curtain_ratio > 0.04:
        metrics["needs_screenshot_backup"] = True
        metrics["backup_reason"] = "character_name_entry_screen"
        return VisualScreenAnalysis(
            inferred_state=GameState.CHARACTER_NAME_ENTRY,
            uncertainty=0.15,
            metrics=metrics,
        )

    ascii_grid_text, grid_meta = extract_dosbox_ascii_grid(canvas)
    metrics.update(grid_meta)

    if grid_meta.get("has_more_prompt"):
        metrics["needs_screenshot_backup"] = True
        metrics["backup_reason"] = "more_prompt_active_on_row0"
        return VisualScreenAnalysis(
            inferred_state=GameState.MORE_PROMPT,
            uncertainty=0.05,
            metrics=metrics,
            ascii_grid_text=ascii_grid_text,
        )

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
