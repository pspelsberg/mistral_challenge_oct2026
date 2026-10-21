"""Prompt construction for Mistral Large 4 across Steam (ASCII-first + Screenshot backup) and Terminal."""

from __future__ import annotations

import base64
from typing import Any

from rogue_agent.shared.domain import BackendId, GameObservation

SYSTEM_PROMPT = """You are 'Le Chonk', an autonomous Rogue-playing AI agent powered by Mistral Large 4.
Your goal is to survive the Dungeons of Doom, fight or evade monsters, manage food/potions/scrolls/equipment wisely, and descend staircases to retrieve the Amulet of Yendor.

CORE AUTONOMY & EFFICIENCY RULES:
1. You own all tactical and strategic decisions: where to explore, when to fight or retreat, which item to use, and when to descend deeper.
2. TOKEN EFFICIENCY & MOVEMENT:
   - Prefer `action='fast_move'` with a `direction` when walking down corridors (`#`) or crossing a room to a wall/door directly in line with you.
   - Note: `fast_move` runs until hitting a wall, corner, item, or monster, so inside a room it will slide right past a door (`+`) located in the middle of a side wall! To step toward a mid-wall door (e.g. moving from col 7 to a door at col 13), use `action='move'` with `steps=2..5` instead of `fast_move`.
   - NEVER walk over empty `.` floor tiles to "check" them for items or stairs! In Rogue, all items (`*`, `!`, `?`, `)`, `]`), monsters (`A-Z`), doors (`+`), and stairs (`%`) in a lit room are ALREADY 100% visible on the grid from the moment you enter. A `.` tile is guaranteed empty floor — exit the room immediately via an unvisited door (`+`) if no items/stairs are visible.
   - Check `UNVISITED Doors '+' on Screen` vs `ALREADY VISITED Doors '+' on Screen` in `BOUNDED AGENT MEMORY`. Always prioritize UNVISITED doors over backtracking through already visited doors!
   - NEVER move diagonally (`NW`, `NE`, `SW`, `SE`) into or out of a doorway (`+`) or corridor (`#`)! Rogue strictly forbids diagonal doorway movement. Only pick directions present in `walkable_directions`, and step cardinally (`N`, `S`, `E`, `W`) to align with a doorway first.
   - Check `Recent Position Trail` in memory and NEVER oscillate back and forth (`E` then `W` then `E`) between two coordinates of the same room.
   - Use `action='move'` with `steps=1` for tactical melee combat or stepping onto a specific tile/doorway.
3. COMBAT, STAIRCASE SPRINT & SURVIVAL DOCTRINE:
   - STAIRCASE SPRINT PRIORITY: If the staircase (`%`) is visible in your room and the step toward `%` is open (`.` or `%`), reaching `%` and descending (`action='descend_stairs'`) takes PRIORITY over fighting adjacent monsters that are NOT blocking the path to `%`! Only fight a monster near `%` if it is physically standing on the tile between you and `%`.
   - ADAPTIVE COMBAT & THREAT ASSESSMENT (Contextual, not rigid):
     * Fast 2x-speed fliers (Kestrel `K`, Bat `B`): NEVER flee across open rooms — fleeing forfeits your attack and gives them free hits. Stand and fight in 1v1 melee.
     * Standard 1x-speed monsters (Hobgoblin `H`, Orc `O`, Emu `E`, Snake `S`, Zombie `Z`): Stand and fight when HP is healthy. However, assess monster damage potential dynamically: heavy hitters like `H` and `O` deal 1d8 damage (up to 6-8 HP in a single blow!). If your HP is within one-shot range (e.g. <= 6-7 HP vs `H`/`O`) and you have no healing items, trading melee swings has a high chance of lethal one-shot. In Rogue 5.4.4, standard 1x monsters spend their turn following, so stepping back into a corridor, toward a known staircase, or creating distance does NOT grant them free attacks.
     * Chokepoints: Prefer fighting at doorway (`+`) or corridor (`#`) tiles so monsters must face you 1v1 rather than surrounding you.
   - LOW HP CONSUMABLE USE: When HP drops to critical levels (e.g. <= 4 HP, or <= 33% max HP, or within one-hit lethal range of a heavy hitter) and you possess a potion (`!`) or scroll (`?`) in `Known Inventory Slots (FACT)`, prioritize `action='quaff_potion'` or `action='read_scroll'` with its `item_key` before risking a fatal melee blow.
4. Only rely on the visible screen, visible status bar, and bounded memory provided to you.
5. Check `walkable_directions` and `adjacent_tiles` in the metadata before moving so you never walk into walls ('|' or '-'). If a corridor or room appears to be a dead end, use `action='search'` (`steps=3`) to search for secret doors.
6. When standing directly on a staircase ('%' or '≡'), choose `action='descend_stairs'` to go deeper once ready.
7. Output a single valid JSON object matching the MistralActionDecision schema with a concise decision_summary."""

_EPYX_LEGEND = """STEAM EPYX ROGUE v1.49 SYMBOLS (RECONSTRUCTED 80x25 ASCII GRID + BACKUP SCREENSHOT):
- @ (☺) : The Hero (you)
- . (∙) : Room floor
- + (╬) : Doorway
- # (▒) : Lit corridor/passage
- | and - (║ / ═) : Room walls
- % (≡) : Staircase down
- : (♣ / ♦) : Food or Trap
- ? (¡ / ♪ / ↑ / ◘) : Potion, Scroll, Weapon, or Armor
- * (☼) : Gold or other item
- M (A-Z) : Monster (move into adjacent monster to attack in melee)"""

_TERMINAL_LEGEND = """TERMINAL ROGUE 5.4.4 ASCII SYMBOLS:
- @ : The Hero (you)
- . : Room floor
- + : Door
- # : Corridor/passage
- | and - : Room walls
- % : Staircase
- * : Gold | ) : Weapon | ] : Armor | ! : Potion | ? : Scroll | : : Food | / : Wand/Staff | = : Ring | ^ : Trap
- A-Z : 26 Monster types (move into adjacent monster to attack in melee)"""


def build_mistral_messages(
    observation: GameObservation,
    memory_summary: str,
    current_objective: str,
    screenshot_backup_only: bool = True,
) -> list[dict[str, Any]]:
    """Construct the official Mistral chat messages payload (ASCII-primary + screenshot backup)."""
    legend = _EPYX_LEGEND if observation.backend == BackendId.STEAM else _TERMINAL_LEGEND
    status = observation.visible_status

    context_lines = [
        f"BACKEND: {observation.backend.value} (Version: {observation.rogue_version})",
        f"DETECTED UI STATE: {observation.game_state.value}",
        f"CURRENT OBJECTIVE: {current_objective}",
        f"PREVIOUS ACTION RESULT: {observation.previous_action_result or 'None (Start of run)'}",
        f"RECENT MESSAGES: {observation.recent_messages or ['None']}",
        (
            f"VISIBLE STATUS BAR: Level={status.dungeon_level} | "
            f"HP={status.hits_current}/{status.hits_max} | "
            f"Str={status.strength_current}/{status.strength_max} | "
            f"Gold={status.gold} | Armor={status.armor} | "
            f"Hunger={status.hunger_state or 'OK'}"
        ),
        "",
        "BOUNDED AGENT MEMORY:",
        memory_summary or "(Empty memory - first turn)",
        "",
        legend,
    ]

    if observation.screen_text is not None:
        header = (
            "CURRENT 80x24 TERMINAL SCREEN:"
            if observation.backend == BackendId.TERMINAL
            else "RECONSTRUCTED 80x25 STEAM DOSBOX ASCII GRID (Rows 01..22):"
        )
        context_lines.extend(
            [
                "",
                header,
                "```text",
                observation.screen_text,
                "```",
                f"VISIBLE ENTITIES & SPATIAL SUMMARY: {observation.inferred_metadata}",
            ]
        )

    should_attach_image = False
    if observation.backend == BackendId.STEAM and observation.screenshot_png_bytes is not None:
        if not screenshot_backup_only:
            should_attach_image = True
        else:
            needs_backup = (observation.screen_text is None) or bool(
                observation.inferred_metadata.get("needs_screenshot_backup", False)
            )
            should_attach_image = needs_backup

    if should_attach_image and observation.screenshot_png_bytes is not None:
        backup_reason = observation.inferred_metadata.get("backup_reason") or "visual_verification"
        context_lines.append(
            f"\n[BACKUP SCREENSHOT ATTACHED — Reason: {backup_reason}]"
        )
        b64_png = base64.b64encode(observation.screenshot_png_bytes).decode("ascii")
        user_content: Any = [
            {"type": "text", "text": "\n".join(context_lines)},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_png}"},
            },
        ]
    else:
        user_content = "\n".join(context_lines)

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
