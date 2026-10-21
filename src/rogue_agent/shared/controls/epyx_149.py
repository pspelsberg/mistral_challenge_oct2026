"""Control profile for Steam Epyx Rogue v1.49 (DOSBox)."""

from __future__ import annotations

from rogue_agent.shared.controls.base import BaseControlProfile
from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState

# Verified against official Steam Epyx Rogue Instruction Manual (Pages 7 & 17):
# Cursor / Keypad 8-direction navigation keys in DOSBox X11:
_EPYX_DIRECTION_KEYS: dict[Direction, str] = {
    Direction.NORTH: "Up",
    Direction.SOUTH: "Down",
    Direction.WEST: "Left",
    Direction.EAST: "Right",
    Direction.NORTHWEST: "Home",
    Direction.NORTHEAST: "Prior",  # PageUp in X11 keysym
    Direction.SOUTHWEST: "End",
    Direction.SOUTHEAST: "Next",   # PageDown in X11 keysym
}


class Epyx149ControlProfile(BaseControlProfile):
    """Control mappings for Epyx Rogue v1.49 running in Steam DOSBox."""

    @property
    def version_name(self) -> str:
        return "epyx-1.49"

    def direction_key(self, direction: Direction) -> str:
        return _EPYX_DIRECTION_KEYS[direction]

    def space_token(self) -> str:
        return "space"

    def enter_token(self) -> str:
        return "Return"

    def escape_token(self) -> str:
        return "Escape"

    def translate_action(self, action: GameAction, current_state: GameState) -> list[str]:
        """Handle Epyx 1.49 specific startup states (Title Screen, Name Entry, Inventory)."""
        if current_state == GameState.START_MENU:
            # Page 5: "After the title screen appears press any key to advance to the next screen."
            return [self.space_token()]

        if current_state == GameState.CHARACTER_NAME_ENTRY and action.action_type != ActionType.ENTER_NAME:
            # Automatically enter character name if model picked another action on the name screen
            name_action = GameAction(
                action_type=ActionType.ENTER_NAME,
                text_input=action.text_input or "LeChonk",
                decision_summary="Enter character name on Epyx 1.49 startup screen",
            )
            return super().translate_action(name_action, current_state)

        if current_state == GameState.INVENTORY and action.action_type == ActionType.ACKNOWLEDGE_PROMPT:
            return [self.space_token()]

        return super().translate_action(action, current_state)
