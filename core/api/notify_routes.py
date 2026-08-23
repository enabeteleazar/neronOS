from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.api.auth import verify_api_key
from agents.builtin.communication.telegram_agent import send_notification

router = APIRouter(tags=["notify"], dependencies=[Depends(verify_api_key)])


class NotifyRequest(BaseModel):
    message: str
    level: str = "info"
    channel: str = "telegram"


@router.post("/notify")
async def notify(payload: NotifyRequest):
    if payload.channel == "telegram":
        await send_notification(payload.message, payload.level)
        return {"status": "sent", "channel": "telegram"}
    raise HTTPException(400, f"Canal non supporté: {payload.channel}")
