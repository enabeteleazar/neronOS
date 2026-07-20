from __future__ import annotations

from pathlib import Path
import re

from .schema import NeronIdentity
from .validator import IdentityValidator


class IdentityError(RuntimeError):
    """Erreur de chargement de l'identité Néron."""


IDENTITY_PATH = Path(__file__).parent / "documents"


class IdentityLoader:

    DOCUMENTS = {
        "identity": "NERON.md",
        "personality": "PERSONALITY.md",
        "conversation": "CONVERSATION.md",
        "context": "CONTEXT.md",
    }


    def _read_document(self, filename: str) -> str:

        path = IDENTITY_PATH / filename

        if not path.exists():
            raise IdentityError(
                f"Document identité absent : {path}"
            )

        try:
            return path.read_text(
                encoding="utf-8"
            ).strip()

        except OSError as exc:
            raise IdentityError(
                f"Impossible de lire {path}"
            ) from exc


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
            key: self._read_document(filename)
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
