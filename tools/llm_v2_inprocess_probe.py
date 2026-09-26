#!/usr/bin/env python3
"""Sonde niveau B pour le benchmark V2 (num_predict variable).

Pourquoi ce fichier existe : POST /llm/generate (GenerateRequest) n'expose
aucun champ num_predict — c'est fixe au demarrage du service, lu depuis
`llm.ollama_num_predict` dans neron.yaml (server/llm/providers/ollama.py).
Le service de production ne doit pas etre modifie ni redemarre pour ce
benchmark. Solution retenue : instancier ici, dans un sous-processus
JETABLE, le meme LLMManager que la production, mais pointe (via la
variable d'environnement NERON_CONFIG, deja supportee par
server/common/paths.py) vers une copie temporaire de neron.yaml dont seul
`llm.ollama_num_predict` differe. Le vrai neron.yaml et le service
neron@llm.service tournant en direct ne sont jamais touches.

Appele en sous-processus par tools/benchmark_llm_v2.py, jamais a la main.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1] / "server"
sys.path.insert(0, str(SERVER_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm.core.manager import LLMManager  # noqa: E402
from llm.core.types import LLMRequest  # noqa: E402
from benchmark_llm import TESTS  # noqa: E402  (reutilise le meme jeu de prompts)


async def run(model: str, num_predict: int, runs: int, warmup: int,
               timeout_s: float, output_path: str, test_ids: set[str] | None) -> None:
    manager = LLMManager()
    tests = TESTS if not test_ids else [t for t in TESTS if t["id"] in test_ids]
    try:
        with open(output_path, "a") as fh:
            for test in tests:
                for i in range(warmup + runs):
                    is_warmup = i < warmup
                    run_idx = None if is_warmup else i - warmup + 1
                    t0 = time.monotonic()
                    error = None
                    text = None
                    try:
                        result = await asyncio.wait_for(
                            manager.handle(LLMRequest(
                                message=test["prompt"],
                                task=test["task_type"],
                                model=model,
                            )),
                            timeout=timeout_s,
                        )
                        text = result.response
                        actual_model = result.model
                        if result.provider == "none" or result.error:
                            error = result.error or "provider none"
                        elif actual_model and actual_model != model:
                            # NeronLLM a son propre fallback interne (router/manager) :
                            # sous charge, une resolution modele qui time out (ex:
                            # GET /api/tags) le fait basculer sur un AUTRE modele que
                            # celui demande. Sans ce controle, l'enregistrement serait
                            # silencieusement mislabelled (attribue au mauvais modele).
                            error = f"modele reellement utilise = '{actual_model}' (fallback, pas '{model}')"
                    except asyncio.TimeoutError:
                        actual_model = None
                        error = f"timeout > {timeout_s}s"
                    except Exception as exc:
                        actual_model = None
                        error = str(exc)
                    wall = time.monotonic() - t0

                    rec = {
                        "level": "B_neron_llm_inprocess",
                        "model": model,
                        "actual_model_used": actual_model,
                        "num_predict": num_predict,
                        "test_id": test["id"],
                        "is_warmup": is_warmup,
                        "run_idx": run_idx,
                        "error": error,
                        "response_text": text,
                        "wall_duration_s": wall,
                        "latency_ms_reported": int(wall * 1000) if error is None else None,
                        # Non disponible : LLMResponse ne porte pas les stats
                        # Ollama internes (eval_count, etc.) — jamais devine.
                        "time_to_first_token_s": None,
                        "load_duration_s": None,
                        "prompt_eval_count": None,
                        "prompt_eval_duration_s": None,
                        "eval_count": None,
                        "eval_duration_s": None,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    status = "WARMUP" if is_warmup else f"run {run_idx}/{runs}"
                    err_str = f" ERREUR: {error}" if error else ""
                    print(f"    [B-inprocess np={num_predict}] {test['id']:<22} {status:<10} {wall:.1f}s{err_str}", flush=True)
    finally:
        await manager.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--num-predict", type=int, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--warmup", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=150.0)
    ap.add_argument("--output", required=True)
    ap.add_argument("--test-ids", default=None)
    args = ap.parse_args()

    ids = {t.strip() for t in args.test_ids.split(",")} if args.test_ids else None
    asyncio.run(run(args.model, args.num_predict, args.runs, args.warmup, args.timeout, args.output, ids))
