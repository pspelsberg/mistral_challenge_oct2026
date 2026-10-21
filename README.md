# ROGUE AGENT — Dual-Backend Autonomous AI Gaming Harness
> **Mistral AI Community Challenge**: *"Le Chonk wants to play"*  
> **Mandatory Gameplay Model**: `mistral-large-4` (Mistral Large 4 Preview via Mistral AI Studio API)  
> **Development Environment**: Google Antigravity (developed with Gemini 4 Argon)

---

## Short Project Description (Competition Submission Summary)

**Rogue Agent ("Le Chonk wants to play")** is a dual-backend autonomous AI gaming harness that enables **Mistral Large 4 (`mistral-large-4`)** to play the classic dungeon crawler *Rogue* across two distinct runtime environments through a unified Hexagonal & Vertical Slice Architecture (VSA):
1. **Backend A (`steam`) — Steam Epyx Rogue v1.49 (App ID `1443430`)**: Connects to a legally installed Steam copy of Epyx Rogue running in DOSBox, verifies X11/Xwayland window identity and input focus, captures client-area frames without leaking desktop content, deterministically reconstructs the **80×25 CP437-to-ASCII dungeon grid** (`@`, `.`, `+`, `|`, `-`, `#`, `%`, `:`, `?`, `*`, `M`), and sends ASCII-primary observations to `mistral-large-4` with automatic compact PNG screenshot backup whenever top-bar messages, menus, or ambiguities occur.
2. **Backend B (`terminal`) — Native Terminal Rogue 5.4.4**: Spawns classic UNIX Rogue 5.4.4 inside a dedicated 80×24 POSIX pseudo-terminal (PTY), reconstructs the exact curses screen state via a `pyte` virtual terminal buffer, and streams structured ASCII observations to `mistral-large-4`.

All meaningful tactical and strategic decisions—where to explore, when to fight or retreat, which potions or scrolls to use, and when to descend deeper into the Dungeons of Doom—belong strictly to **Mistral Large 4**.

---

## Architecture: Vertical Slice Architecture (VSA) + Hexagonal Ports

The codebase combines **Hexagonal Ports & Adapters** (`src/rogue_agent/shared/`) with self-contained **Vertical Feature Slices** (`src/rogue_agent/features/`). Slice isolation is continuously enforced via an AST-based architectural fitness test (`tests/architecture/test_vsa_boundaries.py`).

```text
src/rogue_agent/
├── shared/                        # Hexagonal Kernel (Ports, Domain Contracts, Config, Control Profiles)
│   ├── domain.py                  # GameObservation, GameAction, GameState, ActionType, Direction
│   ├── ports.py                   # GameBackendPort, GameplayAgentPort, MemoryPort, TelemetryPort
│   ├── config.py                  # Pydantic Settings & safety guardrails (enforce mistral-large-4)
│   └── controls/                  # Version-specific Control Profiles
│       ├── base.py                # Multi-step command builder & parameter validation
│       ├── epyx_149.py            # Steam Epyx Rogue v1.49 (Cursor/Keypad & DOSBox controls)
│       └── terminal_rogue.py      # Terminal Rogue 5.4.4 (Classic vi-keys hjklyubn)
└── features/                      # Vertical Feature Slices
    ├── environment_discovery/     # Slice 0: OS, Steam 1443430, Xwayland, Terminal binary & SDK probe
    ├── terminal_backend/          # Slice 1: 80x24 PTY process + pyte virtual screen parser
    ├── steam_backend/             # Slice 2: X11/Xwayland window manager, client capture & safe key injector
    ├── mistral_brain/             # Slice 3: Official mistralai SDK client, structured outputs & BudgetGuard
    ├── memory/                    # Slice 4: Bounded agent memory (Verified Facts vs. Model Hypotheses)
    ├── telemetry_eval/            # Slice 5: JSONL turn logger, frame artifacts & version-segregated reports
    └── game_loop_cli/             # Slice 6: AgentGameController & unified CLI (`rogue-agent`)
```

---

## Documented Version Differences: Steam Epyx Rogue 1.49 vs. Terminal Rogue 5.4.4

Do **not** treat Epyx Rogue 1.49 and UNIX Rogue 5.4.4 as functionally identical:

| Feature | Backend A: Steam Epyx Rogue v1.49 | Backend B: Terminal Rogue 5.4.4 |
| :--- | :--- | :--- |
| **Distribution & License** | Commercial Steam release (App ID `1443430`, Subvert Limited / Epyx) | Open-Source BSD-3-Clause (Roguelike Restoration Project) |
| **Runtime** | `ROGUE.EXE` inside DOSBox (`rogue.conf`, graphical window) | Native ELF binary (`./bin/rogue`) linked against `libncursesw` in an 80×24 PTY |
| **Visual Symbols** | IBM PC CP437 graphical glyphs (`☺` Hero, `∙` Floor, `╬` Door, `▒` Passage, `═`/`║` Wall, `≡` Staircase, `♣` Food, `¡` Potion, `♪` Scroll) | 7-bit ASCII characters (`@` Hero, `.` Floor, `+` Door, `#` Passage, `\|`/`-` Wall, `%` Staircase, `:` Food, `!` Potion, `?` Scroll) |
| **Status Line Format** | `Level:1  Hits:14(17)  Str:16(16)  Gold:29  Armor:5  Guild Novice  12:28` | `Level: 1  Gold: 0  Hp: 12(12)  Str: 16(16)  Arm: 4  Exp: 1/0` |
| **Control Profile** | `Epyx149ControlProfile` (`Up`/`Down`/`Left`/`Right`/`Home`/`Prior`/`End`/`Next`, `f`+dir fast move, `Space` for `More`/`Cont`) | `TerminalRogueControlProfile` (`hjklyubn` 8-way vi-keys, `HJKLYUBN` fast move, `Space` for `--More--`) |
| **Startup Flow** | Title screen (`ROGUE.PIC`) → Press key → Character Name dialog → Level 1 | Starts directly on Dungeon Level 1 (`ROGUEOPTS=name=LeChonk`) |

Benchmark statistics in `telemetry_eval/report.py` are strictly segregated by `backend:rogue_version` (`steam:epyx-1.49` vs. `terminal:rogue-5.4.4`).

---

## Setup Instructions

### 1. Prerequisites
- **Python**: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- **Terminal Backend**: `gcc`, `make`, `git`, and `ncurses` development headers (`libncursesw`)
- **Steam Backend**: Legally installed copy of [Rogue on Steam (App ID 1443430)](https://store.steampowered.com/app/1443430/Rogue/) and an active X11/Xwayland display (`DISPLAY=:0`)
- **Mistral API**: A valid `MISTRAL_API_KEY` with access to `mistral-large-4`

### 2. Install Python Environment & Build Terminal Rogue 5.4.4
```bash
# 1. Sync Python dependencies via uv
uv sync --extra dev

# 2. Compile Terminal Rogue 5.4.4 (BSD-3-Clause) into ./bin/rogue
./scripts/build_terminal_rogue.sh

# 3. Configure environment variables
cp .env.example .env
# Edit .env and set MISTRAL_API_KEY=...
```

### 3. Verify Environment Readiness
```bash
uv run rogue-agent --doctor
```

---

## CLI Usage

```bash
# Run Environment Discovery Doctor
uv run rogue-agent --doctor

# Terminal Backend — Dry-Run (zero API cost, verifies PTY + pyte + action loop)
uv run rogue-agent --backend terminal --dry-run --max-turns 20

# Steam Backend — Dry-Run (zero API cost, verifies X11 window + screenshot + key injection)
uv run rogue-agent --backend steam --dry-run --max-turns 10

# Terminal Backend — Autonomous Mistral Large 4 Gameplay
uv run rogue-agent --backend terminal --max-turns 100 --max-budget-usd 0.50

# Steam Backend — Autonomous Mistral Large 4 Gameplay
uv run rogue-agent --backend steam --max-turns 100 --max-budget-usd 0.50

# Aggregate Version-Segregated Benchmark Metrics
uv run rogue-agent --benchmark-report

# Export a <2 minute competition submission demo.gif from the latest recorded run
uv run rogue-agent --export-gif
```

---

## Testing Strategy (3 Verification Levels)

```bash
# Run full test suite (VSA Fitness + Level 1 Unit + Level 2 Integration + Level 3 E2E)
uv run pytest tests/ -v

# Run VSA Architectural Boundary Fitness Check only
uv run pytest tests/architecture/test_vsa_boundaries.py -v
```

---

## Credits, Open-Source Dependencies & Licensing

- **Harness Source Code**: MIT License (Original work created for the Mistral AI *"Le Chonk wants to play"* challenge)
- **Gameplay Model**: Mistral AI (`mistral-large-4`) via `mistralai` Python SDK (Apache-2.0)
- **Development Assistant**: Developed in Google Antigravity using Gemini 4 Argon
- **Terminal Rogue 5.4.4**: Copyright (C) 1980-1985, 1999 Michael Toy, Ken Arnold, Glenn Wichman; Roguelike Restoration Project (BSD-3-Clause License, built locally via `scripts/build_terminal_rogue.sh`)
- **Steam Epyx Rogue v1.49**: Proprietary commercial software distributed via Steam (App ID `1443430`). **No proprietary Steam or Epyx game binaries are bundled or redistributed in this repository.**
- **Core Python Libraries**: `pydantic` (MIT), `pyte` (LGPLv3), `pillow` (MIT-CMU), `mss` (MIT), `python-xlib` (LGPLv2+), `rich` (MIT)
