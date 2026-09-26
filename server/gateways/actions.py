"""Actions reelles executables une fois un connecteur connecte.

Une seule aujourd'hui : lister les prochains evenements Google Agenda.
Chaque nouvelle action (Gmail, Contacts, GitHub...) suit le meme schema :
un module `providers/<service>.py` pour l'appel API, une fonction ici qui
va chercher le token et formate la reponse humaine.
"""
from __future__ import annotations

import os

import httpx

from gateways.providers.google_auth import GoogleAuthClient, GoogleAuthError
from gateways.providers.google_calendar import GoogleCalendarError, list_upcoming_events
from gateways.token_store import TokenStore


class GatewayActionError(RuntimeError):
    pass


def _google_auth_client() -> GoogleAuthClient:
    client_id = os.getenv("NERON_GATEWAY_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("NERON_GATEWAY_GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise GatewayActionError(
            "NERON_GATEWAY_GOOGLE_CLIENT_ID / NERON_GATEWAY_GOOGLE_CLIENT_SECRET "
            "absents de secrets.env."
        )
    return GoogleAuthClient(client_id=client_id, client_secret=client_secret)


def fetch_upcoming_calendar_events(
    *,
    token_store: TokenStore | None = None,
    auth_client: GoogleAuthClient | None = None,
    calendar_transport: httpx.BaseTransport | None = None,
    max_results: int = 5,
) -> list[dict]:
    store = token_store or TokenStore()
    refresh_token = store.get_refresh_token("google")
    if not refresh_token:
        raise GatewayActionError("Google n'est pas connecte (aucun refresh token enregistre).")

    auth = auth_client or _google_auth_client()
    try:
        token = auth.refresh_access_token(refresh_token)
    except GoogleAuthError as exc:
        raise GatewayActionError(f"Impossible de rafraichir le token Google : {exc}") from exc

    if token.refresh_token and token.refresh_token != refresh_token:
        store.set_refresh_token("google", token.refresh_token)

    try:
        return list_upcoming_events(
            token.access_token, max_results=max_results, transport=calendar_transport
        )
    except GoogleCalendarError as exc:
        raise GatewayActionError(str(exc)) from exc


def format_events_for_response(events: list[dict]) -> str:
    if not events:
        return "Aucun événement à venir dans ton agenda Google."
    lines = ["Voici tes prochains événements Google Agenda :"]
    for event in events:
        summary = event.get("summary") or "(sans titre)"
        start_info = event.get("start") or {}
        start = start_info.get("dateTime") or start_info.get("date") or "date inconnue"
        lines.append(f"- {summary} — {start}")
    return "\n".join(lines)
