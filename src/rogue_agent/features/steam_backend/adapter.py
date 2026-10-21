"""SteamGameAdapter implementing GameBackendPort for Steam Epyx Rogue v1.49 (Section 6)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
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
from rogue_agent.shared.domain import (
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
        steam_bin = shutil.which("steam")
        if not steam_bin:
            raise RuntimeError("Steam executable not found in PATH.")

        subprocess.Popen(
            [steam_bin, "-applaunch", str(self.settings.steam_app_id)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def _advance_startup_screens_zero_token(self, obs: GameObservation) -> GameObservation:
        """Automatically advance Epyx 1.49 Title Screen and Name Entry with 0 API calls."""
        for _ in range(4):
            if obs.game_state == GameState.START_MENU and self._window_info is not None:
                self.injector.send_key_sequence(self._window_info.window_id, ["space"])
                time.sleep(0.5)
                obs = self.observe()
            elif obs.game_state == GameState.CHARACTER_NAME_ENTRY and self._window_info is not None:
                name_keys = [*list(self.settings.player_name[:12]), "Return"]
                self.injector.send_key_sequence(self._window_info.window_id, name_keys)
                # Wait for Epyx yellow-green curtain transition to finish
                time.sleep(2.2)
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
                    "No running Steam Rogue / DOSBox window found on X11 display."
                )
            self._verify_steam_prerequisites()
            self._launch_via_steam()

            deadline = time.monotonic() + self.launch_timeout_seconds
            while time.monotonic() < deadline:
                win = self.window_manager.find_game_window()
                if win is not None:
                    break
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
        # Wait up to 2.5s for DOSBox to finish initial black-screen boot into ROGUE.EXE
        boot_deadline = time.monotonic() + 2.5
        obs = self.observe()
        while obs.game_state == GameState.UNKNOWN and time.monotonic() < boot_deadline:
            time.sleep(0.25)
            obs = self.observe()

        if self.auto_advance_startup:
            obs = self._advance_startup_screens_zero_token(obs)
        return obs

    def observe(self) -> GameObservation:
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
        self._last_state = analysis.inferred_state

        metadata = {
            **analysis.metrics,
            "window_id": hex(win.window_id),
            "window_title": win.title,
            "frame_hash": frame_hash,
            "frame_changed": frame_changed,
            "png_bytes_size": len(png_bytes),
        }
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
            if action.action_type in (ActionType.MOVE, ActionType.SEARCH, ActionType.REST)
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

        for step_idx in range(requested_steps):
            step_prev_hash = self._last_frame_hash
            try:
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
                    if isinstance(walkable, list) and action.direction.short_code not in walkable:
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
