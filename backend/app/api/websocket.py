import asyncio
import json
import logging
from dataclasses import dataclass, field
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from app.api.v1.auth import get_active_user_from_token
from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User

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

# Channels sem store_id — enviados para todos independente do scope
_GLOBAL_CHANNELS = {"automation.kill_switch.changed"}


@dataclass
class ConnectedClient:
    ws: WebSocket
    # store_ids vazio = sem restrição (ADMIN ou usuário global)
    store_ids: set[str] = field(default_factory=set)
    role: str = "VIEWER"


class ConnectionManager:
    def __init__(self):
        self.active: list[ConnectedClient] = []

    async def connect(self, ws: WebSocket, user: User, subprotocol: str | None = None):
        await ws.accept(subprotocol=subprotocol)
        store_ids = {str(s) for s in (user.store_ids or [])} if user.store_ids else set()
        self.active.append(ConnectedClient(ws=ws, store_ids=store_ids, role=user.role))

    def disconnect(self, ws: WebSocket):
        self.active = [c for c in self.active if c.ws is not ws]

    async def broadcast(self, message: dict):
        channel = message.get("channel", "")
        event_store_id: str | None = message.get("data", {}).get("store_id")
        is_global = channel in _GLOBAL_CHANNELS

        dead: list[WebSocket] = []
        for client in self.active:
            # Canal global → todos recebem
            # Sem restrição de loja → recebe tudo
            # Com restrição → só se o evento for da loja do usuário
            if not is_global and client.store_ids and event_store_id:
                if event_store_id not in client.store_ids:
                    continue
            try:
                await client.ws.send_json(message)
            except Exception:
                dead.append(client.ws)
        for ws in dead:
            self.disconnect(ws)


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
            user: User = await get_active_user_from_token(token, db)
        except Exception:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await manager.connect(
        websocket, user,
        subprotocol="bearer" if uses_bearer_subprotocol else None,
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
