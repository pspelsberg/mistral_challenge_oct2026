"""Control profile for native Terminal Rogue 5.4.4 (classic UNIX vi-keys)."""

from __future__ import annotations

from rogue_agent.shared.controls.base import BaseControlProfile
from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState

_TERMINAL_DIRECTION_KEYS: dict[Direction, str] = {
    Direction.NORTH: "k",
    Direction.SOUTH: "j",
    Direction.WEST: "h",
    Direction.EAST: "l",
    Direction.NORTHWEST: "y",
    Direction.NORTHEAST: "u",
    Direction.SOUTHWEST: "b",
    Direction.SOUTHEAST: "n",
}


class TerminalRogueControlProfile(BaseControlProfile):
    """Control mappings for Terminal Rogue 5.4.4 via PTY."""

    @property
    def version_name(self) -> str:
        return "rogue-5.4.4"

    def direction_key(self, direction: Direction) -> str:
        return _TERMINAL_DIRECTION_KEYS[direction]

    def space_token(self) -> str:
        return " "

    def enter_token(self) -> str:
        return "\r"

    def escape_token(self) -> str:
        return "\x1b"

    def translate_action(self, action: GameAction, current_state: GameState) -> list[str]:
        """Handle Rogue 5.4.4 fast movement (uppercase HJKLYUBN) and inventory prompts."""
        if action.action_type == ActionType.FAST_MOVE:
            dir_key = self.validate_direction(action)
            prefix = [self.space_token()] if current_state == GameState.MORE_PROMPT else []
            return [*prefix, dir_key.upper()]

        return super().translate_action(action, current_state)
