from __future__ import annotations

from typing import Any

from integrations.pc_remote.errors import PCRemoteError
from integrations.pc_remote.service import get_pc_remote_service
from tools.models import ToolResult, ToolSpec


PC_REMOTE_TOOL_SLUG = "pc_remote"


def tool_spec() -> ToolSpec:
    return ToolSpec(
        name="pc_remote",
        slug=PC_REMOTE_TOOL_SLUG,
        description=(
            "Permet à Néron d'ouvrir/fermer des applications autorisées sur un "
            "PC distant connecté au même tailnet, via son agent pc_remote."
        ),
        inputs={
            "action": "list|open|close",
            "device_id": "Identifiant du PC distant (registre pc_remote.devices)",
            "app_id": "Identifiant de l'application autorisée sur ce PC",
        },
        outputs={"response": "Réponse naturelle", "data": "Résultat structuré"},
        safety={"allow_system_commands": False, "requires_network": True},
        source="builtin",
        metadata={
            "aliases": [
                "pc distant", "ordinateur distant", "ouvre sur mon pc",
                "ferme sur mon pc", "commande mon pc",
            ],
        },
    )


async def execute(payload: dict[str, Any] | None = None) -> ToolResult:
    payload = dict(payload or {})
    action = str(payload.get("action") or "list")
    device_id = str(payload.get("device_id") or "")
    service = get_pc_remote_service()
    try:
        if action == "list":
            result = await service.list_apps(device_id)
            return ToolResult(
                ok=True,
                response="Applications disponibles listées.",
                data=dict(result or {}),
            )
        if action == "open":
            app_id = str(payload.get("app_id") or "")
            result = await service.open_app(device_id, app_id)
            return ToolResult(
                ok=True,
                response=f"'{app_id}' ouvert sur {device_id}.",
                data=dict(result or {}),
            )
        if action == "close":
            app_id = str(payload.get("app_id") or "")
            result = await service.close_app(device_id, app_id)
            return ToolResult(
                ok=True,
                response=f"'{app_id}' fermé sur {device_id}.",
                data=dict(result or {}),
            )
        return ToolResult(ok=False, error=f"unsupported_action:{action}")
    except PCRemoteError as exc:
        return ToolResult(ok=False, response=exc.user_message, error=exc.user_message)
