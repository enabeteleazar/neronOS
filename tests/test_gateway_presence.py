"""Présence multi-appareils du gateway WebSocket (f8c390b, perdue avec 58ab382).

Le Dashboard (neronDashboard/src/hooks/useNeron.ts) envoie `device.announce`
juste après `gateway.auth` et écoute `presence.changed` : un seul appareil
« possède » l'avatar à la fois. Sans ces méthodes, l'annonce recevait une
erreur et la présence ne basculait jamais.
"""

from __future__ import annotations

import pytest

from core.gateway.gateway import ConnectedClient, NeronGateway


class _Session:  # SessionStore / SkillRegistry / AgentRouter factices
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture
def gateway():
    gw = NeronGateway(
        agent_router=_Session(), session_store=_Session(), skill_registry=_Session()
    )
    gw.events: list[dict] = []

    async def capture(payload: dict) -> None:
        gw.events.append(payload)

    gw.broadcast = capture
    return gw


def _client(name: str) -> ConnectedClient:
    return ConnectedClient(ws=None, client_id=name, authenticated=True)


def _presence(gw) -> list[dict]:
    return [e for e in gw.events if "presence.changed" in str(e)]


def test_dashboard_methods_are_registered(gateway):
    assert "device.announce" in gateway._handlers
    assert "presence.ping" in gateway._handlers


async def test_first_announced_device_gets_presence(gateway):
    pc = _client("c1")
    await gateway._handlers["device.announce"](pc, {"device_id": "pc", "device_label": "Bureau"})
    assert gateway._active_device_id == "pc"
    assert len(_presence(gateway)) == 1

    phone = _client("c2")
    await gateway._handlers["device.announce"](phone, {"device_id": "tel", "device_label": "Téléphone"})
    # Premier arrivé, premier servi : la seconde annonce ne vole pas la présence.
    assert gateway._active_device_id == "pc"
    assert len(_presence(gateway)) == 1


async def test_ping_from_other_device_switches_presence(gateway):
    pc, phone = _client("c1"), _client("c2")
    await gateway._handlers["device.announce"](pc, {"device_id": "pc", "device_label": "Bureau"})
    await gateway._handlers["device.announce"](phone, {"device_id": "tel", "device_label": "Téléphone"})

    await gateway._handlers["presence.ping"](phone, {})
    assert gateway._active_device_id == "tel"
    last = _presence(gateway)[-1]
    assert "tel" in str(last) and "pc" in str(last)  # nouvel appareil + précédent

    await gateway._handlers["presence.ping"](phone, {})  # déjà actif : rien
    assert len(_presence(gateway)) == 2


async def test_announce_requires_device_id(gateway):
    with pytest.raises(ValueError):
        await gateway._handlers["device.announce"](_client("c1"), {})
