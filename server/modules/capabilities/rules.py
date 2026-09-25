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
