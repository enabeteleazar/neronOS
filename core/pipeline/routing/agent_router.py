# core/pipeline/routing/agent_router.py

from __future__ import annotations

import logging
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from core.agent_registry import get_external_agent_registry
from core.config.paths import NERON_WORKSPACE_DIR
from core.pipeline.intent.intent_router import Intent, IntentResult

logger = logging.getLogger("pipeline.agent_router")

WORKSPACE_AGENTS_DIR = NERON_WORKSPACE_DIR / "agents"
_external_agents = get_external_agent_registry()

_llm: Optional[object] = None
_memory: Optional[object] = None
_system: Optional[object] = None
_ha: Optional[object] = None
_web: Optional[object] = None
_news: Optional[object] = None
_weather: Optional[object] = None
_todo: Optional[object] = None
_wiki: Optional[object] = None

AGENT_LIST_QUERIES = {
    "quels agents sont disponibles",
    "agents disponibles",
    "liste les agents",
    "liste agents",
    "affiche les agents",
    "affiche moi les agents",
    "montre les agents",
    "montre moi les agents",
}

AGENT_REGISTRY_SCAN_QUERIES = {
    "scan agents",
    "rescanner agents",
}

AGENT_REGISTRY_INDEX_QUERIES = {
    "index agents",
}

AGENT_REGISTRY_INVALID_QUERIES = {
    "agents invalides",
}


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("'", " ").replace("’", " ")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text


def _clean_agent_name(name: str) -> str:
    name = _normalize(name)
    name = name.replace("-", "_").replace(" ", "_")
    name = "".join(c for c in name if c.isalnum() or c == "_")
    if name.endswith("_agent"):
        name = name[:-6]
    return name.strip("_")


def _clean_agent_module_name(name: str) -> str:
    name = _normalize(name)
    name = name.replace("-", "_").replace(" ", "_")
    name = "".join(c for c in name if c.isalnum() or c == "_")
    return name.strip("_")


def _result_to_text(result: Any) -> str:
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        return result.get("response", str(result))

    if hasattr(result, "content"):
        return result.content if getattr(result, "success", True) else f"⚠️ {result.error}"

    return str(result)


def _get_llm():
    global _llm
    if _llm is None:
        LLMAgent = _external_agents.agent_class("agents.builtin.core.llm_agent", "LLMAgent")
        _llm = LLMAgent()
    return _llm


def _get_memory():
    global _memory
    if _memory is None:
        MemoryAgent = _external_agents.agent_class("agents.builtin.core.memory_agent", "MemoryAgent")
        _memory = MemoryAgent()
    return _memory


def _get_system():
    global _system
    if _system is None:
        SystemAgent = _external_agents.agent_class("agents.builtin.core.system_agent", "SystemAgent")
        _system = SystemAgent()
    return _system


def _get_ha():
    global _ha
    if _ha is None:
        HAAgent = _external_agents.agent_class("agents.builtin.automation.ha_agent", "HAAgent")
        _ha = HAAgent()
    return _ha


def _get_web():
    global _web
    if _web is None:
        WebAgent = _external_agents.agent_class("agents.builtin.communication.web_agent", "WebAgent")
        _web = WebAgent()
    return _web


def _get_news():
    global _news
    if _news is None:
        NewsAgent = _external_agents.agent_class("agents.builtin.io.news_agent", "NewsAgent")
        _news = NewsAgent()
    return _news


def _get_weather():
    global _weather
    if _weather is None:
        WeatherAgent = _external_agents.agent_class("agents.builtin.io.weather_agent", "WeatherAgent")
        _weather = WeatherAgent()
    return _weather


def _get_todo():
    global _todo
    if _todo is None:
        TodoAgent = _external_agents.agent_class("agents.builtin.core.todo_agent", "TodoAgent")
        _todo = TodoAgent()
    return _todo


def _get_wiki():
    global _wiki
    if _wiki is None:
        WikiAgent = _external_agents.agent_class("agents.builtin.io.wiki_agent", "WikiAgent")
        _wiki = WikiAgent()
    return _wiki


def _get_self_model():
    from core.modules.self_model import get_self_model
    return get_self_model()


def _list_dynamic_agents() -> str:
    from agents.factory.registry import DynamicAgentRegistry, AGENT_REGISTRY

    registry = DynamicAgentRegistry()
    registry.load_generated_agents()

    agents = sorted(AGENT_REGISTRY.keys())

    if not agents:
        return "Aucun agent dynamique chargé."

    lines = ["Agents dynamiques disponibles :"]
    lines.extend(f"- {name}" for name in agents)

    return "\n".join(lines)


def _is_agent_list_query(query: str) -> bool:
    return _normalize(query).strip(" ?!.:,;") in AGENT_LIST_QUERIES


def _is_registry_scan_query(query: str) -> bool:
    return _normalize(query).strip(" ?!.:,;") in AGENT_REGISTRY_SCAN_QUERIES


def _is_registry_index_query(query: str) -> bool:
    return _normalize(query).strip(" ?!.:,;") in AGENT_REGISTRY_INDEX_QUERIES


def _is_registry_invalid_query(query: str) -> bool:
    return _normalize(query).strip(" ?!.:,;") in AGENT_REGISTRY_INVALID_QUERIES


async def _scan_agent_registry_text() -> str:
    from agents.runtime.runtime import get_agent_runtime

    runtime = get_agent_runtime()
    result = runtime.registry.scan()
    runtime.reload()
    return "\n".join(
        [
            "Scan agents terminé.",
            f"Agents scannés : {result.get('scanned', 0)}.",
            f"Actifs : {result.get('active', 0)}.",
            f"Invalides : {result.get('invalid', 0)}.",
            "Runtime rechargé : OK.",
        ]
    )


def _agent_registry_records() -> list[dict[str, Any]]:
    from agents.factory.registry import DynamicAgentRegistry

    index = DynamicAgentRegistry().validation_index()
    agents = index.get("agents") if isinstance(index, dict) else {}
    if not isinstance(agents, dict):
        return []
    return sorted(
        (record for record in agents.values() if isinstance(record, dict)),
        key=lambda record: str(record.get("agent_name") or record.get("path") or ""),
    )


def _agent_registry_index_text() -> str:
    records = _agent_registry_records()
    if not records:
        return "Index agents vide."

    lines = ["Index agents :"]
    lines.extend(
        f"- {record.get('agent_name') or 'agent_inconnu'} | {record.get('status') or 'unknown'}"
        for record in records
    )
    return "\n".join(lines)


def _invalid_agent_registry_text() -> str:
    invalid = [record for record in _agent_registry_records() if record.get("status") == "invalid"]
    if not invalid:
        return "Aucun agent invalide."

    lines = ["Agents invalides :"]
    lines.extend(
        f"- {record.get('agent_name') or 'agent_inconnu'} | {record.get('error') or 'erreur inconnue'}"
        for record in invalid
    )
    return "\n".join(lines)


async def _goal_status_text(query: str) -> str:
    from core.modules.goal_status_response import build_goal_status_response_async
    from goal.goals.goal_manager import get_goal_manager
    from goal.goals.goal_orchestrator import get_goal_orchestrator

    active_goal = get_goal_manager().get_active_goal()
    if not active_goal:
        result = await build_goal_status_response_async(None, question=query)
        return result["response"]

    goal_id = str(active_goal.get("id") or active_goal.get("goal_id") or "")
    status = dict(active_goal)
    if goal_id:
        detailed = get_goal_orchestrator().get_goal_status(goal_id)
        if detailed:
            status = {**status, **detailed}

    result = await build_goal_status_response_async(status, question=query)
    return result["response"]


async def _project_status_text(query: str) -> str:
    from agents.factory.build_orchestrator import AgentBuildOrchestrator
    from goal.projects.manager import get_project_manager

    normalized = _normalize(query)
    if "objectif" in normalized or "goal" in normalized:
        return await _goal_status_text(query)

    manager = get_project_manager()
    matches = manager.find_project_by_query(query, limit=1)
    project = matches[0] if matches else None
    return AgentBuildOrchestrator().format_status_response(project)


def _project_list_text() -> str:
    from goal.projects.manager import get_project_manager

    projects = get_project_manager().list_projects(limit=20)
    if not projects:
        return "Aucun projet suivi."

    lines = ["Projets suivis :"]
    for project in projects[:20]:
        lines.append(
            f"- {project.get('project_id')} | {project.get('status')} | "
            f"{project.get('progress')}% | {project.get('current_step')}"
        )
    return "\n".join(lines)


async def _build_tracked_agent(query: str, source_channel: str = "api") -> str:
    from agents.factory.build_orchestrator import AgentBuildOrchestrator

    orchestrator = AgentBuildOrchestrator()
    result = await orchestrator.build_from_request(
        query,
        requested_by="user",
        source_channel=source_channel,
        build_mode="hybrid",
    )
    return result.get("response") or orchestrator.format_project_response(result.get("project"))


def _extract_agent_name(query: str, prefixes: list[str]) -> str | None:
    text = _normalize(query)

    for prefix in prefixes:
        prefix_norm = _normalize(prefix)
        if text.startswith(prefix_norm):
            raw_name = text.replace(prefix_norm, "", 1).strip()
            name = _clean_agent_name(raw_name)
            return name or None

    return None


def _extract_agent_name_for_run(query: str) -> str | None:
    return _extract_agent_name(
        query,
        [
            "lance l agent",
            "lance agent",
            "execute l agent",
            "execute agent",
            "exécute l agent",
            "exécute agent",
            "run agent",
        ],
    )


def _extract_agent_name_for_promote(query: str) -> str | None:
    return _extract_agent_name(
        query,
        [
            "valide l agent",
            "valide agent",
            "promeut l agent",
            "promeut agent",
            "active l agent",
            "active agent",
        ],
    )


def _is_promote_request(query: str) -> bool:
    text = _normalize(query)
    return any(
        text.startswith(_normalize(prefix))
        for prefix in (
            "valide l agent",
            "valide agent",
            "promeut l agent",
            "promeut agent",
            "active l agent",
            "active agent",
        )
    )


def _extract_agent_update_request(query: str) -> tuple[str, str] | None:
    text = unicodedata.normalize("NFC", query)
    match = re.match(
        r"^\s*(?:mets?\s+[aà]\s+jour|am[eé]liore|update)\s+"
        r"(?:l\s+|l['’]\s*)?(?:agent\s+)?"
        r"([A-Za-z0-9_.-]+)(?:\s*:\s*|\s+)(.+?)\s*$",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        name = _clean_agent_module_name(match.group(1))
        update_request = match.group(2).strip()
        if name and update_request:
            return name, update_request
    return None


async def _update_dynamic_agent(query: str) -> str:
    from agents.factory.agent_manager import AgentManager

    parsed = _extract_agent_update_request(query)
    if not parsed:
        return "Demande incomplète. Exemple : améliore agent subnet_calculator_agent ajoute le support IPv6"

    name, request = parsed
    result = await AgentManager().update_agent(name, request=request)

    if result.get("status") == "updated":
        tests_ok = (result.get("test_result") or {}).get("returncode") == 0
        runtime_ok = bool((result.get("runtime_reload") or {}).get("ok"))
        return "\n".join(
            [
                f"Agent mis à jour : {result.get('agent') or name}.",
                "Backup : oui.",
                f"Tests : {'OK' if tests_ok else 'KO'}.",
                f"Runtime rechargé : {'OK' if runtime_ok else 'non'}.",
            ]
        )

    reason = result.get("reason") or result.get("status") or "update_failed"
    return f"Mise à jour agent refusée : {result.get('agent') or name}. Raison : {reason}."


async def _run_dynamic_agent(query: str) -> str:
    from agents.runtime.runtime import get_agent_runtime

    runtime = get_agent_runtime()
    agent_name = _extract_agent_name_for_run(query)

    if not agent_name:
        return "Nom d’agent introuvable. Exemple : lance l agent meteo"

    execution = await runtime.run_agent(agent_name, query)

    if not execution.ok:
        available = ", ".join(runtime.list_agents()) or "aucun"
        return f"Agent introuvable : {agent_name}. Agents disponibles : {available}"

    return execution.response


async def _promote_dynamic_agent(query: str) -> str:
    from agents.factory.promotion import AgentPromotionService
    from agents.factory.validator import validate_agent

    agent_name = _extract_agent_name_for_promote(query)

    if not agent_name:
        return "Nom d’agent introuvable. Exemple : valide l agent meteo"

    candidates = [
        WORKSPACE_AGENTS_DIR / f"{agent_name}_agent.py",
        WORKSPACE_AGENTS_DIR / f"{agent_name}.py",
    ]

    source = next((path for path in candidates if path.exists()), None)

    if source is None:
        checked = ", ".join(str(path) for path in candidates)
        return f"Agent brouillon introuvable : {agent_name}. Chemins vérifiés : {checked}"

    validation = validate_agent(str(source))

    if not validation["ok"]:
        return f"Validation échouée : {validation['error']}"

    test_result = _run_agent_promotion_test(source)
    if test_result is None:
        return "Promotion refusée : aucun test associé au brouillon."

    if test_result and test_result["returncode"] != 0:
        error = test_result["stdout_tail"] or test_result["stderr_tail"] or "pytest_failed"
        return f"Tests échoués : {error}"

    result = AgentPromotionService().promote(
        source,
        requested_by="agent_router_text_promotion",
    )

    if not result["ok"]:
        return f"Promotion échouée : {result['error']}"

    return (
        f"✅ Agent promu : {agent_name}\n"
        f"Source : {result['source']}\n"
        f"Destination : {result['destination']}"
    )


def _run_agent_promotion_test(source: Path) -> dict[str, Any] | None:
    workspace_root = source.parent.parent
    project_root = workspace_root.parent
    candidates = (
        workspace_root / "agent_tests" / f"test_{source.stem}.py",
        project_root / "tests" / f"test_{source.stem}.py",
    )
    test_file = next((path for path in candidates if path.exists()), None)
    if test_file is None:
        return None

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_file)],
        cwd=project_root,
        text=True,
        capture_output=True,
        timeout=120,
    )
    return {
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
        "test_file": str(test_file),
    }


class AgentRouter:
    """
    Dispatch une IntentResult vers l'agent approprié et retourne la réponse.
    """

    def __init__(self, sessions=None, skills=None, llm_config=None, tools=None):
        self.sessions = sessions
        self.skills = skills
        self.llm_config = llm_config
        self.tools = tools

    async def route(self, intent_result, query: str, source_channel: str = "api"):
        model = _get_self_model()
        raw_intent = getattr(
            intent_result,
            "intent",
            intent_result,
        )

        intent_name = getattr(
            raw_intent,
            "value",
            str(raw_intent).replace("Intent.", "").lower(),
        )
        intent_confidence = getattr(
            intent_result,
            "confidence",
            None,
        )
        model.set_last_intent(
            intent_name,
            intent_confidence,
        )
        model.add_recent_activity(f"Intent détecté : {intent_name}")

        intent = Intent.AGENT_LIST if _is_agent_list_query(query) else intent_result.intent
        logger.info("[AGENT_ROUTER] dispatching intent=%s", intent)

        if _extract_agent_update_request(query):
            return await _update_dynamic_agent(query)

        if _is_registry_scan_query(query):
            return await _scan_agent_registry_text()

        if _is_registry_invalid_query(query):
            return _invalid_agent_registry_text()

        if _is_registry_index_query(query):
            return _agent_registry_index_text()

        if _is_promote_request(query):
            return await _promote_dynamic_agent(query)

        if intent == Intent.IDENTITY_QUERY:
            from core.modules.identity import (
                build_identity_response_async,
                detect_identity_intent,
            )

            identity_result = detect_identity_intent(query)
            kind = identity_result.get("kind") or "identity"
            return await build_identity_response_async(kind, question=query)

        if intent == Intent.SELF_STATUS:
            from agents.runtime.runtime import get_agent_runtime

            runtime = get_agent_runtime()
            runtime.reload()

            model.set_agents_available(runtime.list_agents())
            model.set_last_agent("self_model")
            model.set_last_action("consultation du Self-Model")
            model.set_last_decision("répondre depuis l'état interne réel")
            model.set_last_reasoning("l'intention self_status nécessite une réponse issue du Self-Model")
            model.add_recent_activity("self_model exécuté")
            model.set_last_error(None)

            return model.full_status_text() if hasattr(model, 'full_status_text') else model.summary()

        if intent in (Intent.SYSTEM_STATUS, Intent.NETWORK_STATUS):
            model.set_last_agent("system_agent")
            model.set_last_action("analyse système exécutée")
            model.set_last_decision("retourner l'état système")
            model.set_last_reasoning("l'intention system_status nécessite un diagnostic système")
            model.add_recent_activity("system_agent exécuté")
            model.set_last_error(None)
            result = await _get_system().run(query)
            return _result_to_text(result)

        if intent in (Intent.AGENT_CREATION, Intent.TOOL_CREATION):
            return await _build_tracked_agent(query, source_channel=source_channel)

        if intent == Intent.PROJECT_STATUS:
            return await _project_status_text(query)

        if intent == Intent.PROJECT_LIST:
            return _project_list_text()

        if intent == Intent.AGENT_LIST:
            return _list_dynamic_agents()

        if intent == Intent.AGENT_RUN:
            return await _run_dynamic_agent(query)

        if intent == Intent.NEWS_QUERY:
            result = await _get_news().run(query)
            return _result_to_text(result)

        if intent == Intent.WEATHER_QUERY:
            result = await _get_weather().run(query)
            return _result_to_text(result)

        if intent == Intent.TODO_ACTION:
            q = query.lower()

            if (
                "état des tâches" in q
                or "etat des tâches" in q
                or "etat des taches" in q
                or "status des tâches" in q
                or "status des taches" in q
            ):
                from goal.system.task_manager import get_task_manager

                manager = get_task_manager()
                summary = manager.get_status_summary()

                return (
                    "État des tâches : "
                    f"{summary['pending']} en attente, "
                    f"{summary['running']} en cours, "
                    f"{summary['done']} terminées, "
                    f"{summary['failed']} échouées, "
                    f"{summary['cancelled']} annulées, "
                    f"{summary['total']} au total."
                )

            if (
                "prochaine tâche" in q
                or "prochaine tache" in q
                or "tâche suivante" in q
                or "tache suivante" in q
            ):
                from goal.system.task_manager import get_task_manager

                manager = get_task_manager()
                task = manager.get_next_task()

                if not task:
                    return "Aucune tâche en attente."

                return (
                    "Prochaine tâche : "
                    f"{task['title']} "
                    f"(priorité {task['priority']}, statut {task['status']})."
                )

            if (
                "lance la prochaine tâche" in q
                or "lance la prochaine tache" in q
                or "démarre la prochaine tâche" in q
                or "demarre la prochaine tache" in q
                or "commence la prochaine tâche" in q
                or "commence la prochaine tache" in q
            ):
                from goal.system.task_manager import get_task_manager

                manager = get_task_manager()
                task = manager.start_next_task()

                if not task:
                    return "Aucune tâche en attente à démarrer."

                return (
                    "Tâche démarrée : "
                    f"{task['title']} "
                    f"(priorité {task['priority']})."
                )

            result = await _get_todo().run(query)
            return _result_to_text(result)

        if intent == Intent.WIKI_QUERY:
            result = await _get_wiki().run(query)
            return _result_to_text(result)

        if intent == Intent.TIME_QUERY:
            from core.modules.timer import build_timer_response
            return build_timer_response('time')['response']

        if intent == Intent.HA_ACTION:
            result = await _get_ha().execute(query)
            return _result_to_text(result)

        if intent == Intent.WEB_SEARCH:
            result = await _get_web().execute(query)
            return _result_to_text(result)

        if intent in (Intent.CODE, Intent.CODE_AUDIT):
            CodeAuditAgent = _external_agents.agent_class(
                "agents.builtin.dev.code_audit_agent",
                "CodeAuditAgent",
            )
            agent = CodeAuditAgent()
            result = await agent.execute(query)
            return _result_to_text(result)

        if intent == Intent.PERSONALITY_FEEDBACK:
            from core.personality.updater import apply_feedback
            apply_feedback(query)
            return "⚙️ Ajustement de comportement pris en compte."

        memory = _get_memory()
        context = await memory.get_context(query) if hasattr(memory, "get_context") else None
        result = await _get_llm().execute(query, context_data=context)

        if getattr(result, "success", False):
            if hasattr(memory, "save"):
                await memory.save(query, result.content)
            return result.content

        return f"⚠️ Erreur LLM : {getattr(result, 'error', 'erreur inconnue')}"


@dataclass
class LLMConfig:
    provider: str = "ollama"
    model: str = "mistral"
    base_url: str = "http://localhost:11434"
    max_tokens: int = 2048
    temperature: float = 0.7


class RouterToolBindings:
    def __init__(self):
        self._tools: Dict[str, Any] = {}

    def setup_defaults(self) -> "RouterToolBindings":
        return self

    def register(self, name: str, tool: Any) -> "RouterToolBindings":
        self._tools[name] = tool
        return self
