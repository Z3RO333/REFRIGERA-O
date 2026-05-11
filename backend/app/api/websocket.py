import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.api.v1.auth import get_active_user_from_token
from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket, subprotocol: str | None = None):
        await ws.accept(subprotocol=subprotocol)
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
    token = None
    subprotocol_header = websocket.headers.get("sec-websocket-protocol", "")
    protocols = [part.strip() for part in subprotocol_header.split(",") if part.strip()]
    uses_bearer_subprotocol = len(protocols) >= 2 and protocols[0].lower() == "bearer"
    if uses_bearer_subprotocol:
        token = protocols[1]
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = websocket.cookies.get(settings.auth_cookie_name)
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    async with AsyncSessionLocal() as db:
        try:
            await get_active_user_from_token(token, db)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await manager.connect(websocket, subprotocol="bearer" if uses_bearer_subprotocol else None)
    listener_task = asyncio.create_task(redis_listener())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        listener_task.cancel()
