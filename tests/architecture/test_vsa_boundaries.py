"""Architectural Fitness Function enforcing Vertical Slice Architecture (VSA) boundaries.

Rule:
- Feature slices under `rogue_agent.features.<slice>` may import from `rogue_agent.shared.*`
  and from their own slice `rogue_agent.features.<slice>.*`.
- Only `rogue_agent.features.game_loop_cli` (the Composition Root / CLI Orchestrator)
  is permitted to import across multiple feature slices to wire dependencies together.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

FEATURES_ROOT = Path(__file__).resolve().parents[2] / "src" / "rogue_agent" / "features"
COMPOSITION_ROOT_SLICE = "game_loop_cli"


def _iter_imported_modules(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


@pytest.mark.unit
def test_vertical_slice_isolation() -> None:
    """Verify that no non-composition feature slice imports internals of another feature slice."""
    assert FEATURES_ROOT.is_dir(), f"Features root not found: {FEATURES_ROOT}"

    violations: list[str] = []
    for slice_dir in sorted(FEATURES_ROOT.iterdir()):
        if not slice_dir.is_dir() or slice_dir.name.startswith("__"):
            continue
        slice_name = slice_dir.name
        if slice_name == COMPOSITION_ROOT_SLICE:
            continue

        for py_file in sorted(slice_dir.rglob("*.py")):
            for mod in _iter_imported_modules(py_file):
                if mod.startswith("rogue_agent.features."):
                    parts = mod.split(".")
                    if len(parts) >= 3:
                        target_slice = parts[2]
                        if target_slice != slice_name:
                            rel_path = py_file.relative_to(FEATURES_ROOT.parents[2])
                            violations.append(
                                f"{rel_path} (slice '{slice_name}') illegally imports "
                                f"'{mod}' from slice '{target_slice}'"
                            )

    assert not violations, "VSA slice boundary violations detected:\n" + "\n".join(violations)
