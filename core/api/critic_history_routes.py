from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter


CRITIC_HISTORY_PATH = Path("/etc/neron/data/critic_history.jsonl")

router = APIRouter(tags=["critic-history"])


def _read_history(limit: int = 20) -> list[dict]:
    if not CRITIC_HISTORY_PATH.exists():
        return []

    lines = CRITIC_HISTORY_PATH.read_text(
        encoding="utf-8"
    ).splitlines()

    items: list[dict] = []

    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except Exception:
            continue

    return items


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
