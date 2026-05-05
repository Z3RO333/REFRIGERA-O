import json
import logging
from app.cache.redis_client import redis_client
from app.ai.email_sender import send_alert_digest

logger = logging.getLogger(__name__)

REDIS_BUFFER_KEY = "ai:email_buffer"

async def buffer_alert_for_email(analysis, device_info: dict):
    """Armazena um alerta no Redis para envio posterior consolidado."""
    payload = {
        "analysis": analysis.model_dump(),
        "device_info": device_info
    }
    await redis_client.rpush(REDIS_BUFFER_KEY, json.dumps(payload))
    logger.debug(f"Alerta buferizado para {analysis.device_name}")

async def send_consolidated_email_job():
    """Lê todos os alertas do buffer e envia um único email consolidado."""
    try:
        raw_items = await redis_client.lrange(REDIS_BUFFER_KEY, 0, -1)
        if not raw_items:
            logger.debug("Buffer de email vazio, nada a enviar.")
            return

        from app.ai.analyzer import DeviceAnalysis
        items = []
        for raw in raw_items:
            data = json.loads(raw)
            items.append((DeviceAnalysis(**data["analysis"]), data["device_info"]))

        sent = await send_alert_digest(items)
        if sent:
            await redis_client.delete(REDIS_BUFFER_KEY)
            logger.info(f"Relatório consolidado enviado com {len(items)} alertas.")
        else:
            logger.warning("Falha ao enviar relatório consolidado. Itens permanecem no buffer.")

    except Exception as e:
        logger.error(f"Erro no job de email consolidado: {e}", exc_info=True)
