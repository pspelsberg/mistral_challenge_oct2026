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
        return _DIRECTION_TO_SHORT_CODE[self]

    @property
    def delta(self) -> tuple[int, int]:
        """Return (drow, dcol) grid delta for this direction."""
        return _DIRECTION_TO_DELTA[self]

    @property
    def opposite(self) -> Direction:
        """Return the 180-degree opposite direction."""
        return _OPPOSITE_DIRECTIONS[self]

    @property
    def is_diagonal(self) -> bool:
        """Return True if this direction is diagonal (NE, NW, SE, SW)."""
        return self in _DIAGONAL_COMPONENTS

    @property
    def diagonal_components(self) -> tuple[Direction, Direction] | None:
        """Return the (vertical, horizontal) cardinal components if diagonal, else None."""
        return _DIAGONAL_COMPONENTS.get(self)

    def matches_walkable(self, walkable: list[Any] | set[Any] | tuple[Any, ...]) -> bool:
        """Return True if either the short code ('E') or value ('east') is in `walkable`."""
        return self.short_code in walkable or self.value in walkable

    @classmethod
    def from_short_code(cls, code: str) -> Direction | None:
        """Resolve a compass short code ('N', 'NE', etc.) to a Direction."""
        return _SHORT_CODE_TO_DIRECTION.get(code.strip().upper())

    @classmethod
    def from_delta(cls, drow: int, dcol: int) -> Direction | None:
        """Resolve a normalized (-1..1, -1..1) grid delta to a Direction."""
        norm_r = -1 if drow < 0 else (1 if drow > 0 else 0)
        norm_c = -1 if dcol < 0 else (1 if dcol > 0 else 0)
        return _DELTA_TO_DIRECTION.get((norm_r, norm_c))


_DIRECTION_TO_SHORT_CODE: dict[Direction, str] = {
    Direction.NORTH: "N",
    Direction.SOUTH: "S",
    Direction.EAST: "E",
    Direction.WEST: "W",
    Direction.NORTHEAST: "NE",
    Direction.NORTHWEST: "NW",
    Direction.SOUTHEAST: "SE",
    Direction.SOUTHWEST: "SW",
}

_SHORT_CODE_TO_DIRECTION: dict[str, Direction] = {
    code: direction for direction, code in _DIRECTION_TO_SHORT_CODE.items()
}

_DIRECTION_TO_DELTA: dict[Direction, tuple[int, int]] = {
    Direction.NORTH: (-1, 0),
    Direction.SOUTH: (1, 0),
    Direction.EAST: (0, 1),
    Direction.WEST: (0, -1),
    Direction.NORTHEAST: (-1, 1),
    Direction.NORTHWEST: (-1, -1),
    Direction.SOUTHEAST: (1, 1),
    Direction.SOUTHWEST: (1, -1),
}

_DELTA_TO_DIRECTION: dict[tuple[int, int], Direction] = {
    delta: direction for direction, delta in _DIRECTION_TO_DELTA.items()
}

DIRECTION_DELTAS_BY_CODE: dict[str, tuple[int, int]] = {
    direction.short_code: delta for direction, delta in _DIRECTION_TO_DELTA.items()
}

_OPPOSITE_DIRECTIONS: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
    Direction.NORTHEAST: Direction.SOUTHWEST,
    Direction.SOUTHWEST: Direction.NORTHEAST,
    Direction.NORTHWEST: Direction.SOUTHEAST,
    Direction.SOUTHEAST: Direction.NORTHWEST,
}

_DIAGONAL_COMPONENTS: dict[Direction, tuple[Direction, Direction]] = {
    Direction.NORTHEAST: (Direction.NORTH, Direction.EAST),
    Direction.NORTHWEST: (Direction.NORTH, Direction.WEST),
    Direction.SOUTHEAST: (Direction.SOUTH, Direction.EAST),
    Direction.SOUTHWEST: (Direction.SOUTH, Direction.WEST),
}


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


REPEATABLE_HORIZON_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.MOVE,
        ActionType.SEARCH,
        ActionType.REST,
    }
)

MENU_SELECTION_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.THROW_ITEM,
        ActionType.QUAFF_POTION,
        ActionType.READ_SCROLL,
        ActionType.EAT_FOOD,
        ActionType.WIELD_WEAPON,
        ActionType.WEAR_ARMOR,
        ActionType.PUT_ON_RING,
        ActionType.REMOVE_RING,
        ActionType.DROP_ITEM,
        ActionType.ZAP_WAND,
    }
)


def extract_numbered_row_map(screen_text: str | None) -> dict[int, str]:
    """Parse an ASCII screen string (numbered `RR: ...` or raw lines) into a `{row_idx: line}` map."""
    row_map: dict[int, str] = {}
    if not screen_text:
        return row_map
    lines = screen_text.splitlines()
    has_numbered = any(
        len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": "
        for line in lines
    )
    if has_numbered:
        for line in lines:
            if len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": ":
                row_map[int(line[:2])] = line[4:]
    else:
        for idx, line in enumerate(lines):
            row_map[idx] = line
    return row_map


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
    intermediate_screenshot_bytes: bytes | None = Field(default=None, repr=False)
