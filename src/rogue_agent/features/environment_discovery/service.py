"""Environment discovery service probing OS, Steam, Terminal Rogue, and Mistral SDK."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
from pathlib import Path

from rogue_agent.features.environment_discovery.models import EnvironmentDiscoveryReport
from rogue_agent.shared.config import RogueAgentSettings


def discover_environment(settings: RogueAgentSettings | None = None) -> EnvironmentDiscoveryReport:
    """Inspect local OS, Steam Rogue (1443430), Terminal Rogue binary, and Mistral SDK."""
    cfg = settings or RogueAgentSettings()
    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    py_ver = platform.python_version()
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    x11_disp = os.environ.get("DISPLAY")

    steam_bin = shutil.which("steam")
    steam_installed = steam_bin is not None

    steam_dir = cfg.steam_install_dir
    rogue_exe = steam_dir / "c" / "ROGUE" / "ROGUE.EXE"
    dosbox_exe = steam_dir / "DOSBox.exe"
    steam_rogue_installed = steam_dir.is_dir() and rogue_exe.is_file()

    # Check terminal rogue binary (configured path or system PATH)
    term_path: Path | None = None
    if cfg.terminal_binary.is_file() and os.access(cfg.terminal_binary, os.X_OK):
        term_path = cfg.terminal_binary.resolve()
    else:
        which_rogue = shutil.which("rogue")
        if which_rogue:
            term_path = Path(which_rogue)

    mistral_sdk_ok = importlib.util.find_spec("mistralai") is not None
    api_key_ok = bool(cfg.mistral_api_key and cfg.mistral_api_key != "your_mistral_api_key_here")

    blockers: list[str] = []
    warnings: list[str] = []

    if not steam_rogue_installed:
        warnings.append(
            f"Steam Rogue (App ID {cfg.steam_app_id}) not found at {steam_dir}. "
            "Install via Steam before running '--backend steam'."
        )
    if term_path is None:
        warnings.append(
            f"Terminal Rogue binary not found at {cfg.terminal_binary}. "
            "Run './scripts/build_terminal_rogue.sh' to build Rogue 5.4.4."
        )
    if not api_key_ok:
        warnings.append(
            "MISTRAL_API_KEY is not configured in .env or environment. "
            "Dry-run mode (--dry-run) works without a key; live mistral-large-4 play requires it."
        )

    return EnvironmentDiscoveryReport(
        operating_system=os_info,
        python_version=py_ver,
        display_session_type=session_type,
        x11_display=x11_disp,
        steam_installed=steam_installed,
        steam_binary_path=steam_bin,
        steam_rogue_installed=steam_rogue_installed,
        steam_rogue_install_dir=str(steam_dir) if steam_rogue_installed else None,
        steam_rogue_executable=str(rogue_exe) if steam_rogue_installed and dosbox_exe.is_file() else None,
        terminal_rogue_available=term_path is not None,
        terminal_rogue_path=str(term_path) if term_path else None,
        mistral_sdk_available=mistral_sdk_ok,
        mistral_api_key_configured=api_key_ok,
        blockers=blockers,
        warnings=warnings,
    )
