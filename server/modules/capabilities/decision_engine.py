from __future__ import annotations

from typing import Any, Callable

from modules.capabilities.models import CapabilityMatch, IntentUnderstanding
from modules.capabilities.router import normalize_text

GatewayMatch = tuple[Any, Any]  # (gateways.models.Connector, gateways.models.ConnectorState)
GatewayLookup = Callable[[str], list[GatewayMatch]]


def _default_gateway_lookup(domain: str) -> list[GatewayMatch]:
    """Interroge le registre de passerelles (server/gateways) pour ce domaine.

    Import tardif : `gateways` ne doit pas devenir une dependance de
    chargement de `modules.capabilities`, seulement un service consulte a la
    demande (comme `goal`, `agents`, `tools` ailleurs dans ce module).
    """
    from gateways.registry import get_registry
    from gateways.store import ConnectionStore

    connectors = get_registry().find_by_domain(domain)
    if not connectors:
        return []
    store = ConnectionStore()
    return [(connector, store.get_state(connector.id)) for connector in connectors]


class DecisionEngine:
    _OPERATIONAL_DOMAINS = {"logs", "backups", "sqlite", "systemd"}

    # Domaines dont la resolution appartient au registre de passerelles
    # (server/gateways), pas a la generation dynamique d'agent/tool. Un
    # domaine present ici mais sans connecteur couvrant (encore) le domaine
    # produit explicitement "aucune passerelle", jamais un agent auto-genere.
    _GATEWAY_DOMAINS = {
        "mail", "contacts", "notes", "reminders", "calendar", "repos", "docs",
    }

    def __init__(self, *, gateway_lookup: GatewayLookup | None = None) -> None:
        self._gateway_lookup = gateway_lookup or _default_gateway_lookup

    def decide(
        self,
        text: str,
        understanding: IntentUnderstanding,
        match: CapabilityMatch | None,
    ) -> tuple[str, float, str, dict[str, Any]]:
        intent = understanding.intent
        domain = understanding.domain

        if intent.requested_type:
            decision = f"create_{intent.requested_type}"
            return decision, intent.confidence, "Création demandée explicitement.", {}

        if match is not None:
            if match.missing_tools:
                return (
                    "create_tool",
                    match.score,
                    "La capacité existe mais un tool déclaré est indisponible.",
                    {},
                )
            if match.capability.capability_type == "agent":
                return "execute_agent", match.score, "Agent pertinent trouvé.", {}
            return "execute_tool", match.score, "Tool pertinent trouvé.", {}

        if intent.durable or intent.action in {"surveillance", "notification"}:
            return (
                "create_agent",
                max(intent.confidence, domain.confidence),
                "La demande implique une capacité durable.",
                {},
            )

        if (
            domain.domain in self._OPERATIONAL_DOMAINS
            and intent.action in {"analyse", "resume", "diagnostic", "recherche"}
            and not self._is_inline_payload_request(text)
        ):
            return (
                "create_agent",
                round(max(domain.confidence, intent.confidence), 3),
                "Aucun agent pertinent ne couvre ce domaine opérationnel.",
                {},
            )

        if domain.domain in self._GATEWAY_DOMAINS:
            gateway_decision = self._decide_gateway(domain)
            if gateway_decision is not None:
                return gateway_decision

        if domain.domain != "unknown":
            return (
                "create_tool",
                round(max(domain.confidence, intent.confidence), 3),
                "Le domaine est identifié mais aucune capacité ne le couvre.",
                {},
            )

        if intent.action in {
            "analyse",
            "resume",
            "diagnostic",
            "calcul",
            "recherche",
            "comparaison",
        }:
            return (
                "create_tool",
                round(max(domain.confidence, intent.confidence), 3),
                "La demande ponctuelle nécessite un nouveau tool.",
                {},
            )

        return (
            "fallback_conversation",
            understanding.confidence,
            "Aucune intention opérationnelle suffisamment précise.",
            {},
        )

    def _decide_gateway(self, domain: Any) -> tuple[str, float, str, dict[str, Any]] | None:
        matches = self._gateway_lookup(domain.domain)

        connected = [(c, s) for c, s in matches if s.status == "connected"]
        if connected:
            connector, _state = connected[0]
            return (
                "use_gateway",
                round(domain.confidence, 3),
                f"Domaine couvert par le connecteur '{connector.id}', déjà connecté.",
                {"gateway_connector_id": connector.id},
            )

        if matches:
            connector, _state = matches[0]
            return (
                "propose_gateway_connection",
                round(domain.confidence, 3),
                f"Domaine couvert par le connecteur '{connector.id}', non connecté.",
                {"gateway_connector_id": connector.id},
            )

        return (
            "no_gateway_available",
            round(domain.confidence, 3),
            f"Aucun connecteur ne couvre le domaine '{domain.domain}'.",
            {},
        )

    def _is_inline_payload_request(self, text: str) -> bool:
        query = normalize_text(text)
        return any(
            marker in query
            for marker in ("ces logs", "ce contenu", "ces donnees", "ce texte")
        ) or (
            "logs" in query
            and any(marker in query for marker in ("resume", "resumer"))
            and "automatiquement" not in query
        )
