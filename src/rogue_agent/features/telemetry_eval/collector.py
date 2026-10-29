"""Session telemetry collector writing JSONL logs, frames, and summary metrics (Section 15)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rogue_agent.shared.domain import (
    ActionExecutionResult,
    GameAction,
    GameObservation,
    GameState,
)

_SAFE_SEGMENT_RE = re.compile(r"[^a-zA-Z0-9._-]")


class SessionTelemetryCollector:
    """Persists turn-by-turn evidence and computes reproducible session metrics."""

    def __init__(self, base_runs_dir: Path = Path("./runs")) -> None:
        self.base_runs_dir = base_runs_dir
        self.session_dir: Path | None = None
        self.frames_dir: Path | None = None
        self.turns_file: Path | None = None

        self.backend: str = ""
        self.rogue_version: str = ""
        self.model_id: str = ""
        self.dry_run: bool = False
        self.started_at: str = ""

        self.turns_logged: int = 0
        self.valid_actions: int = 0
        self.invalid_actions: int = 0
        self.max_depth: int = 1
        self.max_gold: int = 0
        self.monsters_defeated: int = 0
        self.human_interventions: int = 0
        self._observed_doors_by_level: dict[int, set[tuple[int, int]]] = {}
        self._last_death_message: str | None = None

    @staticmethod
    def _sanitize_segment(value: str, fallback: str = "unknown") -> str:
        cleaned = _SAFE_SEGMENT_RE.sub("_", value.strip()).strip("._")
        return cleaned or fallback

    def start_session(
        self,
        backend: str,
        rogue_version: str,
        model_id: str,
        dry_run: bool = False,
    ) -> str:
        """Create a dedicated timestamped run directory with path-traversal protection."""
        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%d_%H%M%S_%f")
        mode_tag = "dryrun" if dry_run else "live"
        safe_backend = self._sanitize_segment(backend)
        safe_version = self._sanitize_segment(rogue_version)
        folder_name = f"{ts}_{safe_backend}_{safe_version}_{mode_tag}"

        base_resolved = self.base_runs_dir.resolve()
        candidate_dir = (base_resolved / folder_name).resolve()
        if not candidate_dir.is_relative_to(base_resolved):
            raise ValueError(f"Unsafe session directory path: {candidate_dir}")

        self.session_dir = candidate_dir
        self.frames_dir = self.session_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.turns_file = self.session_dir / "turns.jsonl"

        self.backend = backend
        self.rogue_version = rogue_version
        self.model_id = model_id
        self.dry_run = dry_run
        self.started_at = now.isoformat()
        self.turns_logged = 0
        self.valid_actions = 0
        self.invalid_actions = 0
        self.max_depth = 1
        self.max_gold = 0
        self.monsters_defeated = 0
        self.human_interventions = 0
        self._observed_doors_by_level.clear()
        self._last_death_message = None

        return str(self.session_dir)

    def log_turn(
        self,
        turn_index: int,
        observation: GameObservation,
        action: GameAction,
        execution_result: ActionExecutionResult,
        agent_stats: dict[str, Any],
        latency_ms: float,
    ) -> None:
        """Append turn telemetry to turns.jsonl and save the visible frame(s)."""
        if self.session_dir is None or self.turns_file is None or self.frames_dir is None:
            raise RuntimeError("Telemetry session has not been started.")

        self.turns_logged += 1
        if execution_result.success:
            self.valid_actions += 1
        else:
            self.invalid_actions += 1

        lvl = observation.visible_status.dungeon_level or 1
        if lvl > self.max_depth:
            self.max_depth = lvl

        gold = observation.visible_status.gold
        if gold and gold > self.max_gold:
            self.max_gold = gold

        doors = observation.inferred_metadata.get("door_positions")
        if isinstance(doors, list):
            level_doors = self._observed_doors_by_level.setdefault(lvl, set())
            for d in doors:
                if isinstance(d, (tuple, list)) and len(d) == 2:
                    level_doors.add((int(d[0]), int(d[1])))

        for msg in observation.recent_messages:
            low = msg.lower()
            if any(tok in low for tok in ("defeated", "killed the", "destroyed the")):
                self.monsters_defeated += 1
            if "killed by" in low or "died" in low or "quit" in low:
                self._last_death_message = msg

        frame_file: str | None = None
        ascii_file: str | None = None
        if execution_result.intermediate_screenshot_bytes is not None:
            menu_png_path = self.frames_dir / f"turn_{turn_index:04d}_menu.png"
            menu_png_path.write_bytes(execution_result.intermediate_screenshot_bytes)
        if observation.screenshot_png_bytes is not None:
            png_path = self.frames_dir / f"turn_{turn_index:04d}.png"
            png_path.write_bytes(observation.screenshot_png_bytes)
            frame_file = str(png_path.relative_to(self.session_dir))
        if observation.screen_text is not None:
            txt_path = self.frames_dir / f"turn_{turn_index:04d}.txt"
            txt_path.write_text(observation.screen_text, encoding="utf-8")
            ascii_file = str(txt_path.relative_to(self.session_dir))
            if frame_file is None:
                frame_file = ascii_file

        record = {
            "turn": turn_index,
            "timestamp": observation.timestamp.isoformat(),
            "backend": self.backend,
            "rogue_version": self.rogue_version,
            "game_state_before": execution_result.state_before.value,
            "game_state_after": execution_result.state_after.value,
            "visible_status": observation.visible_status.model_dump(),
            "recent_messages": observation.recent_messages,
            "action": action.model_dump(mode="json"),
            "keys_sent": execution_result.keys_sent,
            "steps_requested": execution_result.steps_requested,
            "steps_completed": execution_result.steps_completed,
            "interrupted_early": execution_result.interrupted_early,
            "interrupt_reason": execution_result.interrupt_reason,
            "execution_success": execution_result.success,
            "error_message": execution_result.error_message,
            "latency_ms": round(latency_ms, 2),
            "frame_artifact": frame_file,
            "ascii_artifact": ascii_file,
            "agent_stats": agent_stats,
        }

        with self.turns_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def finish_session(
        self,
        final_observation: GameObservation | None,
        termination_reason: str,
        agent_stats: dict[str, Any],
    ) -> dict[str, Any]:
        """Write summary.json and return the complete session evaluation dictionary."""
        if self.session_dir is None:
            raise RuntimeError("Telemetry session has not been started.")

        if final_observation is not None:
            lvl = final_observation.visible_status.dungeon_level
            if lvl and lvl > self.max_depth:
                self.max_depth = lvl
            gold = final_observation.visible_status.gold
            if gold and gold > self.max_gold:
                self.max_gold = gold

        total_actions = self.valid_actions + self.invalid_actions
        invalid_pct = (
            round((self.invalid_actions / total_actions) * 100.0, 2)
            if total_actions > 0
            else 0.0
        )

        # Estimate rooms discovered from distinct levels visited + doorway clusters
        total_doors_seen = sum(len(ds) for ds in self._observed_doors_by_level.values())
        rooms_discovered = max(1, self.max_depth + (total_doors_seen // 2))

        death_condition = "alive_or_session_limit"
        if final_observation and final_observation.game_state == GameState.GAME_OVER:
            death_condition = self._last_death_message or "game_over"
        elif "terminal_state:GAME_OVER" in termination_reason:
            death_condition = self._last_death_message or "game_over"

        summary = {
            "backend": self.backend,
            "rogue_version": self.rogue_version,
            "model_id": self.model_id,
            "dry_run": self.dry_run,
            "started_at": self.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "successful_game_start": self.turns_logged > 0 or final_observation is not None,
            "turns_survived": self.turns_logged,
            "valid_gameplay_actions": self.valid_actions,
            "invalid_gameplay_actions": self.invalid_actions,
            "invalid_action_percentage": invalid_pct,
            "max_dungeon_depth_reached": self.max_depth,
            "rooms_discovered": rooms_discovered,
            "monsters_defeated": self.monsters_defeated,
            "max_gold_collected": self.max_gold,
            "death_condition": death_condition,
            "human_interventions": self.human_interventions,
            "termination_reason": termination_reason,
            "final_game_state": final_observation.game_state.value if final_observation else "UNKNOWN",
            "api_calls": agent_stats.get("api_calls", 0),
            "total_tokens": agent_stats.get("total_tokens", 0),
            "estimated_cost_usd": agent_stats.get("estimated_cost_usd", 0.0),
            "avg_latency_ms": agent_stats.get("avg_latency_ms", 0.0),
            "session_dir": str(self.session_dir),
        }

        summary_path = self.session_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
