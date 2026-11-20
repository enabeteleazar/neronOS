"""Métriques Prometheus du processus Core, lues localement.

Collecte opérationnelle : elle relève du module status, pas du SelfModel, qui
ne fait que représenter (tests/test_self_model_canonical.py). Le SelfModel
(homelab) s'en sert pour le rack du Core : l'endpoint /metrics du Core exige
la clé d'API, et le collecteur tourne déjà dans son processus.
"""
from __future__ import annotations


def local_metrics_text() -> str:
    """Exposition texte des métriques du processus courant, ou "" si indisponible."""
    try:
        from prometheus_client import REGISTRY, generate_latest

        return generate_latest(REGISTRY).decode("utf-8")
    except Exception:
        return ""
