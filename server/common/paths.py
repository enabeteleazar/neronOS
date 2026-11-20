"""Canonical runtime paths for NeronOS.

Every path can be overridden for development or alternate deployments while
keeping /etc/neronOS as the production default.
"""

from __future__ import annotations

import os
from pathlib import Path


_DEFAULT_ROOT = Path("/etc/neronOS")


def _env_path(name: str) -> Path | None:
    """Resolve an environment variable to an absolute path when present."""
    value = os.getenv(name)
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve(strict=False)


def _iter_project_roots(start: Path | None = None) -> list[Path]:
    """Walk upward from the current file or working directory to find the NeronOS root."""
    seen: set[Path] = set()
    bases = [start] if start is not None else []
    bases.extend([Path(__file__).resolve(), Path.cwd()])

    roots: list[Path] = []
    for base in bases:
        current = base if base.is_dir() else base.parent
        while True:
            current = current.resolve(strict=False)
            if current not in seen:
                seen.add(current)
                roots.append(current)
            if current.parent == current:
                break
            current = current.parent

    return roots


def _looks_like_root(candidate: Path) -> bool:
    # Dépôt unique (depuis le 16/10) : core/ à la racine. Ancienne disposition
    # en sous-modules : server/core/. Les deux restent reconnues.
    has_core = (candidate / "core").is_dir() or (candidate / "server" / "core").is_dir()
    has_config = (candidate / "neron.yaml").exists() or (candidate / "neron.server.yaml").exists()
    return has_core and has_config


def find_neron_home() -> Path:
    """Resolve the NeronOS root without relying on NERON_ROOT being set.

    Priority: (1) NERON_ROOT env var, (2) directory scan from this file / cwd
    up to a directory that looks like the project root, (3) /etc/neronOS.
    En production, systemd pose NERON_ROOT (env/common.env) : le balayage ne
    sert qu'en développement et dans les tests.
    """
    env_root = _env_path("NERON_ROOT")
    if env_root is not None:
        return env_root.resolve(strict=False)

    for candidate in _iter_project_roots():
        if _looks_like_root(candidate):
            return candidate.resolve(strict=False)

    return _DEFAULT_ROOT.resolve(strict=False)


# Défaut de production explicite (verrouillé par tests/test_runtime_paths.py) ;
# find_neron_home() reste disponible pour les composants lancés hors systemd.
NERON_ROOT = Path(os.getenv("NERON_ROOT", "/etc/neronOS")).expanduser()
NERON_CONFIG = Path(
    os.getenv("NERON_CONFIG", str(NERON_ROOT / "neron.yaml"))
).expanduser()
NERON_DATA_DIR = Path(
    os.getenv("NERON_DATA_DIR", str(NERON_ROOT / "data"))
).expanduser()
NERON_SERVER_DIR = Path(
    os.getenv("NERON_SERVER_DIR", str(NERON_ROOT / "server"))
).expanduser()
NERON_WORKSPACE_DIR = Path(
    os.getenv("NERON_WORKSPACE_DIR", str(NERON_ROOT / "workspace"))
).expanduser()


def service_version(start: str, default: str = "0.0.0") -> str:
    """Version du service, lue depuis le premier fichier VERSION trouve.

    `start` est le chemin du module appelant, typiquement `__file__`.
    Le prefixe v/V eventuel est retire.
    """

    for parent in Path(start).resolve().parents:

        candidate = parent / "VERSION"

        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8").strip()
            except OSError:
                break

            if text:
                return text.lstrip("vV")

    return default
NERON_SECRETS_FILE = Path(
    os.getenv("NERON_SECRETS_FILE", str(NERON_ROOT / "secrets.env"))
).expanduser()
# Identité canonique : elle appartient au Core (core/identity/NERON.md).
# L'ancien défaut pointait sur le coffre Obsidian du sous-module memory
# (server/memory/obsidian/identity/NERON.md), absent depuis le dépôt unique.
NERON_IDENTITY_PATH = Path(
    os.getenv(
        "NERON_IDENTITY_PATH",
        str(NERON_ROOT / "core" / "identity" / "NERON.md"),
    )
).expanduser()
