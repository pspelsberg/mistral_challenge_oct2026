"""Level 1 Unit Tests for Shared Kernel (Config, Domain, and Control Profiles)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.controls import (
    ControlValidationError,
    Epyx149ControlProfile,
    TerminalRogueControlProfile,
)
from rogue_agent.shared.domain import ActionType, Direction, GameAction, GameState


@pytest.mark.unit
def test_mandatory_gameplay_model_enforced() -> None:
    """Competition rule: only mistral-large-4 is allowed as gameplay model."""
    cfg = RogueAgentSettings(MISTRAL_API_KEY="dummy")
    assert cfg.model_id == "mistral-large-4"

    with pytest.raises(ValidationError, match="mistral-large-4"):
        RogueAgentSettings(ROGUE_MODEL_ID="gpt-4o")


@pytest.mark.unit
def test_epyx_149_control_profile_mappings() -> None:
    """Verify Epyx Rogue 1.49 control translations against manual specifications."""
    profile = Epyx149ControlProfile()
    assert profile.version_name == "epyx-1.49"

    # Eight-direction movement
    move_north = GameAction(action_type=ActionType.MOVE, direction=Direction.NORTH)
    assert profile.translate_action(move_north, GameState.PLAYING) == ["Up"]

    move_ne = GameAction(action_type=ActionType.MOVE, direction=Direction.NORTHEAST)
    assert profile.translate_action(move_ne, GameState.PLAYING) == ["Prior"]

    # Automatic --More-- clearance prefix when in MORE_PROMPT state
    assert profile.translate_action(move_north, GameState.MORE_PROMPT) == ["space", "Up"]

    # Startup title screen advances with space
    assert profile.translate_action(move_north, GameState.START_MENU) == ["space"]

    # Character name entry types name + Return
    name_keys = profile.translate_action(
        GameAction(action_type=ActionType.ENTER_NAME, text_input="Chonk"),
        GameState.CHARACTER_NAME_ENTRY,
    )
    assert name_keys == ["C", "h", "o", "n", "k", "Return"]

    # Multi-step item and directional commands
    zap = GameAction(
        action_type=ActionType.ZAP_WAND,
        direction=Direction.EAST,
        item_key="c",
    )
    assert profile.translate_action(zap, GameState.PLAYING) == ["z", "Right", "c"]


@pytest.mark.unit
def test_terminal_rogue_control_profile_mappings() -> None:
    """Verify Terminal Rogue 5.4.4 control translations (classic vi-keys)."""
    profile = TerminalRogueControlProfile()
    assert profile.version_name == "rogue-5.4.4"

    move_nw = GameAction(action_type=ActionType.MOVE, direction=Direction.NORTHWEST)
    assert profile.translate_action(move_nw, GameState.PLAYING) == ["y"]

    fast_east = GameAction(action_type=ActionType.FAST_MOVE, direction=Direction.EAST)
    assert profile.translate_action(fast_east, GameState.PLAYING) == ["L"]

    quaff = GameAction(action_type=ActionType.QUAFF_POTION, item_key="b")
    assert profile.translate_action(quaff, GameState.PLAYING) == ["q", "b"]

    # Missing item_key raises ControlValidationError
    bad_quaff = GameAction(action_type=ActionType.QUAFF_POTION)
    with pytest.raises(ControlValidationError):
        profile.translate_action(bad_quaff, GameState.PLAYING)
