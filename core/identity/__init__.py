"""API publique de l'identité de Néron (NERON.md + documents compagnons)."""

from .loader import (
    IdentityError,
    build_identity_prompt,
    get_identity,
    identity_dir,
    identity_document_path,
)

__all__ = [
    "IdentityError",
    "build_identity_prompt",
    "get_identity",
    "identity_dir",
    "identity_document_path",
]
