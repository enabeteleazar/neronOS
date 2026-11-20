"""Passerelles en HTTP : le Core n'importe plus le paquet gateways.

Depuis le retrait des sous-modules (16/10), `gateways` n'est plus livré avec
neronOS : chaque demande de passerelle échouait en « No module named
'gateways' ». Le registre, l'état des connexions et les jetons OAuth vivent
sur la machine de Gateways ; le Core les consulte via son API HTTP.
"""

from __future__ import annotations

import httpx
import pytest

from server.common import gateways_client as gc

_GOOGLE = {
    "connector": {
        "id": "google", "name": "Google", "domains": ["mail", "calendar"],
        "protocol": "oauth", "auth_type": "oauth_device", "connect_hint": "Lance le flux OAuth.",
    },
    "state": {"connector_id": "google", "status": "connected", "updated_at": "2026-11-20T00:00:00Z"},
}


def _client(handler, **kwargs) -> gc.GatewaysClient:
    return gc.GatewaysClient(
        base_url="http://gateways.test",
        transport=httpx.MockTransport(handler),
        async_transport=httpx.MockTransport(handler),
        **kwargs,
    )


# ── Client HTTP ─────────────────────────────────────────────────────────────


def test_lookup_parses_connectors_and_sends_the_key(monkeypatch):
    monkeypatch.setenv("NERON_GATEWAYS_API_KEY", "cle-gw")
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("X-Gateways-Key")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"domain": "mail", "connectors": [_GOOGLE]})

    [(connector, state)] = _client(handler).find_by_domain("mail")
    assert (connector.id, connector.name, state.status) == ("google", "Google", "connected")
    assert seen == {"key": "cle-gw", "path": "/gateways/domain/mail"}


def test_unknown_connector_is_none():
    assert _client(lambda r: httpx.Response(404, json={})).get_connector("x") is None


@pytest.mark.parametrize("code", [401, 403, 500, 503])
def test_auth_and_server_errors_mean_unavailable(code):
    with pytest.raises(gc.GatewaysUnavailable):
        _client(lambda r: httpx.Response(code, text="non")).find_by_domain("mail")


def test_network_error_means_unavailable():
    def handler(request):
        raise httpx.ConnectError("refusé", request=request)

    with pytest.raises(gc.GatewaysUnavailable):
        _client(handler).find_by_domain("mail")


async def test_calendar_action_and_its_refusal():
    ok = _client(lambda r: httpx.Response(200, json={"events": [], "text": "Aucun événement."}))
    assert (await ok.google_calendar_upcoming())["text"] == "Aucun événement."

    refused = _client(lambda r: httpx.Response(409, json={"detail": "Google n'est pas connecte"}))
    with pytest.raises(gc.GatewayActionFailed, match="pas connecte"):
        await refused.google_calendar_upcoming()


def test_address_comes_from_server_yaml(monkeypatch, tmp_path):
    plan = tmp_path / "neron.server.yaml"
    plan.write_text("nodes:\n  gateways: {host: 192.168.1.80, port: 8070}\n", encoding="utf-8")
    monkeypatch.delenv("NERON_GATEWAYS_URL", raising=False)
    monkeypatch.setenv("NERON_SERVER_CONFIG", str(plan))
    assert gc.GatewaysClient().base_url == "http://192.168.1.80:8070"
    monkeypatch.setenv("NERON_GATEWAYS_URL", "http://autre:9000/")
    assert gc.GatewaysClient().base_url == "http://autre:9000"


# ── Moteur de décision et résolveur ─────────────────────────────────────────


class _Unreachable:
    def find_by_domain(self, domain):
        raise gc.GatewaysUnavailable("refusé")

    def get_connector(self, connector_id):
        raise gc.GatewaysUnavailable("refusé")


class _Connected:
    def __init__(self, status="connected"):
        self.status = status

    def find_by_domain(self, domain):
        return [gc._connector({**_GOOGLE, "state": {**_GOOGLE["state"], "status": self.status}})]

    def get_connector(self, connector_id):
        return gc._connector(_GOOGLE)[0]

    async def google_calendar_upcoming(self, max_results=5):
        return {"events": [{"summary": "Dentiste"}], "text": "Voici tes prochains événements : Dentiste"}


@pytest.fixture
def gateways(monkeypatch):
    def install(fake):
        monkeypatch.setattr(gc, "get_gateways_client", lambda: fake)

    return install


async def _resolve(text):
    from modules.capabilities.models import CapabilityRequest
    from modules.capabilities.resolver import CapabilityResolver

    return await CapabilityResolver().resolve(CapabilityRequest(text=text))


async def test_unreachable_gateways_is_not_reported_as_no_gateway(gateways):
    gateways(_Unreachable())
    result = await _resolve("Montre mes mails")
    assert result.decision.decision == "gateway_unavailable"
    assert result.status == "failed"
    assert "injoignable" in result.response


async def test_not_connected_gateway_proposes_connection(gateways):
    gateways(_Connected(status="configured_disconnected"))
    result = await _resolve("Montre mes mails")
    assert result.decision.decision == "propose_gateway_connection"
    assert "Je peux me connecter à Google" in result.response


async def test_calendar_is_read_through_gateways(gateways):
    gateways(_Connected())
    result = await _resolve("Montre mon calendrier")
    assert result.status == "completed"
    assert "Dentiste" in result.response


async def test_orchestrator_answers_clearly_when_gateways_is_down(gateways):
    from core.pipeline.orchestrator import CoreOrchestrator

    gateways(_Unreachable())
    result = await CoreOrchestrator().handle("Montre mes mails")
    assert result.decision.selected_route == "resolver"
    assert "injoignable" in result.response
    assert "No module named" not in result.response
