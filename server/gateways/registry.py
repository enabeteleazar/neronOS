"""Registre declaratif des connecteurs de passerelles (connectors.yaml).

Charge une seule fois par processus : le registre est un catalogue statique,
pas un etat mutable (l'etat de connexion vit dans `gateways.store`).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from gateways.models import Connector

CONNECTORS_FILE = Path(__file__).resolve().parent / "connectors.yaml"


class ConnectorRegistry:
    def __init__(self, path: Path = CONNECTORS_FILE) -> None:
        self._path = path
        self._connectors = self._load(path)

    def _load(self, path: Path) -> dict[str, Connector]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries = data.get("connectors") or []
        connectors = [Connector.model_validate(entry) for entry in entries]
        return {connector.id: connector for connector in connectors}

    def list_connectors(self) -> list[Connector]:
        return list(self._connectors.values())

    def get(self, connector_id: str) -> Connector | None:
        return self._connectors.get(connector_id)

    def find_by_domain(self, domain: str) -> list[Connector]:
        return [c for c in self._connectors.values() if domain in c.domains]

    def domains(self) -> set[str]:
        return {domain for c in self._connectors.values() for domain in c.domains}


@lru_cache
def get_registry() -> ConnectorRegistry:
    return ConnectorRegistry()
