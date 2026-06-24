import sys

from modules.world_model import world_model as _world_model

sys.modules[__name__] = _world_model
