"""Typed models for bounded agent memory separating facts from hypotheses (Section 11)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


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


class TurnMemoryRecord(BaseModel):
    """Compact record of a single completed gameplay turn."""

    turn: int
    action_label: str
    outcome_summary: str
    effective: bool
    dungeon_level: int | None = None
    hp: int | None = None
