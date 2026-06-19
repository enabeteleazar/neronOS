import sys

from modules.memory import persistent_store as _persistent_store

sys.modules[__name__] = _persistent_store
