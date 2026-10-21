# Task Checklist — ROGUE AGENT ("Le Chonk wants to play")
> **Architektur**: Vertical Slice Architecture (VSA) + Hexagonal Ports & Adapters  
> **Gameplay-Modell**: `mistral-large-4` (Mistral AI Studio API)  
> **Deadline**: 29. Oktober 2026, 23:59 Uhr

---

## Milestone 0 — Environment Discovery & Projekt-Fundament (VSA Baseline)
- [x] **M0.1**: Read-only Environment Discovery durchführen (OS, Display/Wayland/Xwayland, Python 3.14 + `uv`, Steam, App ID 1443430, `gcc`/`ncurses`, Mistral API Key Status)
- [x] **M0.2**: Machbarkeits-, Versionsdifferenz- und Risikoanalyse im Implementierungsplan dokumentieren
- [x] **M0.3**: Projekt-Scaffolding mit `uv` (`pyproject.toml`, `.env.example`, `.gitignore`, `task.md` im Workspace) initialisieren
- [x] **M0.4**: Shared Hexagonal Kernel (`src/rogue_agent/shared/`) implementieren:
  - [x] `domain.py` (`GameObservation`, `GameAction`, `GameState`, `ActionType`, `Direction`, `VisibleStatus`)
  - [x] `ports.py` (`GameBackendPort`, `GameplayAgentPort`, `MemoryPort`, `TelemetryPort`, `ControlProfilePort`)
  - [x] `config.py` (Pydantic Settings für `.env`, Budgets, Timeouts, Max-Turns, Pfade)
- [x] **M0.5**: Versionsspezifische Control Profiles (`src/rogue_agent/shared/controls/`) implementieren:
  - [x] `base.py` (Abstrakte Basisklasse & Multi-Step-Sequenz-Validierung)
  - [x] `epyx_149.py` (Steam Epyx Rogue v1.49 Tastenbelegung gemäß offiziellem Handbuch)
  - [x] `terminal_rogue.py` (Rogue 5.4.4 vi-Keys `hjklyubn`, Prompts, `--More--`, Inventar-Dialoge)
- [x] **M0.6**: VSA Slice `features/environment_discovery` implementieren (`rogue-agent --doctor` CLI-Check)
- [x] **M0.7**: Architektur-Fitness-Test (`tests/architecture/test_vsa_boundaries.py`) erstellen (prüft strikte VSA-Slice-Isolation)

---

## Milestone 1 — Steam MVP (`features/steam_backend`)
- [x] **M1.1**: Steam Launcher & Prozess-/Fenster-Detektor für App ID `1443430` (Epyx Rogue 1.49 unter Proton/DOSBox/Xwayland) implementieren
- [x] **M1.2**: X11/Xwayland Window Manager (`window_manager.py`) mit Fokus-Verifikation, Mutter-Frame-Filter und Sicherheits-Stopp bei Fokusverlust
- [x] **M1.3**: Client-Area Screenshot Capture (`capture.py`) via X11/MSS + 29px DOSBox-Titlebar-Stripping & 480×300 32-Color PNG-Kompression
- [x] **M1.4**: Sichere Tastatur-Injektion (`input_injector.py`) ausschließlich an das verifizierte Spielfenster
- [x] **M1.5**: Visuelle Zustandserkennung & **80×25 CP437-zu-ASCII-Grid-Konverter** (`visual_state.py`) mit automatischem Screenshot-Backup
- [x] **M1.6**: Unit-, Xwayland-Integrations- & Live-Steam-E2E-Tests für `steam_backend` ausführen

---

## Milestone 2 — Terminal MVP (`features/terminal_backend`)
- [x] **M2.1**: Lokales Build-Skript (`scripts/build_terminal_rogue.sh`) für **Rogue 5.4.4** (BSD-3-Clause) mit `gcc` + `ncurses` nach `bin/rogue` erstellen und ausführen
- [x] **M2.2**: PTY-Prozessmanager (`pty_process.py`) mit fester 80×24 Terminal-Geometrie, non-blocking Read und sauberem Shutdown implementieren
- [x] **M2.3**: Virtueller ANSI/Curses-Screen-Buffer (`screen_parser.py`) auf Basis von `pyte` zur exakten 80×24-Bildschirmrekonstruktion implementieren
- [x] **M2.4**: Parser für Statuszeile (Level, Gold, HP, Str, Arm, Exp, Hunger), Top-Message-Zeile (`--More--`), Inventar-/Auswahl-Screens und Grabstein (`RIP`)
- [x] **M2.5**: `TerminalGameAdapter` (`adapter.py`) über das gemeinsame `GameBackendPort`-Interface fertigstellen
- [x] **M2.6**: Automatisierte Level-1 (Unit) und Level-2 (echter PTY-Start, Bewegung, Screen-Update) Tests ausführen

---

## Milestone 3 — Mistral Large 4 Integration (`features/mistral_brain`)
- [x] **M3.1**: Offizielles `mistralai` SDK (`mistralai.client.Mistral`) anbinden mit festem Modell `mistral-large-4`
- [x] **M3.2**: Pydantic-Schema `MistralActionDecision` (`schemas.py`) für Structured Outputs (`chat.parse`) inkl. Fallback-Mechanismus bei ungültigen Antworten
- [x] **M3.3**: Prompt-Builder (`prompts.py`) für beide Backends:
  - [x] Multimodal-Prompt (Screenshot + validierte Metadaten + Memory) für Steam Rogue 1.49
  - [x] Rekonstruierter 80×24 ASCII-Screen + validierte Metadaten + Memory für Terminal Rogue 5.4.4
  - [x] Strikte Wahrung der Entscheidungsautonomie von Mistral Large 4 (keine versteckten Spielinformationen, kein eingebauter Solver)
- [x] **M3.4**: End-to-End Gameplay-Loop in `features/game_loop_cli` für beide Backends im `--dry-run` & Mock-SDK-Modus verifiziert
- [x] **M3.5**: Live-Gameplay-Run mit echtem `MISTRAL_API_KEY` (`mistral-large-4`) nach Hinterlegung des Keys in `.env` und Kosten-Freigabe ausführen

---

## Milestone 4 — Zuverlässigkeit, Memory & Safety (`features/memory`, `features/telemetry_eval`)
- [x] **M4.1**: Bounded Agent Memory (`features/memory/store.py`) implementieren:
  - [x] Trennung von beobachteten Fakten (`FACT`) vs. Hypothesen (`HYPOTHESIS`)
  - [x] Besuchte Orte, bekannte Gefahren, wichtige Items, fehlgeschlagene Aktionen (Loop-/Wand-Detektion)
  - [x] Strikte Token-/Längenbegrenzung zur Vermeidung von Kostenexplosionen
- [x] **M4.2**: Resilience & Budget Guard (`features/mistral_brain/resilience.py`):
  - [x] Konfigurierbare Timeouts, Retries mit Exponential Backoff, Rate-Limit-Handling
  - [x] Hard-Limits für `max_turns`, `max_api_calls`, `max_session_seconds`, `max_budget_usd`
  - [x] Emergency-Stop (`SIGINT` / `KeyboardInterrupt`) und automatisches Pausieren bei API-Fehlern
- [x] **M4.3**: Telemetrie & Session-Logging (`features/telemetry_eval`):
  - [x] JSONL-Turn-Logs + Artefakt-Speicherung (Screenshots / Terminal-Frames)
  - [x] Getrennte Auswertung nach Rogue-Version (`epyx-1.49` vs. `rogue-5.4.4`)

---

## Milestone 5 — Kompetitive Verbesserungen (Optional nach stabilem Dual-Backend)
- [x] **M5.1**: Verbesserte Prompt-Struktur für Kampf-/Flucht-Abwägung und Ressourcenmanagement (Nahrung, Tränke, Schriftrollen)
- [x] **M5.2**: 4-Schichten Token-Effizienz (`0-Token UI Bypass`, `steps=1..5` Short-Horizon Queue mit Wand-/Monster-Interrupt, `fast_move`, `80×25` ASCII-Primary + Backup-Screenshot)
- [x] **M5.3**: Reproduzierbare Benchmark-Auswertung (`rogue-agent --benchmark-report`) inkl. `rooms_discovered`, `monsters_defeated`, `death_condition`

---

## Milestone 6 — Wettbewerbs-Abgabe & Dokumentation
- [x] **M6.1**: Englische `README.md` (Architektur, VSA-Struktur, Setup für Steam & Terminal, Versionsunterschiede, CLI-Dokumentation, Lizenz- & Dependency-Nachweis)
- [x] **M6.2**: Englische Kurzbeschreibung des Projekts für die Einreichung ("Le Chonk wants to play")
- [x] **M6.3**: Automatischer `< 2 min` Demo-GIF-Exporter (`rogue-agent --export-gif`) implementiert (bereit für Live-Run mit `mistral-large-4`)
