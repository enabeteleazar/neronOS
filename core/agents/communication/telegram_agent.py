from __future__ import annotations

import importlib
from typing import Any


_TARGET = "agents.builtin.communication.telegram_agent"


def _target() -> Any:
    return importlib.import_module(_TARGET)


def __getattr__(name: str) -> Any:
    return getattr(_target(), name)
