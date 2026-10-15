from __future__ import annotations

from fastapi import APIRouter

from modules.context.neron_context import get_neron_context_status
from core.runtime.governor import get_runtime_governor
from core.modules.runtime_response import build_runtime_response_async

router = APIRouter(tags=["runtime-governor"])


@router.get("/runtime/governor/policy")
async def runtime_governor_policy() -> dict:
    governor = get_runtime_governor()
    policy = governor.to_dict()
    global_context = get_neron_context_status()
    natural = await build_runtime_response_async(policy, global_context)

    return {
        "response": natural["response"],
        "runtime_llm_used": natural["llm_used"],
        "policy": policy,
        "global_context": global_context,
    }
