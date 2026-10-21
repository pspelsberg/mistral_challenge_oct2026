"""Cross-Session Recursive Playbook for Le Chonk (Empirical Bestiary & Post-Mortem Learning).

Strictly separates:
- INVARIANT domain knowledge per Rogue version (`rogue-5.4.4` vs `epyx-1.49`):
  monster combat telemetry (kills, deaths caused, max single-turn HP loss),
  multi-monster chokepoint rules, and post-mortem tactical lessons.
- EPISODIC seed-specific data (NEVER persisted across runs):
  dungeon coordinates, unidentified potion colors, and randomized scroll titles.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

_MONSTER_NAME_TO_SYMBOL_544: dict[str, str] = {
    "aquator": "A",
    "bat": "B",
    "centaur": "C",
    "dragon": "D",
    "emu": "E",
    "venus flytrap": "F",
    "griffin": "G",
    "hobgoblin": "H",
    "ice monster": "I",
    "jabberwock": "J",
    "kestrel": "K",
    "leprechaun": "L",
    "medusa": "M",
    "nymph": "N",
    "orc": "O",
    "phantom": "P",
    "quagga": "Q",
    "rattlesnake": "R",
    "snake": "S",
    "troll": "T",
    "black unicorn": "U",
    "vampire": "V",
    "wraith": "W",
    "xeroc": "X",
    "yeti": "Y",
    "zombie": "Z",
}

_MONSTER_DEFAULT_TACTICS: dict[str, str] = {
    "bat": "Erratic fast flier: do not chase across open rooms; attack when adjacent.",
    "kestrel": "2x-speed flier: NEVER flee (fleeing gives 2 free hits/turn); stand and melee.",
    "emu": "Aggressive Level-1 melee runner: stand and fight 1v1; dies in 1-2 hits.",
    "hobgoblin": (
        "Heavy Level-1 melee hitter (1d8 damage, deals up to 6-8 HP/hit; ~35% hero hit chance). "
        "At <= 6-7 HP without healing, trading melee swings is high-risk for one-shot death. "
        "Normal 1x speed: retreating into corridors or toward stairs does NOT give free hits (unlike 2x flyers)."
    ),
    "orc": (
        "Heavy Level-1 melee hitter (1d8 damage, up to 8 HP/hit). Normal 1x speed: respect damage potential "
        "at low HP and consider tactical corridor retreat if low."
    ),
    "snake": "Fast low-HP biter: eliminate immediately in melee before moving on.",
    "rattlesnake": "Venomous bite drains Strength (Str): fight at high HP or use ranged/magic.",
    "ice monster": "Freeze gaze skips your turns: avoid engaging at low HP.",
    "aquator": "Rusts armor on hit (lowers Arm): kill quickly or avoid.",
    "leprechaun": "Steals gold and flees: strike first when adjacent.",
    "nymph": "Steals magic items and teleports away.",
}

_HIT_BY_MONSTER_RE = re.compile(
    r"the ([a-z ]+?) (?:swings and hits you|scored an excellent hit on you|has injured you|hit you|bites you)",
    re.IGNORECASE,
)
_MISSED_BY_MONSTER_RE = re.compile(
    r"the ([a-z ]+?) (?:swings and misses you|barely misses you|doesn't hit you|misses you)",
    re.IGNORECASE,
)
_DEFEATED_MONSTER_RE = re.compile(
    r"you have defeated the ([a-z ]+?)(?:--more--|$|\.)",
    re.IGNORECASE,
)
_HIT_MONSTER_RE = re.compile(
    r"you (?:swing and hit|hit|have injured|scored an excellent hit on) the ([a-z ]+?)(?:--more--|$|\.)",
    re.IGNORECASE,
)

# Seed-specific patterns that must NEVER enter cross-session memory
_EPISODIC_SEED_RE = re.compile(
    r"(\(\d+\s*,\s*\d+\)|potion|scroll titled|row \d+|col \d+)",
    re.IGNORECASE,
)


class MonsterBestiaryEntry(BaseModel):
    """Aggregated empirical combat statistics for a monster across sessions."""

    symbol: str
    name: str
    combat_turns_observed: int = 0
    hits_landed_on_player: int = 0
    misses_on_player: int = 0
    hits_landed_by_player: int = 0
    kills_by_player: int = 0
    deaths_caused_to_player: int = 0
    max_single_turn_hp_loss: int = 0
    tactical_note: str = ""


class SessionPostMortem(BaseModel):
    """Compact summary and extracted lesson from a single completed session."""

    session_id: str
    rogue_version: str
    turns_survived: int
    max_depth: int
    rooms_discovered: int
    gold_collected: int
    monsters_defeated: int
    final_state: str
    termination_reason: str
    distilled_lesson: str


class CrossSessionPlaybookData(BaseModel):
    """Version-segregated persistent knowledge base learned across runs."""

    rogue_version: str
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    sessions_analyzed: int = 0
    processed_session_ids: list[str] = Field(default_factory=list)
    total_turns_logged: int = 0
    total_monsters_defeated: int = 0
    max_depth_ever: int = 1
    max_gold_ever: int = 0
    bestiary: dict[str, MonsterBestiaryEntry] = Field(default_factory=dict)
    tactical_lessons: list[str] = Field(default_factory=list)
    recent_post_mortems: list[SessionPostMortem] = Field(default_factory=list)


class CrossSessionPlaybookManager:
    """Loads, updates, bootstraps, and renders Le Chonk's recursive cross-session playbook."""

    def __init__(self, runs_dir: Path | None = None) -> None:
        self.runs_dir = runs_dir or Path("runs")

    def _json_path(self, rogue_version: str) -> Path:
        safe_ver = re.sub(r"[^a-zA-Z0-9._-]", "_", rogue_version)
        return self.runs_dir / f"playbook_{safe_ver}.json"

    @property
    def markdown_path(self) -> Path:
        return self.runs_dir / "LE_CHONK_PLAYBOOK.md"

    def load_or_bootstrap(self, rogue_version: str = "rogue-5.4.4") -> CrossSessionPlaybookData:
        """Load the version-specific playbook JSON, bootstrapping from existing live runs if needed."""
        json_path = self._json_path(rogue_version)
        if json_path.is_file():
            try:
                data = CrossSessionPlaybookData.model_validate_json(
                    json_path.read_text(encoding="utf-8")
                )
            except Exception:
                data = CrossSessionPlaybookData(rogue_version=rogue_version)
        else:
            data = CrossSessionPlaybookData(rogue_version=rogue_version)

        # Ingest any live session directories in runs_dir not yet in processed_session_ids
        if self.runs_dir.is_dir():
            new_ingested = False
            for session_dir in sorted(self.runs_dir.iterdir()):
                if not session_dir.is_dir() or session_dir.name in data.processed_session_ids:
                    continue
                summary_file = session_dir / "summary.json"
                turns_file = session_dir / "turns.jsonl"
                if not summary_file.is_file() or not turns_file.is_file():
                    continue
                try:
                    summary = json.loads(summary_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if summary.get("dry_run", False):
                    continue
                if summary.get("rogue_version") != rogue_version:
                    continue
                self._ingest_session_files(data, session_dir, summary, turns_file)
                new_ingested = True

            if new_ingested:
                self.save(data)

        return data

    def record_completed_session(self, session_dir: Path, rogue_version: str) -> CrossSessionPlaybookData:
        """Ingest a newly completed session directory and persist both JSON and Markdown playbooks."""
        data = self.load_or_bootstrap(rogue_version)
        summary_file = session_dir / "summary.json"
        turns_file = session_dir / "turns.jsonl"
        if (
            session_dir.name not in data.processed_session_ids
            and summary_file.is_file()
            and turns_file.is_file()
        ):
            try:
                summary = json.loads(summary_file.read_text(encoding="utf-8"))
                if not summary.get("dry_run", False):
                    self._ingest_session_files(data, session_dir, summary, turns_file)
                    self.save(data)
            except Exception:
                pass
        return data

    def _get_or_create_monster(
        self, data: CrossSessionPlaybookData, monster_name: str
    ) -> MonsterBestiaryEntry:
        clean_name = monster_name.strip().lower()
        sym = _MONSTER_NAME_TO_SYMBOL_544.get(clean_name, clean_name[:1].upper() or "?")
        key = f"{sym}:{clean_name}"
        if key not in data.bestiary:
            data.bestiary[key] = MonsterBestiaryEntry(
                symbol=sym,
                name=clean_name,
                tactical_note=_MONSTER_DEFAULT_TACTICS.get(
                    clean_name,
                    "Engage 1v1 in melee; avoid fighting multiple enemies in open rooms.",
                ),
            )
        return data.bestiary[key]

    @staticmethod
    def _add_unique_lesson(data: CrossSessionPlaybookData, lesson: str) -> None:
        if lesson and lesson not in data.tactical_lessons:
            data.tactical_lessons.append(lesson)

    def _ingest_session_files(
        self,
        data: CrossSessionPlaybookData,
        session_dir: Path,
        summary: dict[str, Any],
        turns_file: Path,
    ) -> None:
        turns_rows: list[dict[str, Any]] = []
        for raw_line in turns_file.read_text(encoding="utf-8").splitlines():
            if raw_line.strip():
                try:
                    turns_rows.append(json.loads(raw_line))
                except Exception:
                    continue

        data.processed_session_ids.append(session_dir.name)
        data.sessions_analyzed += 1
        turns_survived = int(summary.get("turns_survived", len(turns_rows)))
        max_depth = int(summary.get("max_dungeon_depth_reached", 1))
        rooms_disc = int(summary.get("rooms_discovered", 1))
        gold = int(summary.get("max_gold_collected", 0))
        kills = int(summary.get("monsters_defeated", 0))
        final_state = str(summary.get("final_game_state", "PLAYING"))
        term_reason = str(summary.get("termination_reason", "completed"))

        data.total_turns_logged += turns_survived
        data.total_monsters_defeated += kills
        data.max_depth_ever = max(data.max_depth_ever, max_depth)
        data.max_gold_ever = max(data.max_gold_ever, gold)

        prev_hp: int | None = None
        last_hitting_monsters: list[str] = []
        multi_monster_hit_turn = False
        fleeing_hits_taken = 0
        had_consumables_in_pack = False
        used_consumable = False
        dead_end_searched = False

        for row in turns_rows:
            vis = row.get("visible_status") or {}
            hp_curr = vis.get("hits_current")
            hp_loss = 0
            if isinstance(prev_hp, int) and isinstance(hp_curr, int) and hp_curr < prev_hp:
                hp_loss = prev_hp - hp_curr
            if isinstance(hp_curr, int):
                prev_hp = hp_curr

            act = row.get("action") or {}
            act_type = str(act.get("action_type", ""))
            if act_type in ("quaff_potion", "read_scroll"):
                used_consumable = True
            if act_type == "search":
                dead_end_searched = True

            msgs = row.get("recent_messages") or []
            monsters_hitting_this_turn: list[str] = []
            player_attacked_this_turn = False

            for msg in msgs:
                low_m = str(msg).lower()
                if "you now have" in low_m and ("potion" in low_m or "scroll" in low_m):
                    had_consumables_in_pack = True

                for m_hit in _HIT_BY_MONSTER_RE.finditer(low_m):
                    m_name = m_hit.group(1).strip()
                    entry = self._get_or_create_monster(data, m_name)
                    entry.combat_turns_observed += 1
                    entry.hits_landed_on_player += 1
                    monsters_hitting_this_turn.append(m_name)

                for m_miss in _MISSED_BY_MONSTER_RE.finditer(low_m):
                    m_name = m_miss.group(1).strip()
                    entry = self._get_or_create_monster(data, m_name)
                    entry.combat_turns_observed += 1
                    entry.misses_on_player += 1

                for p_hit in _HIT_MONSTER_RE.finditer(low_m):
                    m_name = p_hit.group(1).strip()
                    entry = self._get_or_create_monster(data, m_name)
                    entry.hits_landed_by_player += 1
                    player_attacked_this_turn = True

                for p_def in _DEFEATED_MONSTER_RE.finditer(low_m):
                    m_name = p_def.group(1).strip()
                    entry = self._get_or_create_monster(data, m_name)
                    entry.kills_by_player += 1
                    player_attacked_this_turn = True

                if "you miss the " in low_m or "you barely miss the " in low_m or "you don't hit the " in low_m:
                    player_attacked_this_turn = True

            if monsters_hitting_this_turn:
                last_hitting_monsters = monsters_hitting_this_turn
                if len(set(monsters_hitting_this_turn)) >= 2:
                    multi_monster_hit_turn = True
                if len(monsters_hitting_this_turn) == 1 and hp_loss > 0:
                    entry = self._get_or_create_monster(data, monsters_hitting_this_turn[0])
                    entry.max_single_turn_hp_loss = max(entry.max_single_turn_hp_loss, hp_loss)
                elif len(monsters_hitting_this_turn) >= 2 and hp_loss > 0:
                    per_m = max(1, hp_loss // len(monsters_hitting_this_turn))
                    for m_n in set(monsters_hitting_this_turn):
                        entry = self._get_or_create_monster(data, m_n)
                        entry.max_single_turn_hp_loss = max(entry.max_single_turn_hp_loss, per_m)

                if not player_attacked_this_turn and act_type in ("move", "fast_move"):
                    fleeing_hits_taken += len(monsters_hitting_this_turn)

        # Attribute player death if session ended in GAME_OVER
        is_death = final_state == "GAME_OVER" or "GAME_OVER" in term_reason
        if is_death and last_hitting_monsters:
            for killer in set(last_hitting_monsters):
                entry = self._get_or_create_monster(data, killer)
                entry.deaths_caused_to_player += 1

        # Distill concrete post-mortem lesson from this session
        lesson_parts: list[str] = []
        if multi_monster_hit_turn:
            rule = (
                "CHOKEPOINT RULE: Never fight 2+ monsters simultaneously in an open room "
                "(e.g. Hobgoblin + Emu dealt fatal combined damage); step onto a '+' doorway "
                "or '#' corridor so only 1 monster can attack per turn."
            )
            self._add_unique_lesson(data, rule)
            lesson_parts.append(
                f"Took simultaneous multi-monster hits ({', '.join(set(last_hitting_monsters))}); "
                "must use doorway/corridor chokepoints."
            )

        if fleeing_hits_taken >= 3:
            rule = (
                "ANTI-KITING & MOBILITY HEURISTIC (Contextual, Not Rigid): Fast fliers (Kestrel 'K', "
                "Bat 'B') move at 2x speed and punish fleeing with free hits (stand and fight). Against "
                "standard 1x-speed monsters (Hobgoblin 'H', Orc 'O', Emu 'E'), moving away does NOT grant "
                "free attacks (they spend their turn stepping closer). Tactical retreat into corridors or toward "
                "stairs is viable when HP is within lethal one-shot range."
            )
            self._add_unique_lesson(data, rule)
            lesson_parts.append(
                f"Took {fleeing_hits_taken} free hits while moving away from adjacent monsters."
            )

        if is_death and any(k in ("hobgoblin", "orc") for k in last_hitting_monsters) and not had_consumables_in_pack:
            rule = (
                "HEAVY HITTER THREAT HEURISTIC (Contextual, Not Rigid): Monsters with 1d8 damage (Hobgoblin 'H', "
                "Orc 'O') deal up to 6-8 HP in a single blow. When hero HP is <= 6-7 HP and no healing potions exist, "
                "trading melee swings has a high probability of one-shot death (~35% hero hit rate vs 25% monster hit "
                "rate with 37.5% lethal roll). Since they have normal 1x speed, tactical corridor retreat, kiting toward "
                "stairs, or seeking advantageous terrain is viable."
            )
            self._add_unique_lesson(data, rule)
            lesson_parts.append(
                f"Killed by heavy hitter ({', '.join(set(last_hitting_monsters))}) in melee while at low HP; "
                "consider tactical retreat or distance when facing 1d8 damage."
            )

        if is_death and had_consumables_in_pack and not used_consumable:
            rule = (
                "EMERGENCY CONSUMABLE RULE: Do not die holding unused potions/scrolls; when "
                "HP <= 4 (or <= 33%) with an adjacent monster, quaff_potion or read_scroll "
                "before risking another melee swing."
            )
            self._add_unique_lesson(data, rule)
            lesson_parts.append("Died with unused potion/scroll in inventory.")

        if dead_end_searched and kills >= 1 and not is_death:
            rule = (
                "FRONTIER DISCIPLINE RULE: Search dead-end '#' corridors once (steps=5), "
                "skip cleared rooms (0 items, 0 stairs, 0 unvisited doors), and prioritize "
                "UNEXPLORED '#' corridor branches."
            )
            self._add_unique_lesson(data, rule)
            lesson_parts.append(
                f"Survived {turns_survived} turns, discovered {rooms_disc} rooms, "
                f"defeated {kills} monster(s), and searched dead-end corridors."
            )

        if not lesson_parts:
            lesson_parts.append(
                f"Reached depth {max_depth}, explored {rooms_disc} room(s), "
                f"collected {gold} gold, defeated {kills} monster(s) ({final_state})."
            )

        data.recent_post_mortems.append(
            SessionPostMortem(
                session_id=session_dir.name,
                rogue_version=data.rogue_version,
                turns_survived=turns_survived,
                max_depth=max_depth,
                rooms_discovered=rooms_disc,
                gold_collected=gold,
                monsters_defeated=kills,
                final_state=final_state,
                termination_reason=term_reason,
                distilled_lesson=" ".join(lesson_parts),
            )
        )
        if len(data.recent_post_mortems) > 12:
            data.recent_post_mortems = data.recent_post_mortems[-12:]

    def save(self, data: CrossSessionPlaybookData) -> None:
        """Write both the JSON playbook and the human-readable LE_CHONK_PLAYBOOK.md."""
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        data.updated_at = datetime.now(UTC).isoformat()
        json_path = self._json_path(data.rogue_version)
        json_path.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        self.markdown_path.write_text(self.render_markdown(data), encoding="utf-8")

    def build_prompt_snippet(
        self,
        rogue_version: str = "rogue-5.4.4",
        visible_monster_symbols: list[str] | None = None,
    ) -> str:
        """Build a compact (<150 tokens) cross-session knowledge block for the LLM prompt."""
        data = self.load_or_bootstrap(rogue_version)
        if data.sessions_analyzed == 0:
            return ""

        lines: list[str] = [
            f"- CROSS-SESSION PLAYBOOK ({data.sessions_analyzed} prior runs analyzed, "
            f"{data.total_monsters_defeated} total kills, best depth={data.max_depth_ever}):"
        ]

        # Include empirical stats for currently visible monsters first, or top encountered monsters
        vis_syms = set(visible_monster_symbols or [])
        relevant_entries: list[MonsterBestiaryEntry] = []
        for entry in data.bestiary.values():
            if entry.symbol in vis_syms:
                relevant_entries.append(entry)
        if not relevant_entries:
            relevant_entries = sorted(
                data.bestiary.values(),
                key=lambda e: (e.deaths_caused_to_player, e.combat_turns_observed),
                reverse=True,
            )[:4]

        if relevant_entries:
            m_summaries = [
                f"'{e.symbol}' ({e.name}: kills={e.kills_by_player}, deaths_caused={e.deaths_caused_to_player}, "
                f"max_dmg={e.max_single_turn_hp_loss}HP — {e.tactical_note})"
                for e in relevant_entries[:3]
            ]
            lines.append("  * Empirical Bestiary: " + "; ".join(m_summaries))

        for lesson in data.tactical_lessons[-3:]:
            lines.append(f"  * Learned Rule: {lesson}")

        return "\n".join(lines)

    @staticmethod
    def render_markdown(data: CrossSessionPlaybookData) -> str:
        """Render a rich Markdown report (`runs/LE_CHONK_PLAYBOOK.md`) of Le Chonk's cross-session learning."""
        md: list[str] = [
            "# Le Chonk's Recursive Dungeon Playbook",
            "",
            f"- **Target Rogue Version**: `{data.rogue_version}`",
            f"- **Sessions Analyzed**: `{data.sessions_analyzed}`",
            f"- **Total Turns Logged**: `{data.total_turns_logged}`",
            f"- **Total Monsters Defeated**: `{data.total_monsters_defeated}`",
            f"- **Max Dungeon Depth Reached**: `Level {data.max_depth_ever}`",
            f"- **Max Gold Collected in a Run**: `{data.max_gold_ever}`",
            f"- **Last Updated (UTC)**: `{data.updated_at}`",
            "",
            "> **Epistemic Hygiene Rule**: Seed-randomized properties (map coordinates, unidentified potion colors, and scroll titles) are strictly excluded from cross-session memory. Only version-invariant combat telemetry and tactical post-mortems are persisted.",
            "",
            "## 1. Distilled Cross-Session Tactical Rules",
            "",
        ]
        if data.tactical_lessons:
            for idx, rule in enumerate(data.tactical_lessons, 1):
                md.append(f"{idx}. {rule}")
        else:
            md.append("_No tactical rules distilled yet._")

        md.extend(
            [
                "",
                "## 2. Empirical Monster Bestiary (Learned from Live Combat)",
                "",
                "| Symbol | Monster | Combat Turns | Player Hits / Kills | Monster Hits / Deaths Caused | Max Single-Turn Damage | Tactical Rule |",
                "| :---: | :--- | :---: | :---: | :---: | :---: | :--- |",
            ]
        )
        for entry in sorted(data.bestiary.values(), key=lambda e: e.symbol):
            md.append(
                f"| `{entry.symbol}` | **{entry.name.title()}** | {entry.combat_turns_observed} | "
                f"{entry.hits_landed_by_player} / **{entry.kills_by_player}** | "
                f"{entry.hits_landed_on_player} / **{entry.deaths_caused_to_player}** | "
                f"{entry.max_single_turn_hp_loss} HP | {entry.tactical_note} |"
            )

        md.extend(
            [
                "",
                "## 3. Session Post-Mortem Log",
                "",
                "| Session ID | Turns | Max Depth | Rooms | Gold | Kills | Outcome | Post-Mortem Lesson |",
                "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
            ]
        )
        for pm in data.recent_post_mortems:
            md.append(
                f"| `{pm.session_id}` | {pm.turns_survived} | {pm.max_depth} | "
                f"{pm.rooms_discovered} | {pm.gold_collected} | {pm.monsters_defeated} | "
                f"`{pm.final_state}` | {pm.distilled_lesson} |"
            )

        md.append("")
        return "\n".join(md)
