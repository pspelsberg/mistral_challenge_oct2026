"""Structured output schema and fallback validation for Mistral Large 4 (Section 9)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from rogue_agent.shared.domain import (
    REPEATABLE_HORIZON_ACTIONS,
    ActionType,
    Direction,
    GameAction,
    GameObservation,
    GameState,
)

_DIRECTIONAL_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.MOVE,
        ActionType.FAST_MOVE,
        ActionType.THROW_ITEM,
        ActionType.ZAP_WAND,
    }
)

_ITEM_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.QUAFF_POTION,
        ActionType.READ_SCROLL,
        ActionType.EAT_FOOD,
        ActionType.WIELD_WEAPON,
        ActionType.WEAR_ARMOR,
        ActionType.PUT_ON_RING,
        ActionType.DROP_ITEM,
        ActionType.THROW_ITEM,
        ActionType.ZAP_WAND,
    }
)

_DIRECTION_PRIORITY: tuple[Direction, ...] = (
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
)


class MistralActionDecision(BaseModel):
    """Structured JSON schema returned by mistral-large-4 for each turn."""

    observed_state: GameState = Field(
        default=GameState.PLAYING,
        description="The UI/gameplay state perceived on screen.",
    )
    current_objective: str = Field(
        default="Explore current dungeon level and locate the staircase",
        max_length=200,
        description="High-level tactical objective chosen by Mistral Large 4.",
    )
    action: ActionType = Field(
        description="The permitted game action to execute. Prefer 'fast_move' for crossing open rooms/corridors."
    )
    direction: Direction | None = Field(
        default=None,
        description="Required when action is move, fast_move, throw_item, or zap_wand.",
    )
    steps: int = Field(
        default=1,
        ge=1,
        le=5,
        description=(
            "Short action horizon (1 to 5 steps) when action is 'move', 'search', or 'rest'. "
            "The harness executes up to 'steps' times and automatically interrupts early if "
            "blocked by a wall or if a monster, message, or prompt appears."
        ),
    )
    item_key: str | None = Field(
        default=None,
        max_length=2,
        description="Single inventory letter (a-z) when using/dropping/equipping an item.",
    )
    text_input: str | None = Field(
        default=None,
        max_length=23,
        description="Character name when observed_state is CHARACTER_NAME_ENTRY.",
    )
    decision_summary: str = Field(
        max_length=300,
        description="Concise explanation of why this action was selected (no hidden CoT).",
    )
    notable_memory_fact: str | None = Field(
        default=None,
        max_length=200,
        description="Optional important fact or hypothesis to store in bounded memory.",
    )
    confidence: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Model confidence in this action [0.0, 1.0].",
    )

    def to_game_action(self, fallback_observation: GameObservation) -> GameAction:
        """Convert to a domain GameAction, repairing missing direction/item parameters safely."""
        if self.action in _DIRECTIONAL_ACTIONS and self.direction is None:
            return safe_fallback_action(
                fallback_observation,
                reason=f"Model returned '{self.action.value}' without a direction",
            )

        if self.action in _ITEM_ACTIONS and (not self.item_key or not self.item_key.isalpha()):
            return safe_fallback_action(
                fallback_observation,
                reason=f"Model returned '{self.action.value}' without a valid item_key",
            )

        effective_direction = self.direction
        effective_summary = self.decision_summary
        if (
            self.action in (ActionType.MOVE, ActionType.FAST_MOVE)
            and effective_direction is not None
        ):
            walkable = fallback_observation.inferred_metadata.get("walkable_directions")
            if (
                isinstance(walkable, list)
                and walkable
                and not effective_direction.matches_walkable(walkable)
            ):
                replacement: Direction | None = None
                diag_comps = effective_direction.diagonal_components
                if diag_comps is not None:
                    for comp in diag_comps:
                        if comp.matches_walkable(walkable):
                            replacement = comp
                            break
                if replacement is None:
                    for cand in _DIRECTION_PRIORITY:
                        if cand.matches_walkable(walkable):
                            replacement = cand
                            break
                if replacement is not None:
                    effective_summary = (
                        f"{self.decision_summary} "
                        f"[Wall-Guard: redirected blocked {effective_direction.value} -> {replacement.value}]"
                    )[:300]
                    effective_direction = replacement

        effective_steps = self.steps if self.action in REPEATABLE_HORIZON_ACTIONS else 1

        return GameAction(
            action_type=self.action,
            direction=effective_direction,
            steps=effective_steps,
            item_key=self.item_key.lower()[:1] if self.item_key else None,
            text_input=self.text_input,
            decision_summary=effective_summary,
            objective=self.current_objective,
            notable_memory_fact=self.notable_memory_fact,
            confidence=self.confidence,
        )


def safe_fallback_action(
    observation: GameObservation,
    reason: str = "Fallback",
    player_name: str = "LeChonk",
) -> GameAction:
    """Documented safe fallback when the model returns an invalid or incomplete action."""
    if observation.game_state in (
        GameState.MORE_PROMPT,
        GameState.START_MENU,
        GameState.INVENTORY,
    ):
        return GameAction(
            action_type=ActionType.ACKNOWLEDGE_PROMPT,
            decision_summary=f"[{reason}] Clear prompt with Space",
            objective="Advance dialog prompt",
            confidence=0.5,
        )

    if observation.game_state == GameState.CHARACTER_NAME_ENTRY:
        return GameAction(
            action_type=ActionType.ENTER_NAME,
            text_input=player_name,
            decision_summary=f"[{reason}] Enter character name {player_name}",
            objective="Start game",
            confidence=0.8,
        )

    if observation.game_state == GameState.ITEM_SELECTION:
        return GameAction(
            action_type=ActionType.CANCEL_COMMAND,
            decision_summary=f"[{reason}] Cancel incomplete item selection with Escape",
            objective="Recover to normal playing state",
            confidence=0.5,
        )

    walkable = observation.inferred_metadata.get("walkable_directions")
    if isinstance(walkable, list) and walkable:
        for cand in (Direction.EAST, Direction.SOUTH, Direction.WEST, Direction.NORTH):
            if cand.matches_walkable(walkable):
                return GameAction(
                    action_type=ActionType.MOVE,
                    direction=cand,
                    steps=1,
                    decision_summary=f"[{reason}] Safe fallback: step into walkable direction {cand.value}",
                    objective="Explore walkable tile",
                    confidence=0.4,
                )

    return GameAction(
        action_type=ActionType.SEARCH,
        decision_summary=f"[{reason}] Safe fallback: search adjacent tiles",
        objective="Observe surroundings safely",
        confidence=0.3,
    )
