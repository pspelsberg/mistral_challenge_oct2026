"""Autonomous gameplay loop controller (Observation -> Memory -> Mistral -> Action -> Game)."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from rogue_agent.features.mistral_brain.resilience import (
    BudgetAndRateGuard,
    BudgetExceededError,
    SessionLimitReachedError,
)
from rogue_agent.shared.domain import (
    ActionExecutionResult,
    ActionType,
    GameAction,
    GameObservation,
    GameState,
)
from rogue_agent.shared.ports import (
    GameBackendPort,
    GameplayAgentPort,
    MemoryPort,
    TelemetryPort,
)


class AgentGameController:
    """Orchestrates the turn-by-turn loop across backend, memory, Mistral Large 4, and telemetry."""

    def __init__(
        self,
        backend: GameBackendPort,
        agent: GameplayAgentPort,
        memory: MemoryPort,
        telemetry: TelemetryPort,
        guard: BudgetAndRateGuard,
        dry_run: bool = False,
        console: Console | None = None,
        on_turn_callback: Callable[[int, GameObservation, GameAction, ActionExecutionResult], None]
        | None = None,
    ) -> None:
        self.backend = backend
        self.agent = agent
        self.memory = memory
        self.telemetry = telemetry
        self.guard = guard
        self.dry_run = dry_run
        self.console = console or Console()
        self.on_turn_callback = on_turn_callback
        self._stop_requested = False

    def request_emergency_stop(self) -> None:
        """Signal the controller to stop cleanly before the next action."""
        self._stop_requested = True

    def _render_turn_panel(
        self,
        turn: int,
        obs: GameObservation,
        action: GameAction,
        result: ActionExecutionResult,
        stats: dict[str, Any],
        error_msg: str | None = None,
    ) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()

        table.add_row("Backend / Version:", f"{obs.backend.value} ({obs.rogue_version})")
        table.add_row("Model ID:", str(stats.get("model_id", self.agent.model_id)))
        table.add_row("Turn / State:", f"{turn} / {result.state_after.value}")
        pos = obs.inferred_metadata.get("player_position")
        needs_bkp = obs.inferred_metadata.get("needs_screenshot_backup", False)
        bkp_reason = obs.inferred_metadata.get("backup_reason")
        if obs.backend.value == "steam":
            perc_str = (
                f"80x25 ASCII Grid + Backup PNG ({bkp_reason})"
                if needs_bkp
                else "80x25 ASCII Grid Only (0 image tokens)"
            )
        else:
            perc_str = "80x24 PTY ASCII Grid (0 image tokens)"
        if pos is not None:
            perc_str += f" | @={pos}"
        table.add_row("Perception Mode:", perc_str)
        table.add_row("Agent Objective:", action.objective)
        act_str = (
            f"{action.action_type.value}"
            + (f" [{action.direction.value}]" if action.direction else "")
            + (f" (steps={result.steps_completed}/{result.steps_requested})" if result.steps_requested > 1 else "")
            + (f" (item={action.item_key})" if action.item_key else "")
        )
        if result.interrupted_early:
            act_str += f" [yellow](interrupted: {result.interrupt_reason})[/yellow]"
        table.add_row("Last Action:", f"{act_str} -> keys={result.keys_sent}")
        if obs.recent_messages:
            table.add_row("Game Messages:", " / ".join(obs.recent_messages))
        table.add_row("Decision Summary:", action.decision_summary)
        table.add_row(
            "API Usage:",
            f"calls={stats.get('api_calls', 0)} | tokens={stats.get('total_tokens', 0)} | "
            f"est_cost=${stats.get('estimated_cost_usd', 0.0):.4f}",
        )
        if error_msg or result.error_message:
            table.add_row("Runtime Error:", f"[bold red]{error_msg or result.error_message}[/bold red]")

        self.console.print(
            Panel(table, title=f"[bold green]Rogue Agent — Turn {turn}[/bold green]", expand=False)
        )

    def _select_zero_token_startup_action(self, obs: GameObservation) -> GameAction | None:
        """Return a deterministic 0-token action for non-gameplay startup/pagination screens."""
        if obs.game_state == GameState.START_MENU:
            return GameAction(
                action_type=ActionType.ACKNOWLEDGE_PROMPT,
                decision_summary="[0-Token UI Bypass] Advance title screen",
                objective="Enter dungeon",
                confidence=1.0,
            )
        if obs.game_state == GameState.MORE_PROMPT:
            return GameAction(
                action_type=ActionType.ACKNOWLEDGE_PROMPT,
                decision_summary="[0-Token UI Bypass] Acknowledge --More-- message prompt",
                objective="Continue gameplay",
                confidence=1.0,
            )
        if obs.game_state == GameState.CHARACTER_NAME_ENTRY:
            return GameAction(
                action_type=ActionType.ENTER_NAME,
                text_input="LeChonk",
                decision_summary="[0-Token UI Bypass] Enter character name LeChonk",
                objective="Enter dungeon",
                confidence=1.0,
            )
        return None

    def run_session(self, quiet: bool = False) -> dict[str, Any]:
        """Run a full gameplay session until game-over, limit reached, or emergency stop."""
        self.memory.reset()
        obs: GameObservation | None = None
        termination_reason = "completed"

        try:
            obs = self.backend.start()
            self.telemetry.start_session(
                backend=obs.backend.value,
                rogue_version=obs.rogue_version,
                model_id=self.agent.model_id,
                dry_run=self.dry_run,
            )

            turn = 0
            while not self._stop_requested:
                if obs.game_state in (GameState.GAME_OVER, GameState.VICTORY):
                    termination_reason = f"terminal_state:{obs.game_state.value}"
                    break

                self.guard.check_can_proceed(turn)
                turn += 1

                mem_summary = self.memory.build_prompt_summary(obs)
                mem_snap = self.memory.get_snapshot()
                objective = str(mem_snap.get("current_objective", "Explore and survive"))

                t0 = time.monotonic()
                zero_token_action = self._select_zero_token_startup_action(obs)
                if zero_token_action is not None:
                    action = zero_token_action
                else:
                    action = self.agent.decide_action(
                        observation=obs,
                        memory_summary=mem_summary,
                        current_objective=objective,
                    )
                decision_latency_ms = (time.monotonic() - t0) * 1000.0

                exec_result = self.backend.execute_action(action)
                obs_after = self.backend.observe()

                self.memory.record_turn(
                    turn_index=turn,
                    obs_before=obs,
                    action=action,
                    result=exec_result,
                    obs_after=obs_after,
                )

                stats = self.agent.get_usage_stats()
                self.telemetry.log_turn(
                    turn_index=turn,
                    observation=obs_after,
                    action=action,
                    execution_result=exec_result,
                    agent_stats=stats,
                    latency_ms=decision_latency_ms,
                )

                if not quiet:
                    self._render_turn_panel(turn, obs_after, action, exec_result, stats)

                if self.on_turn_callback:
                    self.on_turn_callback(turn, obs_after, action, exec_result)

                if exec_result.state_after == GameState.PAUSED:
                    termination_reason = f"paused_on_safety_guard:{exec_result.error_message}"
                    break

                obs = obs_after

        except KeyboardInterrupt:
            termination_reason = "emergency_stop_keyboard_interrupt"
        except (BudgetExceededError, SessionLimitReachedError) as exc:
            termination_reason = f"limit_reached:{exc}"
        except Exception as exc:
            termination_reason = f"paused_on_runtime_error:{exc}"
        finally:
            self.backend.close()

        final_stats = self.agent.get_usage_stats()
        if self.telemetry.session_dir is None:
            self.telemetry.start_session(
                backend=obs.backend.value if obs else "unknown",
                rogue_version=self.backend.rogue_version,
                model_id=self.agent.model_id,
                dry_run=self.dry_run,
            )

        summary = self.telemetry.finish_session(
            final_observation=obs,
            termination_reason=termination_reason,
            agent_stats=final_stats,
        )

        playbook_md_str = ""
        playbook_mgr = getattr(self.memory, "playbook", None)
        if playbook_mgr is not None and summary.get("session_dir"):
            try:
                pb_data = playbook_mgr.record_completed_session(
                    Path(str(summary["session_dir"])),
                    str(summary.get("rogue_version", self.backend.rogue_version)),
                )
                summary["playbook_markdown"] = str(playbook_mgr.markdown_path)
                summary["playbook_sessions_analyzed"] = pb_data.sessions_analyzed
                playbook_md_str = (
                    f"\n[bold]Recursive Playbook:[/bold] {playbook_mgr.markdown_path} "
                    f"({pb_data.sessions_analyzed} runs learned)"
                )
            except Exception:
                pass

        if not quiet:
            self.console.print(
                Panel.fit(
                    f"[bold]Backend:[/bold] {summary['backend']} ({summary['rogue_version']})\n"
                    f"[bold]Model:[/bold] {summary['model_id']}\n"
                    f"[bold]Turns Survived:[/bold] {summary['turns_survived']}\n"
                    f"[bold]Max Depth Reached:[/bold] {summary['max_dungeon_depth_reached']}\n"
                    f"[bold]Valid / Invalid Actions:[/bold] {summary['valid_gameplay_actions']} / "
                    f"{summary['invalid_gameplay_actions']} ({summary['invalid_action_percentage']}%)\n"
                    f"[bold]Estimated Cost:[/bold] ${summary['estimated_cost_usd']:.4f}\n"
                    f"[bold]Termination Reason:[/bold] {summary['termination_reason']}\n"
                    f"[bold]Artifacts Saved To:[/bold] {summary['session_dir']}"
                    f"{playbook_md_str}",
                    title="[bold yellow]Session Summary[/bold yellow]",
                )
            )

        return summary
