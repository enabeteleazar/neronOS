from __future__ import annotations

from fastapi import APIRouter

from modules.cognitive_core.core import CognitiveCore
from modules.cognitive_core.core import CognitiveCore
from goal.goals.goal_manager import get_goal_manager
from modules.self_model.self_model import get_self_model
from goal.system.task_manager import get_task_manager
from modules.world_model.world_model import get_world_model

router = APIRouter(tags=["cognitive-core"])

@router.get("/cognitive-core/state")
async def cognitive_core_state() -> dict:
    self_model = get_self_model()
    self_model.refresh()

    goal_model = get_goal_manager()
    task_manager = get_task_manager()
    world_model = get_world_model()

    core = CognitiveCore(
        self_model=self_model,
        world_model=world_model,
        goal_system=goal_model,
        task_manager=task_manager,
        memory=None,
    )
    return core.to_dict()
