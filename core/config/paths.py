from pathlib import Path


def find_neron_home() -> Path:
    """
    Retourne la racine de l'installation NéronOS.
    Fonctionne quel que soit le dossier d'installation.
    """
    return Path(__file__).resolve().parents[3]


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
NERON_CONFIG = NERON_HOME / "neron.server.yaml"
NERON_IDENTITY_PATH = CORE_DIR / "identity" / "NERON.md"
