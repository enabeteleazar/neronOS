from datetime import datetime
from zoneinfo import ZoneInfo


DEFAULT_TZ = "Europe/Paris"


def now(tz: str = DEFAULT_TZ) -> datetime:
    return datetime.now(ZoneInfo(tz))


def build_timer_response(kind: str, tz: str = DEFAULT_TZ) -> dict:
    current = now(tz)

    if kind == "time":
        response = f"Il est {current:%Hh%M}."
    elif kind == "date":
        response = f"Nous sommes le {current:%d/%m/%Y}."
    else:
        response = f"Nous sommes le {current:%d/%m/%Y} et il est {current:%Hh%M}."

    return {
        "response": response,
        "intent": "time_query",
        "agent": "timer_module",
        "confidence": "high" if kind == "time" else "medium",
        "iso": current.isoformat(),
        "source": "timer_module",
    }
