# Core Cleanup Report

Date: 2026-07-18
Scope: `/etc/neronOS/server/core`

## Corrections Performed

- Added Core-owned path aliases in `config/paths.py` for `NERON_ROOT`, `NERON_CONFIG`, `NERON_DATA_DIR`, `NERON_WORKSPACE_DIR`, and `NERON_IDENTITY_PATH`.
- Replaced all detected direct `common.paths` imports in Core Python files with `core.config.paths`.
- Replaced the direct `llm.provider.LLMProvider` dependency with `core.providers.llm.ExternalLLMProvider`, registered through the existing Provider Registry.
- Migrated `runtime/governor.py`, `control_plane/events.py`, and `app.py` away from `modules.events` to `core.infrastructure.event_bus`.
- Added `core.agent_registry.AgentRegistry` as a lazy compatibility loader for external agents.
- Replaced static `agents.builtin.*` imports in `app.py`, planner notification, routing agent constructors, and Core logger imports with Core lazy loading/fallbacks.
- Converted `agents/communication/telegram_agent.py` from a star import wrapper to lazy attribute resolution.
- Fixed the existing `app.py` syntax issue around `/input/text`; validation now passes.

## Files Modified

- `api/action_history_routes.py`
- `api/critic_history_routes.py`
- `api/planner_routes.py`
- `app.py`
- `agents/communication/telegram_agent.py`
- `config.py`
- `config/paths.py`
- `config_loader.py`
- `control_plane/events.py`
- `goal_engine/agent_factory.py`
- `goal_engine/engine.py`
- `identity/loader.py`
- `modules/identity/service.py`
- `modules/self_model/service.py`
- `orchestration/command_dispatcher.py`
- `pipeline/intent/intent_router.py`
- `pipeline/orchestrator.py`
- `pipeline/routing/agent_router.py`
- `providers/bootstrap.py`
- `runtime/governor.py`
- `runtime/sandbox/agent_sandbox.py`
- `storage/sqlite_store.py`

## Files Added

- `agent_registry.py`
- `providers/llm.py`
- `AUDIT_CORE_IMPORTS.md`
- `CORE_CLEANUP_REPORT.md`

## Imports Removed

- `from common.paths ...`
- `from llm.provider import LLMProvider`
- `from modules.events.event import Event`
- `from modules.events.event_bus import event_bus`
- `from modules.events.event_types import USER_MESSAGE_RECEIVED`
- `from modules.events.subscribers import register_default_subscribers`
- Static imports from `agents.builtin.*` in `app.py`
- Static `agents.builtin.base_agent.get_logger` imports in Core routing/orchestration modules
- Star import wrapper for `agents.builtin.communication.telegram_agent`

## Validation

- `python` is not available in this environment.
- `python3 -m compileall .` passed.
- AST parsing of every `*.py` file with `python3` passed.

## Risks Remaining

- Several Core routes still import `goal.*` and external `modules.*` packages directly. They should become optional adapters registered through Core Gateway/Registry boundaries.
- `agent_runtime`, `scheduler`, `tools`, and `world_model` still contain compatibility wrappers to external packages.
- `gateway/telegram_gateway.py` still has an optional Twilio agent import inside a command handler.
- `gateway/gateway.py` references external STT/TTS classes under `TYPE_CHECKING`; this is not runtime-coupled but still documents external type names.
- `providers/bootstrap.py` still imports Home Assistant provider directly from `integrations.homeassistant.provider`; this should become another provider-registry adapter in the next pass.

## Recommended Next Steps

1. Move external route registration in `app.py` behind an optional router registry.
2. Replace direct `goal.*` imports with Core Goal Engine interfaces or HTTP/service clients.
3. Replace external `modules.*` imports with Core-owned adapters for capabilities, scheduler, sessions, skills, world model, and cognitive history.
4. Convert compatibility wrappers (`agent_runtime`, `scheduler`, `tools`, `world_model`) into explicit gateway adapters or remove them once consumers are migrated.
5. Add import-boundary tests that fail on new `common.paths`, `modules.events`, `llm.provider`, or static `agents.builtin` imports.
