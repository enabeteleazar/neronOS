"""Instantane doctor pour le SelfModel.

Interroge doctor (127.0.1.9:8060) cote Core et expose le resultat de ses
trois sondes (server_health, server_status, llm_health), avec le meme
principe de TTL court que homelab.py/print_snapshot.py. Le Dashboard ne
lit que le SelfModel, jamais doctor directement (les adresses 127.0.1.x
ne sont pas joignables depuis un navigateur distant).

doctor protege /health par une cle API (X-Doctor-Key) — lue depuis
NERON_DOCTOR_API_KEY, deja fournie au Core par secrets.env.
"""

import os
import time

import httpx

_DOCTOR_BASE_URL = "http://127.0.1.9:8060"
_TTL_SECONDS = 2.0

_cache: dict = {}
_cache_time: float = 0.0


def doctor_snapshot() -> dict:
    global _cache, _cache_time

    now = time.monotonic()
    if _cache and (now - _cache_time) < _TTL_SECONDS:
        return _cache

    api_key = os.getenv("NERON_DOCTOR_API_KEY", "")
    headers = {"X-Doctor-Key": api_key} if api_key else {}

    snapshot = {"reachable": False, "probes": {}}
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{_DOCTOR_BASE_URL}/health", headers=headers)
            response.raise_for_status()
            probes = response.json()
            snapshot = {
                "reachable": True,
                "probes": probes,
                "all_ok": all(
                    isinstance(p, dict) and p.get("ok", False)
                    for p in probes.values()
                ),
            }
    except Exception:
        pass

    _cache = snapshot
    _cache_time = now
    return snapshot
