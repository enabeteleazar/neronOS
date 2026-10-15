from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Iterable


Rule = Callable[[list[str]], list[str]]


_APOSTROPHES = str.maketrans({
    "’": "'",
    "‘": "'",
    "`": "'",
    "´": "'",
})

_PUNCTUATION_RE = re.compile(r"[^a-z0-9./:' ]+")
_MULTISPACE_RE = re.compile(r"\s+")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _join_clitics(tokens: list[str]) -> list[str]:
    joined: list[str] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"c", "qu", "j", "m", "t", "s", "l", "d", "n"} and i + 1 < len(tokens):
            joined.append(f"{token}'{tokens[i + 1]}")
            i += 2
            continue
        joined.append(token)
        i += 1
    return joined


def _split_clitics(value: str) -> str:
    value = re.sub(r"\b(c|qu|j|m|t|s|l|d|n)'", r"\1 ", value)
    return value


def _rule_light_grammar(tokens: list[str]) -> list[str]:
    fixed = list(tokens)
    for i in range(len(fixed) - 2):
        if fixed[i : i + 3] == ["qui", "est", "tu"]:
            fixed[i + 1] = "es"
        if fixed[i : i + 3] == ["tu", "est", "qui"]:
            fixed[i + 1] = "es"

    for i in range(len(fixed) - 1):
        if fixed[i : i + 2] == ["tu", "est"]:
            fixed[i + 1] = "es"
        if fixed[i : i + 2] == ["quel", "heure"]:
            fixed[i] = "quelle"
        if fixed[i] in {"le", "un"} and fixed[i + 1].endswith("s") and len(fixed[i + 1]) > 3:
            fixed[i + 1] = fixed[i + 1].rstrip("s")

    return fixed


def _rule_stt_fillers(tokens: list[str]) -> list[str]:
    fillers = {"euh", "heu", "hum", "bah", "ben"}
    return [token for token in tokens if token not in fillers]


def _rule_oral_variants(tokens: list[str]) -> list[str]:
    fixed = list(tokens)
    for i in range(len(fixed) - 3):
        if fixed[i : i + 4] == ["c", "est", "quoi", "ton"]:
            fixed[i : i + 4] = ["quel", "est", "ton"]
    return fixed


def _rule_command_synonyms(tokens: list[str]) -> list[str]:
    synonyms = {
        "demarre": "lance",
        "demarrer": "lance",
        "lances": "lance",
    }
    return [synonyms.get(token, token) for token in tokens]


@dataclass(frozen=True)
class FrenchTextNormalizer:
    rules: tuple[Rule, ...] = (
        _rule_stt_fillers,
        _rule_command_synonyms,
        _rule_light_grammar,
        _rule_oral_variants,
    )

    def normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKC", text or "")
        value = value.translate(_APOSTROPHES).lower().strip()
        value = value.replace("-", " ")
        value = _strip_accents(value)
        value = _split_clitics(value)
        value = _PUNCTUATION_RE.sub(" ", value)
        value = _MULTISPACE_RE.sub(" ", value).strip()

        tokens = value.split()
        for rule in self.rules:
            tokens = rule(tokens)

        return " ".join(tokens)

    def display(self, text: str) -> str:
        return " ".join(_join_clitics(self.normalize(text).split()))


_DEFAULT_NORMALIZER = FrenchTextNormalizer()


def normalize_text(text: str) -> str:
    return _DEFAULT_NORMALIZER.normalize(text)


def normalize_many(values: Iterable[str]) -> list[str]:
    return [normalize_text(value) for value in values]
