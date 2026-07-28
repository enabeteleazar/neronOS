"""Homelab catalog and slot assignment for the Self Model."""

from __future__ import annotations

import ipaddress
import json
import urllib.request
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config.paths import NERON_DATA_DIR, find_neron_home
from core.modules.self_model.state import _read_state, _write_state

CATALOG_PATH = Path(
    os.getenv(
        "NERON_HOMELAB_CATALOG_PATH",
        str(NERON_DATA_DIR / "homelab_catalog.json"),
    )
)


def _read_catalog() -> dict[str, Any]:
    if not CATALOG_PATH.exists():
        return {"items": []}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except Exception:
        return {"items": []}


def get_catalog() -> dict[str, Any]:
    return _read_catalog()


def get_homelab_slots() -> dict[str, str]:
    state = _read_state()
    homelab = state.get("homelab") or {}
    return dict(homelab.get("slots") or {})


def set_homelab_slot(unit_id: str, catalog_id: str | None) -> dict[str, str]:
    catalog = _read_catalog()
    valid_ids = {item.get("id") for item in catalog.get("items", [])}
    if catalog_id is not None and catalog_id not in valid_ids:
        raise ValueError(f"catalog_id '{catalog_id}' introuvable dans le catalogue")

    state = _read_state()
    homelab = dict(state.get("homelab") or {})
    slots = dict(homelab.get("slots") or {})
    if catalog_id is None:
        slots.pop(unit_id, None)
    else:
        slots[unit_id] = catalog_id
    homelab["slots"] = slots
    state["homelab"] = homelab
    _write_state(state)
    return slots


# ── Racks : topologie lue dans neron.server.yaml ──────────────────────────────

FOREIGN_NODES = {"homeassistant", "searxng"}

_TCP_TIMEOUT = 0.2
_RACKS_TTL = 5.0
_SCRAPE_TIMEOUT = 0.5

# Metriques standard de prometheus_client, presentes dans tous les services.
_M_RAM = "process_resident_memory_bytes"
_M_CPU = "process_cpu_seconds_total"
_M_START = "process_start_time_seconds"

# Dernier releve CPU par occupant, pour calculer un taux entre deux collectes.
_cpu_samples: dict[str, tuple[float, float]] = {}
_racks_cache: tuple[float, list[dict[str, Any]]] = (0.0, [])


@lru_cache(maxsize=1)
def _server_config_path() -> Path:
    env = os.getenv("NERON_SERVER_CONFIG")
    if env:
        return Path(env).expanduser()
    return find_neron_home() / "neron.server.yaml"


def _load_server_nodes() -> dict[str, Any]:
    """Section `nodes`, relue a chaque appel : changer une adresse dans le
    YAML doit etre pris en compte sans redemarrer le service."""

    import yaml

    try:
        raw = _server_config_path().read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError):
        return {}

    nodes = data.get("nodes")
    return nodes if isinstance(nodes, dict) else {}


def _host_sort_key(host: str) -> tuple:
    try:
        return (0, int(ipaddress.ip_address(host)))
    except ValueError:
        return (1, host)


def _tcp_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_TCP_TIMEOUT):
            return True
    except OSError:
        return False


def _parse_metrics(text: str) -> dict[str, float]:
    wanted = {_M_RAM, _M_CPU, _M_START}
    found: dict[str, float] = {}

    for line in text.splitlines():
        if not line or line[0] == "#":
            continue
        name, _, value = line.partition(" ")
        if name in wanted:
            try:
                found[name] = float(value)
            except ValueError:
                continue

    return found


def _fetch_metrics(key: str, host: str, port: int) -> dict[str, float]:
    """Releve brut d'un noeud. Le Core est lu localement : son endpoint exige
    la cle d'API, et le collecteur tourne deja dans son processus."""

    if key == "core":
        try:
            from prometheus_client import REGISTRY, generate_latest

            return _parse_metrics(generate_latest(REGISTRY).decode("utf-8"))
        except Exception:
            return {}

    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/metrics", timeout=_SCRAPE_TIMEOUT
        ) as response:
            return _parse_metrics(response.read().decode("utf-8", "replace"))
    except Exception:
        return {}


def _measure(key: str, host: str, port: int) -> dict[str, Any]:
    raw = _fetch_metrics(key, host, port)
    if not raw:
        return {}

    now = time.time()
    result: dict[str, Any] = {}

    if _M_RAM in raw:
        result["ram_mb"] = round(raw[_M_RAM] / 1024 / 1024, 1)

    if _M_START in raw:
        result["uptime_seconds"] = round(now - raw[_M_START], 1)

    if _M_CPU in raw:
        previous = _cpu_samples.get(key)
        _cpu_samples[key] = (now, raw[_M_CPU])
        if previous:
            elapsed = now - previous[0]
            if elapsed > 0:
                delta = raw[_M_CPU] - previous[1]
                result["cpu_percent"] = round(max(delta, 0.0) / elapsed * 100, 1)

    return result


def _build_racks() -> list[dict[str, Any]]:
    by_host: dict[str, list[dict[str, Any]]] = {}

    for name, cfg in _load_server_nodes().items():
        if not isinstance(cfg, dict):
            continue
        host = str(cfg.get("host") or "").strip()
        if not host:
            continue
        ports = sorted(
            value
            for key, value in cfg.items()
            if key.endswith("port") and isinstance(value, int)
        )
        by_host.setdefault(host, []).append({"key": name, "ports": ports})

    racks: list[dict[str, Any]] = []
    jobs: list[tuple[dict[str, Any], str, int]] = []

    for index, host in enumerate(sorted(by_host, key=_host_sort_key), start=1):
        occupants = []
        for occupant in sorted(by_host[host], key=lambda o: o["key"]):
            ports = occupant["ports"]
            if not ports:
                state = "inconnu"
            elif any(_tcp_open(host, port) for port in ports):
                state = "actif"
            else:
                state = "injoignable"
            entry = {
                **occupant,
                "state": state,
                "foreign": occupant["key"] in FOREIGN_NODES,
            }
            if state == "actif" and not entry["foreign"]:
                jobs.append((entry, host, ports[0]))
            occupants.append(entry)
        racks.append({"unit": f"U{index}", "host": host, "occupants": occupants})

    if jobs:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_measure, entry["key"], host, port): entry
                for entry, host, port in jobs
            }
            for future in futures:
                try:
                    futures[future].update(future.result(timeout=_SCRAPE_TIMEOUT + 0.2))
                except Exception:
                    pass

    return racks


def get_racks() -> list[dict[str, Any]]:
    global _racks_cache
    now = time.monotonic()
    stamp, cached = _racks_cache
    if cached and now - stamp < _RACKS_TTL:
        return cached
    racks = _build_racks()
    _racks_cache = (now, racks)
    return racks


def homelab_snapshot() -> dict[str, Any]:
    return {
        "catalog": _read_catalog().get("items", []),
        "slots": get_homelab_slots(),
        "racks": get_racks(),
    }
