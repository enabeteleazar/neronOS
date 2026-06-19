import sys

from modules.scheduler import routes as _routes

sys.modules[__name__] = _routes
