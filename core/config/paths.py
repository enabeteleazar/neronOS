from pathlib import Path


def find_neron_home() -> Path:
    """
    Retourne la racine de l'installation NéronOS.
    Fonctionne quel que soit le dossier d'installation.
    """
    return Path(__file__).resolve().parents[3]


NERON_HOME = find_neron_home()

SERVER_DIR = NERON_HOME / "server"
DATA_DIR = NERON_HOME / "data"
MEMORY_DIR = NERON_HOME / "memory"
WORKSPACE_DIR = NERON_HOME / "workspace"
CONFIG_DIR = NERON_HOME / "config"
