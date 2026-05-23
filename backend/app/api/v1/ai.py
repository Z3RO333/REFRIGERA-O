"""
Endpoints de IA: status, trigger manual, análises por device e por zona.
"""
import asyncio
import json
import logging
import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import require_role
from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import get_db
from app.models.device import DeviceStatusLatest, Device, DeviceParameters
from app.models.store import Store
from app.models.user import User
from app.brise.client import brise_client
from app.ai.chat_control_prompt import CHAT_CONTROL_SYSTEM_PROMPT

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
async def trigger_analysis(_: User = Depends(require_role("EDITOR", "ADMIN"))):
    """Dispara análise de IA imediatamente (fora do scheduler)."""
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


@router.get("/zone-analyses")
async def get_zone_analyses(db: AsyncSession = Depends(get_db)):
    """Retorna últimas análises de IA por zona — inclui zonas fixas e customizadas."""
    from app.services.zone_controller import ZONES, _load_all_custom_zones
    from app.models.custom_zone import CustomZone

    stores_res = await db.execute(select(Store).where(Store.active == True))
    stores = stores_res.scalars().all()

    analyses = []
    for store in stores:
        # Bug 11: inclui custom zones além das fixas
        custom = await _load_all_custom_zones(db)
        all_zone_keys = set(custom.keys())

        for zone_key in all_zone_keys:
            raw = await redis_client.get(f"ai:last_zone_analysis:{store.id}:{zone_key}")
            if raw:
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                    analyses.append(data)
                except Exception:
                    pass

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    analyses.sort(key=lambda x: (sev_order.get(x.get("severity", "LOW"), 9), x.get("analyzed_at", "")))

    return {"analyses": analyses, "total": len(analyses)}


@router.post("/zones/{store_id}/{zone_key}/analyze")
async def trigger_zone_analysis(
    store_id: str,
    zone_key: str,
    _: User = Depends(require_role("EDITOR", "ADMIN")),
):
    """Dispara análise aprofundada de zona específica (modelo pesado, on-demand)."""
    from app.ai.job import trigger_zone_analysis as _run

    asyncio.create_task(_run(store_id, zone_key))
    return {"message": f"Análise da zona '{zone_key}' iniciada em background"}


@router.post("/chat-command")
async def ai_chat_command(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
):
    """
    Comando simples em linguagem natural para executar ações em massa:
    - "todos os ar com 25 graus"
    - "desligar todos os ar"
    - "ligar todos os ar"
    """
    text = (payload.get("message") or "").strip().lower()
    if not text:
        raise HTTPException(400, "Mensagem vazia")

    target_temp = None
    m = re.search(r"(\d{2})(?:\s*°?\s*c| graus?)", text)
    if m:
        target_temp = int(m.group(1))

    command = None
    if "deslig" in text:
        command = "power_off"
    elif "lig" in text:
        command = "power_on"
    elif target_temp is not None:
        command = "set_temp"

    if command is None:
        raise HTTPException(400, "Não entendi o comando. Ex.: 'todos os ar com 25 graus'")

    if command == "set_temp" and (target_temp is None or target_temp < 18 or target_temp > 28):
        raise HTTPException(400, "Temperatura fora da faixa permitida (18-28°C)")

    result = await db.execute(select(Device).where(Device.active == True, Device.source_url.is_(None)))
    devices = result.scalars().all()

    success = 0
    failed = 0
    skipped = 0
    errors: list[str] = []
    for device in devices:
        if device.dnd:
            skipped += 1
            continue
        params_row = await db.get(DeviceParameters, device.id)
        current = {
            "mode_device": params_row.mode_device if params_row else 1,
            "mode_ac": params_row.mode_ac if params_row else 0,
            "fan_speed": params_row.fan_speed if params_row else 2,
            "setpoint_cool": params_row.setpoint_cool if params_row else 24,
            "setpoint_heat": params_row.setpoint_heat if params_row else 20,
            "eco_cool": params_row.eco_cool if params_row else 22,
            "eco_heat": params_row.eco_heat if params_row else 18,
        }
        if command == "power_off":
            current["mode_device"] = 0
        elif command == "power_on":
            current["mode_device"] = 1
            current["mode_ac"] = 0
        elif command == "set_temp":
            current["setpoint_cool"] = target_temp
            current["mode_device"] = 1
            current["mode_ac"] = 0

        brise_payload = {
            "modeDevice": current["mode_device"],
            "modeAC": current["mode_ac"],
            "fanSpeed": current["fan_speed"],
            "setpointCool": current["setpoint_cool"],
            "setpointHeat": current["setpoint_heat"],
            "ecoCool": current["eco_cool"],
            "ecoHeat": current["eco_heat"],
        }
        ok = await brise_client.put_parameters(device.brise_device_id, brise_payload)
        if not ok:
            failed += 1
            errors.append(device.name)
            continue
        success += 1
        if params_row:
            params_row.mode_device = current["mode_device"]
            params_row.mode_ac = current["mode_ac"]
            params_row.fan_speed = current["fan_speed"]
            params_row.setpoint_cool = current["setpoint_cool"]
            params_row.setpoint_heat = current["setpoint_heat"]
            params_row.eco_cool = current["eco_cool"]
            params_row.eco_heat = current["eco_heat"]
        else:
            db.add(DeviceParameters(device_id=device.id, **current))

    await db.commit()
    return {
        "message": f"Comando aplicado por {current_user.name}",
        "command": command,
        "target_temp": target_temp,
        "success": success,
        "failed": failed,
        "skipped_dnd": skipped,
        "total": len(devices),
        "failed_devices": errors[:20],
    }


@router.get("/chat-command/prompt")
async def get_chat_command_prompt(_: User = Depends(require_role("EDITOR", "ADMIN"))):
    """Retorna o prompt recomendado para interpretar comandos de HVAC em linguagem natural."""
    return {
        "system_prompt": CHAT_CONTROL_SYSTEM_PROMPT,
        "examples": [
            "quero que todos os ar-condicionados fiquem com 25 graus",
            "desligar todos os ar agora",
            "ligar todos os ar da zona farmacia",
        ],
    }
