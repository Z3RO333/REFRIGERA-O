import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.cache.redis_client import redis_client

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()

async def redis_listener():
    pub = redis_client.client.pubsub()
    await pub.subscribe("device.reading.new", "alert.created", "alert.resolved")
    async for message in pub.listen():
        if message["type"] == "message":
            try:
                data = json.loads(message["data"])
                await manager.broadcast({"channel": message["channel"], "data": data})
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Erro ao processar mensagem do Redis para Websocket: {e}")

@router.websocket("/ws/updates")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    listener_task = asyncio.create_task(redis_listener())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        listener_task.cancel()
