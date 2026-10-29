"""Level 3 End-to-End Tests: Complete Observation -> Agent -> Action -> Game -> New Observation loop."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

try:
    from Xlib import X, display
except ImportError:
    X = None  # type: ignore
    display = None  # type: ignore

from rogue_agent.features.game_loop_cli.cli import main as cli_main
from rogue_agent.features.game_loop_cli.controller import AgentGameController
from rogue_agent.features.memory import BoundedAgentMemory
from rogue_agent.features.mistral_brain import BudgetAndRateGuard, DryRunGameplayAgent
from rogue_agent.features.steam_backend import SteamGameAdapter, X11WindowManager
from rogue_agent.features.telemetry_eval import SessionTelemetryCollector
from rogue_agent.features.terminal_backend import TerminalGameAdapter
from rogue_agent.shared.config import RogueAgentSettings


@pytest.mark.e2e
@pytest.mark.skipif(sys.platform == "win32", reason="Terminal Rogue POSIX PTY backend requires Linux / WSL")
def test_e2e_terminal_loop_multi_turn(tmp_path: Path) -> None:
    """Run a 6-turn autonomous loop on the real Terminal Rogue 5.4.4 PTY backend."""
    settings = RogueAgentSettings(
        ROGUE_MAX_TURNS=6,
        ROGUE_RUNS_DIR=str(tmp_path),
    )
    backend = TerminalGameAdapter(settings=settings)
    guard = BudgetAndRateGuard(settings=settings)
    agent = DryRunGameplayAgent(settings=settings)
    memory = BoundedAgentMemory()
    telemetry = SessionTelemetryCollector(base_runs_dir=tmp_path)

    controller = AgentGameController(
        backend=backend,
        agent=agent,
        memory=memory,
        telemetry=telemetry,
        guard=guard,
        dry_run=True,
    )
    summary = controller.run_session(quiet=True)

    assert summary["successful_game_start"] is True
    assert summary["backend"] == "terminal"
    assert summary["rogue_version"] == "rogue-5.4.4"
    assert summary["turns_survived"] == 6
    assert summary["valid_gameplay_actions"] == 6
    assert summary["invalid_gameplay_actions"] == 0
    assert Path(summary["session_dir"], "turns.jsonl").is_file()
    assert Path(summary["session_dir"], "summary.json").is_file()


@pytest.mark.e2e
@pytest.mark.skipif(sys.platform == "win32", reason="Terminal Rogue POSIX PTY backend requires Linux / WSL")
def test_cli_doctor_and_dry_run_terminal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CLI entry point (`rogue-agent --doctor` and `--backend terminal --dry-run`)."""
    monkeypatch.setenv("ROGUE_RUNS_DIR", str(tmp_path))
    assert cli_main(["--doctor"]) == 0
    assert cli_main(["--backend", "terminal", "--dry-run", "--max-turns", "4", "--quiet"]) == 0
    assert cli_main(["--benchmark-report"]) == 0


@pytest.mark.e2e
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Requires X11/Xwayland DISPLAY")
def test_e2e_steam_adapter_loop_with_x11_window(tmp_path: Path) -> None:
    """Run a 3-turn E2E loop through SteamGameAdapter against a live X11 game window."""
    test_tag = "ROGUE_E2E_STEAM_X11_WINDOW"
    dpy = display.Display()
    screen = dpy.screen()
    win = screen.root.create_window(
        120,
        120,
        320,
        200,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=screen.black_pixel,
        event_mask=X.ExposureMask | X.KeyPressMask | X.KeyReleaseMask | X.FocusChangeMask,
    )
    win.set_wm_name(test_tag)
    win.set_wm_class("dosbox", "DOSBox")
    win.map()
    win.set_input_focus(X.RevertToParent, X.CurrentTime)
    dpy.sync()
    time.sleep(0.15)

    settings = RogueAgentSettings(
        ROGUE_MAX_TURNS=3,
        ROGUE_RUNS_DIR=str(tmp_path),
    )
    wm = X11WindowManager(allow_test_window_tag=test_tag)
    backend = SteamGameAdapter(
        settings=settings,
        window_manager=wm,
        launch_if_missing=False,
    )
    guard = BudgetAndRateGuard(settings=settings)
    agent = DryRunGameplayAgent(settings=settings)
    memory = BoundedAgentMemory()
    telemetry = SessionTelemetryCollector(base_runs_dir=tmp_path)

    controller = AgentGameController(
        backend=backend,
        agent=agent,
        memory=memory,
        telemetry=telemetry,
        guard=guard,
        dry_run=True,
    )
    try:
        summary = controller.run_session(quiet=True)
        assert summary["successful_game_start"] is True
        assert summary["backend"] == "steam"
        assert summary["rogue_version"] == "epyx-1.49"
        assert summary["turns_survived"] == 3
        assert Path(summary["session_dir"], "frames", "turn_0001.png").is_file()
    finally:
        win.unmap()
        win.destroy()
        dpy.sync()
        dpy.close()
