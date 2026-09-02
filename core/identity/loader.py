from __future__ import annotations

import os
from pathlib import Path
import re

from .schema import NeronIdentity
from .validator import IdentityValidator


class IdentityError(RuntimeError):
    """Erreur de chargement de l'identité Néron."""


# Repertoire par defaut du corpus d identite. Reste la valeur de repli : c est
# ce que Neron lit en production, ou NERON_IDENTITY_PATH n est pas defini.
DEFAULT_IDENTITY_DIR = Path(__file__).parent / "documents"

# Conserve pour compatibilite : plusieurs modules importaient cette constante.
IDENTITY_PATH = DEFAULT_IDENTITY_DIR


def identity_dir() -> Path:
    """Repertoire du corpus d identite, resolu a CHAQUE appel.

    NERON_IDENTITY_PATH est la source de verite officielle (decision Phase 2B).
    Il designe le NERON.md canonique ; les documents compagnons
    (PERSONALITY.md, CONVERSATION.md, CONTEXT.md) vivent a cote de lui. Si la
    variable pointe deja sur un repertoire, il est pris tel quel.

    La resolution est dynamique et non mise en cache : sans cela le loader
    ignorait totalement la variable d environnement (chemin code en dur), ce
    qui le rendait ni configurable ni testable.
    """
    raw = os.getenv("NERON_IDENTITY_PATH", "").strip()
    if not raw:
        return DEFAULT_IDENTITY_DIR
    path = Path(raw).expanduser()
    return path.parent if path.suffix else path


def identity_document_path(filename: str = "NERON.md") -> Path:
    """Chemin absolu d un document du corpus d identite."""
    return identity_dir() / filename

VERSION_PLACEHOLDER = "{{version}}"
VERSION_FALLBACK = "0.0.0"


def _read_version() -> str:
    """Version lue depuis le premier fichier VERSION trouve en remontant."""

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


class IdentityLoader:

    DOCUMENTS = {
        "identity": "NERON.md",
        "personality": "PERSONALITY.md",
        "conversation": "CONVERSATION.md",
        "context": "CONTEXT.md",
    }

    # Phase 2C : seul NERON.md (le corpus structure) fait foi. Les documents
    # compagnons enrichissent le prompt quand ils existent, mais leur absence
    # ne doit pas invalider l identite — sinon Neron n aurait pas d identite
    # tant que PERSONALITY.md/CONVERSATION.md/CONTEXT.md ne sont pas ecrits.
    REQUIRED_DOCUMENTS = {"identity"}


    def _read_document(self, filename: str, *, required: bool) -> str:

        path = identity_document_path(filename)

        if not path.exists():
            if not required:
                return ""
            raise IdentityError(
                f"Document identité absent : {path}"
            )

        try:
            content = path.read_text(
                encoding="utf-8"
            ).strip()

        except OSError as exc:
            raise IdentityError(
                f"Impossible de lire {path}"
            ) from exc

        return content.replace(
            VERSION_PLACEHOLDER,
            _read_version()
        )


    def _extract_value(
        self,
        content: str,
        key: str
    ) -> str:

        match = re.search(
            rf"^{key}\s*:\s*(.+)$",
            content,
            re.MULTILINE | re.IGNORECASE
        )

        if match:
            return match.group(1).strip()

        return ""


    def load(self) -> NeronIdentity:

        documents = {
            key: self._read_document(
                filename,
                required=key in self.REQUIRED_DOCUMENTS,
            )
            for key, filename in self.DOCUMENTS.items()
        }


        identity = NeronIdentity(

            name=self._extract_value(
                documents["identity"],
                "Name"
            ) or "Néron",


            version=self._extract_value(
                documents["identity"],
                "Version"
            ),


            role=self._extract_value(
                documents["identity"],
                "Rôle"
            ),


            mission=self._extract_value(
                documents["identity"],
                "Mission"
            ),


            identity=documents["identity"],

            personality=documents["personality"],

            conversation=documents["conversation"],

            context=documents["context"],
        )


        IdentityValidator.validate(identity)

        return identity



def get_identity() -> dict:

    identity = IdentityLoader().load()

    return {
        "name": identity.name,
        "version": identity.version,
        "role": identity.role,
        "mission": identity.mission,
        "identity": identity.identity,
        "personality": identity.personality,
        "conversation": identity.conversation,
        "context": identity.context,
        # Provenance : quel NERON.md a reellement ete lu. Cette cle existait
        # dans l ancien contrat, avait disparu, et empechait de verifier la
        # source de verite. Retablie en Phase 2B.
        "source": str(identity_document_path()),
    }



def build_identity_prompt() -> str:

    identity = IdentityLoader().load()


    return f"""
# IDENTITÉ NÉRON

{identity.identity}


# PERSONNALITÉ

{identity.personality}


# MODÈLE DE CONVERSATION

{identity.conversation}


# CONTEXTE

{identity.context}


# RÈGLES SYSTÈME

Tu es Néron.

Tu dois répondre selon ton identité.
Tu dois comprendre le contexte avant de répondre.
Tu dois éviter les réponses génériques.
Tu dois maintenir une continuité avec ton utilisateur.
"""
