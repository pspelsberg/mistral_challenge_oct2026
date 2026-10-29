"""Bounded memory store preventing runaway token usage (Section 11)."""

from __future__ import annotations

import heapq
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
    DIRECTION_DELTAS_BY_CODE,
    ActionExecutionResult,
    ActionType,
    Direction,
    GameAction,
    GameObservation,
    extract_numbered_row_map,
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
        self.active_oscillation_forbidden_dir: Direction | None = None

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
        diag_deltas = {
            "NE": (-1, 1),
            "NW": (-1, -1),
            "SE": (1, 1),
            "SW": (1, -1),
        }

        pq: list[tuple[int, int, int, int, str]] = []
        dist_map: dict[tuple[int, int], int] = {}
        allowed_initial = set(walkable_dirs) if walkable_dirs else set(DIRECTION_DELTAS_BY_CODE.keys())
        start_ch = _tile(pr, pc)

        # Initial cardinal neighbors (cost 10)
        for d_code, (dr, dc) in cardinal_deltas.items():
            if walkable_dirs and d_code not in allowed_initial:
                continue
            nr, nc = pr + dr, pc + dc
            n_ch = _tile(nr, nc)
            if not _is_walkable_tile(n_ch):
                continue
            dist_map[(nr, nc)] = 10
            routes[(nr, nc)] = (1, d_code)
            heapq.heappush(pq, (10, 1, nr, nc, d_code))

        # Initial diagonal neighbors (cost 21: strictly disfavored compared to cardinal, disallow doorway entries)
        for d_code, (dr, dc) in diag_deltas.items():
            if walkable_dirs and d_code not in allowed_initial:
                continue
            nr, nc = pr + dr, pc + dc
            n_ch = _tile(nr, nc)
            if not _is_walkable_tile(n_ch):
                continue
            if start_ch in ("+", "#") or n_ch in ("+", "#"):
                continue
            dist_map[(nr, nc)] = 21
            routes[(nr, nc)] = (1, d_code)
            heapq.heappush(pq, (21, 1, nr, nc, d_code))

        while pq:
            cost, steps, cr, cc, first_dir = heapq.heappop(pq)
            if cost > dist_map.get((cr, cc), cost):
                continue
            c_ch = _tile(cr, cc)
            cand_map = cardinal_deltas if c_ch in ("+", "#") else {**cardinal_deltas, **diag_deltas}
            for d_code, (dr, dc) in cand_map.items():
                nr, nc = cr + dr, cc + dc
                if (nr, nc) == (pr, pc):
                    continue
                n_ch = _tile(nr, nc)
                if not _is_walkable_tile(n_ch):
                    continue
                if d_code not in cardinal_deltas and n_ch in ("+", "#"):
                    continue
                w = 10 if d_code in cardinal_deltas else 21
                new_cost = cost + w
                new_steps = steps + 1
                if (nr, nc) not in dist_map or new_cost < dist_map[(nr, nc)]:
                    dist_map[(nr, nc)] = new_cost
                    routes[(nr, nc)] = (new_steps, first_dir)
                    heapq.heappush(pq, (new_cost, new_steps, nr, nc, first_dir))

        return routes

    @classmethod
    def _mark_segment_visited(
        cls,
        visited_set: set[tuple[int, int]],
        p1: tuple[int, int],
        p2: tuple[int, int],
        screen_text: str | None = None,
    ) -> None:
        r1, c1 = int(p1[0]), int(p1[1])
        r2, c2 = int(p2[0]), int(p2[1])
        visited_set.add((r1, c1))
        visited_set.add((r2, c2))
        if r1 == r2 and c1 != c2:
            step = 1 if c2 > c1 else -1
            for c in range(c1, c2 + step, step):
                visited_set.add((r1, c))
            return
        if c1 == c2 and r1 != r2:
            step = 1 if r2 > r1 else -1
            for r in range(r1, r2 + step, step):
                visited_set.add((r, c1))
            return

        # Curved or multi-bend corridor movement (e.g. fast_move across bends):
        # run BFS on visible screen to trace and mark all intermediate corridor tiles
        row_map = cls._extract_row_map(screen_text)
        if not row_map:
            return

        def _is_nav(r: int, c: int) -> bool:
            s = row_map.get(r, "")
            ch = s[c] if 0 <= c < len(s) else " "
            return ch in (".", "#", "+", "%", "*", ":", "?", "@") or ("A" <= ch <= "Z")

        queue: deque[tuple[tuple[int, int], list[tuple[int, int]]]] = deque([(p1, [p1])])
        seen = {p1}
        while queue:
            curr, path = queue.popleft()
            if curr == p2:
                for pt in path:
                    visited_set.add(pt)
                return
            cr, cc = curr
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = cr + dr, cc + dc
                np = (nr, nc)
                if np not in seen and (np == p2 or _is_nav(nr, nc)):
                    seen.add(np)
                    queue.append((np, path + [np]))

    @staticmethod
    def _extract_row_map(screen_text: str | None) -> dict[int, str]:
        return extract_numbered_row_map(screen_text)

    @classmethod
    def _analyze_screen_topology(
        cls,
        screen_text: str | None,
        visited_curr: set[tuple[int, int]],
        player_pos: tuple[int, int] | None,
        doors: list[Any],
    ) -> tuple[
        list[tuple[int, int]],
        list[tuple[int, int]],
        list[tuple[int, int]],
        bool,
        list[tuple[int, int]],
    ]:
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
        current_room_unvisited_doors: list[tuple[int, int]] = []
        if row_map:
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
                    elif player_pos is not None and (
                        player_pos in comp or player_pos in border_doors
                    ):
                        for d_pos in sorted(
                            border_doors & unvisited_doors_set,
                            key=lambda dp: (0 if dp not in visited_curr else 1, dp),
                        ):
                            current_room_unvisited_doors.append(d_pos)

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

        return (
            unvisited_doors,
            visited_doors,
            corridor_frontiers,
            current_room_cleared,
            current_room_unvisited_doors,
        )

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
        self.active_oscillation_forbidden_dir = None

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
                            screen_text=obs_after.screen_text,
                        )
            elif (
                isinstance(pos_before, tuple)
                and len(pos_before) == 2
                and lvl_before == lvl_after
            ):
                self._mark_segment_visited(
                    visited_set, pos_before, pos_after, screen_text=obs_after.screen_text
                )
            if (
                len(self.recent_positions) >= 2
                and pos_after == self.recent_positions[-2]
                and pos_before != pos_after
            ):
                dr = pos_before[0] - pos_after[0]
                dc = pos_before[1] - pos_after[1]
                forbidden_d = Direction.from_delta(dr, dc)
                self.active_oscillation_forbidden_dir = forbidden_d
                f_hint = (
                    f" (FORBIDDEN REVERSE DIRECTION: direction='{forbidden_d.value}')"
                    if forbidden_d
                    else ""
                )
                self.recent_failed_actions.append(
                    f"Turn {turn_index}: IMMEDIATE OSCILLATION ALERT! Bounced {pos_after} -> {pos_before} -> {pos_after}. "
                    f"Do NOT reverse direction back to {pos_before}{f_hint}; pick a different direction or door!"
                )
            else:
                self.active_oscillation_forbidden_dir = None
            if (
                len(self.recent_positions) >= 4
                and pos_after in list(self.recent_positions)[-6:-2]
                and pos_before != pos_after
            ):
                self.recent_failed_actions.append(
                    f"Turn {turn_index}: MACRO-BACKTRACKING DETECTED! You just returned to {pos_after}, which you already visited "
                    f"a few turns ago! Stop oscillating between rooms/corridors; proceed forward into UNEXPLORED doors/areas!"
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

        # Record visible threats as verified facts (and prune stale threats when cleared)
        monsters = obs_after.inferred_metadata.get("visible_monsters")
        if isinstance(monsters, list) and monsters:
            summary = ", ".join(f"{m['symbol']}@({m['row']},{m['col']})" for m in monsters[:4])
            self.verified_facts = deque(
                [f for f in self.verified_facts if f.category != "threat"],
                maxlen=self.max_facts,
            )
            self.verified_facts.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.FACT,
                    category="threat",
                    content=f"Visible monsters on Level {lvl_after}: {summary}",
                )
            )
        elif isinstance(monsters, list) and not monsters and any(f.category == "threat" for f in self.verified_facts):
            self.verified_facts = deque(
                [f for f in self.verified_facts if f.category != "threat"],
                maxlen=self.max_facts,
            )
            self.verified_facts.append(
                MemoryFact(
                    turn=turn_index,
                    status=EpistemicStatus.FACT,
                    category="threat",
                    content=f"All visible monsters cleared on Level {lvl_after}",
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
                    content=action.notable_memory_fact[:220],
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
            stairs_visible_screen = observation.inferred_metadata.get("stairs_positions") or []
            stairs_known_level = self.known_stairs_by_level.get(lvl_curr) or []
            if observation.inferred_metadata.get("standing_on_stairs") or (
                pos is not None and pos in stairs_visible_screen
            ):
                lines.append(
                    f"- STAIRCASE ALERT: You are standing DIRECTLY ON the staircase '%' at {pos}! "
                    f"Use action='descend_stairs' immediately to descend to Level {lvl_curr + 1}!"
                )
            elif stairs_visible_screen:
                lines.append(
                    f"- STAIRCASE VISIBLE ON SCREEN: '%' is at {stairs_visible_screen}! "
                    f"Move to {stairs_visible_screen[0]} and use action='descend_stairs'!"
                )
            elif stairs_known_level:
                lines.append(
                    f"- KNOWN STAIRCASE (PREVIOUSLY SEEN ON LEVEL {lvl_curr}): '%' was found at {stairs_known_level}. "
                    f"Navigate back when ready to descend."
                )
            if self.active_oscillation_forbidden_dir:
                lines.append(
                    f"- FORBIDDEN OSCILLATION DIRECTION: direction='{self.active_oscillation_forbidden_dir.value}'! "
                    f"You have been caught in a wall-bouncing loop! You are STRICTLY FORBIDDEN from choosing direction='{self.active_oscillation_forbidden_dir.value}'! "
                    f"Choose ANY other walkable direction or door to break free!"
                )
            if isinstance(pos, tuple) and len(pos) == 2 and isinstance(walkable, list):
                pr, pc = int(pos[0]), int(pos[1])
                doors = observation.inferred_metadata.get("door_positions") or []
                (
                    unvisited_doors,
                    visited_doors,
                    corridor_frontiers,
                    current_room_cleared,
                    current_room_unvisited_doors,
                ) = self._analyze_screen_topology(
                    observation.screen_text,
                    visited_curr,
                    pos,
                    doors if isinstance(doors, list) else [],
                )

                routes = self._compute_bfs_routes(
                    observation.screen_text,
                    pos,
                    walkable if isinstance(walkable, list) else None,
                )

                if current_room_cleared:
                    lines.append(
                        f"- ROOM CLEARED ALERT: The room at {pos} is 100% CLEARED (0 items, 0 stairs, "
                        f"all its doors explored)! Do NOT walk onto '.' floor tiles inside this room — "
                        f"exit immediately toward an UNVISITED Door '+' or UNEXPLORED Corridor Branch '#'!"
                    )
                elif current_room_unvisited_doors:
                    formatted_room_doors = [
                        self._format_relative_coord(pr, pc, dr, dc, routes)
                        for dr, dc in current_room_unvisited_doors
                    ]
                    lines.append(
                        f"- UNEXPLORED DOOR IN THIS ROOM (TOP PRIORITY): You are in a room with unexplored door(s) "
                        f"{formatted_room_doors}! Do NOT backtrack into visited corridors or rooms; "
                        f"head directly to this unexplored door!"
                    )

                unvisited_dirs: list[str] = []
                visited_dirs: list[str] = []
                for d_code in walkable:
                    if d_code in DIRECTION_DELTAS_BY_CODE:
                        dr, dc = DIRECTION_DELTAS_BY_CODE[d_code]
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

                if unvisited_doors:
                    unvisited_doors.sort(
                        key=lambda pt: (
                            0 if (pt not in visited_curr and pt in current_room_unvisited_doors) else
                            1 if (pt not in visited_curr) else
                            2 if (pt in current_room_unvisited_doors) else
                            3,
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

                reachable_doors = [
                    (routes[pt][0], routes[pt][1], pt)
                    for pt in unvisited_doors
                    if pt in routes
                ]
                reachable_corridors = [
                    (routes[pt][0], routes[pt][1], pt)
                    for pt in corridor_frontiers
                    if pt in routes
                ]
                reachable_items: list[tuple[int, str, tuple[int, int], dict[str, Any]]] = []
                if isinstance(items_curr, list) and items_curr:
                    for it in items_curr:
                        if isinstance(it, dict) and "row" in it and "col" in it:
                            itr, itc = int(it["row"]), int(it["col"])
                            if (itr, itc) in routes and (itr, itc) not in visited_curr:
                                st, first_step = routes[(itr, itc)]
                                reachable_items.append((st, first_step, (itr, itc), it))

                if reachable_items and not stairs_visible_screen:
                    reachable_items.sort(key=lambda x: x[0])
                    b_item_steps, b_item_first, b_item_pt, b_item = reachable_items[0]
                    item_in_room = current_room_unvisited_doors and (
                        b_item_steps <= (reachable_doors[0][0] if reachable_doors else 999) + 4
                    )
                    if item_in_room or not reachable_doors:
                        d_enum = Direction.from_short_code(b_item_first)
                        full_d = d_enum.value if d_enum else b_item_first
                        sym = b_item.get("symbol", "*")
                        itype = b_item.get("type", "item")
                        lines.append(
                            f"- TOPOLOGICAL COMPASS HINT: Closest uncollected item in this room is '{sym}' ({itype}) at "
                            f"{b_item_pt} (walk_steps={b_item_steps}); take first_step={b_item_first} (direction='{full_d}')!"
                        )
                if not any("TOPOLOGICAL COMPASS HINT:" in line_txt for line_txt in lines) and reachable_doors and not stairs_visible_screen:
                    reachable_doors.sort(
                        key=lambda x: (
                            0 if (x[2] not in visited_curr and x[2] in current_room_unvisited_doors) else
                            1 if (x[2] not in visited_curr) else
                            2 if (x[2] in current_room_unvisited_doors) else
                            3,
                            x[0],
                        )
                    )
                    best_steps, best_first, best_pt = reachable_doors[0]
                    d_enum = Direction.from_short_code(best_first)
                    full_d = d_enum.value if d_enum else best_first
                    door_type = (
                        "unexplored room door"
                        if (best_pt not in visited_curr and best_pt in current_room_unvisited_doors)
                        else "unvisited door"
                        if best_pt not in visited_curr
                        else "explored room exit door"
                    )
                    lines.append(
                        f"- TOPOLOGICAL COMPASS HINT: Closest {door_type} along walkable tiles is "
                        f"{best_pt} (walk_steps={best_steps}); take first_step={best_first} (direction='{full_d}')!"
                    )
                elif not any("TOPOLOGICAL COMPASS HINT:" in line_txt for line_txt in lines) and reachable_corridors and not stairs_visible_screen:
                    reachable_corridors.sort(key=lambda x: x[0])
                    best_steps, best_first, best_pt = reachable_corridors[0]
                    d_enum = Direction.from_short_code(best_first)
                    full_d = d_enum.value if d_enum else best_first
                    lines.append(
                        f"- TOPOLOGICAL COMPASS HINT: Closest unexplored corridor frontier along walkable tiles is "
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

                # Collect all adjacent monsters in walkable directions
                adjacent_monsters: list[dict[str, Any]] = []
                if isinstance(monsters, list):
                    for m in monsters:
                        mr, mc = int(m.get("row", -99)), int(m.get("col", -99))
                        dr_m, dc_m = mr - pr, mc - pc
                        if max(abs(dr_m), abs(dc_m)) == 1:
                            d_enum = Direction.from_delta(dr_m, dc_m)
                            if d_enum is not None and d_enum.short_code in walkable:
                                adjacent_monsters.append({
                                    "monster": m,
                                    "symbol": str(m.get("symbol", "M")),
                                    "row": mr,
                                    "col": mc,
                                    "dir_code": d_enum.short_code,
                                    "full_dir": d_enum.value,
                                })

                # Check if an open, monster-free step toward a visible staircase '%' on active screen exists
                open_stair_sprint_dir: tuple[str, str, tuple[int, int], int] | None = None
                if stairs_visible_screen and pos not in stairs_visible_screen:
                    sr, sc = int(stairs_visible_screen[0][0]), int(stairs_visible_screen[0][1])
                    s_dist = max(abs(sr - pr), abs(sc - pc))
                    step_r = 0 if sr == pr else (1 if sr > pr else -1)
                    step_c = 0 if sc == pc else (1 if sc > pc else -1)
                    cand_deltas = [(step_r, step_c)]
                    if step_r != 0 and step_c != 0:
                        cand_deltas.extend([(step_r, 0), (0, step_c)])
                    for cd_r, cd_c in cand_deltas:
                        d_enum = Direction.from_delta(cd_r, cd_c)
                        if d_enum is not None and d_enum.short_code in walkable:
                            t_ch = str(adj.get(d_enum.short_code, ""))
                            if not (len(t_ch) == 1 and t_ch.isalpha() and t_ch.isupper()):
                                open_stair_sprint_dir = (
                                    d_enum.short_code,
                                    d_enum.value,
                                    (sr, sc),
                                    s_dist,
                                )
                                break

                # Only emit STAIRCASE SPRINT ALERT if there are NO adjacent monsters blocking melee
                if open_stair_sprint_dir is not None and not adjacent_monsters:
                    sc_code, full_dir, st_pos, st_dist = open_stair_sprint_dir
                    lines.append(
                        f"- STAIRCASE SPRINT ALERT (HIGHEST PRIORITY): Staircase '%' at {st_pos} is "
                        f"{st_dist} tile(s) away and {sc_code} (direction='{full_dir}') is OPEN! "
                        f"Move direction='{full_dir}' immediately to reach {st_pos} and descend!"
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
                    if len(monsters) >= 2 and not adjacent_monsters and not observation.inferred_metadata.get(
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

                    # Handle adjacent monsters: IMMEDIATE ATTACK DOCTRINE
                    for am in adjacent_monsters:
                        sym = am["symbol"]
                        mr, mc = am["row"], am["col"]
                        sc, full_dir = am["dir_code"], am["full_dir"]

                        can_step_onto_stairs = (
                            open_stair_sprint_dir is not None
                            and open_stair_sprint_dir[3] == 1
                        )
                        if can_step_onto_stairs and sym not in ("B", "K"):
                            lines.append(
                                f"- STAIRCASE ESCAPE AVAILABLE: Monster '{sym}' is adjacent at ({mr}, {mc}), "
                                f"but staircase '%' is 1 step away at {open_stair_sprint_dir[2]} ({open_stair_sprint_dir[0]} / direction='{open_stair_sprint_dir[1]}')! "
                                f"You may step onto the stairs with action='move', direction='{open_stair_sprint_dir[1]}', steps=1 "
                                f"to escape, OR attack '{sym}' in melee with action='move', direction='{full_dir}', steps=1."
                            )
                        elif low_hp and usable_items:
                            lines.append(
                                f"- CRITICAL LOW HP ALERT (HP={hp_curr}/{hp_max}): Monster '{sym}' is "
                                f"adjacent at ({mr}, {mc}) ({sc})! Before risking another melee swing at "
                                f"critical HP, consider using an inventory potion/scroll ({', '.join(usable_items)}) "
                                f"with action='quaff_potion' or action='read_scroll'!"
                            )
                        else:
                            is_fast_flier = sym in ("K", "B", "M")
                            if is_fast_flier:
                                lines.append(
                                    f"- TACTICAL COMBAT ALERT (IMMEDIATE MELEE ATTACK): Fast flier / monster '{sym}' at ({mr}, {mc}) "
                                    f"is ADJACENT ({sc} / direction='{full_dir}')! Never flee or circle (fliers move at 2x speed "
                                    f"and get free hits, while Bat 'B' dies in 1-2 hits from your mace). "
                                    f"Stand your ground and ATTACK IMMEDIATELY in melee with action='move', direction='{full_dir}', steps=1!"
                                )
                            else:
                                lines.append(
                                    f"- TACTICAL COMBAT ALERT (MELEE ATTACK): Monster '{sym}' at ({mr}, {mc}) is ADJACENT "
                                    f"({sc} / direction='{full_dir}'). Attack in melee with action='move', direction='{full_dir}', steps=1."
                                )

                    if not adjacent_monsters and open_stair_sprint_dir is None:
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
                            d_enum = Direction.from_delta(step_r, step_c)
                            if d_enum is None or d_enum.short_code not in walkable:
                                continue
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
                            sc, full_dir = d_enum.short_code, d_enum.value
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
                        and not stairs_visible_screen
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
