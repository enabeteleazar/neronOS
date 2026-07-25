"""Homelab catalog and slot assignment for the Self Model."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.config.paths import NERON_DATA_DIR
from core.modules.self_model.state import _read_state, _write_state

CATALOG_PATH = Path(
    os.getenv(
        "NERON_HOMELAB_CATALOG_PATH",
        str(NERON_DATA_DIR / "homelab_catalog.json"),
    )
)


def _read_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"items": []}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except Exception:
        return {"items": []}


def get_catalog() -> dict[str, Any]:
    return _read_catalog()


def get_homelab_slots() -> dict[str, str]:
    state = _read_state()
    homelab = state.get("homelab") or {}
    return dict(homelab.get("slots") or {})


def set_homelab_slot(unit_id: str, catalog_id: str | None) -> dict[str, str]:
    catalog = _read_catalog()
    valid_ids = {item.get("id") for item in catalog.get("items", [])}
    if catalog_id is not None and catalog_id not in valid_ids:
        raise ValueError(f"catalog_id '{catalog_id}' introuvable dans le catalogue")

    state = _read_state()
    homelab = dict(state.get("homelab") or {})
    slots = dict(homelab.get("slots") or {})
    if catalog_id is None:
        slots.pop(unit_id, None)
    else:
        slots[unit_id] = catalog_id
    homelab["slots"] = slots
    state["homelab"] = homelab
    _write_state(state)
    return slots


def homelab_snapshot() -> dict[str, Any]:
    return {
        "catalog": _read_catalog().get("items", []),
        "slots": get_homelab_slots(),
    }
