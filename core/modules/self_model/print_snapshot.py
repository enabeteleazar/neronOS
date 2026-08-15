"""Instantane print_service pour le SelfModel.

Interroge print_service (127.0.1.7:8050) cote Core et expose statut +
niveaux d'encre, avec le meme principe de TTL court que homelab.py.
Le Dashboard ne lit que le SelfModel, jamais print_service directement
(les adresses 127.0.1.x ne sont pas joignables depuis un navigateur
distant).
"""

import time

import httpx

_PRINT_BASE_URL = "http://127.0.1.7:8050"
_KNOWN_PRINTERS = ["EPSON_XP-2200_Series", "HP_LaserJet_M2727nf_MFP"]
_TTL_SECONDS = 2.0

_cache: dict = {}
_cache_time: float = 0.0


def print_snapshot() -> dict:
    global _cache, _cache_time

    now = time.monotonic()
    if _cache and (now - _cache_time) < _TTL_SECONDS:
        return _cache

    printers = []
    with httpx.Client(timeout=2.0) as client:
        for name in _KNOWN_PRINTERS:
            entry = {"name": name, "reachable": False}
            try:
                status_resp = client.get(f"{_PRINT_BASE_URL}/print/status/{name}")
                status_resp.raise_for_status()
                entry.update(status_resp.json())
                entry["reachable"] = True
            except Exception:
                pass

            try:
                supplies_resp = client.get(f"{_PRINT_BASE_URL}/print/supplies/{name}")
                supplies_resp.raise_for_status()
                entry["supplies"] = supplies_resp.json()
            except Exception:
                entry["supplies"] = {"printer": name, "supported": False, "levels": []}

            printers.append(entry)

    snapshot = {"printers": printers}
    _cache = snapshot
    _cache_time = now
    return snapshot
