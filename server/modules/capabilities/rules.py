from __future__ import annotations

from modules.capabilities.models import RuleMatch
from modules.capabilities.router import normalize_text


DOMAIN_RULES: dict[str, tuple[tuple[str, float], ...]] = {
    "christmas": (("noel", 0.99),),
    "easter": (("paques", 0.99),),
    "weather": (
        ("meteo", 0.98),
        ("temperature", 0.91),
        ("pluie", 0.9),
    ),
    "subnet": (
        ("subnet", 0.99),
        ("sous reseau", 0.98),
        ("cidr", 0.97),
    ),
    "logs": (
        ("logs", 0.99),
        ("log neron", 0.98),
        ("journaux systeme", 0.94),
        ("journal systeme", 0.92),
    ),
    "backups": (
        ("sauvegardes", 0.99),
        ("sauvegarde", 0.98),
        ("backups", 0.99),
        ("backup", 0.98),
    ),
    "sqlite": (
        ("sqlite", 0.99),
        ("bases sqlite", 0.99),
        ("base sqlite", 0.99),
    ),
    "systemd": (
        ("systemd", 0.99),
        ("services systemd", 0.99),
        ("unites systemd", 0.97),
    ),
    "agenda": (
        ("agenda", 0.98),
        ("rendez vous", 0.92),
    ),
    "calendar": (
        ("calendrier", 0.98),
        ("evenement calendrier", 0.94),
    ),
    # Domaines couverts par le registre de passerelles (server/gateways) :
    # voir DecisionEngine._GATEWAY_DOMAINS, qui route ces domaines vers un
    # connecteur externe plutot que vers la creation d'une capacite.
    "mail": (
        ("mail", 0.95),
        ("mails", 0.95),
        ("email", 0.95),
        ("emails", 0.95),
        ("courriel", 0.95),
        ("boite mail", 0.96),
        ("boite de reception", 0.97),
    ),
    "contacts": (
        ("mes contacts", 0.98),
        ("carnet d adresses", 0.97),
        ("numero de telephone de", 0.9),
    ),
    "notes": (
        ("mes notes", 0.97),
        ("prise de notes", 0.95),
        ("bloc notes", 0.93),
    ),
    "reminders": (
        ("mes rappels", 0.96),
        ("liste de rappels", 0.96),
        ("rappels google", 0.98),
        ("rappels outlook", 0.98),
    ),
    "repos": (
        ("mon repo", 0.95),
        ("mes repos", 0.95),
        ("depot github", 0.97),
        ("pull request", 0.96),
        ("issue github", 0.96),
    ),
    "docs": (
        ("page notion", 0.97),
        ("mes docs notion", 0.97),
        ("document notion", 0.96),
    ),
}


class RuleEngine:
    def evaluate(self, text: str) -> list[RuleMatch]:
        query = normalize_text(text)
        matches: list[RuleMatch] = []
        for domain, rules in DOMAIN_RULES.items():
            hits = [(term, score) for term, score in rules if term in query]
            if not hits:
                continue
            matches.append(
                RuleMatch(
                    domain=domain,
                    confidence=max(score for _term, score in hits),
                    matched_terms=[term for term, _score in hits],
                )
            )
        return sorted(matches, key=lambda match: match.confidence, reverse=True)

    def best_match(self, text: str) -> RuleMatch | None:
        matches = self.evaluate(text)
        return matches[0] if matches else None
