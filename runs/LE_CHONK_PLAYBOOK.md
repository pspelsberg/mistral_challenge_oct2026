# Le Chonk's Recursive Dungeon Playbook

- **Target Rogue Version**: `epyx-1.49`
- **Sessions Analyzed**: `27`
- **Total Turns Logged**: `767`
- **Total Monsters Defeated**: `7`
- **Max Dungeon Depth Reached**: `Level 3`
- **Max Gold Collected in a Run**: `91`
- **Last Updated (UTC)**: `2026-10-29T18:07:13.606163+00:00`

> **Epistemic Hygiene Rule**: Seed-randomized properties (map coordinates, unidentified potion colors, and scroll titles) are strictly excluded from cross-session memory. Only version-invariant combat telemetry and tactical post-mortems are persisted.

## 1. Distilled Cross-Session Tactical Rules

1. FRONTIER DISCIPLINE RULE: Search dead-end '#' corridors once (steps=5), skip cleared rooms (0 items, 0 stairs, 0 unvisited doors), and prioritize UNEXPLORED '#' corridor branches.

## 2. Empirical Monster Bestiary (Learned from Live Combat)

| Symbol | Monster | Combat Turns | Player Hits / Kills | Monster Hits / Deaths Caused | Max Single-Turn Damage | Tactical Rule |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| `B` | **Bat** | 0 | 2 / **3** | 0 / **0** | 0 HP | Erratic fast flier: do not chase across open rooms; attack when adjacent. |
| `H` | **Hobgoblin** | 5 | 0 / **2** | 3 / **0** | 0 HP | Heavy Level-1 melee hitter (1d8 damage, deals up to 6-8 HP/hit; ~35% hero hit chance). At <= 6-7 HP without healing, trading melee swings is high-risk for one-shot death. Normal 1x speed: retreating into corridors or toward stairs does NOT give free hits (unlike 2x flyers). |
| `I` | **Ice Monster** | 1 | 2 / **0** | 1 / **0** | 0 HP | Freeze gaze skips your turns: avoid engaging at low HP. |

## 3. Session Post-Mortem Log

| Session ID | Turns | Max Depth | Rooms | Gold | Kills | Outcome | Post-Mortem Lesson |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `20261026_153153_709966_steam_epyx-1.49_live` | 10 | 1 | 2 | 0 | 0 | `PLAYING` | Reached depth 1, explored 2 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261026_154157_447938_steam_epyx-1.49_live` | 26 | 1 | 2 | 0 | 0 | `PLAYING` | Reached depth 1, explored 2 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261026_160450_439895_steam_epyx-1.49_live` | 40 | 1 | 3 | 0 | 0 | `PLAYING` | Reached depth 1, explored 3 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261026_161044_541327_steam_epyx-1.49_live` | 40 | 1 | 6 | 0 | 1 | `PLAYING` | Survived 40 turns, reached Level 1, discovered 6 rooms, defeated 1 monster(s), and collected 0 gold. |
| `20261026_173323_259960_steam_epyx-1.49_live` | 30 | 1 | 4 | 32 | 0 | `PLAYING` | Reached depth 1, explored 4 room(s), collected 32 gold, defeated 0 monster(s) (PLAYING). |
| `20261029_125607_805886_steam_epyx-1.49_live` | 50 | 3 | 5 | 91 | 3 | `PLAYING` | Survived 50 turns, reached Level 3, discovered 5 rooms, defeated 3 monster(s), and collected 91 gold. |
| `20261029_163535_951738_steam_epyx-1.49_live` | 15 | 1 | 1 | 0 | 0 | `GAME_OVER` | Reached depth 1, explored 1 room(s), collected 0 gold, defeated 0 monster(s) (GAME_OVER). |
| `20261029_163626_687510_steam_epyx-1.49_live` | 12 | 1 | 1 | 0 | 0 | `GAME_OVER` | Reached depth 1, explored 1 room(s), collected 0 gold, defeated 0 monster(s) (GAME_OVER). |
| `20261029_172851_183261_steam_epyx-1.49_live` | 8 | 1 | 2 | 0 | 0 | `PLAYING` | Reached depth 1, explored 2 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261029_174403_199010_steam_epyx-1.49_live` | 4 | 1 | 2 | 0 | 0 | `PLAYING` | Reached depth 1, explored 2 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261029_174913_925284_steam_epyx-1.49_live` | 7 | 1 | 1 | 0 | 0 | `PLAYING` | Reached depth 1, explored 1 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
| `20261029_180010_437279_steam_epyx-1.49_live` | 30 | 1 | 7 | 0 | 0 | `PLAYING` | Reached depth 1, explored 7 room(s), collected 0 gold, defeated 0 monster(s) (PLAYING). |
