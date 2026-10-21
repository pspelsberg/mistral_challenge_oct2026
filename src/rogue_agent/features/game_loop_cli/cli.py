"""Unified CLI entry point for Rogue Agent supporting both Steam and Terminal backends (Section 13)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console

from rogue_agent.features.environment_discovery import discover_environment
from rogue_agent.features.game_loop_cli.controller import AgentGameController
from rogue_agent.features.memory import BoundedAgentMemory
from rogue_agent.features.mistral_brain import (
    BudgetAndRateGuard,
    DryRunGameplayAgent,
    MistralGameplayAgent,
)
from rogue_agent.features.steam_backend import SteamGameAdapter
from rogue_agent.features.telemetry_eval import (
    SessionTelemetryCollector,
    aggregate_runs_by_version,
    export_session_gif,
)
from rogue_agent.features.terminal_backend import TerminalGameAdapter
from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.domain import BackendId
from rogue_agent.shared.ports import GameBackendPort, GameplayAgentPort


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rogue-agent",
        description="Dual-Backend Autonomous Rogue AI Harness powered by Mistral Large 4 (mistral-large-4).",
    )
    parser.add_argument(
        "--backend",
        choices=[BackendId.STEAM.value, BackendId.TERMINAL.value],
        default=None,
        help="Execution backend to run: 'steam' (Epyx Rogue 1.49) or 'terminal' (Rogue 5.4.4).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the complete observation-action loop using a local mock agent without billable API calls.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="Override maximum gameplay turns for this session.",
    )
    parser.add_argument(
        "--max-api-calls",
        type=int,
        default=None,
        help="Override maximum Mistral API calls for this session.",
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help="Override maximum estimated API budget in USD.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment discovery and print readiness report.",
    )
    parser.add_argument(
        "--benchmark-report",
        action="store_true",
        help="Print version-segregated evaluation report across recorded runs.",
    )
    parser.add_argument(
        "--export-gif",
        nargs="?",
        const="latest",
        default=None,
        help="Export a <2 min competition demo.gif from the latest (or specified) session directory.",
    )
    parser.add_argument(
        "--always-send-screenshot",
        action="store_true",
        help="Always attach the PNG screenshot in Steam mode in addition to the 80x25 ASCII grid.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-turn rich terminal panels.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    console = Console()

    settings = RogueAgentSettings()
    if args.max_turns is not None:
        settings.max_turns = args.max_turns
    if args.max_api_calls is not None:
        settings.max_api_calls = args.max_api_calls
    if args.max_budget_usd is not None:
        settings.max_budget_usd = args.max_budget_usd
    if args.always_send_screenshot:
        settings.steam_screenshot_backup_only = False

    if args.doctor:
        report = discover_environment(settings)
        console.print_json(data=report.model_dump(mode="json"))
        return 0

    if args.benchmark_report:
        agg = aggregate_runs_by_version(settings.runs_dir)
        console.print_json(data=agg)
        return 0

    if args.export_gif is not None:
        if args.export_gif == "latest":
            candidates = sorted(
                d for d in settings.runs_dir.iterdir() if d.is_dir() and (d / "frames").is_dir()
            )
            if not candidates:
                console.print("[bold red]No recorded runs with frames found.[/bold red]")
                return 1
            target_dir = candidates[-1]
        else:
            target_dir = Path(args.export_gif)
        gif_path = export_session_gif(target_dir)
        console.print_json(data={"exported_gif": str(gif_path), "session_dir": str(target_dir)})
        return 0

    if not args.backend:
        parser.error("the following arguments are required: --backend (unless --doctor or --benchmark-report is used)")

    backend_adapter: GameBackendPort
    if args.backend == BackendId.TERMINAL.value:
        backend_adapter = TerminalGameAdapter(settings=settings)
    else:
        backend_adapter = SteamGameAdapter(settings=settings)

    guard = BudgetAndRateGuard(settings=settings)
    agent: GameplayAgentPort
    if args.dry_run:
        agent = DryRunGameplayAgent(settings=settings)
    else:
        agent = MistralGameplayAgent(settings=settings, guard=guard)

    memory = BoundedAgentMemory(runs_dir=settings.runs_dir)
    telemetry = SessionTelemetryCollector(base_runs_dir=settings.runs_dir)

    controller = AgentGameController(
        backend=backend_adapter,
        agent=agent,
        memory=memory,
        telemetry=telemetry,
        guard=guard,
        dry_run=args.dry_run,
        console=console,
    )

    summary = controller.run_session(quiet=args.quiet)
    if args.quiet:
        print(json.dumps(summary))

    return 0 if summary.get("successful_game_start") else 1


if __name__ == "__main__":
    sys.exit(main())
