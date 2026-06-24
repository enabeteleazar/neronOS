from __future__ import annotations

from fastapi import APIRouter

from modules.cognitive.reporter import get_cognitive_reporter
from modules.cognitive_core.core import CognitiveCore
from goal.goals.goal_manager import get_goal_manager
from core.modules.self_model import get_self_model
from goal.system.task_manager import get_task_manager
from modules.world_model.world_model import get_world_model

router = APIRouter(tags=["cognitive-report"])


@router.get("/cognitive-core/report")
async def cognitive_report() -> dict:
    self_model = get_self_model()
    self_model.collect_runtime()

    goal_system = get_goal_manager()
    task_manager = get_task_manager()
    world_model = get_world_model()

    core = CognitiveCore(
        self_model=self_model,
        world_model=world_model,
        goal_system=goal_system,
        task_manager=task_manager,
        memory=None,
    )

    state = core.to_dict()

    reporter = get_cognitive_reporter()
    report = reporter.generate_text_report(state)

    return {
        "report": report,
        "state": state,
    }
