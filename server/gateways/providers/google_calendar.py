"""Client minimal pour l'API Google Calendar (lecture seule).

Une seule action pour l'instant : lister les prochains evenements de
l'agenda principal. Documentation officielle : Google Calendar API v3,
endpoint ``events.list``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarError(RuntimeError):
    pass


def list_upcoming_events(
    access_token: str,
    *,
    max_results: int = 5,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.get(
            EVENTS_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": now,
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
    if response.status_code >= 400:
        raise GoogleCalendarError(
            f"Google Calendar a repondu {response.status_code} : {response.text[:200]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise GoogleCalendarError(f"Reponse Google Calendar non-JSON : {response.text[:200]}") from exc
    return list(payload.get("items") or [])
