"""SteamGameAdapter implementing GameBackendPort for Steam Epyx Rogue v1.49 (Section 6)."""

from __future__ import annotations

import ctypes
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rogue_agent.features.steam_backend.capture import (
    CropMargins,
    capture_window_client_area,
)
from rogue_agent.features.steam_backend.input_injector import X11KeyInjector
from rogue_agent.features.steam_backend.visual_state import analyze_steam_screenshot
from rogue_agent.features.steam_backend.window_manager import (
    WindowFocusLostError,
    WindowInfo,
    WindowNotFoundError,
    X11WindowManager,
)
from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.controls import ControlValidationError, Epyx149ControlProfile
from rogue_agent.shared.controls.base import SAFE_NAME_PATTERN
from rogue_agent.shared.domain import (
    MENU_SELECTION_ACTIONS,
    REPEATABLE_HORIZON_ACTIONS,
    ActionExecutionResult,
    ActionType,
    BackendId,
    GameAction,
    GameObservation,
    GameState,
)


class SteamGameAdapter:
    """Backend A adapter connecting to Steam Epyx Rogue v1.49 (App ID 1443430)."""

    def __init__(
        self,
        settings: RogueAgentSettings | None = None,
        control_profile: Epyx149ControlProfile | None = None,
        window_manager: X11WindowManager | None = None,
        crop_margins: CropMargins | None = None,
        launch_if_missing: bool = True,
        launch_timeout_seconds: float = 25.0,
        auto_advance_startup: bool = True,
    ) -> None:
        self.settings = settings or RogueAgentSettings()
        self.controls = control_profile or Epyx149ControlProfile()
        self.window_manager = window_manager or X11WindowManager()
        self.injector = X11KeyInjector(self.window_manager)
        self.crop_margins = crop_margins or CropMargins()
        self.launch_if_missing = launch_if_missing
        self.launch_timeout_seconds = launch_timeout_seconds
        self.auto_advance_startup = auto_advance_startup

        self._window_info: WindowInfo | None = None
        self._last_state: GameState = GameState.NOT_STARTED
        self._last_action_result: str | None = None
        self._last_frame_hash: str | None = None
        self._frame_hash_before_action: str | None = None
        self._last_action_was_movement: bool = False
        self._last_obs: GameObservation | None = None
        self._rooms_seen: set[tuple[int, int, int, int]] = set()
        self._monsters_seen_count: int = 0
        self._items_seen_count: int = 0
        self._stairs_seen: bool = False
        self._current_level: int = 1

    @property
    def rogue_version(self) -> str:
        return self.controls.version_name

    def _verify_steam_prerequisites(self) -> None:
        rogue_exe = self.settings.steam_install_dir / "c" / "ROGUE" / "ROGUE.EXE"
        if not rogue_exe.is_file():
            raise FileNotFoundError(
                f"Steam Epyx Rogue 1.49 not found at {rogue_exe}. "
                f"Please install App ID {self.settings.steam_app_id} in Steam."
            )

    def _launch_via_steam(self) -> None:
        steam_bin = shutil.which("steam") or shutil.which("steam.exe")
        if not steam_bin:
            default_win_steam = Path("C:/Program Files (x86)/Steam/steam.exe")
            if default_win_steam.is_file():
                steam_bin = str(default_win_steam)
        if not steam_bin:
            raise RuntimeError(
                "Steam executable not found in PATH or standard installation directory."
            )

        kwargs: dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True

        subprocess.Popen(
            [str(steam_bin), "-applaunch", str(self.settings.steam_app_id)],
            **kwargs,
        )

    @staticmethod
    def _spawn_direct_dosbox(dosbox_path: Path, install_dir: Path) -> None:
        """Spawn DOSBox directly on the interactive desktop when Steam launch is delayed."""
        if sys.platform == "win32":
            try:
                kernel32 = ctypes.windll.kernel32

                class _STARTUPINFO(ctypes.Structure):
                    _fields_ = [
                        ("cb", ctypes.c_ulong),
                        ("lpReserved", ctypes.c_wchar_p),
                        ("lpDesktop", ctypes.c_wchar_p),
                        ("lpTitle", ctypes.c_wchar_p),
                        ("dwX", ctypes.c_ulong),
                        ("dwY", ctypes.c_ulong),
                        ("dwXSize", ctypes.c_ulong),
                        ("dwYSize", ctypes.c_ulong),
                        ("dwXCountChars", ctypes.c_ulong),
                        ("dwYCountChars", ctypes.c_ulong),
                        ("dwFillAttribute", ctypes.c_ulong),
                        ("dwFlags", ctypes.c_ulong),
                        ("wShowWindow", ctypes.c_ushort),
                        ("cbReserved2", ctypes.c_ushort),
                        ("lpReserved2", ctypes.c_char_p),
                        ("hStdInput", ctypes.c_void_p),
                        ("hStdOutput", ctypes.c_void_p),
                        ("hStdError", ctypes.c_void_p),
                    ]

                class _PROCESS_INFORMATION(ctypes.Structure):
                    _fields_ = [
                        ("hProcess", ctypes.c_void_p),
                        ("hThread", ctypes.c_void_p),
                        ("dwProcessId", ctypes.c_ulong),
                        ("dwThreadId", ctypes.c_ulong),
                    ]

                si = _STARTUPINFO()
                si.cb = ctypes.sizeof(_STARTUPINFO)
                si.lpDesktop = "Default"
                pi = _PROCESS_INFORMATION()
                cmd_buf = ctypes.create_unicode_buffer(f'"{dosbox_path}" -conf rogue.conf')
                ok = kernel32.CreateProcessW(
                    str(dosbox_path),
                    cmd_buf,
                    None,
                    None,
                    False,
                    0,
                    None,
                    str(install_dir),
                    ctypes.byref(si),
                    ctypes.byref(pi),
                )
                if ok:
                    if pi.hThread:
                        kernel32.CloseHandle(pi.hThread)
                    if pi.hProcess:
                        kernel32.CloseHandle(pi.hProcess)
                    return
            except Exception:
                pass

        subprocess.Popen(
            [str(dosbox_path), "-conf", "rogue.conf"],
            cwd=str(install_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _advance_startup_screens_zero_token(self, obs: GameObservation) -> GameObservation:
        """Automatically advance Epyx 1.49 Title Screen and Name Entry with 0 API calls."""
        raw_name = (self.settings.player_name or "LeChonk").strip()[:12]
        if not SAFE_NAME_PATTERN.match(raw_name):
            raw_name = "LeChonk"

        for _ in range(10):
            if obs.game_state == GameState.UNKNOWN:
                time.sleep(0.5)
                obs = self.observe()
            elif obs.game_state == GameState.START_MENU and self._window_info is not None:
                self.injector.send_key_sequence(self._window_info.window_id, ["space"])
                time.sleep(1.2)
                obs = self.observe()
            elif obs.game_state == GameState.CHARACTER_NAME_ENTRY and self._window_info is not None:
                name_keys = [*list(raw_name), "Return"]
                self.injector.send_key_sequence(self._window_info.window_id, name_keys)
                # Wait for Epyx yellow-green curtain transition to finish into dungeon
                time.sleep(2.5)
                obs = self.observe()
                curtain_deadline = time.monotonic() + 3.0
                while (
                    obs.game_state not in (GameState.PLAYING, GameState.GAME_OVER)
                    and time.monotonic() < curtain_deadline
                ):
                    time.sleep(0.3)
                    obs = self.observe()
            else:
                break
        return obs

    def start(self) -> GameObservation:
        """Connect to an already-running Steam Rogue window or launch via Steam App ID 1443430."""
        win = self.window_manager.find_game_window()
        if win is None:
            if not self.launch_if_missing:
                raise WindowNotFoundError(
                    "No running Steam Rogue / DOSBox window found on display."
                )
            self._verify_steam_prerequisites()
            self._launch_via_steam()

            deadline = time.monotonic() + self.launch_timeout_seconds
            attempted_direct = False
            while time.monotonic() < deadline:
                win = self.window_manager.find_game_window()
                if win is not None:
                    break
                if not attempted_direct and time.monotonic() > (
                    deadline - self.launch_timeout_seconds * 0.6
                ):
                    dosbox_path = self.settings.steam_install_dir / "DOSBox.exe"
                    if dosbox_path.is_file():
                        self._spawn_direct_dosbox(dosbox_path, self.settings.steam_install_dir)
                        attempted_direct = True
                time.sleep(0.5)

            if win is None:
                raise WindowNotFoundError(
                    f"Steam Rogue (App ID {self.settings.steam_app_id}) window did not appear "
                    f"within {self.launch_timeout_seconds}s. Check if a Steam dialog is waiting."
                )

        self._window_info = self.window_manager.ensure_verified_focus(win.window_id)
        self._last_action_result = (
            f"Connected to verified window {hex(self._window_info.window_id)} "
            f"({self._window_info.title!r})"
        )
        # Wait up to 5.0s for DOSBox to finish initial boot into ROGUE.EXE
        boot_deadline = time.monotonic() + 5.0
        obs = self.observe()
        while obs.game_state == GameState.UNKNOWN and time.monotonic() < boot_deadline:
            time.sleep(0.25)
            obs = self.observe()

        if self.auto_advance_startup:
            obs = self._advance_startup_screens_zero_token(obs)
        return obs

    def observe(self, auto_drain_more: bool = True) -> GameObservation:
        """Capture the verified client-area screenshot and construct a GameObservation."""
        win = self.window_manager.find_game_window()
        if win is None:
            self._last_state = GameState.GAME_OVER
            return GameObservation(
                backend=BackendId.STEAM,
                rogue_version=self.rogue_version,
                game_state=GameState.GAME_OVER,
                previous_action_result="Steam Rogue window closed or exited.",
                observation_uncertainty=0.0,
            )

        self._window_info = win
        image, png_bytes = capture_window_client_area(
            self.window_manager,
            win,
            crop_margins=self.crop_margins,
        )
        frame_hash = hashlib.sha256(png_bytes).hexdigest()[:16]
        ref_hash = (
            self._frame_hash_before_action
            if self._frame_hash_before_action is not None
            else self._last_frame_hash
        )
        frame_changed = ref_hash is None or frame_hash != ref_hash
        self._last_frame_hash = frame_hash

        analysis = analyze_steam_screenshot(image)

        drained_count = 0
        max_more_pages = 8
        while (
            auto_drain_more
            and analysis.inferred_state == GameState.MORE_PROMPT
            and drained_count < max_more_pages
        ):
            drained_count += 1
            self.injector.send_key_sequence(win.window_id, ["space"])
            time.sleep(0.08)
            try:
                image, png_bytes = capture_window_client_area(
                    self.window_manager,
                    win,
                    crop_margins=self.crop_margins,
                )
                analysis = analyze_steam_screenshot(image)
            except Exception:
                break

        self._last_state = analysis.inferred_state

        metadata = {
            **analysis.metrics,
            "window_id": hex(win.window_id),
            "window_title": win.title,
            "frame_hash": frame_hash,
            "frame_changed": frame_changed,
            "png_bytes_size": len(png_bytes),
        }
        room_bbox = analysis.metrics.get("room_bbox")
        if room_bbox is not None and room_bbox not in self._rooms_seen:
            self._rooms_seen.add(room_bbox)
            metadata["needs_screenshot_backup"] = True
            metadata["backup_reason"] = f"new_room_discovered:bbox={room_bbox}"

        curr_monsters = analysis.metrics.get("visible_monsters") or []
        num_monsters = len(curr_monsters) if isinstance(curr_monsters, list) else 0
        if self._monsters_seen_count > 0 and num_monsters < self._monsters_seen_count:
            metadata["needs_screenshot_backup"] = True
            if not metadata.get("backup_reason"):
                metadata["backup_reason"] = "monster_defeated_or_cleared"
        self._monsters_seen_count = num_monsters

        curr_items = analysis.metrics.get("visible_items") or []
        num_items = len(curr_items) if isinstance(curr_items, list) else 0
        if self._items_seen_count > 0 and num_items < self._items_seen_count:
            metadata["needs_screenshot_backup"] = True
            if not metadata.get("backup_reason"):
                metadata["backup_reason"] = "item_collected_or_cleared"
        self._items_seen_count = num_items

        stairs_pos = analysis.metrics.get("stairs_positions") or []
        if stairs_pos and not self._stairs_seen:
            self._stairs_seen = True
            metadata["needs_screenshot_backup"] = True
            if not metadata.get("backup_reason"):
                metadata["backup_reason"] = f"staircase_discovered:pos={stairs_pos}"

        if self._last_action_was_movement and not frame_changed:
            metadata["needs_screenshot_backup"] = True
            if not metadata.get("backup_reason"):
                metadata["backup_reason"] = "previous_move_produced_no_frame_change"

        obs = GameObservation(
            backend=BackendId.STEAM,
            rogue_version=self.rogue_version,
            screen_text=analysis.ascii_grid_text,
            screenshot_png_bytes=png_bytes,
            game_state=analysis.inferred_state,
            previous_action_result=self._last_action_result,
            observation_uncertainty=analysis.uncertainty,
            inferred_metadata=metadata,
        )
        self._last_obs = obs
        return obs

    def detect_game_state(self) -> GameState:
        return self.observe().game_state

    def execute_action(self, action: GameAction) -> ActionExecutionResult:
        """Validate window focus, translate action, and execute with interruptible short horizon."""
        state_before = self._last_state
        win = self.window_manager.find_game_window() or self._window_info
        if win is None:
            return ActionExecutionResult(
                success=False,
                keys_sent=[],
                steps_requested=action.steps,
                steps_completed=0,
                summary="Game window missing; stopped safely.",
                error_message="Game window not found.",
                state_before=state_before,
                state_after=GameState.PAUSED,
            )

        try:
            single_step_keys = self.controls.translate_action(action, state_before)
        except ControlValidationError as exc:
            self._last_action_result = f"Control validation error: {exc}"
            return ActionExecutionResult(
                success=False,
                keys_sent=[],
                steps_requested=action.steps,
                steps_completed=0,
                summary=self._last_action_result,
                error_message=str(exc),
                state_before=state_before,
                state_after=state_before,
            )

        requested_steps = (
            action.steps
            if action.action_type in REPEATABLE_HORIZON_ACTIONS
            else 1
        )
        self._frame_hash_before_action = self._last_frame_hash
        self._last_action_was_movement = action.action_type in (
            ActionType.MOVE,
            ActionType.FAST_MOVE,
            ActionType.DESCEND_STAIRS,
            ActionType.ASCEND_STAIRS,
        )
        all_keys_sent: list[str] = []
        steps_completed = 0
        interrupted_early = False
        interrupt_reason: str | None = None
        obs_after: GameObservation | None = None

        menu_wait_seconds = float(getattr(self.settings, "menu_wait_seconds", 1.5))
        is_menu_selection_action = (
            action.action_type in MENU_SELECTION_ACTIONS
            and action.item_key is not None
        )
        intermediate_menu_png: bytes | None = None

        for step_idx in range(requested_steps):
            step_prev_hash = self._last_frame_hash
            try:
                if is_menu_selection_action and len(single_step_keys) >= 2:
                    prompt_keys = single_step_keys[:-1]
                    selection_key = single_step_keys[-1:]
                    self.injector.send_key_sequence(win.window_id, prompt_keys)
                    if menu_wait_seconds > 0:
                        time.sleep(menu_wait_seconds)
                    try:
                        _, intermediate_menu_png = capture_window_client_area(
                            self.window_manager,
                            win,
                            crop_margins=self.crop_margins,
                        )
                    except Exception:
                        intermediate_menu_png = None
                    self.injector.send_key_sequence(win.window_id, selection_key)
                elif action.action_type == ActionType.OPEN_INVENTORY:
                    self.injector.send_key_sequence(win.window_id, single_step_keys)
                    if menu_wait_seconds > 0:
                        time.sleep(menu_wait_seconds)
                    try:
                        _, intermediate_menu_png = capture_window_client_area(
                            self.window_manager,
                            win,
                            crop_margins=self.crop_margins,
                        )
                    except Exception:
                        intermediate_menu_png = None
                else:
                    if (
                        state_before in (
                            GameState.INVENTORY,
                            GameState.ITEM_SELECTION,
                            GameState.MORE_PROMPT,
                        )
                        and menu_wait_seconds > 0
                    ):
                        time.sleep(menu_wait_seconds)
                    self.injector.send_key_sequence(win.window_id, single_step_keys)
            except WindowFocusLostError as exc:
                self._last_state = GameState.PAUSED
                self._last_action_result = f"Safety stop: {exc}"
                return ActionExecutionResult(
                    success=False,
                    keys_sent=all_keys_sent,
                    steps_requested=requested_steps,
                    steps_completed=steps_completed,
                    summary=self._last_action_result,
                    error_message=str(exc),
                    state_before=state_before,
                    state_after=GameState.PAUSED,
                    intermediate_screenshot_bytes=intermediate_menu_png,
                )

            all_keys_sent.extend(single_step_keys)
            steps_completed += 1

            if action.action_type == ActionType.ENTER_NAME or state_before in (
                GameState.START_MENU,
                GameState.CHARACTER_NAME_ENTRY,
            ):
                time.sleep(1.8)
            else:
                time.sleep(0.14)

            obs_after = self.observe()
            step_changed = (
                step_prev_hash is None
                or obs_after.inferred_metadata.get("frame_hash") != step_prev_hash
            )
            top_msg_activity = float(
                obs_after.inferred_metadata.get("top_message_bar_activity", 0.0)
            )

            if step_idx + 1 < requested_steps:
                if obs_after.game_state != GameState.PLAYING:
                    interrupted_early = True
                    interrupt_reason = f"ui_state_changed:{obs_after.game_state.value}"
                    break
                if action.action_type == ActionType.MOVE and not step_changed:
                    interrupted_early = True
                    interrupt_reason = "movement_blocked_no_frame_change"
                    break
                if top_msg_activity > 0.015:
                    interrupted_early = True
                    interrupt_reason = f"top_message_detected:{top_msg_activity}"
                    break
                if obs_after.inferred_metadata.get("visible_monsters"):
                    interrupted_early = True
                    interrupt_reason = "monster_detected_in_ascii_grid"
                    break
                if (
                    action.action_type == ActionType.MOVE
                    and action.direction is not None
                    and obs_after.inferred_metadata.get("player_position") is not None
                ):
                    walkable = obs_after.inferred_metadata.get("walkable_directions", [])
                    if isinstance(walkable, list) and not action.direction.matches_walkable(walkable):
                        adj = obs_after.inferred_metadata.get("adjacent_tiles", {}).get(
                            action.direction.short_code, "?"
                        )
                        interrupted_early = True
                        interrupt_reason = f"wall_ahead_in_ascii_grid:{adj!r}"
                        break

        assert obs_after is not None
        changed = obs_after.inferred_metadata.get("frame_changed", False)
        int_suffix = f" [Interrupted: {interrupt_reason}]" if interrupted_early else ""
        self._last_action_result = (
            f"Injected {all_keys_sent!r} for {action.action_type.value} "
            f"({steps_completed}/{requested_steps} steps, frame_changed={changed}){int_suffix}"
        )
        return ActionExecutionResult(
            success=True,
            keys_sent=all_keys_sent,
            steps_requested=requested_steps,
            steps_completed=steps_completed,
            interrupted_early=interrupted_early,
            interrupt_reason=interrupt_reason,
            summary=self._last_action_result,
            state_before=state_before,
            state_after=obs_after.game_state,
            intermediate_screenshot_bytes=intermediate_menu_png,
        )

    def reset(self) -> GameObservation:
        """Reconnect and observe current Steam game window."""
        return self.start()

    def close(self) -> None:
        """Detach X11 connection without forcibly killing the user's Steam client."""
        self.window_manager.close()
        self._window_info = None

    def get_diagnostics(self) -> dict[str, Any]:
        win = self.window_manager.find_game_window()
        return {
            "backend": BackendId.STEAM.value,
            "rogue_version": self.rogue_version,
            "steam_app_id": self.settings.steam_app_id,
            "window_found": win is not None,
            "window_id": hex(win.window_id) if win else None,
            "window_title": win.title if win else None,
            "last_state": self._last_state.value,
        }
