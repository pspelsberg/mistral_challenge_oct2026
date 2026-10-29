"""Typed models for bounded agent memory separating facts from hypotheses (Section 11)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class EpistemicStatus(StrEnum):
    """Distinguishes harness-verified facts from model-inferred hypotheses."""

    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"


class MemoryFact(BaseModel):
    """A single bounded memory item with epistemic tag."""

    turn: int
    status: EpistemicStatus
    category: str
    content: str = Field(max_length=220)

    @field_validator("content", mode="before")
    @classmethod
    def _truncate_content(cls, v: Any) -> str:
        s = str(v)
        return s[:220] if len(s) > 220 else s


class TurnMemoryRecord(BaseModel):
    """Compact record of a single completed gameplay turn."""

    turn: int
    action_label: str
    outcome_summary: str
    effective: bool
    dungeon_level: int | None = None
    hp: int | None = None
