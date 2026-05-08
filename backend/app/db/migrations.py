"""
Migrações incrementais executadas no startup.
Todos os statements são idempotentes (ADD COLUMN IF NOT EXISTS, ALTER … IF EXISTS).
"""
import json
import logging
from sqlalchemy import select, text
from app.db.session import engine, AsyncSessionLocal

logger = logging.getLogger(__name__)

_STATEMENTS = [
    # devices
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS dnd BOOLEAN NOT NULL DEFAULT false",
    # device_status_latest
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS accumulated_on_minutes BIGINT",
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS accumulated_off_minutes BIGINT",
    # humidity era INTEGER, precisa virar FLOAT
    """DO $$ BEGIN
         IF EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_name='device_status_latest'
             AND column_name='humidity'
             AND data_type='integer'
         ) THEN
           ALTER TABLE device_status_latest ALTER COLUMN humidity TYPE FLOAT USING humidity::float;
         END IF;
       END $$""",
    # device_readings
    "ALTER TABLE device_readings ADD COLUMN IF NOT EXISTS accumulated_on_minutes BIGINT",
    "ALTER TABLE device_readings ADD COLUMN IF NOT EXISTS accumulated_off_minutes BIGINT",
    # sensores externos HTTP (Pró-Digital etc.)
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS source_url TEXT",
    # raio de influência no mapa térmico
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS influence_radius_m INTEGER NOT NULL DEFAULT 8",
]


async def run_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))


async def seed_external_sensors() -> None:
    """Cadastra sensores externos definidos em EXTERNAL_SENSORS_SEED se ainda não existirem."""
    from app.config import settings
    from app.models.device import Device, DeviceParameters

    try:
        sensors = json.loads(settings.external_sensors_seed)
    except (json.JSONDecodeError, AttributeError):
        return
    if not sensors:
        return

    async with AsyncSessionLocal() as session:
        for cfg in sensors:
            source_url = (cfg.get("source_url") or "").strip().rstrip("/")
            name = (cfg.get("name") or "").strip()
            if not source_url or not name:
                continue

            ext_id = "EXT:" + source_url.replace("http://", "").replace("https://", "").replace("/", "_")
            existing = await session.execute(
                select(Device).where(Device.brise_device_id == ext_id)
            )
            if existing.scalar_one_or_none():
                continue

            device = Device(
                brise_device_id=ext_id,
                name=name,
                source_url=source_url,
                is_critical_environment=bool(cfg.get("is_critical", False)),
                active=True,
            )
            session.add(device)
            await session.flush()
            session.add(DeviceParameters(
                device_id=device.id,
                setpoint_cool=int(cfg.get("setpoint_cool") or 24),
            ))
            logger.info("Sensor externo cadastrado: %s (%s)", name, source_url)

        await session.commit()
