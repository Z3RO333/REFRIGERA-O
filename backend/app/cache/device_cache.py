import uuid
from app.cache.redis_client import redis_client

DEVICE_STATUS_TTL = 600
DEVICE_PARAMS_TTL = 2100
ALERT_COOLDOWN_TTL = 14400

async def get_device_status(device_id: uuid.UUID) -> dict | None:
    return await redis_client.get(f"device:status:{device_id}")

async def set_device_status(device_id: uuid.UUID, data: dict):
    await redis_client.set(f"device:status:{device_id}", data, ttl=DEVICE_STATUS_TTL)

async def get_device_params(device_id: uuid.UUID) -> dict | None:
    return await redis_client.get(f"device:parameters:{device_id}")

async def set_device_params(device_id: uuid.UUID, data: dict):
    await redis_client.set(f"device:parameters:{device_id}", data, ttl=DEVICE_PARAMS_TTL)

async def check_alert_cooldown(device_id: uuid.UUID, alert_type: str) -> bool:
    key = f"alerts:cooldown:{device_id}:{alert_type}"
    return await redis_client.exists(key)

P1_ALERT_COOLDOWN_TTL = 300  # 1 ciclo de polling — evita queries redundantes sem silenciar o alerta

async def set_alert_cooldown(device_id: uuid.UUID, alert_type: str, severity: str):
    key = f"alerts:cooldown:{device_id}:{alert_type}"
    ttl = P1_ALERT_COOLDOWN_TTL if severity == "P1" else ALERT_COOLDOWN_TTL
    await redis_client.set(key, "1", ttl=ttl)

async def acquire_polling_lock(device_id: uuid.UUID) -> bool:
    # TTL deve ser > poll_variables_interval (300s) para evitar sobreposição de ciclos
    return await redis_client.acquire_lock(f"polling:lock:{device_id}", ttl=360)

async def release_polling_lock(device_id: uuid.UUID):
    await redis_client.release_lock(f"polling:lock:{device_id}")
