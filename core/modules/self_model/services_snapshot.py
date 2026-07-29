"""Snapshot des unités systemd du projet Néron.

Étape 1 : systemd seul. La fusion avec le registry viendra ensuite.
"""
from __future__ import annotations

import re
import subprocess
import time

from core.runtime.governor import get_runtime_governor

_ACTOR = "self_model.services_snapshot"
_PATTERN = "neron*"
_PROPS = "Id,LoadState,ActiveState,SubState,NRestarts,ActiveEnterTimestamp,MainPID"
_TTL = 5.0
_TIMEOUT = 5

_cache: dict | None = None
_cache_at = 0.0


def _run(command: list[str]) -> str | None:
    governor = get_runtime_governor()
    if not governor.authorize_system_command(
        actor=_ACTOR,
        command=command,
        reason="lecture de l etat des unites systemd pour le self_model",
    ):
        return None
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def _service_key(unit: str) -> str:
    """neron@core.service -> core ; neron-dashboard.service -> dashboard."""
    name = unit.rsplit(".", 1)[0]
    m = re.match(r"^neron@(.+)$", name)
    if m:
        return m.group(1)
    m = re.match(r"^neron-(.+)$", name)
    if m:
        return m.group(1)
    return name


def _discover() -> list[str] | None:
    out = _run([
        "systemctl", "list-units", _PATTERN,
        "--all", "--no-pager", "--no-legend", "--plain",
    ])
    if out is None:
        return None
    units = []
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].endswith(".service"):
            units.append(parts[0])
    return sorted(set(units))


def _show(units: list[str]) -> dict:
    if not units:
        return {}
    out = _run(["systemctl", "show", *units, f"--property={_PROPS}", "--no-pager"])
    if out is None:
        return {}
    blocks = {}
    for block in out.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                fields[k] = v
        unit = fields.get("Id")
        if unit:
            blocks[unit] = fields
    return blocks


_ALIASES = {
    "homeassistant-registry": "homeassistant",
    "web-registry": "web",
}


def _foreign_nodes() -> set:
    try:
        from core.modules.self_model.homelab import FOREIGN_NODES
        return set(FOREIGN_NODES)
    except Exception:
        return set()


def _registry_index() -> dict:
    try:
        from core.infrastructure.registry import service_registry
        entries = service_registry.list_services()
    except Exception:
        return {}
    index = {}
    for e in entries or []:
        name = (e.get("service_name") or e.get("name") or "").strip()
        if name:
            index[name] = e
    return index


def _merge(rows: list[dict]) -> list[dict]:
    index = _registry_index()
    seen = set()
    for row in rows:
        name = _ALIASES.get(row["key"], row["key"])
        row["registry_name"] = name
        entry = index.get(name)
        row["registered"] = bool(entry)
        row["state"] = "ok" if entry else "unregistered"
        row["version"] = (entry or {}).get("version")
        row["registry_status"] = (entry or {}).get("status")
        row["host"] = (entry or {}).get("host")
        row["port"] = (entry or {}).get("port")
        if entry:
            seen.add(name)
    for name, entry in index.items():
        if name in seen:
            continue
        rows.append({
            "key": name,
            "unit": None,
            "registry_name": name,
            "load_state": "not-found",
            "active_state": "unknown",
            "sub_state": "unknown",
            "restarts": 0,
            "since": None,
            "main_pid": None,
            "registered": True,
            "state": "foreign" if name in _foreign_nodes() else "orphan",
            "version": entry.get("version"),
            "registry_status": entry.get("status"),
            "host": entry.get("host"),
            "port": entry.get("port"),
        })
    return rows


def _build() -> dict:
    units = _discover()
    if units is None:
        return {"available": False, "reason": "system_command_denied", "units": []}
    by_unit = _show(units)
    rows = []
    for unit in units:
        f = by_unit.get(unit, {})
        try:
            restarts = int(f.get("NRestarts", "0"))
        except ValueError:
            restarts = 0
        rows.append({
            "key": _service_key(unit),
            "unit": unit,
            "load_state": f.get("LoadState", "unknown"),
            "active_state": f.get("ActiveState", "unknown"),
            "sub_state": f.get("SubState", "unknown"),
            "restarts": restarts,
            "since": f.get("ActiveEnterTimestamp") or None,
            "main_pid": f.get("MainPID") or None,
        })
    return {"available": True, "units": _merge(rows)}


def services_snapshot() -> dict:
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _TTL:
        return _cache
    _cache = _build()
    _cache_at = now
    return _cache
