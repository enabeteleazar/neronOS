"""Verrouille la reconciliation Phase 2C : core.config.paths est une facade.

Avant : `server/core/config/paths.py` etait un fork de `server/common/paths.py`
(memes constantes, logique dupliquee — voir phase2b-kernel-extraction.md §7).
Desormais : implementation unique dans common, core ne fait que reexporter.
"""

import server.common.paths as common_paths
import core.config.paths as core_paths


def test_core_paths_reexports_common_objects():
    """Meme objet, pas une valeur recalculee independamment."""
    for name in (
        "NERON_ROOT",
        "NERON_CONFIG",
        "NERON_DATA_DIR",
        "NERON_SERVER_DIR",
        "NERON_WORKSPACE_DIR",
        "NERON_IDENTITY_PATH",
        "NERON_SECRETS_FILE",
    ):
        assert getattr(core_paths, name) is getattr(common_paths, name)

    assert core_paths.find_neron_home is common_paths.find_neron_home
    assert core_paths.service_version is common_paths.service_version


def test_find_neron_home_prefers_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("NERON_ROOT", str(tmp_path))

    assert common_paths.find_neron_home() == tmp_path.resolve()


def test_find_neron_home_falls_back_to_directory_scan(monkeypatch):
    monkeypatch.delenv("NERON_ROOT", raising=False)

    home = common_paths.find_neron_home()

    # Dépôt unique depuis le 16/10 : core/ à la racine (server/core/ reste
    # reconnu pour l'ancienne disposition en sous-modules).
    assert (home / "core").is_dir() or (home / "server" / "core").is_dir()
    assert (home / "neron.yaml").exists() or (home / "neron.server.yaml").exists()
