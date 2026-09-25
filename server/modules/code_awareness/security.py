from __future__ import annotations

import fnmatch
from pathlib import Path

from common.paths import NERON_SERVER_DIR

PROJECT_ROOT = NERON_SERVER_DIR.resolve()

# Doit rester aligne sur les repertoires reellement presents sous server/.
# "web_bridge" et "providers" ont ete retires : le premier a ete supprime
# (commit a4fdda3), le second n a jamais existe sous server/.
ALLOWED_TOP_LEVEL_DIRS = {
    "agents",
    "common",
    "core",
    "doctor",
    "goal",
    "integrations",
    "llm",
    "memory",
    "modules",
    "print",
    "tools",
    "voice",
    "watchdog",
}

DENIED_DIR_NAMES = {
    ".git",
    "venv",
    ".venv",
    "node_modules",
    "__pycache__",
    "pycache",
    ".pytest_cache",
    "logs",
    "workspace",
    "data",
    "backups",
    "backup",
    "cache",
    ".cache",
}

DENIED_FILE_PATTERNS = {
    ".env",
    ".env.*",
    "secrets.*",
    "*.key",
    "*.pem",
    "*.crt",
    "token*",
    "credentials*",
    "config.secrets.*",
    "config.secret.*",
}

SECRET_NAME_MARKERS = {
    "secret",
    "secrets",
    "token",
    "credential",
    "credentials",
}


class CodeAwarenessSecurityError(ValueError):
    pass


def project_root() -> Path:
    return PROJECT_ROOT


def is_denied_dir(path: Path) -> bool:
    return any(part in DENIED_DIR_NAMES for part in path.parts)


def is_hidden_path(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def is_sensitive_file(path: Path) -> bool:
    name = path.name.lower()
    stem = path.stem.lower()

    if any(fnmatch.fnmatch(name, pattern.lower()) for pattern in DENIED_FILE_PATTERNS):
        return True

    return any(marker in stem for marker in SECRET_NAME_MARKERS)


def relative_to_project(path: Path) -> str:
    return str(path.resolve().relative_to(PROJECT_ROOT))


def resolve_user_path(path: str) -> Path:
    if not path or not path.strip():
        raise CodeAwarenessSecurityError("Chemin vide.")

    raw = Path(path)
    if raw.is_absolute():
        raise CodeAwarenessSecurityError("Chemin absolu refusé.")

    if any(part == ".." for part in raw.parts):
        raise CodeAwarenessSecurityError("Traversée de répertoire refusée.")

    candidate = (PROJECT_ROOT / raw).resolve()

    try:
        relative = candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise CodeAwarenessSecurityError("Chemin hors dépôt refusé.") from exc

    if not relative.parts:
        raise CodeAwarenessSecurityError("Chemin racine refusé.")

    if relative.parts[0] not in ALLOWED_TOP_LEVEL_DIRS:
        raise CodeAwarenessSecurityError("Dossier non autorisé.")

    if is_hidden_path(relative):
        raise CodeAwarenessSecurityError("Fichiers cachés refusés.")

    if is_denied_dir(relative):
        raise CodeAwarenessSecurityError("Dossier sensible refusé.")

    if is_sensitive_file(relative):
        raise CodeAwarenessSecurityError("Fichier sensible refusé.")

    if candidate.is_symlink():
        raise CodeAwarenessSecurityError("Symlink refusé.")

    if candidate.exists():
        try:
            real_relative = candidate.resolve().relative_to(PROJECT_ROOT)
        except ValueError as exc:
            raise CodeAwarenessSecurityError("Symlink hors dépôt refusé.") from exc

        if real_relative.parts[0] not in ALLOWED_TOP_LEVEL_DIRS:
            raise CodeAwarenessSecurityError("Cible non autorisée.")

    return candidate


def is_allowed_scan_path(path: Path) -> bool:
    if path.is_symlink():
        return False

    try:
        relative = path.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        return False

    if not relative.parts:
        return True

    if relative.parts[0] not in ALLOWED_TOP_LEVEL_DIRS:
        return False

    if is_hidden_path(relative) or is_denied_dir(relative):
        return False

    if path.is_file() and is_sensitive_file(relative):
        return False

    return True
