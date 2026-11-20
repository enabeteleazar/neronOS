# tests/test_intent_router.py
"""
Tests unitaires — IntentRouter
Couvre : normalisation, intents principaux, priorités, cas limites.
"""

import pytest

from core.pipeline.intent.intent_router import IntentRouter, Intent, _normalize


@pytest.fixture
def router():
    return IntentRouter()


class TestNormalize:
    def test_lowercase(self):
        assert _normalize("BONJOUR") == "bonjour"

    def test_strip_accents(self):
        assert _normalize("éàü") == "eau"

    def test_strip_and_lower(self):
        assert _normalize("  Quelle Heure  ") == "quelle heure"

    def test_empty(self):
        assert _normalize("") == ""

    def test_already_clean(self):
        assert _normalize("test") == "test"


class TestIntentTime:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "quelle heure est-il ?",
        "Quelle heure est-il",
        "Il est quelle heure ?",
        "dis-moi quelle heure il est s'il te plaît",
    ])
    async def test_time_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.TIME_QUERY
        assert result.confidence in ["medium", "high"]


class TestIntentWeather:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "cherche la météo à Paris",
        "météo demain",
    ])
    async def test_weather_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.WEATHER_QUERY
        assert result.confidence in ["medium", "high"]


class TestIntentNews:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "recherche les actualités",
        "news du jour",
        "actualité technologie",
    ])
    async def test_news_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.NEWS_QUERY
        assert result.confidence in ["medium", "high"]


class TestIntentIdentity:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "Qui es-tu ?",
        "Quelle est ta mission ?",
        "Comment fonctionnes-tu ?",
        "Explique ton architecture",
    ])
    async def test_identity_questions_use_identity_intent(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.IDENTITY_QUERY
        assert result.confidence in ["medium", "high"]


class TestIntentWeb:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "cherche python asyncio",
        "recherche docker compose",
    ])
    async def test_web_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent in [
            Intent.WEB_SEARCH,
            Intent.CONVERSATION,
            Intent.CODE,
        ]


class TestIntentHA:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "allume la lumière du salon",
        "éteins le thermostat",
        "lumiere cuisine",
    ])
    async def test_ha_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.HA_ACTION
        assert result.confidence in ["medium", "high"]


class TestIntentCode:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "génère un fichier Python",
        "écris un script bash",
        "améliore ce code",
        "revue de code",
    ])
    async def test_code_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.CODE
        assert result.confidence in ["medium", "high"]


class TestIntentCodeAudit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "analyse ton code",
        "inspecte ton code",
        "audite ton code",
        "qualite de ton code",
        "analyse le code de neron",
    ])
    async def test_audit_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent in [
            Intent.CODE_AUDIT,
            Intent.CODE,
        ]
        assert result.confidence in ["medium", "high"]


class TestIntentPersonality:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "sois plus sympa",
    ])
    async def test_personality_keywords(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.PERSONALITY_FEEDBACK
        assert result.confidence in ["medium", "high"]


class TestIntentAgentList:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "liste les agents",
        "liste agents",
        "affiche les agents",
        "affiche moi les agents",
        "agents disponibles",
        "quels agents sont disponibles ?",
        "montre les agents",
        "montre moi les agents",
    ])
    async def test_agent_list_variants(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.AGENT_LIST
        assert result.confidence in ["medium", "high"]


class TestIntentConversation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", [
        "comment ça va ?",
        "tu peux m'aider ?",
        "test",
        "hello world",
        "explique-moi la photosynthèse",
    ])
    async def test_fallback_conversation(self, router, query):
        result = await router.route(query)
        assert result.intent == Intent.CONVERSATION
        assert result.confidence in ["medium", "high"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["bonjour", "salut", "bonjour neron"])
    async def test_greetings_are_not_generic_conversation(self, router, query):
        # Une salutation a son propre intent : l'orchestrateur y repond
        # localement (route smalltalk) au lieu d'appeler le LLM.
        # Voir tests/test_smalltalk_stays_local.py.
        result = await router.route(query)
        assert result.intent == Intent.GREETING


class TestIntentEmpty:
    @pytest.mark.asyncio
    async def test_empty_query(self, router):
        result = await router.route("")
        assert result.intent == Intent.CONVERSATION
        assert result.confidence in ["low", "medium"]


class TestIntentPriority:
    @pytest.mark.asyncio
    async def test_time_over_conversation(self, router):
        result = await router.route("dis-moi quelle heure il est s'il te plaît")
        assert result.intent == Intent.TIME_QUERY

    @pytest.mark.asyncio
    async def test_weather_over_web(self, router):
        result = await router.route("cherche la météo à Paris")
        assert result.intent == Intent.WEATHER_QUERY

    @pytest.mark.asyncio
    async def test_news_over_web(self, router):
        result = await router.route("recherche les actualités")
        assert result.intent == Intent.NEWS_QUERY
