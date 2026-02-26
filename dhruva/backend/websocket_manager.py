"""Dhruva — WebSocket Connection Manager."""

import asyncio
import json
import logging
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger("dhruva.ws")


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events to all clients."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected clients."""
        if not self._connections:
            return

        payload = json.dumps(message, default=str)
        disconnected = []

        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message, default=str))
        except Exception:
            self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)
