#!/usr/bin/env python3
"""Instance jetable de NeronLLM pour validation V3 — expose le VRAI
POST /llm/generate (meme code que server/llm/api/routes.py) sans passer
par create_service_app(), pour eviter tout enregistrement au registry de
services de Core (qui pourrait entrer en collision avec le service
neron@llm.service en production).

Isolation totale :
  - config lue depuis NERON_CONFIG (copie temporaire de neron.yaml, seul
    ollama_num_predict differe) — jamais le neron.yaml reel ;
  - port dedie (jamais 8765, celui de la prod) ;
  - pas de RegistryClient, pas de mount_metrics partage ;
  - NERON_API_KEY non definie => auth desactivee (instance non exposee
    au-dela de 127.0.0.1, usage test uniquement).

Lance par tools/benchmark_llm_v3.py, jamais a la main en temps normal.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))

from fastapi import FastAPI  # noqa: E402
from llm.api.routes import router  # noqa: E402
from llm.core.manager import LLMManager  # noqa: E402


def build_app() -> FastAPI:
    app = FastAPI(title="neron_llm_v3_test_instance")
    app.state.settings = None  # force repli sur get_settings() (cache module) dans routes.py
    app.state.manager = LLMManager()
    app.state.reload_lock = asyncio.Lock()
    app.include_router(router)

    @app.get("/v3_ready")
    async def _ready():
        return {"ready": True}

    return app


app = build_app()

if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
