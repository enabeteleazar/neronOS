from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter


ACTION_HISTORY_PATH = Path("/etc/neron/data/action_history.jsonl")

router = APIRouter(tags=["action-history"])


def _read_history(limit: int = 20) -> list[dict]:
    if not ACTION_HISTORY_PATH.exists():
        return []

    lines = ACTION_HISTORY_PATH.read_text(
        encoding="utf-8"
    ).splitlines()

    items: list[dict] = []

    for line in lines[-limit:]:
        try:
            items.append(json.loads(line))
        except Exception:
            continue

    return items


@router.get("/actions/history")
async def actions_history(limit: int = 20) -> dict:
    return {
        "items": _read_history(limit=limit)
    }


@router.get("/actions/latest")
async def actions_latest() -> dict:
    items = _read_history(limit=1)

    return {
        "item": items[-1] if items else None
    }
