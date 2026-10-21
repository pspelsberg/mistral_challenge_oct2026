"""Latency, retry, rate-limit, and API spending budget guardrails (Section 12)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from rogue_agent.shared.config import RogueAgentSettings

T = TypeVar("T")


class BudgetExceededError(RuntimeError):
    """Raised when the configured API spending budget or call limit is reached."""


class SessionLimitReachedError(RuntimeError):
    """Raised when max turns or max session duration is reached."""


class BudgetAndRateGuard:
    """Tracks API usage, enforces hard session/cost limits, and handles exponential backoff."""

    def __init__(self, settings: RogueAgentSettings) -> None:
        self.settings = settings
        self.session_start_monotonic = time.monotonic()
        self.api_calls: int = 0
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.estimated_cost_usd: float = 0.0
        self.total_latency_ms: float = 0.0
        self.unknown_usage_calls: int = 0

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.session_start_monotonic

    def check_can_proceed(self, current_turn: int) -> None:
        """Verify turn, time, call, and budget limits before making a decision."""
        if current_turn >= self.settings.max_turns:
            raise SessionLimitReachedError(
                f"Reached maximum configured turns ({self.settings.max_turns})."
            )
        if self.elapsed_seconds >= self.settings.max_session_seconds:
            raise SessionLimitReachedError(
                f"Reached maximum session duration ({self.settings.max_session_seconds}s)."
            )
        if self.api_calls >= self.settings.max_api_calls:
            raise BudgetExceededError(
                f"Reached maximum API call limit ({self.settings.max_api_calls})."
            )
        if self.estimated_cost_usd >= self.settings.max_budget_usd:
            raise BudgetExceededError(
                f"Estimated API cost (${self.estimated_cost_usd:.4f}) reached budget limit "
                f"(${self.settings.max_budget_usd:.2f})."
            )
        if self.unknown_usage_calls >= 3:
            raise BudgetExceededError(
                "API token usage could not be estimated reliably for 3 consecutive calls; "
                "stopping safely per Section 12."
            )

    def record_api_call(
        self,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: float,
    ) -> None:
        """Update cumulative token usage and conservative USD cost estimate."""
        self.api_calls += 1
        self.total_latency_ms += latency_ms

        if prompt_tokens is None or completion_tokens is None:
            self.unknown_usage_calls += 1
            # Apply conservative fallback estimate (2500 input, 250 output tokens)
            p_tok = 2500
            c_tok = 250
        else:
            self.unknown_usage_calls = 0
            p_tok = int(prompt_tokens)
            c_tok = int(completion_tokens)

        self.prompt_tokens += p_tok
        self.completion_tokens += c_tok

        call_cost = (
            (p_tok / 1_000_000.0) * self.settings.estimated_input_cost_per_1m
            + (c_tok / 1_000_000.0) * self.settings.estimated_output_cost_per_1m
        )
        self.estimated_cost_usd += call_cost

    def call_with_backoff(self, func: Callable[[], T], sleep_fn: Callable[[float], None] = time.sleep) -> T:
        """Execute an API call with exponential backoff on rate limits and transient errors."""
        max_retries = self.settings.max_retries
        base_delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as exc:
                msg = str(exc).lower()
                is_retryable = any(
                    token in msg
                    for token in ("429", "rate limit", "timeout", "temporarily", "502", "503", "504")
                )
                if not is_retryable or attempt >= max_retries:
                    raise
                delay = base_delay * (2**attempt)
                sleep_fn(delay)

        raise RuntimeError("Exhausted retries in call_with_backoff")

    def get_stats(self) -> dict[str, Any]:
        avg_latency = (self.total_latency_ms / self.api_calls) if self.api_calls > 0 else 0.0
        return {
            "api_calls": self.api_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "budget_limit_usd": self.settings.max_budget_usd,
            "avg_latency_ms": round(avg_latency, 2),
            "elapsed_seconds": round(self.elapsed_seconds, 2),
        }
