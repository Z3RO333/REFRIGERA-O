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
    # diagnóstico de falhas de polling
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS last_error VARCHAR(200)",
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMP",
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMP",
    "ALTER TABLE device_status_latest ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0",
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
    # padroniza horário de encerramento para 18:00 (não 18:30) — parar comandos às 18h Manaus
    "UPDATE zone_automations SET allowed_end_minute = 0 WHERE allowed_end_hour = 18",
    # padroniza horário de início para 07:00 (não 07:30)
    "UPDATE zone_automations SET allowed_start_minute = 0 WHERE allowed_start_hour = 7",
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
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true",
    # posição visual legada (coordenadas SVG absolutas — mantidas para backward compat)
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS x FLOAT",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS y FLOAT",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS w FLOAT",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS h FLOAT",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS floor INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS color VARCHAR(30)",
    # geometria canônica em % da planta (nova — substitui x/y/w/h absolutos)
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS geometry JSONB",
    "ALTER TABLE custom_zones ADD COLUMN IF NOT EXISTS updated_by_name VARCHAR(100)",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS decision_ms INTEGER",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS api_ms INTEGER",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS suggestion_signature VARCHAR(80)",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS fan_speed_before INTEGER",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS fan_speed_after INTEGER",
    "CREATE INDEX IF NOT EXISTS ix_zone_actions_suggestion_signature ON zone_actions (suggestion_signature)",
    """DO $$ BEGIN
         IF EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_name='zone_automations'
             AND column_name='max_daily_adjustments'
         ) THEN
           UPDATE zone_automations
           SET max_daily_adjustments = 9999
           WHERE max_daily_adjustments IS NULL OR max_daily_adjustments < 9999;
           ALTER TABLE zone_automations ALTER COLUMN max_daily_adjustments DROP NOT NULL;
           ALTER TABLE zone_automations ALTER COLUMN max_daily_adjustments DROP DEFAULT;
         END IF;
       END $$""",
    # migra zonas antigas com x/y/w/h para geometry JSONB em percentual (viewBox 800x556)
    """UPDATE custom_zones
       SET geometry = jsonb_build_object(
         'type', 'polygon',
         'unit', 'percent',
         'points', jsonb_build_array(
           jsonb_build_object('x', round((x/800*100)::numeric,2), 'y', round((y/556*100)::numeric,2)),
           jsonb_build_object('x', round(((x+w)/800*100)::numeric,2), 'y', round((y/556*100)::numeric,2)),
           jsonb_build_object('x', round(((x+w)/800*100)::numeric,2), 'y', round(((y+h)/556*100)::numeric,2)),
           jsonb_build_object('x', round((x/800*100)::numeric,2), 'y', round(((y+h)/556*100)::numeric,2))
         )
       )
       WHERE x IS NOT NULL AND y IS NOT NULL AND w IS NOT NULL AND h IS NOT NULL
         AND geometry IS NULL""",
    # persistência de tokens Brise no PostgreSQL (sobrevive restart do container)
    """CREATE TABLE IF NOT EXISTS brise_tokens (
        key VARCHAR(80) PRIMARY KEY,
        value TEXT NOT NULL,
        expires_at TIMESTAMP
    )""",
    # unicidade de binding activo: cada device só pode estar numa zona activa de cada vez
    "ALTER TABLE custom_zone_devices ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT true",
    """CREATE UNIQUE INDEX IF NOT EXISTS uq_custom_zone_device_active
       ON custom_zone_devices (device_id)
       WHERE active = true""",
    # ciclo de vida do binding (spatial_auto | manual_pending | manual_override)
    "ALTER TABLE custom_zone_devices ADD COLUMN IF NOT EXISTS binding_mode VARCHAR(30) NOT NULL DEFAULT 'spatial_auto'",
    # flag para binding fora do polígono — avisar o operador
    "ALTER TABLE custom_zone_devices ADD COLUMN IF NOT EXISTS out_of_shape BOOLEAN NOT NULL DEFAULT false",
    # store_epochs: fencing tokens monotónicos por loja para rejeitar planos antigos (P0.4)
    """CREATE TABLE IF NOT EXISTS store_epochs (
        store_id UUID PRIMARY KEY REFERENCES stores(id) ON DELETE CASCADE,
        epoch    BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_store_epochs_store ON store_epochs (store_id)",
    # allow_auto_power_off: False em zonas comerciais (farma/loja) — AC nunca desliga automaticamente
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allow_auto_power_off BOOLEAN NOT NULL DEFAULT true",
    # allowed_end_next_day: True quando a zona opera até depois da meia-noite (Farma Flores, Boulevard)
    "ALTER TABLE zone_automations ADD COLUMN IF NOT EXISTS allowed_end_next_day BOOLEAN NOT NULL DEFAULT false",
    # horário de funcionamento por loja (usado para herdar nas zonas e exibir no dashboard)
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS open_hour INTEGER NOT NULL DEFAULT 7",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS open_minute INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS close_hour INTEGER NOT NULL DEFAULT 18",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS close_minute INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE stores ADD COLUMN IF NOT EXISTS close_next_day BOOLEAN NOT NULL DEFAULT false",
    # atualiza horários reais das Farmas e garante allow_auto_power_off=false nas zonas delas
    """UPDATE stores SET open_hour=7, open_minute=0, close_hour=0,  close_minute=0, close_next_day=true  WHERE code='FARMA_BOULEVARD'""",
    """UPDATE stores SET open_hour=7, open_minute=0, close_hour=23, close_minute=0, close_next_day=false WHERE code='FARMA_DOM_PEDRO'""",
    """UPDATE stores SET open_hour=7, open_minute=0, close_hour=1,  close_minute=0, close_next_day=true  WHERE code='FARMA_FLORES'""",
    """UPDATE stores SET open_hour=8, open_minute=0, close_hour=18, close_minute=0, close_next_day=false WHERE code='FARMA_MATRIZ'""",
    # propaga horários das Farmas para suas zone_automations
    """UPDATE zone_automations za
       SET allowed_start_hour=s.open_hour, allowed_start_minute=s.open_minute,
           allowed_end_hour=s.close_hour,  allowed_end_minute=s.close_minute,
           allowed_end_next_day=s.close_next_day,
           allow_auto_power_off=false
       FROM stores s
       WHERE za.store_id=s.id AND s.code IN ('FARMA_BOULEVARD','FARMA_DOM_PEDRO','FARMA_FLORES','FARMA_MATRIZ')""",
    # ── Aprendizado adaptativo (Fase 1) ──────────────────────────────────────
    """CREATE TABLE IF NOT EXISTS ai_decisions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        zone_action_id UUID REFERENCES zone_actions(id) ON DELETE SET NULL,
        store_id UUID NOT NULL REFERENCES stores(id),
        zone_key VARCHAR(50) NOT NULL,
        zone_label VARCHAR(100),
        decision_type VARCHAR(20) NOT NULL,
        thermal_status VARCHAR(20),
        avg_temp FLOAT,
        ideal_min FLOAT,
        ideal_max FLOAT,
        trend_c_per_hour FLOAT,
        freshness_ratio FLOAT,
        devices_on SMALLINT,
        devices_off SMALLINT,
        had_hotspot BOOLEAN NOT NULL DEFAULT false,
        hotspot_peak_temp FLOAT,
        action_type VARCHAR(30),
        device_id UUID REFERENCES devices(id),
        device_name VARCHAR(100),
        setpoint_from SMALLINT,
        setpoint_to SMALLINT,
        fan_speed_from SMALLINT,
        fan_speed_to SMALLINT,
        confidence FLOAT,
        energy_strategy VARCHAR(30),
        thermal_impact_score FLOAT,
        energy_cost_score FLOAT,
        final_score FLOAT,
        learning_bonus_applied FLOAT,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ai_decisions_store ON ai_decisions (store_id)",
    "CREATE INDEX IF NOT EXISTS ix_ai_decisions_zone ON ai_decisions (zone_key)",
    "CREATE INDEX IF NOT EXISTS ix_ai_decisions_created ON ai_decisions (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ai_decisions_type ON ai_decisions (decision_type)",
    # Idempotência: tabela ai_decisions criada antes via SQL manual pode estar sem colunas
    "ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS zone_label VARCHAR(100)",
    "ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS trend_c_per_hour FLOAT",
    "ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS thermal_impact_score FLOAT",
    "ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS energy_cost_score FLOAT",
    "ALTER TABLE ai_decisions ADD COLUMN IF NOT EXISTS final_score FLOAT",
    # migra dados da coluna antiga 'trend' (versão pré-rename) para 'trend_c_per_hour'
    """DO $$ BEGIN
         IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name='ai_decisions' AND column_name='trend')
         THEN
           UPDATE ai_decisions SET trend_c_per_hour = trend
             WHERE trend_c_per_hour IS NULL AND trend IS NOT NULL;
         END IF;
       END $$""",
    """CREATE TABLE IF NOT EXISTS ai_decision_feedback (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        decision_id UUID NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE UNIQUE,
        feedback_type VARCHAR(20) NOT NULL,
        operator_name VARCHAR(100),
        operator_email VARCHAR(200),
        actual_action_type VARCHAR(30),
        actual_device_id UUID,
        actual_device_name VARCHAR(100),
        actual_setpoint_to SMALLINT,
        feedback_at TIMESTAMP NOT NULL DEFAULT now()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ai_feedback_decision ON ai_decision_feedback (decision_id)",
    "CREATE INDEX IF NOT EXISTS ix_ai_feedback_type ON ai_decision_feedback (feedback_type)",
    """CREATE TABLE IF NOT EXISTS ai_decision_outcomes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        decision_id UUID NOT NULL REFERENCES ai_decisions(id) ON DELETE CASCADE UNIQUE,
        temp_before FLOAT,
        status_before VARCHAR(20),
        temp_15m FLOAT,
        status_15m VARCHAR(20),
        delta_15m FLOAT,
        measured_at_15 TIMESTAMP,
        temp_30m FLOAT,
        status_30m VARCHAR(20),
        delta_30m FLOAT,
        measured_at_30 TIMESTAMP,
        temp_60m FLOAT,
        status_60m VARCHAR(20),
        delta_60m FLOAT,
        measured_at_60 TIMESTAMP,
        success_score FLOAT,
        completed BOOLEAN NOT NULL DEFAULT false
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ai_outcomes_decision ON ai_decision_outcomes (decision_id)",
    "CREATE INDEX IF NOT EXISTS ix_ai_outcomes_completed ON ai_decision_outcomes (completed)",
    """CREATE TABLE IF NOT EXISTS ai_learning_scores (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        scope VARCHAR(20) NOT NULL,
        scope_id VARCHAR(100) NOT NULL,
        action_type VARCHAR(30) NOT NULL,
        thermal_status VARCHAR(20) NOT NULL,
        approval_rate FLOAT NOT NULL DEFAULT 0.5,
        success_rate FLOAT NOT NULL DEFAULT 0.5,
        avg_delta_30m FLOAT,
        sample_count INTEGER NOT NULL DEFAULT 0,
        confidence FLOAT NOT NULL DEFAULT 0.0,
        updated_at TIMESTAMP NOT NULL DEFAULT now(),
        UNIQUE (scope, scope_id, action_type, thermal_status)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_ai_scores_scope ON ai_learning_scores (scope, scope_id)",
]


async def run_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))


async def seed_floor_plans() -> None:
    """Vincula plantas baixas e áreas de setores aos respectivos stores pelo code exato."""
    from app.models.store import Store, StoreSector

    # (store_code_exato, floor_plan_url, {setor_name: area_m2})
    _PLANS = [
        (
            "MATRIZ",
            "/floorplans/escritorio-matriz.jpg",
            {},
        ),
        (
            "FARMA_MATRIZ",
            "/floorplans/farma-matriz.png",
            {},
        ),
        (
            "FARMA_DOM_PEDRO",
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
            "FARMA_BOULEVARD",
            "/floorplans/farma-boulevard.jpg",
            {
                "Salão": 254.55,
                "Medicamentos": 20.29,
                "Consultório": 2.99,
                "DML": 1.90,
                "Copa": 1.96,
                "WC": 2.73,
                "ADM": 5.28,
                "Reserva": 9.93,
            },
        ),
        (
            "FARMA_FLORES",
            "/floorplans/farma-flores.jpg",
            {},
        ),
    ]

    async with AsyncSessionLocal() as session:
        for store_code, plan_url, sector_areas in _PLANS:
            stores_result = await session.execute(
                select(Store).where(Store.code == store_code)
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
