"""
Endpoints de IA: status, trigger manual e últimas análises.
"""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import verify_password  # reutiliza deps existentes
from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import get_db
from app.models.device import DeviceStatusLatest, Device

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/status")
async def ai_status():
    """Retorna configuração e disponibilidade do serviço de IA."""
    import httpx

    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{settings.ollama_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erro ignorado no arquivo ai.py: {e}")
    return {
        "ai_analysis_enabled": settings.ai_analysis_enabled,
        "ollama_url": settings.ollama_url,
        "ollama_model": settings.ollama_model,
        "ollama_available": ollama_ok,
        "email_enabled": settings.email_enabled,
        "email_host": settings.email_host or None,
        "email_recipients": settings.email_alert_recipients or None,
    }


@router.post("/trigger")
async def trigger_analysis():
    """Dispara análise de IA imediatamente (fora do scheduler)."""
    import asyncio
    from app.ai.job import run_ai_analysis

    asyncio.create_task(run_ai_analysis())
    return {"message": "Análise de IA iniciada em background"}


@router.get("/analyses")
async def get_recent_analyses(db: AsyncSession = Depends(get_db)):
    """
    Retorna as últimas análises da IA (cache Redis, TTL 24h).
    Inclui apenas devices que tiveram pelo menos uma análise.
    """
    result = await db.execute(
        select(Device.id).where(Device.active == True)
    )
    device_ids = [str(row.id) for row in result.all()]

    analyses = []
    for did in device_ids:
        raw = await redis_client.get(f"ai:last_analysis:{did}")
        if raw:
            try:
                data = json.loads(raw) if isinstance(raw, str) else raw
                analyses.append(data)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Erro ignorado no arquivo ai.py: {e}")
    # Ordena por severidade e horário
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    analyses.sort(key=lambda x: (sev_order.get(x.get("severity", "LOW"), 9), x.get("analyzed_at", "")))

    return {"analyses": analyses, "total": len(analyses)}
