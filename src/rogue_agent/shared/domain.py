"""Backend-neutral typed domain models for Rogue Agent (Section 5)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BackendId(StrEnum):
    """Supported execution backends."""

    STEAM = "steam"
    TERMINAL = "terminal"


class GameState(StrEnum):
    """Explicit UI and game states across Rogue backends."""

    NOT_STARTED = "NOT_STARTED"
    START_MENU = "START_MENU"
    CHARACTER_NAME_ENTRY = "CHARACTER_NAME_ENTRY"
    PLAYING = "PLAYING"
    MORE_PROMPT = "MORE_PROMPT"
    INVENTORY = "INVENTORY"
    ITEM_SELECTION = "ITEM_SELECTION"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"
    VICTORY = "VICTORY"
    UNKNOWN = "UNKNOWN"


class Direction(StrEnum):
    """Eight-direction movement in Rogue."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"

    @property
    def short_code(self) -> str:
        """Return the compass abbreviation ('N', 'S', 'E', 'W', 'NE', 'NW', 'SE', 'SW')."""
        return {
            Direction.NORTH: "N",
            Direction.SOUTH: "S",
            Direction.EAST: "E",
            Direction.WEST: "W",
            Direction.NORTHEAST: "NE",
            Direction.NORTHWEST: "NW",
            Direction.SOUTHEAST: "SE",
            Direction.SOUTHWEST: "SW",
        }[self]

    @property
    def delta(self) -> tuple[int, int]:
        """Return (drow, dcol) grid delta for this direction."""
        return {
            Direction.NORTH: (-1, 0),
            Direction.SOUTH: (1, 0),
            Direction.EAST: (0, 1),
            Direction.WEST: (0, -1),
            Direction.NORTHEAST: (-1, 1),
            Direction.NORTHWEST: (-1, -1),
            Direction.SOUTHEAST: (1, 1),
            Direction.SOUTHWEST: (1, -1),
        }[self]


class ActionType(StrEnum):
    """Permitted gameplay and UI actions."""

    MOVE = "move"
    FAST_MOVE = "fast_move"
    SEARCH = "search"
    REST = "rest"
    DESCEND_STAIRS = "descend_stairs"
    ASCEND_STAIRS = "ascend_stairs"
    OPEN_INVENTORY = "open_inventory"
    QUAFF_POTION = "quaff_potion"
    READ_SCROLL = "read_scroll"
    EAT_FOOD = "eat_food"
    WIELD_WEAPON = "wield_weapon"
    WEAR_ARMOR = "wear_armor"
    TAKE_OFF_ARMOR = "take_off_armor"
    PUT_ON_RING = "put_on_ring"
    REMOVE_RING = "remove_ring"
    DROP_ITEM = "drop_item"
    THROW_ITEM = "throw_item"
    ZAP_WAND = "zap_wand"
    ACKNOWLEDGE_PROMPT = "acknowledge_prompt"
    CONFIRM_DIALOG = "confirm_dialog"
    ENTER_NAME = "enter_name"
    CANCEL_COMMAND = "cancel_command"


class VisibleStatus(BaseModel):
    """Status bar information explicitly visible to the player on screen."""

    model_config = ConfigDict(frozen=True)

    dungeon_level: int | None = None
    hits_current: int | None = None
    hits_max: int | None = None
    strength_current: int | None = None
    strength_max: int | None = None
    gold: int | None = None
    armor: int | None = None
    exp_level: int | None = None
    exp_points: int | None = None
    rank_title: str | None = None
    hunger_state: str | None = None
    raw_status_line: str = ""


class GameObservation(BaseModel):
    """Backend-neutral representation of a single game observation (Section 5)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    backend: BackendId
    rogue_version: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    screen_text: str | None = None
    screenshot_png_bytes: bytes | None = Field(default=None, repr=False)
    visible_status: VisibleStatus = Field(default_factory=VisibleStatus)
    game_state: GameState = GameState.UNKNOWN
    recent_messages: list[str] = Field(default_factory=list)
    previous_action_result: str | None = None
    observation_uncertainty: float = Field(default=0.0, ge=0.0, le=1.0)
    cursor_position: tuple[int, int] | None = None
    inferred_metadata: dict[str, Any] = Field(default_factory=dict)


class GameAction(BaseModel):
    """Validated gameplay action selected by the Mistral gameplay agent."""

    model_config = ConfigDict(frozen=True)

    action_type: ActionType
    direction: Direction | None = None
    steps: int = Field(default=1, ge=1, le=5)
    item_key: str | None = Field(default=None, max_length=2)
    text_input: str | None = Field(default=None, max_length=23)
    decision_summary: str = Field(default="", max_length=300)
    objective: str = Field(default="Explore and survive", max_length=200)
    notable_memory_fact: str | None = Field(default=None, max_length=200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ActionExecutionResult(BaseModel):
    """Outcome of executing a GameAction (including interruptible multi-step horizon)."""

    success: bool
    keys_sent: list[str] = Field(default_factory=list)
    steps_requested: int = 1
    steps_completed: int = 1
    interrupted_early: bool = False
    interrupt_reason: str | None = None
    summary: str = ""
    error_message: str | None = None
    state_before: GameState = GameState.UNKNOWN
    state_after: GameState = GameState.UNKNOWN
