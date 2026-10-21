"""Bounded memory store preventing runaway token usage (Section 11)."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

from rogue_agent.features.memory.models import (
    EpistemicStatus,
    MemoryFact,
    TurnMemoryRecord,
)
from rogue_agent.features.memory.playbook import CrossSessionPlaybookManager
from rogue_agent.shared.domain import (
    ActionExecutionResult,
    ActionType,
    GameAction,
    GameObservation,
)


class BoundedAgentMemory:
    """Maintains bounded history of turns, visited positions, threats, and hypotheses."""

    def __init__(
        self,
        max_recent_turns: int = 8,
        max_facts: int = 12,
        max_hypotheses: int = 8,
        max_failed_actions: int = 6,
        runs_dir: Path | None = None,
    ) -> None:
        self.max_recent_turns = max_recent_turns
        self.max_facts = max_facts
        self.max_hypotheses = max_hypotheses
        self.max_failed_actions = max_failed_actions
        self.playbook = CrossSessionPlaybookManager(runs_dir=runs_dir)

        self.current_objective: str = "Explore Dungeon Level 1 and locate the staircase"
        self.recent_turns: deque[TurnMemoryRecord] = deque(maxlen=max_recent_turns)
        self.verified_facts: deque[MemoryFact] = deque(maxlen=max_facts)
        self.model_hypotheses: deque[MemoryFact] = deque(maxlen=max_hypotheses)
        self.recent_failed_actions: deque[str] = deque(maxlen=max_failed_actions)
        self.recent_positions: deque[tuple[int, int]] = deque(maxlen=10)
        self.visited_by_level: dict[int, set[tuple[int, int]]] = {}
        self.searched_positions_by_level: dict[int, set[tuple[int, int]]] = {}
        self.known_stairs_by_level: dict[int, list[tuple[int, int]]] = {}
        self.known_inventory: dict[str, str] = self._default_starting_inventory()
        self.max_depth_reached: int = 1

    @staticmethod
    def _default_starting_inventory() -> dict[str, str]:
        return {
            "a": "a ration of food",
            "b": "+1,+1 ring mail [armor class 4] (being worn)",
            "c": "+1,+1 mace (weapon in hand)",
            "d": "+1 short bow",
            "e": "arrows",
        }

    @staticmethod
    def _format_relative_coord(
        pr: int,
        pc: int,
        tr: int,
        tc: int,
        routes: dict[tuple[int, int], tuple[int, str]] | None = None,
    ) -> str:
        dr = tr - pr
        dc = tc - pc
        dist = max(abs(dr), abs(dc))
        parts: list[str] = []
        if dr < 0:
            parts.append(f"{abs(dr)}N")
        elif dr > 0:
            parts.append(f"{dr}S")
        if dc < 0:
            parts.append(f"{abs(dc)}W")
        elif dc > 0:
            parts.append(f"{dc}E")
        rel = ",".join(parts) if parts else "HERE"
        if routes and (tr, tc) in routes:
            walk_steps, first_step = routes[(tr, tc)]
            return f"({tr}, {tc}) [{rel}, walk_steps={walk_steps}, first_step={first_step}]"
        return f"({tr}, {tc}) [{rel}, dist={dist}]"

    @classmethod
    def _compute_bfs_routes(
        cls,
        screen_text: str | None,
        player_pos: tuple[int, int] | None,
        walkable_dirs: list[str] | None = None,
    ) -> dict[tuple[int, int], tuple[int, str]]:
        """Compute shortest walkable path length (walk_steps) and initial compass direction
        (first_step) from player_pos to every reachable tile on the visible ASCII grid."""
        routes: dict[tuple[int, int], tuple[int, str]] = {}
        if player_pos is None:
            return routes
        row_map = cls._extract_row_map(screen_text)
        if not row_map:
            return routes

        pr, pc = int(player_pos[0]), int(player_pos[1])
        walkable_chars = frozenset(
            {".", "+", "#", "%", "*", "!", "?", ":", ")", "]", "/", "=", ",", "^", "@"}
        )

        def _tile(r: int, c: int) -> str:
            s = row_map.get(r, "")
            return s[c] if 0 <= c < len(s) else " "

        def _is_walkable_tile(ch: str) -> bool:
            return ch in walkable_chars or ("A" <= ch <= "Z")

        cardinal_deltas = {
            "N": (-1, 0),
            "S": (1, 0),
            "E": (0, 1),
            "W": (0, -1),
        }
        all_deltas = {
            **cardinal_deltas,
            "NE": (-1, 1),
            "NW": (-1, -1),
            "SE": (1, 1),
            "SW": (1, -1),
        }

        queue: deque[tuple[int, int, int, str]] = deque()
        allowed_initial = set(walkable_dirs) if walkable_dirs else set(all_deltas.keys())
        start_ch = _tile(pr, pc)

        for d_code, (dr, dc) in all_deltas.items():
            if walkable_dirs and d_code not in allowed_initial:
                continue
            nr, nc = pr + dr, pc + dc
            n_ch = _tile(nr, nc)
            if not _is_walkable_tile(n_ch):
                continue
            if d_code not in cardinal_deltas and (
                start_ch in ("+", "#") or n_ch in ("+", "#")
            ):
                continue
            routes[(nr, nc)] = (1, d_code)
            queue.append((nr, nc, 1, d_code))

        while queue:
            cr, cc, dist, first_dir = queue.popleft()
            c_ch = _tile(cr, cc)
            cand_map = cardinal_deltas if c_ch in ("+", "#") else all_deltas
            for d_code, (dr, dc) in cand_map.items():
                nr, nc = cr + dr, cc + dc
                if (nr, nc) in routes or (nr, nc) == (pr, pc):
                    continue
                n_ch = _tile(nr, nc)
                if not _is_walkable_tile(n_ch):
                    continue
                if d_code not in cardinal_deltas and n_ch in ("+", "#"):
                    continue
                routes[(nr, nc)] = (dist + 1, first_dir)
                queue.append((nr, nc, dist + 1, first_dir))

        return routes

    @staticmethod
    def _mark_segment_visited(
        visited_set: set[tuple[int, int]],
        p1: tuple[int, int],
        p2: tuple[int, int],
    ) -> None:
        r1, c1 = int(p1[0]), int(p1[1])
        r2, c2 = int(p2[0]), int(p2[1])
        visited_set.add((r1, c1))
        visited_set.add((r2, c2))
        if r1 == r2 and c1 != c2:
            step = 1 if c2 > c1 else -1
            for c in range(c1, c2 + step, step):
                visited_set.add((r1, c))
        elif c1 == c2 and r1 != r2:
            step = 1 if r2 > r1 else -1
            for r in range(r1, r2 + step, step):
                visited_set.add((r, c1))

    @staticmethod
    def _extract_row_map(screen_text: str | None) -> dict[int, str]:
        row_map: dict[int, str] = {}
        if not screen_text:
            return row_map
        lines = screen_text.splitlines()
        has_numbered = any(
            len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": "
            for line in lines
        )
        if has_numbered:
            for line in lines:
                if len(line) >= 4 and line[:2].isdigit() and line[2:4] == ": ":
                    row_map[int(line[:2])] = line[4:]
        else:
            for idx, line in enumerate(lines):
                row_map[idx] = line
        return row_map

    @classmethod
    def _analyze_screen_topology(
        cls,
        screen_text: str | None,
        visited_curr: set[tuple[int, int]],
        player_pos: tuple[int, int] | None,
        doors: list[Any],
    ) -> tuple[list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], bool]:
        """Classify doors into (unexplored, explored), find unexplored '#' corridor frontiers,
        and auto-mark 100% cleared rooms (0 items, 0 stairs, 0 unexplored doors) in visited_curr."""
        row_map = cls._extract_row_map(screen_text)

        def _tile(r: int, c: int) -> str:
            s = row_map.get(r, "")
            return s[c] if 0 <= c < len(s) else " "

        def _is_door_unexplored(dr: int, dc: int) -> bool:
            if (dr, dc) not in visited_curr:
                return True
            if not row_map:
                return False
            # If any adjacent corridor '#' or floor '.' tile is unvisited, the door is not fully traversed
            for d_r, d_c in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = dr + d_r, dc + d_c
                ch = _tile(nr, nc)
                if ch == "#" and (nr, nc) not in visited_curr:
                    return True
            return False

        unvisited_doors: list[tuple[int, int]] = []
        visited_doors: list[tuple[int, int]] = []
        for d in doors:
            if isinstance(d, (tuple, list)) and len(d) == 2:
                dp = (int(d[0]), int(d[1]))
                if _is_door_unexplored(dp[0], dp[1]):
                    unvisited_doors.append(dp)
                else:
                    visited_doors.append(dp)

        current_room_cleared = False
        if row_map:
            # Flood-fill connected room floor components and mark cleared rooms as visited
            room_chars = frozenset({".", "@", "%", "*", "!", "?", ":", ")", "]", "/", "=", ",", "^"})
            seen_room_tiles: set[tuple[int, int]] = set()
            unvisited_doors_set = set(unvisited_doors)

            for r, line_str in row_map.items():
                if r in (0, 23):
                    continue
                for c, ch in enumerate(line_str):
                    if (r, c) in seen_room_tiles:
                        continue
                    if ch not in room_chars and not ("A" <= ch <= "Z"):
                        continue
                    # BFS across this room interior
                    comp: set[tuple[int, int]] = set()
                    border_doors: set[tuple[int, int]] = set()
                    has_loot_or_stairs = False
                    queue: deque[tuple[int, int]] = deque([(r, c)])
                    seen_room_tiles.add((r, c))
                    while queue:
                        cr, cc = queue.popleft()
                        comp.add((cr, cc))
                        c_ch = _tile(cr, cc)
                        if c_ch in ("%", "*", "!", "?", ":", ")", "]", "/", "=", ",", "^"):
                            has_loot_or_stairs = True
                        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            nr, nc = cr + dr, cc + dc
                            n_ch = _tile(nr, nc)
                            if n_ch == "+":
                                border_doors.add((nr, nc))
                            elif (
                                (nr, nc) not in seen_room_tiles
                                and (n_ch in room_chars or ("A" <= n_ch <= "Z"))
                            ):
                                seen_room_tiles.add((nr, nc))
                                queue.append((nr, nc))

                    room_entered = bool(
                        (comp & visited_curr)
                        or (border_doors & visited_curr)
                        or (player_pos is not None and player_pos in comp)
                    )
                    room_has_unexplored_door = bool(border_doors & unvisited_doors_set)
                    if room_entered and not has_loot_or_stairs and not room_has_unexplored_door:
                        for tr, tc in comp:
                            if _tile(tr, tc) in (".", "@"):
                                visited_curr.add((tr, tc))
                        if player_pos is not None and (
                            player_pos in comp or player_pos in border_doors
                        ):
                            current_room_cleared = True

        # Find unexplored '#' corridor frontiers (unvisited '#' adjacent to a visited tile)
        corridor_frontiers: list[tuple[int, int]] = []
        if row_map:
            for r, line_str in row_map.items():
                if r in (0, 23):
                    continue
                for c, ch in enumerate(line_str):
                    if ch == "#" and (r, c) not in visited_curr:
                        if any(
                            (r + dr, c + dc) in visited_curr
                            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                        ):
                            corridor_frontiers.append((r, c))

        return unvisited_doors, visited_doors, corridor_frontiers, current_room_cleared

    def reset(self) -> None:
        self.current_objective = "Explore Dungeon Level 1 and locate the staircase"
        self.recent_turns.clear()
        self.verified_facts.clear()
        self.model_hypotheses.clear()
        self.recent_failed_actions.clear()
        self.recent_positions.clear()
        self.visited_by_level.clear()
        self.searched_positions_by_level.clear()
        self.known_stairs_by_level.clear()
        self.known_inventory = self._default_starting_inventory()
        self.max_depth_reached: int = 1

    def record_turn(
        self,
        turn_index: int,
        obs_before: GameObservation,
        action: GameAction,
        result: ActionExecutionResult,
        obs_after: GameObservation,
    ) -> None:
        """Update memory with observed facts, failed actions, and model hypotheses."""
        if action.objective:
            self.current_objective = action.objective

        lvl_before = obs_before.visible_status.dungeon_level or 1
        lvl_after = obs_after.visible_status.dungeon_level or lvl_before
        if lvl_after > self.max_depth_reached:
            self.max_depth_reached = lvl_after
            self.verified_facts.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.FACT,
                    category="event",
                    content=f"Descended to Dungeon Level {lvl_after}",
                )
            )

        # Track visited coordinates when available (Terminal Rogue 5.4.4 / Steam ASCII)
        pos_before = obs_before.inferred_metadata.get("player_position")
        pos_after = obs_after.inferred_metadata.get("player_position")
        if (
            isinstance(pos_before, tuple)
            and len(pos_before) == 2
            and not self.recent_positions
        ):
            self.recent_positions.append(pos_before)
            self.visited_by_level.setdefault(lvl_before, set()).add(pos_before)
        if isinstance(pos_after, tuple) and len(pos_after) == 2:
            visited_set = self.visited_by_level.setdefault(lvl_after, set())
            visited_set.add(pos_after)
            if action.action_type == ActionType.SEARCH:
                self.searched_positions_by_level.setdefault(lvl_after, set()).add(pos_after)
            waypoints = obs_after.inferred_metadata.get("turn_waypoints")
            if (
                isinstance(waypoints, list)
                and len(waypoints) >= 2
                and lvl_before == lvl_after
            ):
                for idx in range(len(waypoints) - 1):
                    wp1, wp2 = waypoints[idx], waypoints[idx + 1]
                    if (
                        isinstance(wp1, (tuple, list))
                        and len(wp1) == 2
                        and isinstance(wp2, (tuple, list))
                        and len(wp2) == 2
                    ):
                        self._mark_segment_visited(
                            visited_set,
                            (int(wp1[0]), int(wp1[1])),
                            (int(wp2[0]), int(wp2[1])),
                        )
            elif (
                isinstance(pos_before, tuple)
                and len(pos_before) == 2
                and lvl_before == lvl_after
            ):
                self._mark_segment_visited(visited_set, pos_before, pos_after)
            if (
                len(self.recent_positions) >= 2
                and pos_after == self.recent_positions[-2]
                and pos_before != pos_after
            ):
                self.recent_failed_actions.append(
                    f"Turn {turn_index}: OSCILLATION ALERT! Bounced {pos_after} -> {pos_before} -> {pos_after}. "
                    f"Do NOT reverse direction back to {pos_before}; pick a different direction or door!"
                )
            self.recent_positions.append(pos_after)

        stairs = obs_after.inferred_metadata.get("stairs_positions")
        if isinstance(stairs, list) and stairs:
            self.known_stairs_by_level[lvl_after] = stairs
            self.verified_facts.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.FACT,
                    category="map",
                    content=f"Staircase '%' observed on Level {lvl_after} at {stairs}",
                )
            )

        # Track picked-up, identified, and consumed inventory items across the entire run
        combined_msgs = list(obs_after.recent_messages)
        if len(combined_msgs) >= 2:
            for idx_m in range(len(combined_msgs) - 1):
                if combined_msgs[idx_m].strip().lower() == "you now have":
                    combined_msgs.append(f"You now have {combined_msgs[idx_m + 1].strip()}")
        for raw_msg in combined_msgs:
            low_msg = raw_msg.lower()
            if "you now have " in low_msg and raw_msg.endswith(")") and "(" in raw_msg:
                slot = raw_msg.rsplit("(", 1)[-1].rstrip(")").strip()
                desc = raw_msg.split("You now have ", 1)[-1].rsplit("(", 1)[0].strip()
                if len(slot) == 1 and slot.isalpha():
                    self.known_inventory[slot] = desc
                    self.verified_facts.append(
                        MemoryFact(
                            turn=turn_index,
                            status=EpistemicStatus.FACT,
                            category="inventory",
                            content=f"Picked up item ({slot}): {desc}",
                        )
                    )
            elif (
                raw_msg.endswith(")")
                and "(" in raw_msg
                and any(
                    k in low_msg
                    for k in ("potion of ", "scroll of ", "ring of ", "wand of ", "staff of ")
                )
            ):
                slot = raw_msg.rsplit("(", 1)[-1].rstrip(")").strip()
                desc = raw_msg.rsplit("(", 1)[0].strip()
                if len(desc) >= 3 and desc[1] == ")":
                    desc = desc[2:].strip()
                if len(slot) == 1 and slot.isalpha():
                    self.known_inventory[slot] = desc
                    self.verified_facts.append(
                        MemoryFact(
                            turn=turn_index,
                            status=EpistemicStatus.FACT,
                            category="inventory",
                            content=f"Identified item ({slot}): {desc}",
                        )
                    )
        if (
            result.success
            and action.item_key
            and action.action_type
            in (
                ActionType.QUAFF_POTION,
                ActionType.READ_SCROLL,
                ActionType.EAT_FOOD,
                ActionType.DROP_ITEM,
            )
        ):
            self.known_inventory.pop(action.item_key.lower(), None)

        # Record visible threats as verified facts
        monsters = obs_after.inferred_metadata.get("visible_monsters")
        if isinstance(monsters, list) and monsters:
            summary = ", ".join(f"{m['symbol']}@({m['row']},{m['col']})" for m in monsters[:4])
            self.verified_facts.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.FACT,
                    category="threat",
                    content=f"Visible monsters on Level {lvl_after}: {summary}",
                )
            )

        # Detect ineffective movement (e.g., walking into a wall or closed obstacle)
        effective = result.success
        action_desc = (
            f"{action.action_type.value}"
            + (f"({action.direction.value})" if action.direction else "")
            + (f"[{action.item_key}]" if action.item_key else "")
        )

        if action.action_type in (ActionType.MOVE, ActionType.FAST_MOVE):
            if pos_before is not None and pos_after is not None and pos_before == pos_after:
                adj_before = obs_before.inferred_metadata.get("adjacent_tiles") or {}
                target_tile = (
                    adj_before.get(action.direction.short_code, "")
                    if action.direction is not None and isinstance(adj_before, dict)
                    else ""
                )
                is_melee_attack = (
                    len(target_tile) == 1 and target_tile.isalpha() and target_tile.isupper()
                ) or any(
                    w in m.lower()
                    for m in obs_after.recent_messages
                    for w in ("hit", "miss", "injure", "kill", "defeat", "swing", "bite")
                )
                if not is_melee_attack:
                    effective = False
                    self.recent_failed_actions.append(
                        f"Turn {turn_index}: {action_desc} at {pos_before} did not change position (blocked)"
                    )
            elif (
                obs_after.inferred_metadata.get("frame_changed") is False
                and pos_before is None
            ):
                effective = False
                self.recent_failed_actions.append(
                    f"Turn {turn_index}: {action_desc} produced no screen change"
                )

        if not result.success:
            self.recent_failed_actions.append(
                f"Turn {turn_index}: {action_desc} failed ({result.error_message})"
            )

        # Store model-reported observation as a HYPOTHESIS (never conflated with verified facts)
        if action.notable_memory_fact:
            self.model_hypotheses.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.HYPOTHESIS,
                    category="model_note",
                    content=action.notable_memory_fact,
                )
            )

        msg = " / ".join(obs_after.recent_messages) if obs_after.recent_messages else "No message"
        pos_str = f"pos={pos_before}->{pos_after} | " if pos_after is not None else ""
        self.recent_turns.append(
            TurnMemoryRecord(
                turn=turn_index,
                action_label=action_desc,
                outcome_summary=(
                    f"{pos_str}effective={effective} | state={obs_after.game_state.value} | msg={msg[:60]}"
                ),
                effective=effective,
                dungeon_level=obs_after.visible_status.dungeon_level,
                hp=obs_after.visible_status.hits_current,
            )
        )

    def build_prompt_summary(self, observation: GameObservation | None = None) -> str:
        """Render a strictly bounded (< 500 tokens) memory summary for the model."""
        lines: list[str] = [f"- Current Objective: {self.current_objective}"]
        lines.append(f"- Max Dungeon Depth Reached: {self.max_depth_reached}")

        if self.known_stairs_by_level:
            lines.append(f"- Known Staircases by Level (FACT): {self.known_stairs_by_level}")

        if self.known_inventory:
            inv_str = ", ".join(f"{k}: {v}" for k, v in sorted(self.known_inventory.items()))
            lines.append(f"- Known Inventory Slots (FACT): {inv_str}")

        for lvl, coords in sorted(self.visited_by_level.items()):
            lines.append(f"- Level {lvl} visited tiles count (FACT): {len(coords)}")

        vis_monster_syms: list[str] = []
        if observation is not None:
            raw_m = observation.inferred_metadata.get("visible_monsters") or []
            if isinstance(raw_m, list):
                vis_monster_syms = [
                    str(m.get("symbol", "")) for m in raw_m if isinstance(m, dict)
                ]
        playbook_snippet = self.playbook.build_prompt_snippet(
            rogue_version=observation.rogue_version if observation is not None else "rogue-5.4.4",
            visible_monster_symbols=vis_monster_syms,
        )
        if playbook_snippet:
            lines.append(playbook_snippet)

        if observation is not None:
            pos = observation.inferred_metadata.get("player_position")
            walkable = observation.inferred_metadata.get("walkable_directions") or []
            adj = observation.inferred_metadata.get("adjacent_tiles") or {}
            lvl_curr = observation.visible_status.dungeon_level or 1
            visited_curr = self.visited_by_level.get(lvl_curr, set())
            stairs_curr = (
                observation.inferred_metadata.get("stairs_positions")
                or self.known_stairs_by_level.get(lvl_curr)
                or []
            )
            if observation.inferred_metadata.get("standing_on_stairs") or (
                pos is not None and pos in stairs_curr
            ):
                lines.append(
                    f"- STAIRCASE ALERT: You are standing DIRECTLY ON the staircase '%' at {pos}! "
                    f"Use action='descend_stairs' immediately to descend to Level {lvl_curr + 1}!"
                )
            elif stairs_curr:
                lines.append(
                    f"- STAIRCASE VISIBLE ON LEVEL {lvl_curr}: '%' is at {stairs_curr}! "
                    f"Move to {stairs_curr[0]} and use action='descend_stairs'!"
                )
            if isinstance(pos, tuple) and len(pos) == 2 and isinstance(walkable, list):
                pr, pc = int(pos[0]), int(pos[1])
                doors = observation.inferred_metadata.get("door_positions") or []
                (
                    unvisited_doors,
                    visited_doors,
                    corridor_frontiers,
                    current_room_cleared,
                ) = self._analyze_screen_topology(
                    observation.screen_text,
                    visited_curr,
                    pos,
                    doors if isinstance(doors, list) else [],
                )

                if current_room_cleared:
                    lines.append(
                        f"- ROOM CLEARED ALERT: The room at {pos} is 100% CLEARED (0 items, 0 stairs, "
                        f"all its doors explored)! Do NOT walk onto '.' floor tiles inside this room — "
                        f"exit immediately toward an UNVISITED Door '+' or UNEXPLORED Corridor Branch '#'!"
                    )

                deltas = {
                    "N": (-1, 0),
                    "S": (1, 0),
                    "E": (0, 1),
                    "W": (0, -1),
                    "NE": (-1, 1),
                    "NW": (-1, -1),
                    "SE": (1, 1),
                    "SW": (1, -1),
                }
                unvisited_dirs: list[str] = []
                visited_dirs: list[str] = []
                for d_code in walkable:
                    if d_code in deltas:
                        dr, dc = deltas[d_code]
                        np = (pr + dr, pc + dc)
                        tile_ch = adj.get(d_code, "?")
                        entry = f"{d_code}->{np}('{tile_ch}')"
                        if np in visited_curr:
                            visited_dirs.append(entry)
                        else:
                            unvisited_dirs.append(entry)
                if unvisited_dirs:
                    lines.append(
                        f"- UNVISITED Walkable Neighbors from {pos} (PRIORITIZE!): {unvisited_dirs}"
                    )
                if visited_dirs:
                    lines.append(
                        f"- ALREADY VISITED Walkable Neighbors from {pos}: {visited_dirs}"
                    )

                routes = self._compute_bfs_routes(
                    observation.screen_text,
                    pos,
                    walkable if isinstance(walkable, list) else None,
                )

                if unvisited_doors:
                    unvisited_doors.sort(
                        key=lambda pt: (
                            routes.get(pt, (999, ""))[0],
                            max(abs(pt[0] - pr), abs(pt[1] - pc)),
                        )
                    )
                    formatted_unvisited = [
                        self._format_relative_coord(pr, pc, dr, dc, routes)
                        for dr, dc in unvisited_doors
                    ]
                    lines.append(
                        f"- UNVISITED Doors '+' on Screen (closest walkable path first - TARGET THESE!): "
                        f"{formatted_unvisited}"
                    )
                if corridor_frontiers:
                    corridor_frontiers.sort(
                        key=lambda pt: (
                            routes.get(pt, (999, ""))[0],
                            max(abs(pt[0] - pr), abs(pt[1] - pc)),
                        )
                    )
                    formatted_frontiers = [
                        self._format_relative_coord(pr, pc, fr, fc, routes)
                        for fr, fc in corridor_frontiers
                    ]
                    lines.append(
                        f"- UNEXPLORED Corridor Branches '#' on Screen (HIGH PRIORITY!): "
                        f"{formatted_frontiers}"
                    )
                if visited_doors:
                    lines.append(
                        f"- ALREADY VISITED Doors '+' on Screen (Already explored): {visited_doors}"
                    )

                items_curr = observation.inferred_metadata.get("visible_items") or []
                if isinstance(items_curr, list) and items_curr:
                    formatted_items = [
                        f"'{it.get('symbol', '?')}' at "
                        + self._format_relative_coord(
                            pr, pc, int(it.get("row", 0)), int(it.get("col", 0)), routes
                        )
                        for it in items_curr[:5]
                    ]
                    lines.append(
                        f"- Visible Items on Screen (Step onto tile to pick up): {formatted_items}"
                    )

                code_to_full_dir = {
                    "N": "north",
                    "S": "south",
                    "E": "east",
                    "W": "west",
                    "NE": "northeast",
                    "NW": "northwest",
                    "SE": "southeast",
                    "SW": "southwest",
                }
                frontier_candidates = list(unvisited_doors) + list(corridor_frontiers)
                reachable_frontiers = [
                    (routes[pt][0], routes[pt][1], pt)
                    for pt in frontier_candidates
                    if pt in routes
                ]
                if reachable_frontiers and not stairs_curr:
                    reachable_frontiers.sort(key=lambda x: x[0])
                    best_steps, best_first, best_pt = reachable_frontiers[0]
                    full_d = code_to_full_dir.get(best_first, best_first)
                    lines.append(
                        f"- TOPOLOGICAL COMPASS HINT: Closest unexplored frontier along walkable tiles is "
                        f"{best_pt} (walk_steps={best_steps}); take first_step={best_first} (direction='{full_d}')!"
                    )

                searched_curr = self.searched_positions_by_level.get(lvl_curr, set())
                if (
                    len(walkable) == 1
                    and not unvisited_dirs
                    and pos not in searched_curr
                    and adj.get(walkable[0]) in ("#", "+")
                ):
                    lines.append(
                        f"- DEAD-END CORRIDOR ALERT: {pos} has only 1 walkable neighbor (already visited) "
                        f"and has NOT been searched yet! In Rogue, dead-end corridors often hide a secret "
                        f"door — use action='search', steps=5 ONCE before turning back!"
                    )

                monsters = observation.inferred_metadata.get("visible_monsters") or []
                delta_to_dir = {
                    (-1, 0): ("N", "north"),
                    (1, 0): ("S", "south"),
                    (0, 1): ("E", "east"),
                    (0, -1): ("W", "west"),
                    (-1, 1): ("NE", "northeast"),
                    (-1, -1): ("NW", "northwest"),
                    (1, 1): ("SE", "southeast"),
                    (1, -1): ("SW", "southwest"),
                }

                # Check if an open, monster-free step toward a visible staircase '%' exists
                open_stair_sprint_dir: tuple[str, str, tuple[int, int], int] | None = None
                if stairs_curr and pos not in stairs_curr:
                    sr, sc = int(stairs_curr[0][0]), int(stairs_curr[0][1])
                    s_dist = max(abs(sr - pr), abs(sc - pc))
                    step_r = 0 if sr == pr else (1 if sr > pr else -1)
                    step_c = 0 if sc == pc else (1 if sc > pc else -1)
                    cand_deltas = [(step_r, step_c)]
                    if step_r != 0 and step_c != 0:
                        cand_deltas.extend([(step_r, 0), (0, step_c)])
                    for cd in cand_deltas:
                        d_info = delta_to_dir.get(cd)
                        if d_info is not None and d_info[0] in walkable:
                            t_ch = str(adj.get(d_info[0], ""))
                            if not (len(t_ch) == 1 and t_ch.isalpha() and t_ch.isupper()):
                                open_stair_sprint_dir = (
                                    d_info[0],
                                    d_info[1],
                                    (sr, sc),
                                    s_dist,
                                )
                                break

                if open_stair_sprint_dir is not None:
                    sc_code, full_dir, st_pos, st_dist = open_stair_sprint_dir
                    lines.append(
                        f"- STAIRCASE SPRINT ALERT (HIGHEST PRIORITY): Staircase '%' at {st_pos} is "
                        f"{st_dist} tile(s) away and {sc_code} (direction='{full_dir}') is OPEN! "
                        f"Ignore non-blocking monsters and move direction='{full_dir}' immediately "
                        f"to reach {st_pos} and descend!"
                    )

                if isinstance(monsters, list) and monsters:
                    hp_curr = observation.visible_status.hits_current
                    hp_max = observation.visible_status.hits_max
                    has_heavy_hitter = any(m.get("symbol") in ("H", "O") for m in monsters)
                    low_hp = (
                        hp_curr is not None
                        and hp_max is not None
                        and (hp_curr <= 4 or hp_curr * 3 <= hp_max or (has_heavy_hitter and hp_curr <= 7))
                    )
                    usable_items = [
                        f"{k} ({v})"
                        for k, v in sorted(self.known_inventory.items())
                        if "potion" in v.lower() or "scroll" in v.lower()
                    ]
                    if len(monsters) >= 2 and not observation.inferred_metadata.get(
                        "in_doorway_or_corridor", False
                    ):
                        chokepoint_dirs = [
                            d_code
                            for d_code in walkable
                            if str(adj.get(d_code, "")) in ("+", "#")
                        ]
                        if chokepoint_dirs:
                            lines.append(
                                f"- MULTI-MONSTER CHOKEPOINT ALERT: {len(monsters)} monsters are visible "
                                f"and you are in an open room! Step onto adjacent doorway/corridor "
                                f"{chokepoint_dirs[0]} ('{adj.get(chokepoint_dirs[0])}') to force 1v1 combat "
                                f"so two monsters cannot hit you in the same turn!"
                            )
                    any_adjacent_monster = False
                    for m in monsters:
                        mr, mc = int(m.get("row", -99)), int(m.get("col", -99))
                        sym = str(m.get("symbol", "M"))
                        d_info = delta_to_dir.get((mr - pr, mc - pc))
                        if d_info is not None and d_info[0] in walkable:
                            any_adjacent_monster = True
                            sc, full_dir = d_info
                            if open_stair_sprint_dir is not None:
                                lines.append(
                                    f"- ADJACENT MONSTER NOTE: '{sym}' is at ({mr}, {mc}) ({sc}), "
                                    f"but the path {open_stair_sprint_dir[0]} (direction='{open_stair_sprint_dir[1]}') "
                                    f"to staircase '%' at {open_stair_sprint_dir[2]} is OPEN! Step "
                                    f"direction='{open_stair_sprint_dir[1]}' toward the stairs instead of fighting '{sym}'!"
                                )
                            elif low_hp and usable_items:
                                lines.append(
                                    f"- CRITICAL LOW HP ALERT (HP={hp_curr}/{hp_max}): Monster '{sym}' is "
                                    f"adjacent at ({mr}, {mc}) ({sc})! Before risking another melee swing at "
                                    f"critical HP, consider using an inventory potion/scroll ({', '.join(usable_items)}) "
                                    f"with action='quaff_potion' or action='read_scroll'!"
                                )
                            else:
                                is_fast_flier = sym in ("K", "B")
                                if is_fast_flier:
                                    lines.append(
                                        f"- TACTICAL COMBAT ALERT: Fast flier '{sym}' at ({mr}, {mc}) is ADJACENT "
                                        f"({sc} / direction='{full_dir}')! Never flee (fliers move at 2x speed "
                                        f"and get free hits). Stand and attack in melee with "
                                        f"action='move', direction='{full_dir}', steps=1!"
                                    )
                                else:
                                    lines.append(
                                        f"- TACTICAL COMBAT ALERT: Monster '{sym}' at ({mr}, {mc}) is ADJACENT "
                                        f"({sc} / direction='{full_dir}'). Assess threat: heavy hitters ('H', 'O') "
                                        f"deal 1d8 damage; if HP is within one-shot range (<= 6-7 HP), tactical corridor "
                                        f"retreat or distance is viable as 1x monsters do not get free hits. "
                                        f"Otherwise, attack in melee with action='move', direction='{full_dir}', steps=1."
                                    )

                    if not any_adjacent_monster and open_stair_sprint_dir is None:
                        row_map_los = self._extract_row_map(observation.screen_text)
                        arrow_slots = [
                            k
                            for k, v in sorted(self.known_inventory.items())
                            if "arrow" in v.lower()
                        ]
                        for m in monsters:
                            mr, mc = int(m.get("row", -99)), int(m.get("col", -99))
                            sym = str(m.get("symbol", "M"))
                            dr_m, dc_m = mr - pr, mc - pc
                            dist_m = max(abs(dr_m), abs(dc_m))
                            if not (2 <= dist_m <= 5):
                                continue
                            if not (dr_m == 0 or dc_m == 0 or abs(dr_m) == abs(dc_m)):
                                continue
                            step_r = 0 if dr_m == 0 else (1 if dr_m > 0 else -1)
                            step_c = 0 if dc_m == 0 else (1 if dc_m > 0 else -1)
                            d_info = delta_to_dir.get((step_r, step_c))
                            if d_info is None or d_info[0] not in walkable:
                                continue
                            # Check line of fire across floor/corridor tiles
                            los_clear = True
                            for s_idx in range(1, dist_m):
                                lr, lc = pr + step_r * s_idx, pc + step_c * s_idx
                                r_str = row_map_los.get(lr, "")
                                t_ch = r_str[lc] if 0 <= lc < len(r_str) else " "
                                if t_ch not in (".", "#", "+"):
                                    los_clear = False
                                    break
                            if not los_clear:
                                continue
                            sc, full_dir = d_info
                            if arrow_slots:
                                lines.append(
                                    f"- RANGED WAIT-SHOT / FIRST-STRIKE ALERT: Monster '{sym}' at ({mr}, {mc}) "
                                    f"is {dist_m} tiles {sc} (direction='{full_dir}') in a clear line of fire! "
                                    f"Do NOT step to distance 1 (stepping adjacent gives '{sym}' the first melee hit!). "
                                    f"Throw an arrow now with action='throw_item', direction='{full_dir}', "
                                    f"item_key='{arrow_slots[0]}' so you deal free ranged damage and get the "
                                    f"first melee strike when it steps adjacent!"
                                )
                            elif dist_m == 2:
                                lines.append(
                                    f"- FIRST-STRIKE TIMING ALERT: Monster '{sym}' at ({mr}, {mc}) is 2 tiles "
                                    f"{sc} (direction='{full_dir}')! Do NOT step adjacent (that gives '{sym}' "
                                    f"the first melee hit); use action='rest', steps=1 so '{sym}' steps next "
                                    f"to you and YOU get the first melee swing!"
                                )
                            break

                elif (
                    observation.visible_status.hits_current is not None
                    and observation.visible_status.hits_max is not None
                    and observation.visible_status.hits_current * 2
                    < observation.visible_status.hits_max
                ):
                    hp_c = observation.visible_status.hits_current
                    hp_m = observation.visible_status.hits_max
                    lines.append(
                        f"- RECOVERY HINT (HP={hp_c}/{hp_m}, no monsters visible): Your HP is below 50%. "
                        f"You can safely recover HP with action='rest', steps=5 before entering dangerous new rooms."
                    )
                else:
                    # Safe Scroll Discovery when monster-free, healthy HP, and holding >= 2 unidentified scrolls
                    hp_c = observation.visible_status.hits_current or 12
                    hp_m = observation.visible_status.hits_max or 12
                    unidentified_scrolls = [
                        k
                        for k, v in sorted(self.known_inventory.items())
                        if "scroll titled" in v.lower()
                    ]
                    if (
                        len(unidentified_scrolls) >= 2
                        and hp_c * 4 >= hp_m * 3
                        and not stairs_curr
                    ):
                        first_sc = unidentified_scrolls[0]
                        lines.append(
                            f"- SAFE SCROLL DISCOVERY HINT (HP={hp_c}/{hp_m}, 0 monsters visible): "
                            f"You are carrying {len(unidentified_scrolls)} unidentified scrolls ({', '.join(unidentified_scrolls)}). "
                            f"Reading an unknown scroll in a safe room is high-value (can trigger Magic Mapping, "
                            f"Identify, or Enchant Armor/Weapon): consider action='read_scroll', item_key='{first_sc}'!"
                        )

            hunger = observation.visible_status.hunger_state
            if hunger and hunger.strip().lower() in ("hungry", "weak", "faint"):
                food_slots = [
                    k
                    for k, v in sorted(self.known_inventory.items())
                    if "food" in v.lower() or "ration" in v.lower() or "mold" in v.lower()
                ]
                if food_slots:
                    lines.append(
                        f"- CRITICAL HUNGER ALERT (State={hunger}): You are {hunger.lower()} and risk fainting/starving! "
                        f"Eat food immediately with action='eat_food', item_key='{food_slots[0]}'!"
                    )

        if self.recent_positions:
            trail = " -> ".join(str(p) for p in self.recent_positions)
            lines.append(f"- Recent Position Trail (FACT - do not oscillate!): {trail}")

        if self.verified_facts:
            lines.append("- Verified Facts (Observed):")
            for fact in list(self.verified_facts)[-4:]:
                lines.append(f"  * [T{fact.turn} {fact.category}] {fact.content[:90]}")

        if self.model_hypotheses:
            lines.append("- Model Hypotheses (Unverified Notes):")
            for hyp in list(self.model_hypotheses)[-2:]:
                lines.append(f"  * [T{hyp.turn}] {hyp.content[:90]}")

        if self.recent_failed_actions:
            lines.append("- Recent Blocked/Failed Actions (Avoid repeating!):")
            for fail in list(self.recent_failed_actions)[-3:]:
                lines.append(f"  * {fail}")

        if self.recent_turns:
            lines.append("- Last Turns History:")
            for rec in list(self.recent_turns)[-4:]:
                lines.append(f"  * T{rec.turn}: {rec.action_label} -> {rec.outcome_summary}")

        return "\n".join(lines)

    def get_snapshot(self) -> dict[str, Any]:
        return {
            "current_objective": self.current_objective,
            "max_depth_reached": self.max_depth_reached,
            "recent_turns_count": len(self.recent_turns),
            "verified_facts_count": len(self.verified_facts),
            "model_hypotheses_count": len(self.model_hypotheses),
            "recent_failed_actions": list(self.recent_failed_actions),
        }
