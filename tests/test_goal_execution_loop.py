from __future__ import annotations

import pytest

from goal_engine import GoalExecutionLoop


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_loop_succeeds_on_first_attempt():
    loop = GoalExecutionLoop(max_iterations=3)

    result = await loop.run(lambda iteration: {"attempt": iteration}, lambda _result: {"ok": True})

    assert result.status == "completed"
    assert result.iterations == 1


async def test_loop_fixes_then_succeeds():
    fixed = {"value": False}
    loop = GoalExecutionLoop(max_iterations=3)

    async def fix(_result, _verification, _iteration):
        fixed["value"] = True

    result = await loop.run(
        lambda iteration: {"attempt": iteration},
        lambda _result: {"ok": fixed["value"]},
        fix,
    )

    assert result.status == "completed"
    assert result.iterations == 2
    assert "fixing" in result.history[0]["states"]


async def test_loop_blocks_at_max_iterations_and_never_finishes_failed():
    loop = GoalExecutionLoop(max_iterations=2)

    result = await loop.run(lambda iteration: iteration, lambda _result: {"ok": False})

    assert result.status == "blocked"
    assert result.status != "failed"
    assert result.iterations == 2
    assert result.next_action
