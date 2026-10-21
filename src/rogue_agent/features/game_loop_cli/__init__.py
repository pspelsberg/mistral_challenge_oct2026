"""Slice 6: Agent Controller and CLI Composition Root (Section 13)."""

from rogue_agent.features.game_loop_cli.cli import main
from rogue_agent.features.game_loop_cli.controller import AgentGameController

__all__ = ["AgentGameController", "main"]
