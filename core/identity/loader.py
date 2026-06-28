from __future__ import annotations

import os
import re
from pathlib import Path


DEFAULT_IDENTITY_PATH = Path("/etc/neron/server/memory/obsidian/identity/NERON.md")


class IdentityError(RuntimeError):
    """Raised when the canonical identity document cannot be parsed."""


def _identity_path() -> Path:
    return Path(os.getenv("NERON_IDENTITY_PATH", str(DEFAULT_IDENTITY_PATH)))


def _section(document: str, title: str) -> str:
    heading = re.compile(
        rf"^#{{1,6}}\s+(?:\d+(?:\.\d+)*\.?\s+)?{re.escape(title)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = heading.search(document)
    if not match:
        raise IdentityError(f"Section '{title}' absente du document d'identité")

    next_heading = re.search(r"^#{1,6}\s+.+$", document[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(document)
    return document[match.end():end].strip().strip("-").strip()


def _plain_text(markdown: str) -> str:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)
    return " ".join(lines)


def _parse_identity(document: str, source: Path) -> dict[str, str]:
    version_match = re.search(
        r"^Version\s*:\s*(?P<version>\S+)\s*$",
        document,
        re.IGNORECASE | re.MULTILINE,
    )
    if not version_match:
        raise IdentityError("Champ 'Version' absent du document d'identité")

    mission = _plain_text(_section(document, "Mission"))
    identity_section = _section(document, "Identité")
    description = _plain_text(identity_section).split("\n", 1)[0]
    first_sentence = re.match(r"^(?P<name>.+?)\s+est\s+(?P<role>.+?)\.", description)
    if not first_sentence:
        raise IdentityError(
            "La section 'Identité' doit commencer par '<nom> est <rôle>.'"
        )

    name = first_sentence.group("name").strip()
    role = re.sub(r"^(?:un|une)\s+", "", first_sentence.group("role").strip(), flags=re.I)
    role = role[:1].upper() + role[1:]

    return {
        "name": name,
        "role": role,
        "mission": mission,
        "description": description,
        "language": "fr" if re.search(r"\b(?:est|système|identité)\b", document, re.I) else "",
        "version": version_match.group("version"),
        "source": str(source),
    }


def get_identity() -> dict[str, str]:
    """Read and parse NERON.md on every call so changes are immediately visible."""
    source = _identity_path()
    try:
        document = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise IdentityError(f"Document d'identité illisible: {source}") from exc
    return _parse_identity(document, source)


def build_identity_prompt() -> str:
    identity = get_identity()
    return (
        f"Tu es {identity['name']}, {identity['role']}. "
        f"Ta mission est la suivante : {identity['mission']}"
    )
