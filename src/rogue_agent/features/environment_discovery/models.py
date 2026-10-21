"""Data models for the Environment Discovery slice."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnvironmentDiscoveryReport(BaseModel):
    """Structured report of local environment capabilities and prerequisites (Section 3)."""

    operating_system: str
    python_version: str
    display_session_type: str
    x11_display: str | None = None
    steam_installed: bool
    steam_binary_path: str | None = None
    steam_rogue_installed: bool
    steam_rogue_install_dir: str | None = None
    steam_rogue_executable: str | None = None
    terminal_rogue_available: bool
    terminal_rogue_path: str | None = None
    terminal_rogue_version: str = "rogue-5.4.4"
    terminal_rogue_license: str = "BSD-3-Clause (Roguelike Restoration Project)"
    mistral_sdk_available: bool
    mistral_api_key_configured: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
