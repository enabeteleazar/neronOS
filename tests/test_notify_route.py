"""POST /notify : contrat HTTP de neronReminders (cf. neronReminders/scheduler.py).

Perdu lors de la réintégration du Core (58ab382) : chaque rappel recevait un
404. La route ne doit répondre « sent » que si Telegram a accepté le message,
sinon 503 pour que Reminders retente.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.api import notify_routes

API_KEY = "test-api-key"  # cf. tests/conftest.py


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("core.config.settings.API_KEY", API_KEY, raising=False)
    app = FastAPI()
    app.include_router(notify_routes.router)
    return TestClient(app)


@pytest.fixture
def telegram(monkeypatch):
    sent: list[tuple[str, str]] = []
    state = {"ok": True}

    async def fake_send(message: str, level: str = "info") -> bool:
        sent.append((message, level))
        return state["ok"]

    monkeypatch.setattr(
        "agents.builtin.communication.telegram_agent.send_notification", fake_send
    )
    return sent, state


def _reminders_call(client, **overrides):
    # Requête exacte de neronReminders/scheduler.py::_notify_one
    body = {"message": "Rendez-vous chez le dentiste", "level": "info", "channel": "telegram"}
    body.update(overrides)
    return client.post("/notify", json=body, headers={"Authorization": f"Bearer {API_KEY}"})


def test_reminder_is_sent(client, telegram):
    sent, _ = telegram
    response = _reminders_call(client)
    assert response.status_code == 200
    assert response.json() == {"status": "sent", "channel": "telegram"}
    assert sent == [("Rendez-vous chez le dentiste", "info")]


def test_inactive_bot_is_not_reported_as_sent(client, telegram):
    _, state = telegram
    state["ok"] = False
    assert _reminders_call(client).status_code == 503


def test_unknown_channel_is_rejected(client, telegram):
    assert _reminders_call(client, channel="pigeon").status_code == 400


def test_requires_api_key(client, telegram):
    response = client.post("/notify", json={"message": "x"})
    assert response.status_code in {401, 403}
