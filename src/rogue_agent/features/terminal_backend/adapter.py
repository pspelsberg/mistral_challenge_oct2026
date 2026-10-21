"""TerminalGameAdapter implementing GameBackendPort for Rogue 5.4.4 (Section 7)."""

from __future__ import annotations

from typing import Any

from rogue_agent.features.terminal_backend.pty_process import PtyRogueProcess
from rogue_agent.features.terminal_backend.screen_parser import parse_terminal_screen
from rogue_agent.shared.config import RogueAgentSettings
from rogue_agent.shared.controls import ControlValidationError, TerminalRogueControlProfile
from rogue_agent.shared.domain import (
    ActionExecutionResult,
    ActionType,
    BackendId,
    Direction,
    GameAction,
    GameObservation,
    GameState,
)

_DIAGONAL_COMPONENTS: dict[Direction, tuple[Direction, Direction]] = {
    Direction.NORTHEAST: (Direction.NORTH, Direction.EAST),
    Direction.NORTHWEST: (Direction.NORTH, Direction.WEST),
    Direction.SOUTHEAST: (Direction.SOUTH, Direction.EAST),
    Direction.SOUTHWEST: (Direction.SOUTH, Direction.WEST),
}

_OPPOSITE_DIRECTION: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

_SHORT_CODE_TO_DIRECTION: dict[str, Direction] = {
    "N": Direction.NORTH,
    "S": Direction.SOUTH,
    "E": Direction.EAST,
    "W": Direction.WEST,
}


class TerminalGameAdapter:
    """Backend B adapter running native Terminal Rogue 5.4.4 inside a 80x24 PTY."""

    def __init__(
        self,
        settings: RogueAgentSettings | None = None,
        control_profile: TerminalRogueControlProfile | None = None,
    ) -> None:
        self.settings = settings or RogueAgentSettings()
        self.controls = control_profile or TerminalRogueControlProfile()
        self._pty = PtyRogueProcess(
            binary_path=self.settings.terminal_binary,
            player_name=self.settings.player_name,
        )
        self._last_action_result: str | None = None
        self._last_state: GameState = GameState.NOT_STARTED
        self._pending_turn_messages: list[str] = []
        self._known_stairs_level: int = 1
        self._known_stairs_positions: list[tuple[int, int]] = []
        self._turn_waypoints: list[tuple[int, int]] = []
        self._visited_tiles: set[tuple[int, int]] = set()
        self._last_observed_pos: tuple[int, int] | None = None

    @property
    def rogue_version(self) -> str:
        return self.controls.version_name

    def start(self) -> GameObservation:
        """Start the Terminal Rogue PTY process and return the initial observation."""
        self._known_stairs_level = 1
        self._known_stairs_positions.clear()
        self._pending_turn_messages.clear()
        self._visited_tiles.clear()
        self._last_observed_pos = None
        self._pty.start()
        self._last_action_result = "Game started in 80x24 PTY"
        return self.observe()

    @staticmethod
    def _clean_more_banner(msg: str) -> str:
        """Strip trailing --More-- markers from a top-line Rogue message."""
        cleaned = msg.replace("--More--", "").strip()
        return cleaned

    def observe(self, auto_drain_more: bool = True) -> GameObservation:
        """Read current PTY screen buffer and construct a typed GameObservation.

        When `auto_drain_more=True`, any `--More--` pagination prompts on row 0 are
        automatically acknowledged with Space (0 API tokens, 0 extra turns) while
        accumulating every paginated message into `recent_messages`.
        """
        self._pty.drain_output(max_wait=0.1, quiet_window=0.03)
        lines = self._pty.get_screen_lines()
        cursor = self._pty.get_cursor()
        parsed = parse_terminal_screen(
            lines=lines,
            cursor_pos=cursor,
            process_alive=self._pty.is_alive,
        )

        collected_messages: list[str] = list(self._pending_turn_messages)
        self._pending_turn_messages.clear()
        for m in parsed.recent_messages:
            cleaned = self._clean_more_banner(m)
            if cleaned and cleaned not in collected_messages:
                collected_messages.append(cleaned)

        drained_count = 0
        max_more_pages = 8
        while (
            auto_drain_more
            and parsed.game_state == GameState.MORE_PROMPT
            and self._pty.is_alive
            and drained_count < max_more_pages
        ):
            drained_count += 1
            self._pty.send_keys([" "])
            self._pty.drain_output(max_wait=0.08, quiet_window=0.025)
            lines = self._pty.get_screen_lines()
            cursor = self._pty.get_cursor()
            parsed = parse_terminal_screen(
                lines=lines,
                cursor_pos=cursor,
                process_alive=self._pty.is_alive,
            )
            for m in parsed.recent_messages:
                cleaned = self._clean_more_banner(m)
                if cleaned and cleaned not in collected_messages:
                    collected_messages.append(cleaned)

        if (
            auto_drain_more
            and parsed.game_state in (GameState.INVENTORY, GameState.ITEM_SELECTION)
            and self._pty.is_alive
        ):
            top_lower = lines[0].lower() if lines else ""
            if parsed.game_state == GameState.ITEM_SELECTION and "identify" in top_lower:
                # Scroll of identify requires selecting a valid item of the target type
                # (Escape does not cancel whatis() in Rogue 5.4.4 unless * reveals 0 items).
                drained_count += 1
                self._pty.send_keys(["*"])
                self._pty.drain_output(max_wait=0.08, quiet_window=0.025)
                lines = self._pty.get_screen_lines()
                inv_slots: list[str] = []
                for ln in lines:
                    s_ln = ln.strip()
                    if len(s_ln) >= 3 and s_ln[0].isalpha() and s_ln[1] == ")":
                        inv_slots.append(s_ln[0])
                        cleaned_inv = self._clean_more_banner(s_ln)
                        if cleaned_inv and cleaned_inv not in collected_messages:
                            collected_messages.append(cleaned_inv)
                if inv_slots:
                    # Dismiss the --Press space to continue-- list, then send the best slot
                    non_starting = [ch for ch in inv_slots if ch > "e"]
                    chosen_slot = non_starting[0] if non_starting else inv_slots[0]
                    self._pty.send_keys([" ", chosen_slot])
                else:
                    # No matching items in pack ("You don't have anything appropriate--More--")
                    self._pty.send_keys([" "])
                self._pty.drain_output(max_wait=0.08, quiet_window=0.025)
                lines = self._pty.get_screen_lines()
                cursor = self._pty.get_cursor()
                parsed = parse_terminal_screen(
                    lines=lines,
                    cursor_pos=cursor,
                    process_alive=self._pty.is_alive,
                )
                for m in parsed.recent_messages:
                    cleaned = self._clean_more_banner(m)
                    if cleaned and cleaned not in collected_messages:
                        collected_messages.append(cleaned)
                if parsed.game_state == GameState.MORE_PROMPT and self._pty.is_alive:
                    self._pty.send_keys([" "])
                    self._pty.drain_output(max_wait=0.08, quiet_window=0.025)
                    lines = self._pty.get_screen_lines()
                    cursor = self._pty.get_cursor()
                    parsed = parse_terminal_screen(
                        lines=lines,
                        cursor_pos=cursor,
                        process_alive=self._pty.is_alive,
                    )
                    for m in parsed.recent_messages:
                        cleaned = self._clean_more_banner(m)
                        if cleaned and cleaned not in collected_messages:
                            collected_messages.append(cleaned)
            else:
                if parsed.game_state == GameState.INVENTORY:
                    inv_lines = [
                        ln.strip()
                        for ln in lines
                        if len(ln.strip()) >= 3 and ln.strip()[0].isalpha() and ln.strip()[1] == ")"
                    ]
                    if inv_lines:
                        collected_messages.append("Inventory: " + "; ".join(inv_lines))
                    dismiss_key = " "
                else:
                    dismiss_key = "\x1b"
                drained_count += 1
                self._pty.send_keys([dismiss_key])
                self._pty.drain_output(max_wait=0.08, quiet_window=0.025)
                lines = self._pty.get_screen_lines()
                cursor = self._pty.get_cursor()
                parsed = parse_terminal_screen(
                    lines=lines,
                    cursor_pos=cursor,
                    process_alive=self._pty.is_alive,
                )

        self._last_state = parsed.game_state
        metadata = dict(parsed.visible_metadata)
        if drained_count > 0:
            metadata["drained_more_prompts"] = drained_count

        # Preserve known staircase coordinates on the current level even when '@' steps onto '%'
        curr_level = parsed.visible_status.dungeon_level or self._known_stairs_level
        if curr_level != self._known_stairs_level:
            self._known_stairs_level = curr_level
            self._known_stairs_positions = []
            self._visited_tiles.clear()
            self._last_observed_pos = None
        visible_stairs = list(metadata.get("stairs_positions") or [])
        for st in visible_stairs:
            if isinstance(st, tuple) and len(st) == 2 and st not in self._known_stairs_positions:
                self._known_stairs_positions.append(st)
        if self._known_stairs_positions:
            merged_stairs = list(visible_stairs)
            for st in self._known_stairs_positions:
                if st not in merged_stairs:
                    merged_stairs.append(st)
            metadata["stairs_positions"] = merged_stairs
        player_pos = metadata.get("player_position")
        if isinstance(player_pos, tuple) and len(player_pos) == 2:
            pr_o, pc_o = int(player_pos[0]), int(player_pos[1])
            self._visited_tiles.add((pr_o, pc_o))
            if self._last_observed_pos is not None:
                lr, lc = self._last_observed_pos
                if lr == pr_o and lc != pc_o:
                    step = 1 if pc_o > lc else -1
                    for c in range(lc, pc_o + step, step):
                        self._visited_tiles.add((pr_o, c))
                elif lc == pc_o and lr != pr_o:
                    step = 1 if pr_o > lr else -1
                    for r in range(lr, pr_o + step, step):
                        self._visited_tiles.add((r, pc_o))
            self._last_observed_pos = (pr_o, pc_o)
        metadata["standing_on_stairs"] = bool(
            player_pos is not None and player_pos in (metadata.get("stairs_positions") or [])
        )
        if self._turn_waypoints:
            metadata["turn_waypoints"] = list(self._turn_waypoints)

        return GameObservation(
            backend=BackendId.TERMINAL,
            rogue_version=self.rogue_version,
            screen_text=parsed.screen_text,
            screenshot_png_bytes=None,
            visible_status=parsed.visible_status,
            game_state=parsed.game_state,
            recent_messages=collected_messages or parsed.recent_messages,
            previous_action_result=self._last_action_result,
            observation_uncertainty=0.0 if parsed.game_state != GameState.UNKNOWN else 0.5,
            cursor_position=cursor,
            inferred_metadata=metadata,
        )

    def detect_game_state(self) -> GameState:
        """Return the current detected game state."""
        return self.observe().game_state

    @staticmethod
    def _find_midwall_door_stop_steps(
        obs: GameObservation,
        direction: Direction,
        visited_tiles: set[tuple[int, int]] | None = None,
    ) -> int | None:
        """If moving E/W or N/S inside a room would overshoot an UNVISITED mid-wall door '+',
        return the exact step count to align with the nearest unvisited door ahead."""
        pos = obs.inferred_metadata.get("player_position")
        doors = obs.inferred_metadata.get("door_positions") or []
        items = obs.inferred_metadata.get("visible_items") or []
        monsters = obs.inferred_metadata.get("visible_monsters") or []
        if not isinstance(pos, tuple) or len(pos) != 2 or not doors or monsters:
            return None
        pr, pc = int(pos[0]), int(pos[1])
        dr_step, dc_step = direction.delta
        if (dr_step, dc_step) not in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            return None

        row_map: dict[int, str] = {}
        if obs.screen_text:
            for line in obs.screen_text.splitlines():
                if len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": ":
                    row_map[int(line[:2])] = line[4:]

        def _tile(r: int, c: int) -> str:
            row_str = row_map.get(r, "")
            return row_str[c] if 0 <= c < len(row_str) else " "

        best_unvisited_steps: int | None = None
        best_visited_steps: int | None = None
        for d in doors:
            if not isinstance(d, (tuple, list)) or len(d) != 2:
                continue
            dr, dc = int(d[0]), int(d[1])
            is_visited_door = bool(visited_tiles and (dr, dc) in visited_tiles)
            if dc_step != 0:
                # Moving E or W: check doors 1..6 rows N/S whose column lies ahead
                ahead = (dc - pc) * dc_step
                perp = abs(dr - pr)
            else:
                # Moving N or S: check doors 1..6 cols E/W whose row lies ahead
                ahead = (dr - pr) * dr_step
                perp = abs(dc - pc)
            if not (1 <= ahead <= 25 and 1 <= perp <= 6):
                continue

            if row_map:
                # 1. Every step along our travel line up to `ahead` must be room floor '.'
                if any(
                    _tile(pr + dr_step * s, pc + dc_step * s) != "."
                    for s in range(1, ahead + 1)
                ):
                    continue
                # 2. The tile one step past `ahead` must also be '.' (otherwise native
                #    fast_move already stops at the room wall without overshooting).
                if _tile(pr + dr_step * (ahead + 1), pc + dc_step * (ahead + 1)) != ".":
                    continue
                # 3. Every perpendicular tile between the stop point and the door '+' must be '.'
                stop_r, stop_c = pr + dr_step * ahead, pc + dc_step * ahead
                p_dr = 0 if dr == stop_r else (1 if dr > stop_r else -1)
                p_dc = 0 if dc == stop_c else (1 if dc > stop_c else -1)
                if any(
                    _tile(stop_r + p_dr * p, stop_c + p_dc * p) != "."
                    for p in range(1, perp)
                ):
                    continue

            if not is_visited_door:
                if best_unvisited_steps is None or ahead < best_unvisited_steps:
                    best_unvisited_steps = ahead
            else:
                if best_visited_steps is None or ahead < best_visited_steps:
                    best_visited_steps = ahead

        best_steps = (
            best_unvisited_steps
            if best_unvisited_steps is not None
            else best_visited_steps
        )
        if best_steps is None:
            return None

        # If an item lies directly on our line of travel closer/further in the room,
        # let native fast_move stop on the item first.
        for it in items:
            ir, ic = int(it.get("row", -1)), int(it.get("col", -1))
            if dc_step != 0 and ir == pr and (ic - pc) * dc_step > 0:
                return None
            if dr_step != 0 and ic == pc and (ir - pr) * dr_step > 0:
                return None

        return best_steps

    @staticmethod
    def _find_stair_sprint_steps(
        obs: GameObservation,
        direction: Direction,
    ) -> int | None:
        """If the staircase '%' is directly in line with `direction` across open '.' tiles,
        return the exact step count (1..5) so fast_move doesn't abort early due to nearby monsters."""
        pos = obs.inferred_metadata.get("player_position")
        stairs = obs.inferred_metadata.get("stairs_positions") or []
        if not isinstance(pos, tuple) or len(pos) != 2 or not stairs:
            return None
        pr, pc = int(pos[0]), int(pos[1])
        dr_step, dc_step = direction.delta
        if (dr_step, dc_step) == (0, 0):
            return None

        row_map: dict[int, str] = {}
        if obs.screen_text:
            for line in obs.screen_text.splitlines():
                if len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": ":
                    row_map[int(line[:2])] = line[4:]

        def _tile(r: int, c: int) -> str:
            row_str = row_map.get(r, "")
            return row_str[c] if 0 <= c < len(row_str) else " "

        for st in stairs:
            if not isinstance(st, (tuple, list)) or len(st) != 2:
                continue
            sr, sc = int(st[0]), int(st[1])
            for s in range(1, 9):
                if pr + dr_step * s == sr and pc + dc_step * s == sc:
                    if row_map and any(
                        _tile(pr + dr_step * k, pc + dc_step * k) not in (".", "%", "+")
                        for k in range(1, s + 1)
                    ):
                        break
                    return min(s, 5)
        return None

    def execute_action(self, action: GameAction) -> ActionExecutionResult:
        """Translate GameAction and execute with an interruptible short horizon (1..5 steps)."""
        obs_initial = self.observe()
        state_before = obs_initial.game_state

        # If the agent attempts a diagonal move into/out of a doorway or corridor where
        # Rogue 5.4.4 blocks diagonals, automatically align cardinally in 1 step.
        if (
            state_before == GameState.PLAYING
            and action.action_type in (ActionType.MOVE, ActionType.FAST_MOVE)
            and action.direction in _DIAGONAL_COMPONENTS
        ):
            walkable = obs_initial.inferred_metadata.get("walkable_directions", [])
            if isinstance(walkable, list) and action.direction.short_code not in walkable:
                for cand in _DIAGONAL_COMPONENTS[action.direction]:
                    if cand.short_code in walkable:
                        action = action.model_copy(
                            update={
                                "action_type": ActionType.MOVE,
                                "direction": cand,
                                "steps": 1,
                            }
                        )
                        break

        # Prevent fast_move inside a room from sliding past a mid-wall door '+',
        # or ensure fast_move toward an open staircase '%' completes up to 5 steps even if monsters are nearby.
        was_fast_move_cardinal = (
            state_before == GameState.PLAYING
            and action.action_type == ActionType.FAST_MOVE
            and action.direction in _OPPOSITE_DIRECTION
        )
        fast_move_dir: Direction | None = action.direction if was_fast_move_cardinal else None
        door_align_steps: int | None = None
        stair_sprint_steps: int | None = None
        if (
            state_before == GameState.PLAYING
            and action.action_type == ActionType.FAST_MOVE
            and action.direction is not None
        ):
            stair_sprint_steps = self._find_stair_sprint_steps(obs_initial, action.direction)
            if stair_sprint_steps is not None:
                action = action.model_copy(
                    update={
                        "action_type": ActionType.MOVE,
                        "steps": stair_sprint_steps,
                    }
                )
            else:
                door_align_steps = self._find_midwall_door_stop_steps(
                    obs_initial, action.direction, self._visited_tiles
                )
                if door_align_steps is not None:
                    action = action.model_copy(
                        update={
                            "action_type": ActionType.MOVE,
                            "steps": min(door_align_steps, 5),
                        }
                    )

        try:
            single_step_keys = self.controls.translate_action(action, state_before)
        except ControlValidationError as exc:
            self._last_action_result = f"Validation error: {exc}"
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
            door_align_steps
            if door_align_steps is not None
            else (
                action.steps
                if action.action_type in (ActionType.MOVE, ActionType.SEARCH, ActionType.REST)
                else 1
            )
        )
        all_keys_sent: list[str] = []
        steps_completed = 0
        interrupted_early = False
        interrupt_reason: str | None = None

        obs_curr = obs_initial
        self._turn_waypoints.clear()
        pos_init = obs_initial.inferred_metadata.get("player_position")
        if isinstance(pos_init, tuple) and len(pos_init) == 2:
            self._turn_waypoints.append(pos_init)
        monsters_initial = obs_initial.inferred_metadata.get("visible_monsters") or []
        for step_idx in range(requested_steps):
            pos_before = obs_curr.inferred_metadata.get("player_position")
            hp_before = obs_curr.visible_status.hits_current
            step_keys = (
                single_step_keys
                if step_idx == 0
                else self.controls.translate_action(action, obs_curr.game_state)
            )

            try:
                self._pty.send_keys(step_keys)
            except Exception as exc:
                self._last_action_result = f"PTY write error: {exc}"
                return ActionExecutionResult(
                    success=False,
                    keys_sent=all_keys_sent,
                    steps_requested=requested_steps,
                    steps_completed=steps_completed,
                    summary=self._last_action_result,
                    error_message=str(exc),
                    state_before=state_before,
                    state_after=GameState.UNKNOWN,
                )

            all_keys_sent.extend(step_keys)
            steps_completed += 1
            obs_after = self.observe()
            pos_step = obs_after.inferred_metadata.get("player_position")
            if isinstance(pos_step, tuple) and len(pos_step) == 2:
                self._turn_waypoints.append(pos_step)
            drained_more = int(obs_after.inferred_metadata.get("drained_more_prompts", 0) or 0)
            if drained_more > 0:
                all_keys_sent.extend([" "] * drained_more)

            # Check local interrupt conditions if more steps remain in the horizon
            if step_idx + 1 < requested_steps:
                pos_after = obs_after.inferred_metadata.get("player_position")
                hp_after = obs_after.visible_status.hits_current
                monsters = obs_after.inferred_metadata.get("visible_monsters") or []
                stairs = obs_after.inferred_metadata.get("stairs_positions") or []

                if obs_after.game_state != GameState.PLAYING:
                    interrupted_early = True
                    interrupt_reason = f"ui_state_changed:{obs_after.game_state.value}"
                    obs_curr = obs_after
                    break
                if drained_more > 0:
                    interrupted_early = True
                    interrupt_reason = "message_prompt_cleared"
                    obs_curr = obs_after
                    break
                if action.action_type == ActionType.MOVE and pos_before == pos_after:
                    interrupted_early = True
                    interrupt_reason = "movement_blocked_by_wall_or_obstacle"
                    obs_curr = obs_after
                    break
                if hp_before is not None and hp_after is not None and hp_after < hp_before:
                    interrupted_early = True
                    interrupt_reason = f"hp_decreased:{hp_before}->{hp_after}"
                    obs_curr = obs_after
                    break
                adjacent_monster_sym: str | None = None
                if isinstance(pos_after, tuple) and len(pos_after) == 2 and monsters:
                    pr_a, pc_a = int(pos_after[0]), int(pos_after[1])
                    for m in monsters:
                        mr, mc = int(m.get("row", -99)), int(m.get("col", -99))
                        if max(abs(mr - pr_a), abs(mc - pc_a)) <= 1:
                            adjacent_monster_sym = str(m.get("symbol", "M"))
                            break
                if adjacent_monster_sym is not None and stair_sprint_steps is None:
                    interrupted_early = True
                    interrupt_reason = f"monster_adjacent:{adjacent_monster_sym}"
                    obs_curr = obs_after
                    break
                if monsters and not monsters_initial:
                    interrupted_early = True
                    interrupt_reason = f"monster_visible:{monsters[0]['symbol']}"
                    obs_curr = obs_after
                    break
                if pos_after in stairs:
                    interrupted_early = True
                    interrupt_reason = "stepped_onto_staircase"
                    obs_curr = obs_after
                    break
                if (
                    action.action_type == ActionType.MOVE
                    and action.direction is not None
                    and pos_after is not None
                ):
                    walkable = obs_after.inferred_metadata.get("walkable_directions", [])
                    if isinstance(walkable, list) and action.direction.short_code not in walkable:
                        interrupted_early = True
                        interrupt_reason = "wall_ahead_in_ascii_grid"
                        obs_curr = obs_after
                        break
                    adj_tiles = obs_after.inferred_metadata.get("adjacent_tiles", {})
                    pr_a, pc_a = int(pos_after[0]), int(pos_after[1])
                    if action.direction in (Direction.EAST, Direction.WEST) and (
                        (
                            adj_tiles.get("N") == "+"
                            and (pr_a - 1, pc_a) not in self._visited_tiles
                        )
                        or (
                            adj_tiles.get("S") == "+"
                            and (pr_a + 1, pc_a) not in self._visited_tiles
                        )
                    ):
                        interrupted_early = True
                        interrupt_reason = "aligned_with_doorway"
                        obs_curr = obs_after
                        break
                    if action.direction in (Direction.NORTH, Direction.SOUTH) and (
                        (
                            adj_tiles.get("E") == "+"
                            and (pr_a, pc_a + 1) not in self._visited_tiles
                        )
                        or (
                            adj_tiles.get("W") == "+"
                            and (pr_a, pc_a - 1) not in self._visited_tiles
                        )
                    ):
                        interrupted_early = True
                        interrupt_reason = "aligned_with_doorway"
                        obs_curr = obs_after
                        break

            obs_curr = obs_after

        # If door_align_steps aligned '@' directly adjacent to a mid-wall door '+' (perp == 1)
        # with no monsters or items present, step 1 tile onto '+' so we don't need an extra turn.
        if (
            door_align_steps is not None
            and fast_move_dir is not None
            and not interrupted_early
            and obs_curr.game_state == GameState.PLAYING
            and not obs_curr.inferred_metadata.get("visible_monsters")
            and not obs_curr.inferred_metadata.get("visible_items")
        ):
            adj_align = obs_curr.inferred_metadata.get("adjacent_tiles") or {}
            walk_align = obs_curr.inferred_metadata.get("walkable_directions") or []
            perp_codes = (
                ("N", "S")
                if fast_move_dir in (Direction.EAST, Direction.WEST)
                else ("E", "W")
            )
            for p_code in perp_codes:
                if (
                    isinstance(adj_align, dict)
                    and isinstance(walk_align, list)
                    and adj_align.get(p_code) == "+"
                    and p_code in walk_align
                ):
                    p_dir = _SHORT_CODE_TO_DIRECTION[p_code]
                    d_key = self.controls.direction_key(p_dir)
                    self._pty.send_keys([d_key])
                    all_keys_sent.append(d_key)
                    obs_curr = self.observe()
                    p_now = obs_curr.inferred_metadata.get("player_position")
                    if isinstance(p_now, tuple) and len(p_now) == 2:
                        self._turn_waypoints.append(p_now)
                    break

        # Corridor auto-cornering & door-threshold stepping for FAST_MOVE:
        # 1. In Rogue 5.4.4, H/J/K/L stops 1 tile BEFORE a door '+', leaving the room dark.
        #    Stepping 1 tile onto '+' reveals the room on the same turn.
        # 2. In winding 1-way corridors ('#') with no branching intersections, automatically
        #    follow up to 3 forced bends until reaching a door '+', junction, dead end, or monster.
        if (
            was_fast_move_cardinal
            and fast_move_dir is not None
            and door_align_steps is None
            and stair_sprint_steps is None
            and not interrupted_early
            and obs_curr.game_state == GameState.PLAYING
        ):
            curr_dir = fast_move_dir
            hp_init = obs_initial.visible_status.hits_current
            for _ in range(3):
                if obs_curr.game_state != GameState.PLAYING or obs_curr.recent_messages:
                    break
                hp_now = obs_curr.visible_status.hits_current
                if hp_init is not None and hp_now is not None and hp_now < hp_init:
                    break
                if obs_curr.inferred_metadata.get("visible_monsters"):
                    break
                adj_now = obs_curr.inferred_metadata.get("adjacent_tiles") or {}
                walk_now = obs_curr.inferred_metadata.get("walkable_directions") or []
                if not isinstance(adj_now, dict) or not isinstance(walk_now, list):
                    break

                # Case A: H/J/K/L stopped 1 tile short of a door '+' directly ahead
                if adj_now.get(curr_dir.short_code) == "+" and curr_dir.short_code in walk_now:
                    door_key = self.controls.direction_key(curr_dir)
                    self._pty.send_keys([door_key])
                    all_keys_sent.append(door_key)
                    obs_curr = self.observe()
                    p_now = obs_curr.inferred_metadata.get("player_position")
                    if isinstance(p_now, tuple) and len(p_now) == 2:
                        self._turn_waypoints.append(p_now)
                    break

                # Case B: Inside a non-branching 1-way '#' corridor bend
                cardinal_walk = [d for d in walk_now if d in _SHORT_CODE_TO_DIRECTION]
                if not cardinal_walk or any(adj_now.get(d) not in ("#", "+") for d in cardinal_walk):
                    break
                rev_code = _OPPOSITE_DIRECTION[curr_dir].short_code
                forward_codes = [d for d in cardinal_walk if d != rev_code]
                if len(forward_codes) != 1:
                    break
                next_code = forward_codes[0]
                next_dir = _SHORT_CODE_TO_DIRECTION[next_code]
                if adj_now.get(next_code) == "+":
                    door_key = self.controls.direction_key(next_dir)
                    self._pty.send_keys([door_key])
                    all_keys_sent.append(door_key)
                    obs_curr = self.observe()
                    p_now = obs_curr.inferred_metadata.get("player_position")
                    if isinstance(p_now, tuple) and len(p_now) == 2:
                        self._turn_waypoints.append(p_now)
                    break
                corridor_key = self.controls.direction_key(next_dir).upper()
                self._pty.send_keys([corridor_key])
                all_keys_sent.append(corridor_key)
                obs_curr = self.observe()
                p_now = obs_curr.inferred_metadata.get("player_position")
                if isinstance(p_now, tuple) and len(p_now) == 2:
                    self._turn_waypoints.append(p_now)
                curr_dir = next_dir

        self._pending_turn_messages = list(obs_curr.recent_messages)
        joined_msgs = " / ".join(obs_curr.recent_messages)
        msg_suffix = f" | Msg: {joined_msgs}" if joined_msgs else ""
        int_suffix = f" [Interrupted: {interrupt_reason}]" if interrupted_early else ""
        self._last_action_result = (
            f"Executed {action.action_type.value} ({steps_completed}/{requested_steps} steps, "
            f"keys={all_keys_sent!r}) -> {obs_curr.game_state.value}{int_suffix}{msg_suffix}"
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
            state_after=obs_curr.game_state,
        )

    def reset(self) -> GameObservation:
        """Restart the Terminal Rogue PTY process for a fresh game."""
        self.close()
        return self.start()

    def close(self) -> None:
        """Terminate the PTY process cleanly."""
        self._pty.close()
        self._last_state = GameState.NOT_STARTED

    def get_diagnostics(self) -> dict[str, Any]:
        """Return runtime diagnostics for the Terminal backend."""
        return {
            "backend": BackendId.TERMINAL.value,
            "rogue_version": self.rogue_version,
            "binary_path": str(self.settings.terminal_binary),
            "process_alive": self._pty.is_alive,
            "last_state": self._last_state.value,
        }
