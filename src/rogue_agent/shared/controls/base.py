"""Base control profile logic and action-to-key validation (Section 8)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState

ITEM_KEY_PATTERN = re.compile(r"^[a-zA-Z*]$")
SAFE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9 _-]{1,23}$")


class ControlValidationError(ValueError):
    """Raised when a GameAction is invalid or missing required parameters for a control profile."""


class BaseControlProfile(ABC):
    """Abstract base for version-specific Rogue control profiles."""

    @property
    @abstractmethod
    def version_name(self) -> str:
        """Return the target Rogue version identifier."""

    @abstractmethod
    def direction_key(self, direction: Direction) -> str:
        """Map an 8-way Direction to the version-specific key token."""

    @abstractmethod
    def space_token(self) -> str:
        """Return the key token used to clear --More-- / Cont prompts."""

    @abstractmethod
    def enter_token(self) -> str:
        """Return the key token for Enter/Return."""

    @abstractmethod
    def escape_token(self) -> str:
        """Return the key token for Escape."""

    def validate_item_key(self, action: GameAction) -> str:
        """Validate that a single inventory letter (a-z) is provided."""
        if not action.item_key or not ITEM_KEY_PATTERN.match(action.item_key):
            raise ControlValidationError(
                f"Action '{action.action_type.value}' requires a single inventory letter (a-z), "
                f"got {action.item_key!r}."
            )
        return action.item_key.lower()

    def validate_direction(self, action: GameAction) -> str:
        """Validate that a Direction is provided and return its key token."""
        if action.direction is None:
            raise ControlValidationError(
                f"Action '{action.action_type.value}' requires a direction."
            )
        return self.direction_key(action.direction)

    def translate_action(self, action: GameAction, current_state: GameState) -> list[str]:
        """Translate a validated GameAction into an ordered sequence of key tokens."""
        # If the game is currently waiting on a --More-- or Cont prompt, clear it first
        if current_state == GameState.MORE_PROMPT and action.action_type != ActionType.ACKNOWLEDGE_PROMPT:
            prefix = [self.space_token()]
        else:
            prefix = []

        if action.action_type == ActionType.ACKNOWLEDGE_PROMPT:
            return [self.space_token()]

        if action.action_type == ActionType.CANCEL_COMMAND:
            return [self.escape_token()]

        if action.action_type == ActionType.CONFIRM_DIALOG:
            return [self.enter_token()]

        if action.action_type == ActionType.ENTER_NAME:
            raw_name = (action.text_input or "LeChonk").strip()
            if not SAFE_NAME_PATTERN.match(raw_name):
                raw_name = "LeChonk"
            return [*list(raw_name), self.enter_token()]

        if action.action_type == ActionType.MOVE:
            return [*prefix, self.validate_direction(action)]

        if action.action_type == ActionType.FAST_MOVE:
            return [*prefix, "f", self.validate_direction(action)]

        if action.action_type == ActionType.SEARCH:
            return [*prefix, "s"]

        if action.action_type == ActionType.REST:
            return [*prefix, "."]

        if action.action_type == ActionType.DESCEND_STAIRS:
            return [*prefix, ">"]

        if action.action_type == ActionType.ASCEND_STAIRS:
            return [*prefix, "<"]

        if action.action_type == ActionType.OPEN_INVENTORY:
            return [*prefix, "i"]

        if action.action_type == ActionType.QUAFF_POTION:
            return [*prefix, "q", self.validate_item_key(action)]

        if action.action_type == ActionType.READ_SCROLL:
            return [*prefix, "r", self.validate_item_key(action)]

        if action.action_type == ActionType.EAT_FOOD:
            return [*prefix, "e", self.validate_item_key(action)]

        if action.action_type == ActionType.WIELD_WEAPON:
            return [*prefix, "w", self.validate_item_key(action)]

        if action.action_type == ActionType.WEAR_ARMOR:
            return [*prefix, "W", self.validate_item_key(action)]

        if action.action_type == ActionType.TAKE_OFF_ARMOR:
            return [*prefix, "T"]

        if action.action_type == ActionType.PUT_ON_RING:
            return [*prefix, "P", self.validate_item_key(action)]

        if action.action_type == ActionType.REMOVE_RING:
            if action.item_key:
                return [*prefix, "R", self.validate_item_key(action)]
            return [*prefix, "R"]

        if action.action_type == ActionType.DROP_ITEM:
            return [*prefix, "d", self.validate_item_key(action)]

        if action.action_type == ActionType.THROW_ITEM:
            dir_token = self.validate_direction(action)
            item_token = self.validate_item_key(action)
            return [*prefix, "t", dir_token, item_token]

        if action.action_type == ActionType.ZAP_WAND:
            dir_token = self.validate_direction(action)
            item_token = self.validate_item_key(action)
            return [*prefix, "z", dir_token, item_token]

        raise ControlValidationError(f"Unsupported action type: {action.action_type}")
