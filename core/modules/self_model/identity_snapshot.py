"""Identity snapshot for the Self Model."""

from __future__ import annotations

from typing import Any

from core.identity import get_identity


def _safe_identity() -> dict[str, Any]:
    try:
        return dict(get_identity())
    except Exception as exc:
        return {"name": "Néron", "status": "unavailable", "error": str(exc)}
