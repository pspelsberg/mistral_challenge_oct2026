"""Slice 1: Native Terminal Rogue 5.4.4 Backend (Section 7)."""

from rogue_agent.features.terminal_backend.adapter import TerminalGameAdapter
from rogue_agent.features.terminal_backend.screen_parser import (
    ParsedTerminalScreen,
    parse_terminal_screen,
)

__all__ = ["ParsedTerminalScreen", "TerminalGameAdapter", "parse_terminal_screen"]
