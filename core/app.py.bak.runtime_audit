from __future__ import annotations

from core.api.self_model_context_routes import router as self_model_router
from core.api.selfmodel_routes import router as selfmodel_router
from core.api.runtime_governor_routes import router as runtime_governor_router
from core.api.world_model_routes import router as world_model_router
from goal.goals.routes import router as goals_router
from tools.routes import router as tools_router
from modules.scheduler.routes import router as scheduler_router
from agents.runtime.routes import router as agent_runtime_router
from modules.capabilities.routes import router as capabilities_router
from core.api.task_routes import router as task_router
from core.api.goal_task_routes import router as goal_task_router
from core.api.cognitive_core_routes import router as cognitive_core_router
from core.api.cognitive_report_routes import router as cognitive_report_router
from core.api.action_history_routes import router as action_history_router
from core.api.critic_history_routes import router as critic_history_router
from modules.code_awareness.routes import router as code_awareness_router
from goal.projects.routes import router as projects_router
from modules.evolution.routes import router as evolution_router



# =========================
# INIT LOGGING (PRIORITAIRE)
# =========================

from core.logging.setup import logger

from core.modules.memory.router import router as memory_router

logger.info("Booting Néron Core...")

# =========================
# IMPORTS STANDARD
# =========================

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import psutil
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

# =========================
# IMPORTS NÉRON (APRÈS LOGGING)
# =========================

from core.agent_registry import get_external_agent_registry, get_logger
from core.api.auth import verify_api_key
from core.infrastructure.auth import (
    AuthenticationError,
    authenticate_request,
    is_local_registry_route,
    is_public_route,
    publish_auth_failure,
    publish_auth_success,
)
from core.infrastructure.event_bus import event_bus as infrastructure_event_bus
from core.infrastructure.gateway import GatewayError, proxy_request
from core.infrastructure.health import health_state
from core.infrastructure.logging import log_event
from core.infrastructure.registry import ServiceRegistration, service_registry
from core.infrastructure.topology import build_topology, get_topology_service
from core.a2a import a2a_client
from core.providers import ensure_default_providers, provider_registry

from core.config import settings
from modules.capabilities.resolver import CapabilityResolver
from core.identity import get_identity
from core.pipeline.routing.agent_router import (
    AgentRouter,
    LLMConfig,
    RouterToolBindings,
)
from core.gateway.gateway import GatewayConfig, NeronGateway
from modules.scheduler.routes import router as scheduler_router
from modules.scheduler.scheduler import get_task_scheduler
# scheduler_stop handled via get_task_scheduler().stop
from modules.sessions import SessionStore
from modules.skills import SkillRegistry
from core.pipeline.intent.intent_router import IntentRouter
from core.pipeline.orchestrator import (
    CoreOrchestrator,
    get_core_orchestrator,
    set_core_orchestrator,
)
from modules.self_model.monitor import get_self_monitor

from core.config_loader import config
HA_CONFIG = config.get("home_assistant", config.get("homeassistant", {}))
BASE_URL = HA_CONFIG.get("url")
TOKEN = HA_CONFIG.get("token")
SYNC_INTERVAL = HA_CONFIG.get("sync_interval", 60)

from core.api.planner_routes import router as planner_router

_external_agents = get_external_agent_registry()
CodeAgent = _external_agents.agent_class("agents.builtin.dev.code_agent.agent", "CodeAgent")
CodeAuditAgent = _external_agents.agent_class("agents.builtin.dev.code_audit_agent", "CodeAuditAgent")
HAAgent = _external_agents.agent_class("agents.builtin.automation.ha_agent", "HAAgent")
LLMAgent = _external_agents.agent_class("agents.builtin.core.llm_agent", "LLMAgent")
MemoryAgent = _external_agents.agent_class("agents.builtin.core.memory_agent", "MemoryAgent")
WebAgent = _external_agents.agent_class("agents.builtin.communication.web_agent", "WebAgent")
STTAgent = _external_agents.agent_class("agents.builtin.io.voice_proxy", "STTAgentProxy")
TTSAgent = _external_agents.agent_class("agents.builtin.io.voice_proxy", "TTSAgentProxy")
set_agents = _external_agents.function("agents.builtin.communication.telegram_agent", "set_agents")
start_bot = _external_agents.function(
    "agents.builtin.communication.telegram_agent",
    "start_bot",
    async_default=True,
)
stop_bot = _external_agents.function(
    "agents.builtin.communication.telegram_agent",
    "stop_bot",
    async_default=True,
)

# =========================
# LOGGER LOCAL (OPTIONNEL PAR MODULE)
# =========================

logger = get_logger("neron.core")

VERSION = settings.VERSION
TAG = "Phase 2.1 - Codex Assisted Agent Builder validated"

# ── Etat global ───────────────────────────────────────────────────────────────

_startup_time: float               = 0.0
_gateway_task: asyncio.Task | None = None
_self_monitor_task: asyncio.Task | None = None
_registry_stale_task: asyncio.Task | None = None

llm_agent:        LLMAgent        | None = None
memory_agent:     MemoryAgent     | None = None
web_agent:        WebAgent        | None = None
stt_agent:        STTAgent        | None = None
tts_agent:        TTSAgent        | None = None
ha_agent:         HAAgent         | None = None
code_agent:       CodeAgent       | None = None
code_audit_agent: CodeAuditAgent  | None = None
router:           IntentRouter    | None = None
_capability_resolver: CapabilityResolver | None = None

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_capability_resolver() -> CapabilityResolver:
    global _capability_resolver
    if _capability_resolver is None:
        _capability_resolver = CapabilityResolver()
    return _capability_resolver


def _active_core_orchestrator() -> CoreOrchestrator:
    """Return the Core authority wired to the currently active app services."""
    orchestrator = get_core_orchestrator()
    if router is not None:
        orchestrator.intent_router = router
    active_agent_router = globals().get("agent_router")
    if active_agent_router is not None:
        orchestrator.agent_router = active_agent_router
    orchestrator._capability_resolver = get_capability_resolver()
    return orchestrator


def _capability_confidence(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"

# ── Module personality ────────────────────────────────────────────────────────

def _personality_available() -> bool:
    try:
        import modules.personality  # noqa: F401
        return True
    except ImportError:
        return False


# ── Metriques Prometheus ──────────────────────────────────────────────────────

def _counter(name: str, doc: str, labels=None):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Counter(name, doc, labels or [])


def _gauge(name: str, doc: str):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return Gauge(name, doc)


def _histogram(name: str, doc: str, labels=None, buckets=None):
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    kwargs = {}
    if labels:
        kwargs["labelnames"] = labels
    if buckets:
        kwargs["buckets"] = buckets
    return Histogram(name, doc, **kwargs)


_prom_requests_total  = _counter("neron_requests_total",     "Nombre total de requetes")
_prom_intent_total    = _counter("neron_intent_total",       "Requetes par intent",      ["intent"])
_prom_agent_errors    = _counter("neron_agent_errors_total", "Erreurs par agent",        ["agent"])
_prom_llm_calls       = _counter("neron_llm_calls_by_model", "Appels LLM par modele",   ["model"])
_prom_requests_flight = _gauge("neron_requests_in_flight",   "Requetes en cours")
_prom_uptime          = _gauge("neron_uptime_seconds",        "Duree depuis le demarrage")
_prom_cpu             = _gauge("neron_system_cpu_percent",    "CPU systeme %")
_prom_ram             = _gauge("neron_system_ram_percent",    "RAM systeme %")
_prom_disk            = _gauge("neron_system_disk_percent",   "Disque systeme %")
_prom_process_ram     = _gauge("neron_process_ram_mb",        "RAM process Neron MB")
_prom_exec_time       = _histogram(
    "neron_execution_time_ms", "Temps orchestration ms",
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000, 10000],
)
_prom_agent_latency   = _histogram(
    "neron_agent_latency_ms", "Latence par agent ms",
    labels=["agent"],
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000],
)


class Metrics:
    """Facade prometheus_client."""

    def record_request_start(self) -> None:
        _prom_requests_total.inc()
        _prom_requests_flight.inc()

    def record_request_end(self, execution_time_ms: float) -> None:
        _prom_requests_flight.dec()
        _prom_exec_time.observe(execution_time_ms)

    def record_intent(self, intent: str) -> None:
        _prom_intent_total.labels(intent=intent).inc()

    def record_error(self, agent: str) -> None:
        _prom_agent_errors.labels(agent=agent).inc()

    def record_latency(self, agent: str, latency_ms: float) -> None:
        _prom_agent_latency.labels(agent=agent).observe(latency_ms)

    def record_model_call(self, model: str) -> None:
        if model:
            _prom_llm_calls.labels(model=model).inc()

    def update_system_metrics(self) -> None:
        try:
            _prom_uptime.set(round(time.monotonic() - _startup_time, 2))
            _prom_cpu.set(psutil.cpu_percent(interval=0.5))
            _prom_ram.set(psutil.virtual_memory().percent)
            _prom_disk.set(psutil.disk_usage("/").percent)
            proc = psutil.Process(os.getpid())
            _prom_process_ram.set(round(proc.memory_info().rss / 1024 / 1024))
        except Exception as e:
            logger.warning("update_system_metrics error : %s", e)

    def export(self) -> str:
        self.update_system_metrics()
        return generate_latest(REGISTRY).decode("utf-8")


metrics = Metrics()


# ── Lifespan ──────────────────────────────────────────────────────────────────



async def _registry_stale_loop() -> None:
    timeout_seconds = float(os.getenv("NERON_REGISTRY_STALE_TIMEOUT_SECONDS", "90"))
    interval_seconds = float(os.getenv("NERON_REGISTRY_STALE_INTERVAL_SECONDS", "30"))

    while True:
        try:
            stale = service_registry.mark_stale_services(timeout_seconds)
            if stale:
                logger.warning(
                    "Registry stale services: %s",
                    ", ".join(s["service_name"] for s in stale),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Registry stale loop error: %s", exc)

        await asyncio.sleep(interval_seconds)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global llm_agent, web_agent, stt_agent, tts_agent, ha_agent
    global router, _startup_time, memory_agent
    global code_agent, code_audit_agent, _gateway_task, _self_monitor_task, _registry_stale_task
    global obsidian_agent

    telegram_enabled = False
    telegram_token = ""

    try:
        _startup_time = time.monotonic()
        health_state.mark_started()
        logger.info(json.dumps({"event": "startup", "version": VERSION}))
        ensure_default_providers()

        try:
            from goal.goals.execution_engine import get_goal_execution_engine
            from goal.goals.goal_manager import get_goal_manager
            get_goal_manager().ensure_core_goals()
            interrupted = get_goal_execution_engine().recover_interrupted_goals()
            if interrupted:
                logger.warning(
                    "Goal executions interrupted after restart: %s",
                    ", ".join(interrupted),
                )
            logger.info("GoalManager initialise")
        except Exception as exc:
            logger.warning("GoalManager init failed: %s", exc)

        try:
            from modules.scheduler.scheduler import get_task_scheduler

            task_scheduler = get_task_scheduler()
            recovered_tasks = task_scheduler.recover_running_tasks()
            if recovered_tasks:
                logger.warning(
                    "Scheduler tasks interrupted after restart: %s",
                    ", ".join(task.task_id for task in recovered_tasks),
                )
            await task_scheduler.start_worker()
            logger.info(
                "TaskScheduler initialise worker_enabled=%s max_concurrent=%s",
                task_scheduler.worker_enabled,
                task_scheduler.max_concurrent_tasks,
            )
        except Exception as exc:
            logger.warning("TaskScheduler init failed: %s", exc)

        _self_monitor_task = asyncio.create_task(get_self_monitor().start())
        logger.info("SelfMonitor demarre")

        metrics.update_system_metrics()

        llm_agent = LLMAgent()
        web_agent = WebAgent()

        memory_agent = MemoryAgent()

        ha_agent = HAAgent()

        stt_agent = STTAgent()
        if not await stt_agent.check_connection():
            logger.warning("Voice service (STT) injoignable au démarrage sur port 8045")

        try:
            tts_agent = TTSAgent()
            if not await tts_agent.check_connection():
                logger.warning("Voice service (TTS) injoignable au démarrage")
        except Exception as exc:
            logger.warning("TTS indisponible au démarrage : %s", exc)

        code_agent = CodeAgent()
        code_audit_agent = CodeAuditAgent()

        await ha_agent.on_start()

        router = IntentRouter(llm_agent=llm_agent)

        if _personality_available():
            try:
                from modules.personality import get_current_state
                state = get_current_state()
                logger.info(json.dumps({
                    "event": "personality_loaded",
                    "mood": state.get("mood"),
                    "energy": state.get("energy_level"),
                    "tone": state.get("communication", {}).get("tone"),
                }))
            except Exception as e:
                logger.warning("Personality charge mais etat illisible : %s", e)
        else:
            logger.warning("Module personality non disponible — system prompt statique actif")

        logger.info(json.dumps({"event": "agents_ready"}))

        logger.warning("scheduler_setup introuvable — setup scheduler ignoré")
        try:
            get_task_scheduler().start()
        except Exception as e:
            logger.warning("TaskScheduler start ignoré : %s", e)

        try:
            llm_cfg = LLMConfig(
                provider="ollama",
                model=settings.OLLAMA_MODEL,
                base_url=settings.OLLAMA_HOST,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
            )

            _sessions = SessionStore()
            _skills = SkillRegistry()
            _tools = RouterToolBindings().setup_defaults()

            global agent_router
            agent_router = AgentRouter(
                sessions=_sessions,
                skills=_skills,
                llm_config=llm_cfg,
                tools=_tools,
            )
            set_core_orchestrator(
                CoreOrchestrator(
                    intent_router=router,
                    agent_router=agent_router,
                    capability_resolver=get_capability_resolver(),
                )
            )

            gw_config = GatewayConfig(
                host=settings.SERVER_HOST,
                port=18789,
                token=settings.API_KEY or None,
                ping_interval=60.0,
                ping_timeout=120.0,
            )

            _gw = NeronGateway(
                config=gw_config,
                agent_router=agent_router,
                session_store=_sessions,
                skill_registry=_skills,
                stt_agent=stt_agent,
                tts_agent=tts_agent,
            )

            _gateway_task = asyncio.create_task(_gw.start())
            logger.info("Gateway WebSocket demarre sur ws://0.0.0.0:18789")

        except Exception as e:
            logger.warning("Gateway WebSocket non demarre : %s", e)

        set_agents({
            "llm": llm_agent,
            "stt": stt_agent,
            "tts": tts_agent,
            "memory": memory_agent,
            "ha": ha_agent,
            "code": code_agent,
            "code_audit": code_audit_agent,
        })

        telegram_enabled = getattr(settings, "TELEGRAM_ENABLED", False)
        telegram_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")

        if telegram_enabled and telegram_token not in ("", "votre_token_ici", None):
            try:
                await start_bot()
            except Exception as e:
                logger.warning("Impossible de demarrer Telegram : %s", e)
        else:
            logger.info("Telegram desactive ou token non configure")


        _registry_stale_task = asyncio.create_task(_registry_stale_loop())
        logger.info("Registry stale detector demarre")

        yield

    finally:
        logger.info(json.dumps({"event": "shutdown_started"}))

        if _registry_stale_task and not _registry_stale_task.done():
            _registry_stale_task.cancel()
            try:
                await _registry_stale_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Erreur arrêt Registry stale detector : %s", e)


        try:
            from goal.goals.background_runner import get_goal_background_runner
            await get_goal_background_runner().shutdown()
        except Exception as e:
            logger.warning("Erreur arrêt workflows goals : %s", e)

        try:
            from modules.scheduler.scheduler import get_task_scheduler

            await get_task_scheduler().stop_worker()
        except Exception as e:
            logger.warning("Erreur arrêt TaskScheduler : %s", e)

        try:
            await get_self_monitor().stop()
        except Exception as e:
            logger.warning("Erreur arrêt SelfMonitor : %s", e)

        if _self_monitor_task and not _self_monitor_task.done():
            _self_monitor_task.cancel()
            try:
                await _self_monitor_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Erreur tâche SelfMonitor : %s", e)

        try:
            get_task_scheduler().stop()
        except Exception as e:
            logger.warning("Erreur arrêt scheduler : %s", e)

        if ha_agent:
            try:
                await ha_agent.on_stop()
            except Exception as e:
                logger.warning("Erreur arrêt HAAgent : %s", e)

        if _gateway_task and not _gateway_task.done():
            _gateway_task.cancel()
            try:
                await _gateway_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("Erreur arrêt Gateway WebSocket : %s", e)

                logger.warning("Erreur arrêt watchdog : %s", e)

        if telegram_enabled and telegram_token not in ("", "votre_token_ici", None):
            try:
                await stop_bot()
            except Exception as e:
                logger.warning("Impossible d'arreter Telegram : %s", e)

        logger.info(json.dumps({"event": "shutdown"}))

# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=f"{get_identity()['name']} Core",
    description="Orchestrateur central - v" + VERSION,
    version=VERSION,
    lifespan=lifespan,
)

@app.middleware("http")
async def enforce_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or is_public_route(
        request.method,
        request.url.path,
    ) or is_local_registry_route(request):
        return await call_next(request)

    try:
        context = authenticate_request(request)
    except AuthenticationError as exc:
        publish_auth_failure(request, exc)
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    request.state.auth = context
    try:
        return await call_next(request)
    finally:
        publish_auth_success(request, context)


_INTERNAL_AUTH = [Depends(verify_api_key)]

app.include_router(self_model_router, dependencies=_INTERNAL_AUTH)
app.include_router(selfmodel_router, dependencies=_INTERNAL_AUTH)
app.include_router(runtime_governor_router, dependencies=_INTERNAL_AUTH)
app.include_router(world_model_router, dependencies=_INTERNAL_AUTH)
app.include_router(goals_router, dependencies=_INTERNAL_AUTH)
app.include_router(tools_router)
app.include_router(scheduler_router)
app.include_router(agent_runtime_router)
app.include_router(capabilities_router)
app.include_router(task_router)
app.include_router(goal_task_router, dependencies=_INTERNAL_AUTH)
app.include_router(cognitive_core_router, dependencies=_INTERNAL_AUTH)
app.include_router(cognitive_report_router, dependencies=_INTERNAL_AUTH)
app.include_router(action_history_router, dependencies=_INTERNAL_AUTH)
app.include_router(critic_history_router, dependencies=_INTERNAL_AUTH)
app.include_router(code_awareness_router, dependencies=_INTERNAL_AUTH)
app.include_router(projects_router)
app.include_router(evolution_router)
app.include_router(memory_router, dependencies=_INTERNAL_AUTH)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ────────────────────────────────────────────────────────────────────

class TextInput(BaseModel):
    text: str
    source_channel: str = "api"
    user_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class CoreResponse(BaseModel):
    response:          str
    intent:            str
    agent:             str
    confidence:        str
    timestamp:         str
    execution_time_ms: float
    model:             Optional[str] = None
    error:             Optional[str] = None
    transcription:     Optional[str] = None
    metadata:          dict          = Field(default_factory=dict)


class EventPublishInput(BaseModel):
    event_type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    target: Optional[str] = None
    trace_id: Optional[str] = None
    level: str = Field(default="info", pattern="^(info|warning|error)$")


class ServiceRegisterInput(BaseModel):
    service_name: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65_535)
    version: Optional[str] = None
    status: str = Field(
        default="unknown",
        pattern="^(healthy|degraded|unhealthy|unknown)$",
    )
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class ServiceHeartbeatInput(BaseModel):
    service_name: str = Field(min_length=1)
    status: Optional[str] = Field(
        default=None,
        pattern="^(healthy|degraded|unhealthy|unknown)$",
    )
    metadata: Optional[dict] = None


def _service_registration_response(service: dict) -> ServiceRegistration:
    """Rebuild the strict response model from the Registry wire format."""

    payload = dict(service)
    payload.pop("last_heartbeat", None)
    return ServiceRegistration.model_validate(payload, strict=False)


# ── Routes systeme ────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": f"{get_identity()['name']} Core",
        "version": VERSION,
        "status": "active",
    }


@app.get("/health")
def health():
    return health_state.health(VERSION)


async def _refresh_provider_health() -> None:
    for provider_info in provider_registry.list():
        provider = provider_registry.get(provider_info.name)
        if provider is None:
            continue
        try:
            await provider.health()
        except Exception as exc:
            logger.warning("Provider health refresh failed for %s: %s", provider_info.name, exc)


@app.get("/status")
async def status():
    ensure_default_providers()
    await _refresh_provider_health()
    return health_state.status(
        VERSION,
        dependencies={},
        registry=service_registry.status(),
        event_bus=infrastructure_event_bus.status(),
        providers=provider_registry.status(),
        a2a=a2a_client.status(),
    )


@app.get("/events")
def list_infrastructure_events(
    limit: int = 100,
    event_type: Optional[str] = None,
    source: Optional[str] = None,
    target: Optional[str] = None,
    trace_id: Optional[str] = None,
):
    limit = min(max(0, limit), 1_000)
    events = infrastructure_event_bus.get_events(
        limit,
        event_type=event_type,
        source=source,
        target=target,
        trace_id=trace_id,
    )
    return {"events": events, "count": len(events)}


@app.post("/events/publish")
def publish_infrastructure_event(input_data: EventPublishInput):
    event = infrastructure_event_bus.publish(
        event_type=input_data.event_type,
        source=input_data.source,
        payload=input_data.payload,
        target=input_data.target,
        trace_id=input_data.trace_id,
        level=input_data.level,
    )
    log_event(
        service="core",
        level="info",
        message="infrastructure_event_published",
        trace_id=event["trace_id"],
        extra={"event_id": event["event_id"], "event_type": event["type"]},
    )
    return event


@app.get("/registry/services")
def list_registered_services(
    status: Optional[str] = None,
    capability: Optional[str] = None,
):
    services = service_registry.list_services(
        status=status,
        capability=capability,
    )
    return {"services": services, "count": len(services)}


@app.get("/registry/topology")
def registry_topology():
    return build_topology(service_registry)


@app.get("/registry/topology/{service_name}")
def registry_topology_service(service_name: str):
    service = get_topology_service(service_registry, service_name)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not registered")
    return service


@app.get("/registry/services/{service_name}", response_model=ServiceRegistration)
def get_registered_service(service_name: str):
    service = service_registry.get_service(service_name)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not registered")
    return _service_registration_response(service)


@app.post("/registry/register", response_model=ServiceRegistration)
def register_service(input_data: ServiceRegisterInput):
    service = service_registry.register(
        service_name=input_data.service_name,
        host=input_data.host,
        port=input_data.port,
        version=input_data.version,
        status=input_data.status,
        capabilities=input_data.capabilities,
        metadata=input_data.metadata,
    )
    log_event(
        service="core",
        level="info",
        message="service_registered",
        extra={"service_name": input_data.service_name},
    )
    return _service_registration_response(service)


@app.post("/registry/heartbeat", response_model=ServiceRegistration)
def heartbeat_service(input_data: ServiceHeartbeatInput):
    service = service_registry.heartbeat(
        input_data.service_name,
        status=input_data.status,
        metadata=input_data.metadata,
    )
    if service is None:
        raise HTTPException(status_code=404, detail="Service not registered")
    return _service_registration_response(service)


@app.delete("/registry/services/{service_name}", response_model=ServiceRegistration)
def unregister_service(service_name: str):
    service = service_registry.unregister(service_name)
    if service is None:
        raise HTTPException(status_code=404, detail="Service not registered")
    return _service_registration_response(service)


@app.api_route(
    "/gateway/{service_name}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def gateway_proxy(service_name: str, path: str, request: Request):
    try:
        proxied = await proxy_request(
            service_name=service_name,
            path=path,
            method=request.method,
            headers=request.headers,
            body=await request.body(),
            query_params=list(request.query_params.multi_items()),
        )
    except GatewayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    response_headers = dict(proxied.headers)
    response_headers["X-Neron-Trace-Id"] = proxied.trace_id
    return Response(
        content=proxied.content,
        status_code=proxied.status_code,
        headers=response_headers,
    )


@app.get("/metrics")
def prometheus_metrics():
    return Response(content=metrics.export(), media_type=CONTENT_TYPE_LATEST)


@app.post("/ha/reload")
async def ha_reload(_: None = Depends(verify_api_key)):
    if not ha_agent:
        raise HTTPException(503, "Agent HA non disponible")
    count = await ha_agent.reload()
    return {"status": "ok", "entities": count, "timestamp": utc_now_iso()}


# ── Route /memory ─────────────────────────────────────────────────────────────

@app.get("/memory")
async def get_memory(limit: int = 5, _: None = Depends(verify_api_key)):
    """Retourne les dernières entrées de la mémoire conversationnelle."""
    if not memory_agent:
        raise HTTPException(status_code=503, detail="Agent mémoire non disponible")
    limit = min(max(1, limit), 100)
    try:
        entries = await memory_agent.retrieve(limit=limit)
        return {"entries": entries, "count": len(entries), "timestamp": utc_now_iso()}
    except Exception as e:
        logger.error("Erreur récupération mémoire : %s", e)
        raise HTTPException(status_code=500, detail=f"Erreur mémoire : {e}")


# ── Routes /personality ───────────────────────────────────────────────────────

@app.get("/personality/state")
async def personality_state(_: None = Depends(verify_api_key)):
    if not _personality_available():
        raise HTTPException(503, "Module personality non disponible")
    try:
        from modules.personality import get_current_state
        return {"status": "ok", "state": get_current_state(), "timestamp": utc_now_iso()}
    except Exception as e:
        raise HTTPException(500, f"Erreur lecture etat personality : {e}")


@app.get("/personality/history")
async def personality_history(limit: int = 20, _: None = Depends(verify_api_key)):
    if not _personality_available():
        raise HTTPException(503, "Module personality non disponible")
    limit = min(max(1, limit), 100)
    try:
        from personality import get_history
        history = get_history(limit=limit)
        return {"status": "ok", "history": history, "count": len(history), "timestamp": utc_now_iso()}
    except Exception as e:
        raise HTTPException(500, f"Erreur lecture historique personality : {e}")


@app.post("/personality/reset")
async def personality_reset(_: None = Depends(verify_api_key)):
    if not _personality_available():
        raise HTTPException(503, "Module personality non disponible")
    try:
        from personality import force_update
        from personality.updater import _resolve_protected
        results = [
            force_update(None, "mood",         "neutre", "reset via API"),
            force_update(None, "energy_level", "normal", "reset via API"),
        ]
        _resolve_protected.cache_clear()
        return {"status": "ok", "reset": ["mood", "energy_level"], "results": results, "timestamp": utc_now_iso()}
    except Exception as e:
        raise HTTPException(500, f"Erreur reset personality : {e}")


# ── Route /nlp ────────────────────────────────────────────────────────────────

@app.post("/nlp/parse")
async def nlp_parse(input_data: TextInput, _: None = Depends(verify_api_key)):
    """Analyse NLP d'un texte brut — retourne intent, entities, confidence."""
    from core.pipeline.nlp.nlp_processor import process as nlp_process
    result = nlp_process(input_data.text.strip())
    return result.to_dict()

# ── Routes /input ─────────────────────────────────────────────────────────────

@app.post("/input/text", response_model=CoreResponse)
async def text_input(input_data: TextInput, _: None = Depends(verify_api_key)):
    query = input_data.text.strip()
    if not query:
        raise HTTPException(status_code=422, detail="text is required")

    metrics.record_request_start()
    logger.info(json.dumps({"event": "request_received", "query": query[:80]}))
    infrastructure_event_bus.publish(
        event_type="user.message.received",
        source=f"{input_data.source_channel}.input.text",
        payload={"text": query},
    )

    started = time.monotonic()
    try:
        result = await _active_core_orchestrator().handle(
            query,
            source_channel=input_data.source_channel,
            user_id=input_data.user_id,
            request_metadata=input_data.metadata,
        )
        metrics.record_intent(result.intent)
        if result.error:
            metrics.record_error(result.executor)
        if result.model:
            metrics.record_model_call(result.model)

        return CoreResponse(
            response=result.response,
            intent=result.intent,
            agent=result.executor,
            confidence=(
                "high"
                if result.confidence >= 0.7
                else "medium"
                if result.confidence >= 0.4
                else "low"
            ),
            timestamp=utc_now_iso(),
            execution_time_ms=result.elapsed_ms,
            model=result.model,
            error=result.error,
            metadata={
                **result.to_metadata(),
                "source": input_data.source_channel,
            },
        )
    finally:
        metrics.record_request_end(
            round((time.monotonic() - started) * 1000, 2)
        )


@app.get("/capabilities/requests/{request_id}")
async def capability_request_status(
    request_id: str,
    _: None = Depends(verify_api_key),
):
    result = await get_capability_resolver().get_result(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Capability request not found")
    return result.to_dict()


@app.post("/input/stream")
async def text_input_stream(input_data: TextInput, _: None = Depends(verify_api_key)):
    query = input_data.text.strip()

    async def generate():
        try:
            result = await _active_core_orchestrator().handle(
                query,
                source_channel=input_data.source_channel,
                user_id=input_data.user_id,
                request_metadata=input_data.metadata,
            )
            yield (
                "data: "
                + json.dumps(
                    {
                        "token": result.response,
                        "done": True,
                        "intent": result.intent,
                        "selected_route": result.decision.selected_route,
                        "error": result.error,
                    }
                )
                + "\n\n"
            )
        except Exception as e:
            logger.exception("stream: exception : %s", e)

        yield f"data: {json.dumps({'token': '', 'done': True, 'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/input/audio", response_model=CoreResponse)
async def audio_input(file: UploadFile = File(...)):
    start = time.monotonic()
    metrics.record_request_start()
    try:
        if stt_agent is None:
            raise HTTPException(503, "STT non disponible (désactivé dans cette configuration)")
        audio_bytes = await file.read()
        result      = await stt_agent.transcribe(audio_bytes, file.filename)
        if not result.success:
            metrics.record_error("stt_agent")
            raise HTTPException(503, f"STT indisponible : {result.error}")
        if result.latency_ms:
            metrics.record_latency("stt_agent", result.latency_ms)
        transcription               = result.content
        core_response               = await text_input(TextInput(text=transcription))
        core_response.transcription = transcription
        core_response.metadata["stt"] = {
            "language":       result.metadata.get("language"),
            "stt_latency_ms": result.latency_ms,
        }
        return core_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur pipeline audio : {e}")
    finally:
        metrics.record_request_end(round((time.monotonic() - start) * 1000, 2))


@app.post("/input/voice")
async def voice_input(file: UploadFile = File(...)):
    from fastapi.responses import Response as FastAPIResponse
    start = time.monotonic()
    metrics.record_request_start()
    try:
        if stt_agent is None or tts_agent is None:
            raise HTTPException(503, "Pipeline vocal non disponible (STT/TTS désactivés dans cette configuration)")
        audio_bytes = await file.read()
        stt_result  = await stt_agent.transcribe(audio_bytes, file.filename)
        if not stt_result.success:
            metrics.record_error("stt_agent")
            raise HTTPException(503, f"STT indisponible : {stt_result.error}")
        if stt_result.latency_ms:
            metrics.record_latency("stt_agent", stt_result.latency_ms)
        transcription = stt_result.content
        if not transcription:
            raise HTTPException(400, "Transcription vide")
        core_response = await text_input(TextInput(text=transcription))
        tts_result    = await tts_agent.synthesize(core_response.response)
        if not tts_result.success:
            metrics.record_error("tts_agent")
            return core_response
        if tts_result.latency_ms:
            metrics.record_latency("tts_agent", tts_result.latency_ms)
        execution_time_ms = round((time.monotonic() - start) * 1000, 2)
        return FastAPIResponse(
            content=tts_result.metadata["audio_bytes"],
            media_type=tts_result.metadata.get("mimetype", "audio/wav"),
            headers={
                "X-Transcription":     transcription[:200].encode("ascii", "replace").decode(),
                "X-Response-Text":     core_response.response[:200].encode("ascii", "replace").decode(),
                "X-Intent":            core_response.intent,
                "X-Execution-Time-Ms": str(execution_time_ms),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur pipeline vocal : {e}")
    finally:
        metrics.record_request_end(round((time.monotonic() - start) * 1000, 2))


# Planner autonome
app.include_router(planner_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.SERVER_HOST, port=settings.SERVER_PORT)
