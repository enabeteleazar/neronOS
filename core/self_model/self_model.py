import sys

from modules.self_model import self_model as _self_model

sys.modules[__name__] = _self_model
