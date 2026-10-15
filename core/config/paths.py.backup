from __future__ import annotations

import os
from pathlib import Path


def _env_path(name: str) -> Path | None:
    """Resolve an environment variable to an absolute path when present."""
    value = os.getenv(name)
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (Path.cwd() / path).resolve(strict=False)


def _iter_project_roots(start: Path | None = None) -> list[Path]:
    """Walk upward from the current file or working directory to find the NéronOS root."""
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


def find_neron_home() -> Path:
    """
    Resolve the NéronOS root with this priority order:
    1. NERON_ROOT environment variable
    2. Automatic scan from the current file / cwd up the directory tree
    """
    env_root = _env_path("NERON_ROOT")
    if env_root is not None:
        return env_root.resolve(strict=False)

    for candidate in _iter_project_roots():
        if (candidate / "server" / "core").exists() and (
            (candidate / "neron.yaml").exists() or (candidate / "neron.server.yaml").exists()
        ):
            return candidate.resolve(strict=False)

    return Path("/etc/neronOS").resolve(strict=False)


def resolve_neron_config(root: Path) -> Path:
    """Resolve the primary configuration file, preferring NERON_CONFIG if set."""
    env_config = _env_path("NERON_CONFIG")
    if env_config is not None:
        return env_config.resolve(strict=False)

    for candidate in (root / "neron.yaml", root / "neron.server.yaml"):
        if candidate.exists():
            return candidate.resolve(strict=False)

    return (root / "neron.yaml").resolve(strict=False)


def resolve_identity_path(root: Path, core_dir: Path) -> Path:
    """Resolve the canonical identity document path with env override support."""
    env_identity = _env_path("NERON_IDENTITY_PATH")
    if env_identity is not None:
        return env_identity.resolve(strict=False)

    for candidate in (
        core_dir / "identity" / "NERON.md",
        root / "server" / "core" / "identity" / "NERON.md",
    ):
        if candidate.exists():
            return candidate.resolve(strict=False)

    return (core_dir / "identity" / "NERON.md").resolve(strict=False)


NERON_HOME = find_neron_home()

SERVER_DIR = NERON_HOME / "server"
CORE_DIR = SERVER_DIR / "core"
DATA_DIR = NERON_HOME / "data"
MEMORY_DIR = NERON_HOME / "memory"
WORKSPACE_DIR = NERON_HOME / "workspace"
CONFIG_DIR = NERON_HOME / "config"

# Compatibility names formerly provided by common.paths. They now live in Core
# so core modules do not depend on the legacy shared submodule.
NERON_ROOT = NERON_HOME
NERON_SERVER_DIR = SERVER_DIR
NERON_CORE_DIR = CORE_DIR
NERON_DATA_DIR = DATA_DIR
NERON_MEMORY_DIR = MEMORY_DIR
NERON_WORKSPACE_DIR = WORKSPACE_DIR
NERON_CONFIG_DIR = CONFIG_DIR
NERON_CONFIG = resolve_neron_config(NERON_ROOT)
NERON_IDENTITY_PATH = resolve_identity_path(NERON_ROOT, CORE_DIR)
