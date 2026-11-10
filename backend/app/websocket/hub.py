"""WebSocket hub: pushes live events (alerts, transactions, rings) to dashboards."""

import json
import logging
from typing import Any

from fastapi import WebSocket

from app.db.serialize import jsonable

logger = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.connections.discard(ws)

    async def broadcast(self, event: str, data: Any) -> None:
        message = json.dumps({"event": event, "data": jsonable(data)}, default=str)
        for ws in list(self.connections):
            try:
                await ws.send_text(message)
            except Exception:  # client went away
                self.disconnect(ws)
