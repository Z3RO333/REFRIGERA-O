import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import devices, alerts, history, kpis, stores, maintenance, auth, ai, zones, automation, digital_twin, users, audit
from app.api.v1.auth import get_current_user
from app.models import zone as _zone_models  # noqa: F401 — ensure tables are created
from app.models import audit as _audit_models  # noqa: F401
from app.api import websocket as ws_router
from app.db.session import engine, Base
from app.db.migrations import run_migrations, seed_external_sensors
from app.cache.redis_client import redis_client
from app.config import settings
from app.polling.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


async def _wait_for_redis(retries: int = 30, delay: float = 1.0) -> None:
    for attempt in range(1, retries + 1):
        try:
            await redis_client.connect()
            await redis_client.client.ping()
            return
        except Exception as exc:
            logger.warning("Redis not ready (attempt %d/%d): %s", attempt, retries, exc)
            if attempt < retries:
                await asyncio.sleep(delay)
    raise RuntimeError("Redis unavailable after startup retries")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _wait_for_redis()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_migrations()
    await seed_external_sensors()
    await start_scheduler()
    yield
    await stop_scheduler()
    await redis_client.disconnect()

app = FastAPI(
    title="Refrigeração Monitor API",
    description="Monitoramento de Refrigeração — Bemol Varejo",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
auth_required = [Depends(get_current_user)]
app.include_router(stores.router, prefix="/api/v1/stores", tags=["stores"], dependencies=auth_required)
app.include_router(devices.router, prefix="/api/v1/devices", tags=["devices"], dependencies=auth_required)
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"], dependencies=auth_required)
app.include_router(history.router, prefix="/api/v1/history", tags=["history"], dependencies=auth_required)
app.include_router(kpis.router, prefix="/api/v1/kpis", tags=["kpis"], dependencies=auth_required)
app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["maintenance"], dependencies=auth_required)
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"], dependencies=auth_required)
app.include_router(zones.router, prefix="/api/v1/zones", tags=["zones"], dependencies=auth_required)
app.include_router(automation.router, prefix="/api/v1/automation", tags=["automation"], dependencies=auth_required)
app.include_router(digital_twin.router, prefix="/api/v1/digital-twin", tags=["digital-twin"], dependencies=auth_required)
app.include_router(users.router, prefix="/api/v1/users", tags=["users"], dependencies=auth_required)
app.include_router(audit.router, prefix="/api/v1/audit", tags=["audit"], dependencies=auth_required)
app.include_router(ws_router.router, tags=["websocket"])

@app.get("/health")
async def health():
    return {"status": "ok"}
