"""Le Core (Agent Patron) ne dépend pas de Goal ni du Goal Engine.

Goal et le Goal Engine appartiennent au Manager de chantier. Le Core ne doit
ni les importer, ni les initialiser, ni monter leurs routes.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core"
FORBIDDEN_ROOTS = {"goal", "goal_engine"}


def _forbidden_imports(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            if name.split(".")[0] in FORBIDDEN_ROOTS:
                found.append((node.lineno, name))
    return found


def _core_sources() -> list[Path]:
    return [
        path
        for path in sorted(CORE.rglob("*.py"))
        if "tests" not in path.relative_to(CORE).parts
        and "__pycache__" not in path.parts
    ]


def test_core_has_no_direct_import_of_goal_or_goal_engine():
    violations = {
        str(path.relative_to(ROOT)): hits
        for path in _core_sources()
        if (hits := _forbidden_imports(path))
    }

    assert violations == {}


def test_goal_engine_is_not_hosted_by_the_core():
    assert not (CORE / "goal_engine").exists()


def test_core_app_neither_initialises_goal_manager_nor_mounts_goal_routes():
    source = (CORE / "app.py").read_text(encoding="utf-8")

    assert "GoalManager" not in source
    assert "goal.goals" not in source
    assert "goal.projects" not in source
    assert "get_goal_background_runner" not in source


def test_core_does_not_expose_goal_coupled_routes():
    api = CORE / "api"
    for name in (
        "planner_routes",
        "task_routes",
        "goal_task_routes",
        "cognitive_core_routes",
        "cognitive_report_routes",
        "self_model_context_routes",
    ):
        assert not (api / f"{name}.py").exists(), name
