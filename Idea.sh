# ROGUE AGENT — Dual-Backend Autonomous AI Gaming Harness

## ROLE AND DEVELOPMENT ENVIRONMENT

You are my senior AI systems engineer, software architect, implementation partner, and quality assurance engineer.

You are working in **Google Antigravity**, using **Gemini 4 Argon** as the development model selected in the Antigravity model selector.

Your mission is to build a working, competition-ready, autonomous Rogue-playing AI agent for the Mistral AI community challenge:

**"Le Chonk wants to play"**

The agent must support Rogue running through **Steam** and a native **terminal environment**.

Development communication and progress reports must be in German. Source code, README files, API documentation, and competition submission materials must be in English.

Think critically, make justified architectural decisions, and prioritize real-world functionality over unnecessary complexity.

---

# 1. COMPETITION REQUIREMENTS

Competition deadline: October 29, 2026, 23:59.

Build an original, functional, interesting gaming harness.

Mandatory gameplay model:

- Provider: Mistral AI Studio API
- Model ID: `mistral-large-4`
- Model: Mistral Large 4 Preview

Gemini 4 Argon is used to DEVELOP the application.

Mistral Large 4 is used to PLAY Rogue.

Never confuse these responsibilities.

Do not substitute another model for gameplay without explicit permission.

Evaluation criteria:

1. Complexity
2. Gameplay performance
3. Reproducibility

Submission deliverables:

- Public GitHub repository containing the harness source code
- Comprehensive setup README
- Demo video or GIF of no more than 2 minutes
- Short English project description
- Documentation of development tools, open-source dependencies, and human contributors

The competition permits only one entry per person. Team participation is not explicitly confirmed in the provided rules; do not assume an official team policy.

Do not submit entries automatically.

---

# 2. FUNDAMENTAL PRODUCT REQUIREMENT

The project must support TWO execution backends:

## Backend A — Steam Rogue

Target:

https://store.steampowered.com/app/1443430/Rogue/

Steam App ID: 1443430

This is Epyx Rogue v1.49, a DOS-based commercial version.

Important characteristics:

- Distributed through Steam
- Windows is the officially supported platform
- Uses DOSBox
- Runs in a graphical game window
- Uses DOS-era graphical/text characters
- Requires actual keyboard interaction
- May display additional startup and resume dialogs

The harness must connect to a legally installed copy of the game.

Do not bundle or redistribute proprietary Steam game files.

## Backend B — Terminal Rogue

The second backend must allow Rogue to run as a terminal-based application.

Requirements:

- Genuine terminal input/output
- Programmatic keyboard interaction
- Terminal screen capture
- ANSI/ASCII state handling
- Reliable detection of game state changes

Investigate suitable native terminal Rogue implementations.

Do NOT assume that Rogue 5.4.4 and Epyx Rogue 1.49 are functionally identical.

If a compatible native terminal port of the Steam edition is legally and technically unavailable, use a clearly identified alternative Rogue implementation.

Document all version differences.

Prefer Windows-compatible terminal execution where practical. WSL may be supported when technically appropriate.

Do not claim that the Steam DOS executable itself can run directly in a native terminal unless this has been demonstrated.

Both backends are required project goals, not optional architectural placeholders.

---

# 3. ENVIRONMENT DISCOVERY

Before writing implementation code:

1. Detect the operating system.
2. Identify the installed Python version.
3. Check whether Steam is installed.
4. Determine whether Steam Rogue is installed locally.
5. Discover the actual game installation path.
6. Identify the actual game executable and launcher behavior.
7. Check available terminal capabilities.
8. Check whether WSL or an alternative terminal environment is available.
9. Verify the selected terminal Rogue implementation and its license.
10. Verify the current Mistral Python SDK interface and required API features.

Do not invent installation paths.

Do not assume the game is already installed.

If Steam Rogue is missing, explain the prerequisite and request user intervention.

Never purchase, download paid software, or modify Steam account settings without explicit authorization.

### Environment Discovery Deliverable

Produce a short report containing:

- Operating system
- Steam availability
- Steam Rogue installation status
- Terminal Rogue implementation
- Dependencies
- Technical limitations
- Recommended architecture
- First executable milestone

Proceed with implementation after resolving critical blockers.

---

# 4. TARGET ARCHITECTURE

Implement a clean hexagonal or ports-and-adapters architecture.

Core components:

1. Game environment interface
2. Steam game adapter
3. Terminal game adapter
4. Observation and perception layer
5. Mistral gameplay agent
6. Action execution and validation
7. Agent memory
8. Telemetry and evaluation
9. CLI application

The Mistral gameplay agent must be independent of the concrete game backend.

Example architecture:

```text
                  MISTRAL LARGE 4
                   GAMEPLAY AGENT
                         |
                  Agent Controller
                         |
                Observation / Action
                     Interface
                         |
              +----------+----------+
              |                     |
         Steam Adapter        Terminal Adapter
              |                     |
         Steam / DOSBox         Native Terminal
              |                     |
        Epyx Rogue 1.49       Terminal Rogue
```

Use dependency injection where useful.

Avoid creating a large framework when simple typed Python interfaces are sufficient.

---

# 5. COMMON GAME INTERFACE

Define a backend-neutral game interface.

Suggested operations:

- `start()`
- `observe()`
- `execute_action(action)`
- `detect_game_state()`
- `reset()`
- `close()`
- `get_diagnostics()`

Do not assume every backend supports reset or deterministic seeding.

Create typed models for:

### GameObservation

Include:

- Backend identifier
- Rogue version
- Timestamp
- Current screen representation
- Visible status information
- Current UI mode
- Recent game messages
- Previous action result
- Observation uncertainty

Allow optional screenshot and terminal-text representations.

### GameAction

Include:

- Action type
- Direction, where applicable
- Relevant item identifier
- Optional permitted action parameters

### GameState

Represent states such as:

- NOT_STARTED
- START_MENU
- CHARACTER_NAME_ENTRY
- PLAYING
- MORE_PROMPT
- INVENTORY
- ITEM_SELECTION
- PAUSED
- GAME_OVER
- VICTORY
- UNKNOWN

Adapt these states according to actual observed game behavior.

Maintain explicit separation between information visible to the player and information inferred by the harness.

---

# 6. STEAM GAME ADAPTER

Implement a robust Steam-specific adapter.

## Launching

Investigate the supported Steam launch mechanism.

Prefer launching through the installed Steam client and the correct App ID.

Do not bypass Steam licensing or authentication.

Support detecting an already-running game.

## Window Management

Implement:

- Game-window discovery
- Window identification
- Focus verification
- Client-area screenshot capture
- Configurable screenshot cropping
- Resolution and scaling handling
- Keyboard input injection through suitable desktop automation
- Input release and timeout handling
- Detection of a missing, minimized, or obstructed window

Investigate suitable libraries such as `pyautogui`, `mss`, and OS-specific window APIs.

Choose libraries based on verified compatibility.

Never send keystrokes blindly to an unrelated application.

Stop safely if the game window cannot be verified.

## Visual Perception

The primary Steam observation must be based on the actual visible game screen.

Support sending screenshots to Mistral Large 4 through a verified multimodal API request.

Optionally implement image preprocessing:

- Crop unused borders
- Normalize image dimensions
- Improve legibility without changing game information
- Detect relevant screen regions

Do not require an OCR pipeline as a prerequisite for basic gameplay.

If additional parsing is useful, implement it incrementally and test accuracy.

Be aware that Epyx Rogue uses DOS-era characters and symbols that may differ from native terminal Rogue representations.

## Startup State Handling

Support:

- Steam game launch
- New-game or resume selection
- Initial game title screen
- Character naming
- Help screens
- Confirmation dialogs
- Game-over screens

Use explicit, validated state transitions.

Do not assume that every keypress represents a gameplay turn.

---

# 7. TERMINAL GAME ADAPTER

Implement a native terminal adapter independently from the Steam adapter.

Preferred implementation:

- Python subprocess management
- PTY-based interaction where supported
- Terminal screen buffering
- ANSI escape sequence handling
- Keyboard command execution
- Terminal dimension management

Consider `pexpect`, `pywinpty`, or other appropriate tools based on the actual operating system.

Verify library and terminal compatibility rather than assuming it.

The adapter must:

1. Start the selected Rogue executable.
2. Capture its actual visible output.
3. Maintain a stable terminal-screen representation.
4. Send commands.
5. Detect prompts and state changes.
6. Handle process termination.
7. Recognize game-over conditions.

Do not simply collect stdout lines if the application uses cursor positioning or screen rewriting.

Reconstruct the actual terminal screen as faithfully as necessary.

Document the supported operating systems and terminal implementation.

---

# 8. VERSION-SPECIFIC CONTROL PROFILES

Implement separate control mappings when needed.

Example:

```text
controls/
    base.py
    epyx_149.py
    terminal_rogue.py
```

Control mappings must be derived from the selected game's real documentation and verified gameplay.

For Steam Epyx Rogue, use the official manual:

https://store.steampowered.com/manual/1443430

Verify:

- Eight-direction movement
- Inventory
- Item use
- Searching
- Resting
- Staircase interactions
- Confirmations
- Help screens
- Game-over actions

The controller must support multi-step commands where the game requests additional input.

Avoid sending unsupported commands.

Do not assume that control profiles are interchangeable across Rogue versions.

---

# 9. MISTRAL GAMEPLAY AGENT

Use the official Mistral API.

Mandatory model:

`mistral-large-4`

Use the official Python SDK where suitable.

The model should:

- Perceive the visible game state.
- Identify relevant objects.
- Understand immediate threats.
- Select tactical objectives.
- Choose gameplay actions.
- Remember important observations.
- React to unexpected results.
- Revise plans based on new information.

### Model Input

For Steam:

- Actual game screenshot
- Validated optional metadata
- Current objective
- Relevant memory
- Recent actions and results

For Terminal:

- Actual reconstructed terminal screen
- Validated optional metadata
- Current objective
- Relevant memory
- Recent actions and results

Avoid supplying hidden game information.

### Model Output

Prefer structured actions using supported function calling or structured outputs.

Possible action representation:

```json
{
  "action": "move",
  "direction": "north",
  "decision_summary": "Explore the visible corridor",
  "confidence": 0.81
}
```

Validate actions with Pydantic or an equivalent schema.

The example is illustrative; use only fields supported by the actual implementation.

Do not request hidden chain-of-thought. A concise decision summary is sufficient for telemetry and debugging.

If the model returns an invalid action, request correction or apply a documented safe fallback.

Never execute arbitrary shell commands generated by the gameplay model.

---

# 10. AUTONOMY AND DECISION OWNERSHIP

This is a core competition design principle.

The harness may:

- Start and observe the game.
- Translate commands.
- Parse visible state.
- Maintain bounded memory.
- Validate actions.
- Detect failed execution.
- Handle technical recovery.

Mistral must remain responsible for meaningful gameplay decisions.

Examples:

- Where to explore
- Whether to fight
- Whether to retreat
- Which item to use
- Which resource to conserve
- When to descend deeper

Do not embed a complete autonomous Rogue solver inside the harness.

If pathfinding or macro-actions are introduced later:

- Make them transparent.
- Keep them interruptible.
- Require Mistral to choose objectives.
- Document deterministic assistance.
- Measure their impact.

Prioritize transparent agent behavior over hidden automation.

---

# 11. MEMORY AND STATE MANAGEMENT

Implement minimal, useful memory first.

Keep track of:

- Recent observations
- Current goal
- Visited locations
- Known threats
- Important items
- Recent failed actions
- Significant events

Distinguish facts from hypotheses.

Avoid transmitting unlimited gameplay history with every request.

Use bounded summaries and retain raw telemetry separately.

Prevent runaway token usage.

If coordinate-based memory is implemented, verify how coordinates behave across maps, screen redraws, and backend versions.

---

# 12. LATENCY, COST AND RELIABILITY

This project uses a remote API to play a turn-based game.

Optimize for reliability and reasonable cost.

Implement:

- Configurable request timeout
- Retry limits
- Exponential backoff
- Rate-limit handling
- Maximum gameplay turns
- Maximum API calls
- Maximum session duration
- Configurable API spending budget
- Emergency stop command
- Automatic pause on API errors
- Graceful termination

Do not treat an estimated cost as a guaranteed billing limit.

Stop when a configured limit is reached or spending cannot be estimated reliably.

Use a configurable short action horizon.

After unexpected events, re-observe before continuing.

Never implement long, uncontrolled sequences of blind gameplay actions.

Reduce unnecessary context and screenshot processing where possible without sacrificing essential observations.

Only execute billable API tests after user approval.

---

# 13. CLI REQUIREMENTS

Provide one CLI entry point supporting both backends.

Desired interface:

```bash
rogue-agent --backend steam
rogue-agent --backend terminal
rogue-agent --backend steam --dry-run
rogue-agent --backend terminal --max-turns 100
```

These are target CLI commands, not claims about already implemented functionality.

Implement the actual commands and document them.

The CLI should display:

- Selected backend
- Game version
- Model ID
- Current game state
- Current agent objective
- Last action
- Turn count
- Estimated API usage
- Runtime errors
- Session summary

A lightweight terminal dashboard is desirable but not required for the initial MVP.

Do not build a web dashboard until basic gameplay is functional in both backends.

---

# 14. TESTING STRATEGY

Use three verification levels.

## Level 1 — Unit Tests

Test:

- Action validation
- Screen parsing
- Control mappings
- State transitions
- Memory updates
- Budget limits
- Error handling

Use recorded observations and mock API responses.

## Level 2 — Integration Tests

Test:

- Real terminal process startup
- PTY interaction
- Actual keyboard commands
- Steam game-window discovery
- Real screenshot capture
- UI state detection
- Game termination handling

Some Steam tests may require manual confirmation because of desktop interaction.

Clearly mark tests as automated, interactive, or manually verified.

## Level 3 — End-to-End Tests

Test the complete loop:

Observation → Mistral → Action → Game → New Observation

Run the loop on both Steam and Terminal backends.

Do not declare a backend functional merely because its mock tests pass.

Save actual logs and evidence.

If full integration cannot be tested because of missing local prerequisites, report it explicitly.

---

# 15. PERFORMANCE EVALUATION

Collect measurable statistics.

Suggested metrics:

- Successful game starts
- Valid gameplay actions
- Invalid-action percentage
- Turns survived
- Dungeon depth reached
- Rooms discovered where measurable
- Monsters defeated where observable
- Death conditions
- Latency per decision
- Token usage
- Estimated API cost
- Human interventions

Record the Rogue version for every run.

Do not directly compare gameplay scores across different Rogue versions as if they had identical difficulty.

For comparisons, prefer repeated runs within the same backend and game version.

If deterministic seeds are available, use them.

Otherwise document the limits of reproducibility.

Never invent experimental results.

---

# 16. SECURITY AND LICENSING

Requirements:

- Store secrets in environment variables.
- Use `.env.example`.
- Never commit API keys.
- Restrict the gameplay model to predefined game actions.
- Do not expose unrestricted shell execution.
- Avoid transmitting unrelated desktop content in screenshots.
- Do not redistribute Steam game binaries.
- Respect licenses of terminal Rogue implementations.
- Track dependencies and third-party code attribution.
- Do not modify or publish proprietary game assets without permission.
- Do not modify Steam security or licensing mechanisms.

The published repository must contain the original harness code and clear instructions for obtaining legitimate game dependencies.

---

# 17. DEVELOPMENT PRIORITIES

The deadline is October 29, 2026.

Do not implement every feature simultaneously.

## Milestone 0 — Technical Feasibility

Verify:

- Local platform
- Steam Rogue installation and launch
- Steam screenshot capture
- Steam keyboard control
- Terminal Rogue installation and launch
- Terminal input/output
- Mistral API compatibility

Deliver a short feasibility report.

## Milestone 1 — Steam MVP

Demonstrate:

- Start Steam Rogue
- Capture real game screen
- Detect gameplay state
- Execute a movement command
- Capture the resulting screen

Do this without requiring the full AI architecture.

## Milestone 2 — Terminal MVP

Demonstrate:

- Start terminal Rogue
- Read visible terminal state
- Execute a movement command
- Observe the resulting state

Use the shared game interface.

## Milestone 3 — Mistral Integration

Connect Mistral Large 4.

Demonstrate a genuine model-controlled gameplay loop in BOTH backends.

This is the primary competition-ready milestone.

## Milestone 4 — Reliability

Add:

- Game-state recovery
- Action validation
- Bounded memory
- Session limits
- Logging
- Automated tests

## Milestone 5 — Competitive Improvements

Only after both backends work:

- Improve exploration
- Improve combat decisions
- Reduce API calls
- Evaluate short macro-actions
- Introduce additional memory strategies
- Benchmark improvements

## Milestone 6 — Submission

Prepare:

- GitHub repository
- README
- Dependency and license documentation
- Steam setup instructions
- Terminal setup instructions
- Architecture overview
- Reproducible demonstration
- Performance results
- English project description
- Two-minute demo video or GIF

If time becomes limited, preserve the working end-to-end system rather than introducing untested complexity.

---

# 18. DEFINITION OF DONE

A backend is only considered functional when:

1. The actual game starts.
2. The actual visible game state can be observed.
3. A valid action can be executed.
4. Mistral Large 4 can select that action.
5. The real game responds.
6. The new state is observable.
7. Multiple agent-controlled turns can run without manual intervention.
8. Errors and game-over conditions are handled.
9. The result can be reproduced using documented steps.

The overall project is complete when both backends meet these conditions and the competition deliverables are prepared.

Partial functionality must be reported transparently.

---

# 19. WORKING PRINCIPLES

Follow these rules throughout implementation:

1. Verify assumptions before depending on them.
2. Prefer working code over speculative architecture.
3. Make small, testable changes.
4. Run tests after significant changes.
5. Never fabricate tests, performance, or API results.
6. Explain important trade-offs.
7. Keep a concise progress log.
8. Report blockers immediately.
9. Avoid unnecessary dependencies.
10. Keep user-facing progress reports in German.
11. Do not publish anything without approval.
12. Do not incur API charges without approval.
13. Do not silently change game versions or models.
14. Preserve the separation between harness mechanics and Mistral gameplay decisions.

You may continue independently through reversible local implementation steps.

Ask for approval only when required by missing credentials, paid API access, external publication, game installation, legal uncertainty, or consequential changes to the environment.

---

# 20. START NOW

Begin with:

1. Inspect the workspace and operating system.
2. Check whether Steam Rogue (App ID 1443430) is installed.
3. Inspect the Steam runtime and its DOSBox environment without modifying the installation.
4. Research suitable terminal-native Rogue implementations.
5. Verify the official Mistral Large 4 API integration.
6. Define the common game interface.
7. Identify technical differences between Steam Rogue and terminal Rogue.
8. Produce a concise risk analysis and implementation plan.

Then implement Milestone 1 and Milestone 2 using small verifiable steps.

Prioritize a working dual-backend gameplay harness over advanced optional features.

**SUCCESS MEANS REAL GAMEPLAY, REAL MISTRAL DECISIONS, REAL OBSERVATIONS, AND REPRODUCIBLE RESULTS — NOT JUST CODE THAT LOOKS COMPLETE.**
