"""Client OAuth2 Google — flux "device authorization grant" (RFC 8628).

Choisi plutot qu'un flux redirect classique : neronOS tourne sur un serveur
domestique sans URL de callback publiquement joignable par le navigateur de
l'utilisateur. Le flux device ne demande aucune redirection HTTP : Google
affiche un code que l'utilisateur saisit sur n'importe quel appareil
(telephone, laptop), et le serveur interroge Google en arriere-plan jusqu'a
validation.

Documentation officielle : "OAuth 2.0 for TV and Limited-Input Device
Applications", console Google Cloud -> APIs & Services -> Credentials ->
Create Credentials -> OAuth client ID -> type "TVs and Limited Input
devices".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/calendar.readonly",
)

_PENDING_ERRORS = {"authorization_pending", "slow_down"}


class GoogleAuthError(RuntimeError):
    pass


@dataclass
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_url: str
    expires_in: int
    interval: int


@dataclass
class TokenResult:
    access_token: str
    refresh_token: str | None
    expires_in: int
    token_type: str = "Bearer"


class GoogleAuthClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, transport=self._transport)

    def start_device_authorization(
        self, scopes: tuple[str, ...] = DEFAULT_SCOPES
    ) -> DeviceAuthorization:
        with self._client() as client:
            response = client.post(
                DEVICE_CODE_URL,
                data={"client_id": self.client_id, "scope": " ".join(scopes)},
            )
        payload = self._parse(response)
        verification_url = payload.get("verification_url") or payload.get("verification_uri")
        if not verification_url or "user_code" not in payload or "device_code" not in payload:
            raise GoogleAuthError(f"Reponse device_code inattendue de Google : {payload}")
        return DeviceAuthorization(
            device_code=payload["device_code"],
            user_code=payload["user_code"],
            verification_url=verification_url,
            expires_in=int(payload.get("expires_in", 1800)),
            interval=int(payload.get("interval", 5)),
        )

    def poll_device_token(self, device_code: str) -> TokenResult | None:
        """Une iteration de polling.

        Retourne None si l'utilisateur n'a pas encore valide le code (Google
        renvoie ``authorization_pending``/``slow_down``). Leve GoogleAuthError
        pour toute autre erreur (code expire, acces refuse...).
        """
        with self._client() as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "device_code": device_code,
                    "grant_type": DEVICE_GRANT_TYPE,
                },
            )
        payload = self._parse_tolerant(response)
        error = payload.get("error")
        if error in _PENDING_ERRORS:
            return None
        if error:
            raise GoogleAuthError(f"Autorisation Google refusee : {error}")
        return self._token_result(payload)

    def refresh_access_token(self, refresh_token: str) -> TokenResult:
        with self._client() as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        payload = self._parse(response)
        # Google ne renvoie pas toujours un nouveau refresh_token : celui en
        # cours reste valide dans ce cas.
        payload.setdefault("refresh_token", refresh_token)
        return self._token_result(payload)

    def _token_result(self, payload: dict[str, Any]) -> TokenResult:
        if "access_token" not in payload:
            raise GoogleAuthError(f"Reponse Google inattendue : {payload}")
        return TokenResult(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_in=int(payload.get("expires_in", 3600)),
            token_type=payload.get("token_type", "Bearer"),
        )

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        payload = self._parse_tolerant(response)
        if response.status_code >= 400 and "error" not in payload:
            raise GoogleAuthError(
                f"Erreur Google ({response.status_code}) : {response.text[:200]}"
            )
        if "error" in payload:
            raise GoogleAuthError(
                f"Erreur Google : {payload.get('error_description') or payload['error']}"
            )
        return payload

    def _parse_tolerant(self, response: httpx.Response) -> dict[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise GoogleAuthError(
                f"Reponse Google non-JSON ({response.status_code}) : {response.text[:200]}"
            ) from exc
