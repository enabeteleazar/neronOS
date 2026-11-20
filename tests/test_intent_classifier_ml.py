"""Classifieur d'intentions CamemBERT (7259a53, rétabli après 58ab382).

Deux familles de tests :

- rapides, sans le modèle : le routeur doit fonctionner exactement comme
  avant quand le classifieur est coupé ou indisponible, et la correspondance
  target/operation -> Intent ne doit jamais transformer une demande d'action
  (redémarrage, sauvegarde) en simple consultation d'état ;
- lents (marqueur slow), avec le modèle réel s'il est présent dans le cache
  HuggingFace local : `pytest -m slow tests/test_intent_classifier_ml.py`.
"""

from __future__ import annotations

import pytest

from core.pipeline.intent import intent_router as ir
from core.pipeline.intent import neron_intent_classifier as nic
from core.pipeline.intent.intent_router import Intent, IntentRouter


class _FakeML:
    def __init__(self, target: str, operation: str, method: str = "ml_classifier"):
        self.result = {"target": target, "operation": operation, "method": method}
        self.calls: list[str] = []

    def route(self, text: str) -> dict:
        self.calls.append(text)
        return self.result


@pytest.fixture
def fake_ml(monkeypatch):
    def install(target: str, operation: str, method: str = "ml_classifier") -> _FakeML:
        fake = _FakeML(target, operation, method)
        monkeypatch.setattr(nic, "get_ml_router", lambda: fake)
        return fake

    return install


async def test_disabled_classifier_changes_nothing(monkeypatch):
    monkeypatch.setenv("NERON_INTENT_CLASSIFIER", "0")
    assert nic.get_ml_router() is None
    result = await IntentRouter().route("raconte moi une histoire")
    assert result.intent == Intent.CONVERSATION
    assert "target" not in result.entities


async def test_ml_refines_generic_conversation(fake_ml):
    # « store » échappe à la cascade de mots-clés : sans le modèle, la phrase
    # partirait au LLM.
    fake = fake_ml("homeassistant", "close_cover", "lexical_rule")
    result = await IntentRouter().route(
        "baisse le store du salon", raw_query="Baisse le store du salon"
    )
    assert result.intent == Intent.HA_ACTION
    assert result.entities["operation"] == "close_cover"
    assert result.confidence == "high"
    # Le modèle reçoit la phrase d'origine, pas la version normalisée.
    assert fake.calls == ["Baisse le store du salon"]


async def test_keyword_cascade_keeps_priority(fake_ml):
    fake = fake_ml("goal", "create_agent")
    result = await IntentRouter().route("bonjour")
    assert result.intent == Intent.GREETING
    assert fake.calls == [], "le modèle ne doit pas être consulté"


@pytest.mark.parametrize("operation", ["restart_service", "backup"])
async def test_actions_are_never_downgraded_to_status(fake_ml, operation):
    fake_ml("system", operation)
    result = await IntentRouter().route("fais quelque chose sur le serveur")
    assert result.intent == Intent.CONVERSATION
    assert result.entities["operation"] == operation


async def test_classifier_failure_falls_back(monkeypatch):
    class _Broken:
        def route(self, _text):
            raise RuntimeError("boom")

    monkeypatch.setattr(nic, "get_ml_router", lambda: _Broken())
    result = await IntentRouter().route("raconte moi une histoire")
    assert result.intent == Intent.CONVERSATION


def test_unavailable_model_is_tolerated(monkeypatch):
    monkeypatch.setenv("NERON_INTENT_CLASSIFIER", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setattr(nic, "_router", None)
    monkeypatch.setattr(nic, "_unavailable_reason", None)
    monkeypatch.setattr(nic, "_model_id", lambda: "/chemin/inexistant/camembert")
    assert nic.get_ml_router() is None
    assert nic.classifier_status()["unavailable_reason"]


# ---------------------------------------------------------------------------
# Modèle réel
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_router():
    import os

    os.environ["NERON_INTENT_CLASSIFIER"] = "1"
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        router = nic.IntentRouter(model_id=nic.DEFAULT_MODEL_ID)
    except Exception as exc:
        pytest.skip(f"modèle CamemBERT absent du cache local : {exc}")
    finally:
        os.environ["NERON_INTENT_CLASSIFIER"] = "0"
    return router


@pytest.mark.slow
@pytest.mark.parametrize(
    ("phrase", "target", "operation"),
    [
        ("Allume la lumière du salon", "homeassistant", "turn_on_light"),
        ("Éteins la lampe du bureau", "homeassistant", "turn_off_light"),
        ("Ferme les volets de la chambre", "homeassistant", "close_cover"),
        ("Où en es-tu de tes objectifs ?", "goal", "get_status"),
        ("Crée un agent qui surveille mes sauvegardes", "goal", "create_agent"),
        ("Montre-moi les logs du service memory", "system", "get_logs"),
    ],
)
def test_real_model_predictions(real_router, phrase, target, operation):
    result = real_router.route(phrase)
    assert (result["target"], result["operation"]) == (target, operation)
