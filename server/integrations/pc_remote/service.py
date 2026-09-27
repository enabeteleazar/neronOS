from __future__ import annotations

from typing import Any, Callable

from integrations.pc_remote.client import PCRemoteClient
from integrations.pc_remote.config import PCRemoteDevice, load_devices
from integrations.pc_remote.errors import PCRemoteAppNotFound, PCRemoteDeviceNotFound
from integrations.pc_remote.nlu import detect_action, resolve_app, resolve_device


class PCRemoteService:
    def __init__(
        self,
        devices: dict[str, PCRemoteDevice] | None = None,
        client_factory: Callable[[PCRemoteDevice], PCRemoteClient] = PCRemoteClient,
    ) -> None:
        self._devices = devices if devices is not None else load_devices()
        self._client_factory = client_factory

    def _client(self, device_id: str) -> PCRemoteClient:
        device = self._devices.get(device_id)
        if device is None:
            raise PCRemoteDeviceNotFound(f"PC distant inconnu : {device_id}")
        return self._client_factory(device)

    async def health(self, device_id: str) -> Any:
        return await self._client(device_id).health()

    async def list_apps(self, device_id: str) -> Any:
        return await self._client(device_id).list_apps()

    async def open_app(self, device_id: str, app_id: str) -> Any:
        return await self._client(device_id).open_app(app_id)

    async def close_app(self, device_id: str, app_id: str) -> Any:
        return await self._client(device_id).close_app(app_id)

    async def execute_natural(self, text: str) -> dict[str, Any]:
        """Interprete une commande en langage naturel (open/close/list) et
        l'execute. Resout le device par id/nom (ou le seul device configure),
        et l'app contre la liste LIVE exposee par l'agent (/apps) — jamais
        contre `apps:` dans neron.yaml, purement indicatif et potentiellement
        perime par rapport a ce que l'agent expose reellement (auto-discovery
        + overrides) sur la machine distante.
        """
        device = resolve_device(text, self._devices)
        if device is None:
            raise PCRemoteDeviceNotFound("Aucun PC distant configure ne correspond a la demande.")

        action = detect_action(text)

        apps_result = await self.list_apps(device.id)
        apps = list(apps_result.get("apps") or [])
        app_ids = [str(app["id"]) for app in apps if isinstance(app, dict) and app.get("id")]

        if action == "list":
            if apps:
                listed = ", ".join(
                    f"{app['id']} ({'en cours' if app.get('running') else 'arrete'})"
                    for app in apps
                )
                response = f"Sur {device.name} : {listed}."
            else:
                response = f"Aucune application configuree sur {device.name}."
            return {"action": "list", "device_id": device.id, "apps": apps, "response": response}

        app_id = resolve_app(text, app_ids)
        if app_id is None:
            raise PCRemoteAppNotFound(
                f"Aucune application connue de {device.name} ne correspond a la demande."
            )

        if action == "open":
            await self.open_app(device.id, app_id)
            return {
                "action": "open",
                "device_id": device.id,
                "app_id": app_id,
                "response": f"'{app_id}' ouvert sur {device.name}.",
            }

        await self.close_app(device.id, app_id)
        return {
            "action": "close",
            "device_id": device.id,
            "app_id": app_id,
            "response": f"'{app_id}' ferme sur {device.name}.",
        }


_SERVICE: PCRemoteService | None = None


def get_pc_remote_service() -> PCRemoteService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = PCRemoteService()
    return _SERVICE
