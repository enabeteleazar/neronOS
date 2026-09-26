"""Garde-fous sur la racine runtime canonique de NeronOS.

La racine est /etc/neronOS. La racine historique /etc/neron (sans suffixe) et
la racine /srv/homelab/server-1/neronOS ne doivent plus apparaitre nulle part.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"

# /etc/neron NON suivi de "OS" : la racine abandonnee. Le negative lookahead
# est indispensable, sinon /etc/neronOS — la racine actuelle — matche aussi et
# le test ne peut plus jamais passer.
LEGACY_ROOT_RE = re.compile(r"/etc/neron(?!OS)")
LEGACY_HOMELAB_RE = re.compile(r"/srv/homelab/server-1/neronOS")

# Sous-modules : hors perimetre du depot parent, corriges dans leur propre
# depot (Phase 2/3). Voir system/docs/architecture/neronos-architecture.md.
SUBMODULE_DIRS = {
    "core", "doctor", "goal", "llm", "memory",
    "print", "voice", "watchdog",
}


def _parent_owned_sources():
    for path in SERVER.rglob("*.py"):
        parts = path.relative_to(SERVER).parts
        if "__pycache__" in parts:
            continue
        if parts and parts[0] in SUBMODULE_DIRS:
            continue
        yield path


def test_runtime_python_has_no_legacy_etc_neron_default():
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _parent_owned_sources()
        if LEGACY_ROOT_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]

    assert offenders == [], f"racine /etc/neron abandonnee: {offenders}"


def test_runtime_python_has_no_legacy_homelab_root():
    offenders = [
        p.relative_to(ROOT).as_posix()
        for p in _parent_owned_sources()
        if LEGACY_HOMELAB_RE.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]

    assert offenders == [], f"racine /srv/homelab abandonnee: {offenders}"


def test_canonical_paths_default_to_current_runtime(monkeypatch):
    monkeypatch.delenv("NERON_ROOT", raising=False)
    monkeypatch.delenv("NERON_CONFIG", raising=False)

    source = (SERVER / "common" / "paths.py").read_text(encoding="utf-8")

    assert 'os.getenv("NERON_ROOT", "/etc/neronOS")' in source
    assert 'os.getenv("NERON_CONFIG", str(NERON_ROOT / "neron.yaml"))' in source
