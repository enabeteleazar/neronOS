from __future__ import annotations

from fastapi import APIRouter

from modules.context.neron_context import get_neron_context_status
from core.runtime.governor import get_runtime_governor

router = APIRouter(tags=["runtime-governor"])


@router.get("/runtime/governor/policy")
async def runtime_governor_policy() -> dict:
    governor = get_runtime_governor()

    return {
        "policy": governor.to_dict(),
        "global_context": get_neron_context_status(),
    }
