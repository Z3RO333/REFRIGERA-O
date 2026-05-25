"""
Endpoints de IA: status, trigger manual, análises por device e por zona.
"""
import asyncio
import json
import logging
import re
from types import SimpleNamespace
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
from app.api.v1.devices import (
    DEFAULT_PARAMETERS,
    _persist_device_parameters,
    _to_brise_params,
    _validate_control_action,
)
from app.services.audit_service import log_action

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
    skipped_reasons: dict[str, int] = {}
    command_for_validation = "set_temperature" if command == "set_temp" else command

    for device in devices:
        params_row = await db.get(DeviceParameters, device.id)
        status = await db.get(DeviceStatusLatest, device.id)
        current = DEFAULT_PARAMETERS.copy()
        if params_row:
            current.update({
                "mode_device": params_row.mode_device,
                "mode_ac": params_row.mode_ac,
                "fan_speed": params_row.fan_speed,
                "setpoint_cool": params_row.setpoint_cool,
                "setpoint_heat": params_row.setpoint_heat,
                "eco_cool": params_row.eco_cool,
                "eco_heat": params_row.eco_heat,
            })
        next_params = current.copy()

        if command == "power_off":
            next_params["mode_device"] = 0
        elif command == "power_on":
            next_params["mode_device"] = 1
            next_params["mode_ac"] = 0
        elif command == "set_temp":
            next_params["setpoint_cool"] = target_temp

        validation_command = SimpleNamespace(action=command_for_validation, step=0)
        validation_error = _validate_control_action(device, status, current, next_params, validation_command)
        if validation_error:
            validation_code, validation_message = validation_error
            skipped += 1
            skipped_reasons[validation_code] = skipped_reasons.get(validation_code, 0) + 1
            await log_action(
                db, "device_control",
                f"{current_user.name} tentou comando em massa — {device.name}, mas foi bloqueado: {validation_message}",
                user=current_user,
                device_id=device.id,
                device_name=device.name,
                old_value=str(current.get("setpoint_cool")) if command == "set_temp" else str(current.get("mode_device")),
                new_value=str(next_params.get("setpoint_cool")) if command == "set_temp" else str(next_params.get("mode_device")),
                extra_data={
                    "action": command_for_validation,
                    "confirmed": False,
                    "rejected": validation_code,
                    "source": "ai_chat_command",
                },
                severity="LOW" if validation_code.startswith("NO_OP") else "MEDIUM",
            )
            continue

        ok = await brise_client.put_parameters(device.brise_device_id, _to_brise_params(next_params))
        if not ok:
            failed += 1
            errors.append(device.name)
            await log_action(
                db, "device_control",
                f"{current_user.name} tentou comando em massa — {device.name}, mas a Brise API recusou/falhou",
                user=current_user,
                device_id=device.id,
                device_name=device.name,
                old_value=str(current.get("setpoint_cool")) if command == "set_temp" else str(current.get("mode_device")),
                new_value=str(next_params.get("setpoint_cool")) if command == "set_temp" else str(next_params.get("mode_device")),
                extra_data={"action": command_for_validation, "confirmed": False, "source": "ai_chat_command"},
                severity="HIGH",
            )
            continue

        success += 1
        await _persist_device_parameters(device.id, next_params, db)
        await log_action(
            db, "device_control",
            f"{current_user.name} aplicou comando em massa — {device.name}",
            user=current_user,
            device_id=device.id,
            device_name=device.name,
            old_value=str(current.get("setpoint_cool")) if command == "set_temp" else str(current.get("mode_device")),
            new_value=str(next_params.get("setpoint_cool")) if command == "set_temp" else str(next_params.get("mode_device")),
            extra_data={"action": command_for_validation, "confirmed": True, "source": "ai_chat_command"},
        )

    await db.commit()
    return {
        "message": f"Comando processado por {current_user.name}",
        "command": command,
        "target_temp": target_temp,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "skipped_dnd": skipped_reasons.get("DEVICE_BLOCKED", 0),
        "skipped_reasons": skipped_reasons,
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
