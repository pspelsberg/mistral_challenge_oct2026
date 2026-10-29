"""Configuration and safety guardrails via Pydantic Settings (Sections 12 & 16)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MANDATORY_GAMEPLAY_MODEL = "mistral-large-4"
_SAFE_PLAYER_NAME_RE = re.compile(r"^[a-zA-Z0-9 _-]{1,23}$")


class RogueAgentSettings(BaseSettings):
    """Environment-backed configuration with strict safety defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mistral_api_key: str = Field(
        default="",
        validation_alias="MISTRAL_API_KEY",
        repr=False,
    )
    model_id: str = Field(default=MANDATORY_GAMEPLAY_MODEL, validation_alias="ROGUE_MODEL_ID")

    # Safety, Latency, and Budget Guardrails (Section 12)
    max_turns: int = Field(default=100, ge=1, le=10000, validation_alias="ROGUE_MAX_TURNS")
    max_api_calls: int = Field(default=120, ge=1, le=10000, validation_alias="ROGUE_MAX_API_CALLS")
    max_session_seconds: int = Field(
        default=1800, ge=10, le=86400, validation_alias="ROGUE_MAX_SESSION_SECONDS"
    )
    max_budget_usd: float = Field(
        default=1.00, gt=0.0, le=100.0, validation_alias="ROGUE_MAX_BUDGET_USD"
    )
    request_timeout_seconds: float = Field(
        default=30.0, gt=1.0, le=180.0, validation_alias="ROGUE_REQUEST_TIMEOUT_SECONDS"
    )
    max_retries: int = Field(default=3, ge=0, le=10, validation_alias="ROGUE_MAX_RETRIES")
    menu_wait_seconds: float = Field(
        default=1.5, ge=0.0, le=10.0, validation_alias="ROGUE_MENU_WAIT_SECONDS"
    )

    # Pricing estimate for mistral-large-4 (conservative upper-bound per 1M tokens)
    estimated_input_cost_per_1m: float = Field(default=2.00)
    estimated_output_cost_per_1m: float = Field(default=6.00)

    # Backend paths
    terminal_binary: Path = Field(
        default=Path("./bin/rogue"), validation_alias="ROGUE_TERMINAL_BINARY"
    )
    steam_app_id: int = Field(default=1443430, validation_alias="ROGUE_STEAM_APP_ID")
    steam_install_dir: Path = Field(
        default=Path("/home/peppi/.local/share/Steam/steamapps/common/Rogue"),
        validation_alias="ROGUE_STEAM_INSTALL_DIR",
    )
    runs_dir: Path = Field(default=Path("./runs"), validation_alias="ROGUE_RUNS_DIR")
    player_name: str = Field(
        default="LeChonk",
        max_length=23,
        validation_alias="ROGUE_PLAYER_NAME",
    )
    steam_screenshot_backup_only: bool = Field(
        default=True, validation_alias="ROGUE_STEAM_SCREENSHOT_BACKUP_ONLY"
    )

    @field_validator("model_id")
    @classmethod
    def enforce_mandatory_model(cls, value: str) -> str:
        """Never substitute another model for gameplay (Section 1)."""
        if value != MANDATORY_GAMEPLAY_MODEL:
            raise ValueError(
                f"Competition rules require '{MANDATORY_GAMEPLAY_MODEL}', got '{value}'."
            )
        return value

    @field_validator("player_name")
    @classmethod
    def sanitize_player_name(cls, value: str) -> str:
        """Sanitize player_name to prevent ROGUEOPTS or keystroke injection."""
        cleaned = value.strip()
        if not cleaned or not _SAFE_PLAYER_NAME_RE.match(cleaned):
            raise ValueError(
                "player_name must be 1..23 characters containing only [a-zA-Z0-9 _-]."
            )
        return cleaned
