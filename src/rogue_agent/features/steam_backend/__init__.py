"""Slice 2: Steam Epyx Rogue 1.49 Backend (Section 6)."""

from rogue_agent.features.steam_backend.adapter import SteamGameAdapter
from rogue_agent.features.steam_backend.window_manager import (
    WindowFocusLostError,
    WindowInfo,
    WindowNotFoundError,
    X11WindowManager,
)

__all__ = [
    "SteamGameAdapter",
    "WindowFocusLostError",
    "WindowInfo",
    "WindowNotFoundError",
    "X11WindowManager",
]
