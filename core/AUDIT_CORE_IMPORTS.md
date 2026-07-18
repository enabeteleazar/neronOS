# Audit Core Imports

Date: 2026-07-18
Scope: `/etc/neronOS/server/core`
Branch: `develop`
Base commit: `19b40b2`

## Commands Run

- `git status`
- `git branch --show-current`
- `git log -5 --oneline`
- `rg -n "^(from |import )" -g "*.py" .`
- `find . -path "*event*" -type f`
- `rg -n "common\.paths|\bllm\b|agents\.builtin|modules\.events|from goal\.|from modules\." -g "*.py" .`

## Findings

| File | Problematic import | Severity | Proposed correction |
| --- | --- | --- | --- |
| `modules/identity/service.py` | `from common.paths import NERON_IDENTITY_PATH` | High | Replace with `from core.config.paths import NERON_IDENTITY_PATH`. |
| `runtime/sandbox/agent_sandbox.py` | `from common.paths import NERON_ROOT` | High | Replace with `from core.config.paths import NERON_ROOT`. |
| `config.py` | `from common.paths import NERON_CONFIG, NERON_ROOT` | High | Move to `core.config.paths` and expose compatibility aliases there. |
| `config_loader.py` | `from common.paths import NERON_CONFIG` | High | Move to `core.config.paths`. |
| `identity/loader.py` | `from common.paths import NERON_IDENTITY_PATH` | High | Move to `core.config.paths`. |
| `api/action_history_routes.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `api/critic_history_routes.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `api/planner_routes.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `modules/self_model/service.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `storage/sqlite_store.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `orchestration/command_dispatcher.py` | `from common.paths import NERON_DATA_DIR` | Medium | Move to `core.config.paths`. |
| `goal_engine/agent_factory.py` | `from common.paths import NERON_DATA_DIR, NERON_ROOT, NERON_WORKSPACE_DIR` | Medium | Move to `core.config.paths`. |
| `pipeline/routing/agent_router.py` | `from common.paths import NERON_WORKSPACE_DIR` | Medium | Move to `core.config.paths`. |
| `providers/bootstrap.py` | `from llm.provider import LLMProvider` | Critical | Replace direct provider import with a Core provider-registry adapter for the external LLM service. |
| `runtime/governor.py` | `from modules.events.event import Event` | High | Use `core.infrastructure.event_bus.Event`, the only event implementation found in Core. |
| `control_plane/events.py` | `from modules.events.event...`, `from modules.events.event_bus...` | High | Replace with a compatibility facade over `core.infrastructure.event_bus`. |
| `app.py` | `from modules.events...` | High | Publish input events through `core.infrastructure.event_bus`. |
| `app.py` | `from agents.builtin.*` | High | Replace static imports with a lazy Core agent registry that can load external agents if available. |
| `api/planner_routes.py` | `from agents.builtin.communication.telegram_agent import send_notification` | Medium | Load notification hook through the Core lazy agent registry. |
| `pipeline/routing/agent_router.py` | lazy `from agents.builtin.*` imports | Medium | Load via the Core lazy agent registry. |
| `goal_engine/engine.py`, `pipeline/orchestrator.py`, `pipeline/intent/intent_router.py` | `from agents.builtin.base_agent import get_logger` | Medium | Use Core fallback logger loader. |
| `agents/communication/telegram_agent.py` | `from agents.builtin.communication.telegram_agent import *` | Medium | Replace with lazy attribute resolution. |
| `app.py`, `api/*`, `orchestration/*`, `pipeline/*` | imports from `goal.*` and `modules.*` submodules | High | Keep for compatibility in this pass; migrate to service/registry interfaces in a later dedicated phase. |
| `agent_runtime/*`, `scheduler/*`, `tools/*`, `world_model/*` | compatibility wrappers to external packages | Medium | Replace with local registry/service adapters or optional router registration. |

## Event System

`find . -path "*event*" -type f` found the current Core implementation at:

- `infrastructure/event_bus.py`
- `control_plane/events.py`

No `modules.events` implementation exists inside Core, so direct imports from `modules.events` are invalid for an autonomous Core.

## Circular Dependencies

No syntax-level circular import blocker was exposed by `compileall`. The remaining architectural cycle risk is indirect: `app.py` and routing modules still import external `goal.*` and `modules.*` packages at import time. Those should be moved behind registries or optional route adapters.
