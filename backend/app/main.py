from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import devices, alerts, history, kpis, stores, maintenance, auth, ai
from app.api import websocket as ws_router
from app.db.session import engine, Base
from app.db.migrations import run_migrations, seed_external_sensors
from app.cache.redis_client import redis_client
from app.polling.scheduler import start_scheduler, stop_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_client.connect()
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(stores.router, prefix="/api/v1/stores", tags=["stores"])
app.include_router(devices.router, prefix="/api/v1/devices", tags=["devices"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(history.router, prefix="/api/v1/history", tags=["history"])
app.include_router(kpis.router, prefix="/api/v1/kpis", tags=["kpis"])
app.include_router(maintenance.router, prefix="/api/v1/maintenance", tags=["maintenance"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
app.include_router(ws_router.router, tags=["websocket"])

@app.get("/health")
async def health():
    return {"status": "ok"}
