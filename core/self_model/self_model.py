"""Legacy compatibility adapter for the canonical Core SelfModel."""

import sys

from core.modules.self_model import service as _service

sys.modules[__name__] = _service
