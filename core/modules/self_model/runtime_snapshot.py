"""Runtime and services status snapshot for the Self Model."""

from __future__ import annotations

from typing import Any


def _runtime_from_status(status: dict[str, Any]) -> dict[str, Any]:
    resources = status.get("resources") or {}
    return {
        "cpu_usage": resources.get("cpu_pct"),
        "ram_usage": resources.get("ram_pct"),
        "disk_usage": resources.get("disk_pct"),
        "source": "status_module",
    }


def _services_from_status(status: dict[str, Any]) -> dict[str, Any]:
    modules = status.get("modules") or {}
    items = {"core": status.get("core", "unknown")}
    items.update({f"module:{name}": state for name, state in modules.items()})
    items["goal_pipeline"] = status.get("goal_pipeline", "unknown")

    active = [name for name, state in items.items() if state in {"online", "loaded", "available"}]
    inactive = [name for name, state in items.items() if name not in active]

    return {
        "items": items,
        "summary": {
            "total": len(items),
            "active": len(active),
            "inactive": len(inactive),
            "all_active": len(inactive) == 0,
        },
    }
