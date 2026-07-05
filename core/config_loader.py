from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common.paths import NERON_CONFIG

CONFIG_PATH = str(NERON_CONFIG)


class ConfigLoader:
    def __init__(
        self,
        config_path: str = CONFIG_PATH,
    ):
        self.config_path = Path(config_path)
        self.data = self._load()

    def _load(self) -> dict[str, Any]:

        if not self.config_path.exists():
            return {}

        with open(
            self.config_path,
            "r",
            encoding="utf-8",
        ) as f:

            return yaml.safe_load(f) or {}

    def reload(self) -> None:
        self.data = self._load()

    def get(
        self,
        path: str,
        default: Any = None,
    ) -> Any:

        current: Any = self.data

        for part in path.split("."):

            if not isinstance(current, dict):
                return default

            current = current.get(part)

            if current is None:
                return default

        return current


def load_config() -> dict[str, Any]:
    loader = ConfigLoader()
    return loader.data


config = load_config()
