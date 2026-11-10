"""WebSocket endpoint. Browsers cannot set headers on a WebSocket, so the JWT
access token is passed as `?token=`."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.config import get_settings
from app.security.jwt import TokenError, decode_token

router = APIRouter()


@router.websocket("/ws")
async def live(ws: WebSocket, token: str = "") -> None:
    try:
        decode_token(token, "access", get_settings())
    except TokenError:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    hub = ws.app.state.services.hub
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive pings from the client; content ignored
    except WebSocketDisconnect:
        hub.disconnect(ws)
