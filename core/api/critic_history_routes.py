from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter
from modules.cognitive.history import read_jsonl_tail


CRITIC_HISTORY_PATH = Path("/etc/neron/data/critic_history.jsonl")

router = APIRouter(tags=["critic-history"])


def _read_history(limit: int = 20) -> list[dict]:
    return read_jsonl_tail(CRITIC_HISTORY_PATH, limit=limit)


@router.get("/critic/history")
async def critic_history(limit: int = 20) -> dict:
    return {
        "items": _read_history(limit=limit)
    }


@router.get("/critic/latest")
async def critic_latest() -> dict:
    items = _read_history(limit=1)

    return {
        "item": items[-1] if items else None
    }
