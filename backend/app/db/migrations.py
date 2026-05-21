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
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS enable_fan BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS enable_heat BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS dnd BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS time_zone INTEGER NOT NULL DEFAULT -4",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS group_level1 VARCHAR(50)",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS group_level2 VARCHAR(50)",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS group_level3 VARCHAR(50)",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS group_level4 VARCHAR(50)",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS position_x FLOAT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS position_y FLOAT",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS polling_interval INTEGER NOT NULL DEFAULT 300",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_critical_environment BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_maintenance TIMESTAMP",
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
    # stores / sectors
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS address TEXT",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS state VARCHAR(2)",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS timezone INTEGER NOT NULL DEFAULT -4",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS latitude FLOAT",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS longitude FLOAT",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
    "ALTER TABLE store_sectors ADD COLUMN IF NOT EXISTS floor INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE store_sectors ADD COLUMN IF NOT EXISTS area_m2 FLOAT",
    "ALTER TABLE store_sectors ADD COLUMN IF NOT EXISTS floor_plan_url TEXT",
    "ALTER TABLE store_sectors ADD COLUMN IF NOT EXISTS is_critical BOOLEAN NOT NULL DEFAULT false",
    # device_parameters
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS mode_device INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS mode_ac INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS fan_speed INTEGER NOT NULL DEFAULT 2",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS setpoint_cool INTEGER NOT NULL DEFAULT 24",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS setpoint_heat INTEGER NOT NULL DEFAULT 20",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS eco_cool INTEGER NOT NULL DEFAULT 22",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS eco_heat INTEGER NOT NULL DEFAULT 18",
    "ALTER TABLE device_parameters ADD COLUMN IF NOT EXISTS synced_at TIMESTAMP",
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
    "ALTER TABLE device_readings ADD COLUMN IF NOT EXISTS raw_payload JSONB",
    # sensores externos HTTP (Pró-Digital etc.)
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS source_url TEXT",
    # raio de influência no mapa térmico
    "ALTER TABLE devices ADD COLUMN IF NOT EXISTS influence_radius_m INTEGER NOT NULL DEFAULT 8",
    # guardrails por zona
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allowed_start_hour INTEGER NOT NULL DEFAULT 7",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allowed_end_hour INTEGER NOT NULL DEFAULT 22",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS is_critical_zone BOOLEAN NOT NULL DEFAULT FALSE",
    # precisão de minutos no horário (07:30 / 18:30)
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allowed_start_minute INTEGER NOT NULL DEFAULT 30",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allowed_end_minute INTEGER NOT NULL DEFAULT 30",
    # corrige registros antigos que tinham end_hour=22 (antes do ajuste para 18:30)
    "UPDATE zone_automations SET allowed_end_hour = 18 WHERE allowed_end_hour = 22",
    # tipo de zona e confiança de leitura (bloqueio térmico)
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS zone_type VARCHAR(20) NOT NULL DEFAULT 'ABERTA'",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS reading_confidence FLOAT NOT NULL DEFAULT 1.0",
    # índice composto para queries de histórico (device_id + time é o padrão de acesso)
    "CREATE INDEX IF NOT EXISTS ix_device_readings_device_time ON device_readings (device_id, time DESC)",
    # índice para lookup de alertas abertos por device+tipo (dedup e listagem)
    "CREATE INDEX IF NOT EXISTS ix_alerts_device_type_status ON alerts (device_id, alert_type, status)",
    # FK sector_id agora usa ON DELETE SET NULL (dispositivo fica sem setor se o setor for deletado)
    "ALTER TABLE devices DROP CONSTRAINT IF EXISTS devices_sector_id_fkey",
    """ALTER TABLE devices ADD CONSTRAINT devices_sector_id_fkey
       FOREIGN KEY (sector_id) REFERENCES store_sectors(id) ON DELETE SET NULL""",
    # último login de cada usuário
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
    # administrador inicial garantido (idempotente)
    "UPDATE users SET role = 'ADMIN' WHERE email = 'gustavoandrade@bemol.com.br'",
    # remove conta genérica de admin (idempotente)
    "DELETE FROM users WHERE email = 'admin@bemol.com.br'",
    # modo manutenção/bloqueado para zonas
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS blocked_reason TEXT",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS blocked_until TIMESTAMP",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS blocked_by_user_name VARCHAR(100)",
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMP",
    # audit_logs enriquecido para rastreabilidade completa
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS origin VARCHAR(20)",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS severity VARCHAR(10)",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS sector_name VARCHAR(100)",
    "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS store_name VARCHAR(100)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_origin ON audit_logs (origin)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_severity ON audit_logs (severity)",
    # prioridade operacional por zona (conforto | economia | estabilidade | manutencao)
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'conforto'",
    # zonas personalizadas criadas pelo usuário
    """CREATE TABLE IF NOT EXISTS custom_zones (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        store_id UUID NOT NULL REFERENCES stores(id),
        zone_key VARCHAR(50) NOT NULL UNIQUE,
        name VARCHAR(100) NOT NULL,
        zone_type VARCHAR(20) NOT NULL DEFAULT 'ABERTA',
        ideal_min INTEGER NOT NULL DEFAULT 20,
        ideal_max INTEGER NOT NULL DEFAULT 24,
        created_by_name VARCHAR(100),
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    """CREATE TABLE IF NOT EXISTS custom_zone_devices (
        zone_id UUID NOT NULL REFERENCES custom_zones(id) ON DELETE CASCADE,
        device_id UUID NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
        PRIMARY KEY (zone_id, device_id)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_custom_zones_store ON custom_zones (store_id)",
]


async def run_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))


async def seed_floor_plans() -> None:
    """Vincula plantas baixas e áreas de setores aos respectivos stores pelo nome."""
    from app.models.store import Store, StoreSector

    # (padrão_store_name, floor_plan_url, {setor_name: area_m2})
    _PLANS = [
        (
            "MATRIZ",
            "/floorplans/farma-matriz.png",
            {},
        ),
        (
            "DOM PEDRO",
            "/floorplans/farma-dom-pedro.jpg",
            {
                "Salão": 132.06,
                "Medicamentos": 21.62,
                "Reserva": 16.85,
                "Copa": 3.79,
                "Consultório": 3.79,
                "WC": 2.16,
                "ADM": 2.16,
            },
        ),
        (
            "BOULEVARD",
            "/floorplans/farma-boulevard.jpg",
            {
                "Salão": 254.55,        # 146,33 (frente) + 108,22 (fundo)
                "Medicamentos": 20.29,
                "Consultório": 2.99,
                "DML": 1.90,
                "Copa": 1.96,
                "WC": 2.73,
                "ADM": 5.28,            # 3,89 (fundo) + 1,39 (frente)
                "Reserva": 9.93,
            },
        ),
        (
            "FLORES",
            "/floorplans/farma-flores.jpg",
            {},
        ),
    ]

    async with AsyncSessionLocal() as session:
        for name_pattern, plan_url, sector_areas in _PLANS:
            stores_result = await session.execute(
                select(Store).where(Store.name.ilike(f"%{name_pattern}%"))
            )
            matched_stores = stores_result.scalars().all()
            for store in matched_stores:
                sectors_result = await session.execute(
                    select(StoreSector).where(StoreSector.store_id == store.id)
                )
                sectors = sectors_result.scalars().all()
                for sector in sectors:
                    sector.floor_plan_url = plan_url
                    if sector.name in sector_areas:
                        sector.area_m2 = sector_areas[sector.name]
        await session.commit()
    logger.info("Plantas baixas de setores sincronizadas")


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
