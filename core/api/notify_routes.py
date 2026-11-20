"""Notifications sortantes : POST /notify.

Contrat HTTP consommé par d'autres modules, éventuellement sur d'autres
serveurs. Appelant connu : neronReminders (scheduler.py), qui envoie chaque
rappel échu ici :

    POST {core}/notify
    Authorization: Bearer <NERON_API_KEY>
    {"message": "...", "level": "info", "channel": "telegram"}

Route créée en 5572c95, perdue lors de la réintégration du Core (58ab382) :
depuis, chaque rappel recevait un 404 et restait en backoff. Rétablie avec
une différence : elle ne répond plus « sent » quand rien n'est parti. Le bot
Telegram vit dans le processus Core ; s'il n'est pas démarré (token absent)
ou que l'envoi échoue, la route répond 503 pour que l'appelant retente au
lieu de marquer la notification comme remise.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.api.auth import verify_api_key

router = APIRouter(tags=["notify"], dependencies=[Depends(verify_api_key)])

SUPPORTED_CHANNELS = ("telegram",)


class NotifyRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    level: Literal["info", "warning", "alert", "error"] = "info"
    channel: str = "telegram"


@router.post("/notify")
async def notify(payload: NotifyRequest) -> dict[str, str]:
    if payload.channel not in SUPPORTED_CHANNELS:
        raise HTTPException(400, f"Canal non supporté : {payload.channel}")

    try:
        from agents.builtin.communication.telegram_agent import send_notification
    except Exception as exc:  # dépendance Telegram absente sur ce serveur
        raise HTTPException(503, f"Canal telegram indisponible : {exc}") from exc

    if not await send_notification(payload.message, payload.level):
        raise HTTPException(503, "Notification non envoyée : bot Telegram inactif ou envoi refusé")

    return {"status": "sent", "channel": payload.channel}
