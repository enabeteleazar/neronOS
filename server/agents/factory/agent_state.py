"""État activé / désactivé des agents générés, persistant sur disque.

Le fichier vit à côté des agents eux-mêmes (`<generated_agents>/agents_state.json`)
et sur la même machine qu'eux : celle qui les exécute. Lu par le runtime avant
chaque exécution et par le registre goal_engine à chaque rechargement.

Il remplace la désactivation de septembre (9f4e3e6, perdue avec 58ab382), qui
changeait le statut d'une carte dans un registre EN MÉMOIRE : perdu au
redémarrage, écrasé au rechargement suivant (load_existing_agents ré-enregistre
tout en « available »), et sans effet sur l'exécution directe d'un agent.

Absent ou illisible : aucun agent désactivé (fail-open, comme avant).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("neron.agent_state")

STATE_FILENAME = "agents_state.json"
_lock = threading.Lock()


def state_path(generated_dir: Path | str) -> Path:
    return Path(generated_dir) / STATE_FILENAME


def _read(generated_dir: Path | str) -> dict[str, Any]:
    path = state_path(generated_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("agents_state_unreadable path=%s error=%s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def disabled_agents(generated_dir: Path | str) -> set[str]:
    disabled = _read(generated_dir).get("disabled")
    return {str(name) for name in disabled} if isinstance(disabled, list) else set()


def is_disabled(generated_dir: Path | str, agent_name: str) -> bool:
    return agent_name in disabled_agents(generated_dir)


def set_enabled(generated_dir: Path | str, agent_name: str, enabled: bool) -> set[str]:
    """Active ou désactive un agent ; renvoie l'ensemble des agents désactivés.

    Écriture atomique (fichier temporaire puis remplacement) : un lecteur
    concurrent voit l'ancien ou le nouvel état, jamais un fichier tronqué.
    """
    directory = Path(generated_dir)
    with _lock:
        data = _read(directory)
        disabled = disabled_agents(directory)
        if enabled:
            disabled.discard(agent_name)
        else:
            disabled.add(agent_name)
        data["disabled"] = sorted(disabled)

        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".agents_state.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, state_path(directory))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    return disabled
