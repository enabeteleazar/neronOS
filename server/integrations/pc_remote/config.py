from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SECRETS_PATHS = (
    ROOT / "secrets.env",
    ROOT / "secret.env",
    Path("/etc/neronOS/secrets.env"),
)


@dataclass(frozen=True)
class PCRemoteDevice:
    id: str
    name: str
    url: str
    token: str
    timeout: float = 5.0
    retries: int = 1

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _secrets() -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in DEFAULT_SECRETS_PATHS:
        merged.update(_parse_env_file(path))
    return merged


def _project_config() -> dict[str, Any]:
    path = ROOT / "neron.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def is_enabled() -> bool:
    """Lit `pc_remote.enabled` dans neron.yaml (par defaut True si absent, pour
    ne pas casser une config existante qui ne declare pas cette cle)."""
    section = _project_config().get("pc_remote") or {}
    if not isinstance(section, dict):
        return True
    return bool(section.get("enabled", True))


def load_devices() -> dict[str, PCRemoteDevice]:
    """Charge le registre declaratif des PC distants pilotables (neron.yaml: pc_remote.devices).

    Chaque entree attend un `token_env` (ou `PC_REMOTE_<ID>_TOKEN` par defaut)
    resolu depuis l'environnement ou secrets.env : jamais de secret en dur ici.

    Retourne un registre vide si `pc_remote.enabled: false` : plus aucun
    device n'est expose, quelle que soit la liste declaree sous `devices`.
    """
    devices: dict[str, PCRemoteDevice] = {}
    if not is_enabled():
        return devices

    secrets = _secrets()
    project = _project_config()
    section = project.get("pc_remote") or {}
    if not isinstance(section, dict):
        section = {}
    raw_devices = section.get("devices")
    if not isinstance(raw_devices, list):
        return devices
    for entry in raw_devices:
        if not isinstance(entry, dict):
            continue
        device_id = str(entry.get("id") or "").strip()
        if not device_id:
            continue
        token_env = str(entry.get("token_env") or f"PC_REMOTE_{device_id.upper()}_TOKEN")
        token = os.getenv(token_env) or secrets.get(token_env) or ""
        devices[device_id] = PCRemoteDevice(
            id=device_id,
            name=str(entry.get("name") or device_id),
            url=str(entry.get("url") or "").rstrip("/"),
            token=token,
            timeout=float(entry.get("timeout") or 5.0),
            retries=int(entry.get("retries") or 1),
        )
    return devices
