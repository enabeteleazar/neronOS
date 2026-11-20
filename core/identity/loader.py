"""Chargement de l'identité de Néron.

Source canonique : NERON.md, qui appartient au Core (core/identity/NERON.md,
ou NERON_IDENTITY_PATH). Trois documents compagnons facultatifs vivent à côté
de lui et enrichissent le prompt système : PERSONALITY.md, CONVERSATION.md,
CONTEXT.md (décision Phase 2C).

Rétabli après la réintégration du Core (58ab382), qui avait gardé un loader
réduit à NERON.md seul. Ce module :

- n'importe PAS core.config : le loader d'octobre importait
  core.config.paths, dont le chargement exécute core/config.py, qui importe
  core.identity. Importer core.identity en premier échouait (import
  circulaire) ;
- résout le chemin à chaque appel (NERON_IDENTITY_PATH peut désigner le
  NERON.md ou son répertoire), sans cache ;
- lit les deux formats de NERON.md en circulation :
    · champs « Clé: valeur » (Name, Version, Rôle/Role, Mission) ;
    · sections Markdown (# Mission, # Identité — « <nom> est <rôle>. »).
  Un champ explicite prime sur la valeur déduite des sections ;
- remplace {{version}} par le contenu du fichier VERSION le plus proche.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .schema import NeronIdentity
from .validator import IdentityValidationError, IdentityValidator


class IdentityError(RuntimeError):
    """Erreur de chargement de l'identité Néron."""


# Répertoire du corpus d'identité par défaut : celui de ce module.
DEFAULT_IDENTITY_DIR = Path(__file__).parent

# Conservé pour compatibilité : plusieurs modules importaient cette constante.
IDENTITY_PATH = DEFAULT_IDENTITY_DIR

VERSION_PLACEHOLDER = "{{version}}"
VERSION_FALLBACK = "0.0.0"

DOCUMENTS = {
    "identity": "NERON.md",
    "personality": "PERSONALITY.md",
    "conversation": "CONVERSATION.md",
    "context": "CONTEXT.md",
}


def identity_dir() -> Path:
    """Répertoire du corpus d'identité, résolu à CHAQUE appel.

    NERON_IDENTITY_PATH désigne le NERON.md canonique (les compagnons vivent
    à côté) ou directement le répertoire.
    """
    raw = os.getenv("NERON_IDENTITY_PATH", "").strip()
    if not raw:
        return DEFAULT_IDENTITY_DIR
    path = Path(raw).expanduser()
    return path.parent if path.suffix else path


def identity_document_path(filename: str = "NERON.md") -> Path:
    """Chemin absolu d'un document du corpus d'identité.

    Si NERON_IDENTITY_PATH désigne un fichier, c'est lui le document
    principal, quel que soit son nom ; les compagnons sont cherchés à côté.
    """
    raw = os.getenv("NERON_IDENTITY_PATH", "").strip()
    if raw and filename == DOCUMENTS["identity"]:
        path = Path(raw).expanduser()
        if path.suffix:
            return path
    return identity_dir() / filename


def _read_version() -> str:
    """Version lue depuis le premier fichier VERSION trouvé en remontant."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "VERSION"
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                break
            if text:
                return text.lstrip("vV")
    return VERSION_FALLBACK


def _read_document(filename: str, *, required: bool) -> str:
    path = identity_document_path(filename)
    if not path.exists():
        if required:
            raise IdentityError(f"Document d'identité illisible: {path}")
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise IdentityError(f"Document d'identité illisible: {path}") from exc
    return content.replace(VERSION_PLACEHOLDER, _read_version())


def _field(document: str, *keys: str) -> str:
    """Valeur d'un champ « Clé: valeur » (valeur sur la ligne ou la suivante)."""
    for key in keys:
        match = re.search(
            rf"^{key}\s*:[ \t]*(?P<value>.*)$", document, re.IGNORECASE | re.MULTILINE
        )
        if not match:
            continue
        value = match.group("value").strip()
        if not value:
            following = document[match.end():].lstrip("\n").split("\n\n", 1)[0]
            value = " ".join(line.strip() for line in following.splitlines() if line.strip())
        if value:
            return value
    return ""


def _section(document: str, title: str) -> str:
    heading = re.compile(
        rf"^#{{1,6}}\s+(?:\d+(?:\.\d+)*\.?\s+)?{re.escape(title)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = heading.search(document)
    if not match:
        return ""
    next_heading = re.search(r"^#{1,6}\s+.+$", document[match.end():], re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(document)
    return document[match.end():end].strip().strip("-").strip()


def _plain_text(markdown: str) -> str:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        lines.append(re.sub(r"^[-*]\s+", "", line))
    return " ".join(lines)


def _from_identity_section(document: str) -> tuple[str, str, str]:
    """(nom, rôle, description) déduits de « # Identité » : « <nom> est <rôle>. »"""
    description = _plain_text(_section(document, "Identité"))
    sentence = re.match(r"^(?P<name>.+?)\s+est\s+(?P<role>.+?)\.", description)
    if not sentence:
        return "", "", description
    role = re.sub(r"^(?:un|une)\s+", "", sentence.group("role").strip(), flags=re.I)
    return sentence.group("name").strip(), role[:1].upper() + role[1:], description


def _load() -> tuple[NeronIdentity, dict[str, str]]:
    documents = {
        key: _read_document(filename, required=key == "identity")
        for key, filename in DOCUMENTS.items()
    }
    main = documents["identity"]
    section_name, section_role, description = _from_identity_section(main)

    identity = NeronIdentity(
        name=_field(main, "Name") or section_name or "Néron",
        version=_field(main, "Version").lstrip("vV"),
        role=_field(main, "Rôle", "Role") or section_role,
        mission=_field(main, "Mission") or _plain_text(_section(main, "Mission")),
        identity=main,
        personality=documents["personality"],
        conversation=documents["conversation"],
        context=documents["context"],
    )
    try:
        IdentityValidator.validate(identity)
    except IdentityValidationError as exc:
        raise IdentityError(f"{exc} ({identity_document_path()})") from exc

    extra = {
        "description": description,
        "language": "fr" if re.search(r"\b(?:est|système|identité)\b", main, re.I) else "",
    }
    return identity, extra


def get_identity() -> dict[str, str]:
    """Identité courante, relue à chaque appel (modifications visibles aussitôt)."""
    identity, extra = _load()
    return {
        "name": identity.name,
        "version": identity.version,
        "role": identity.role,
        "mission": identity.mission,
        "description": extra["description"],
        "language": extra["language"],
        "identity": identity.identity,
        "personality": identity.personality,
        "conversation": identity.conversation,
        "context": identity.context,
        # Provenance : quel NERON.md a réellement été lu.
        "source": str(identity_document_path()),
    }


def build_identity_prompt() -> str:
    identity, _ = _load()
    sections = [
        f"Tu es {identity.name}, {identity.role}. "
        f"Ta mission est la suivante : {identity.mission}",
        f"# IDENTITÉ NÉRON\n\n{identity.identity}",
    ]
    for title, content in (
        ("PERSONNALITÉ", identity.personality),
        ("MODÈLE DE CONVERSATION", identity.conversation),
        ("CONTEXTE", identity.context),
    ):
        if content:
            sections.append(f"# {title}\n\n{content}")
    sections.append(
        "# RÈGLES SYSTÈME\n\n"
        "Tu dois répondre selon ton identité.\n"
        "Tu dois comprendre le contexte avant de répondre.\n"
        "Tu dois éviter les réponses génériques.\n"
        "Tu dois maintenir une continuité avec ton utilisateur."
    )
    return "\n\n".join(sections)
