import sys

from agents.runtime import routes as _routes

sys.modules[__name__] = _routes
