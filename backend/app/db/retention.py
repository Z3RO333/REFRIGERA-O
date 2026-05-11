"""
Retenção de dados históricos — executada diariamente pelo scheduler.
- device_readings: mantém 180 dias
- alerts resolvidos: mantém 365 dias
"""
import logging
from datetime import datetime, timedelta
from sqlalchemy import text
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

READINGS_RETENTION_DAYS = 180
ALERTS_RETENTION_DAYS   = 365


async def purge_old_readings() -> None:
    cutoff_readings = datetime.utcnow() - timedelta(days=READINGS_RETENTION_DAYS)
    cutoff_alerts   = datetime.utcnow() - timedelta(days=ALERTS_RETENTION_DAYS)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("DELETE FROM device_readings WHERE time < :cutoff RETURNING 1"),
            {"cutoff": cutoff_readings},
        )
        deleted_readings = result.rowcount

        result = await session.execute(
            text("""
                DELETE FROM alerts
                WHERE status IN ('RESOLVED', 'ACK')
                  AND COALESCE(resolved_at, acked_at) < :cutoff
                RETURNING 1
            """),
            {"cutoff": cutoff_alerts},
        )
        deleted_alerts = result.rowcount

        await session.commit()

    if deleted_readings or deleted_alerts:
        logger.info(
            "Retenção: %d leituras e %d alertas removidos",
            deleted_readings, deleted_alerts,
        )
