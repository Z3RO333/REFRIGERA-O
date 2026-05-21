import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.api.v1.auth import get_active_user_from_token
from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()

_CHANNELS = [
    "device.reading.new",
    "alert.created",
    "alert.resolved",
    "zone.automation.mode.changed",
    "zone.action.created",
    "automation.kill_switch.changed",
    "ai.analysis.created",
    "zone.ai_analysis.created",
    "device.command.sent",
    "device.command.failed",
]


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


async def start_redis_listener():
    """Starts the single global Redis pub/sub listener. Called once from lifespan."""
    asyncio.create_task(_redis_listener_loop())


async def _redis_listener_loop():
    """Runs forever in the background, reconnecting on error."""
    while True:
        try:
            pub = redis_client.client.pubsub()
            await pub.subscribe(*_CHANNELS)
            logger.info("WebSocket Redis listener subscribed to %d channels", len(_CHANNELS))
            async for message in pub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await manager.broadcast({"channel": message["channel"], "data": data})
                    except Exception as e:
                        logger.error("Erro ao processar mensagem Redis→WS: %s", e)
        except Exception as e:
            logger.error("Redis listener caiu, reconectando em 5s: %s", e)
            await asyncio.sleep(5)


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
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
