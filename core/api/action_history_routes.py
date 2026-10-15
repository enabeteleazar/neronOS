from __future__ import annotations

import os
from pathlib import Path
from fastapi import APIRouter
from core.config.paths import NERON_DATA_DIR
from modules.cognitive.history import read_jsonl_tail


ACTION_HISTORY_PATH = Path(
    os.getenv(
        "NERON_ACTION_HISTORY_PATH",
        str(NERON_DATA_DIR / "action_history.jsonl"),
    )
)

router = APIRouter(tags=["action-history"])


def _read_history(limit: int = 20) -> list[dict]:
    return read_jsonl_tail(ACTION_HISTORY_PATH, limit=limit)


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
