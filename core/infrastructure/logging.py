from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


def log_event(
    service: str,
    level: str,
    message: str,
    trace_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit one JSON log record through the standard logging pipeline."""
    level_name = level.upper()
    level_number = getattr(logging, level_name, None)
    if not isinstance(level_number, int):
        raise ValueError(f"invalid log level: {level}")

    record = {
        "service": service,
        "level": level_name,
        "message": message,
        "trace_id": trace_id,
        "extra": extra or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logging.getLogger(f"neron.{service}").log(
        level_number,
        json.dumps(record, ensure_ascii=False, default=str),
    )
