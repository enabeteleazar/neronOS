"""Ensure the parent server directory is importable when the core package is run from its own directory."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# Allow systemd and manual launches to preserve the official runtime layout.
for env_name in ("NERON_ROOT", "NERON_CONFIG", "NERON_IDENTITY_PATH"):
    if env_name not in os.environ:
        continue
    value = os.environ[env_name]
    if value and os.path.isabs(value):
        os.environ.setdefault(env_name, value)
