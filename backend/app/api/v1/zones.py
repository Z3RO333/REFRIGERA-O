import json
import re
import uuid
from datetime import datetime, timedelta
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import redis_client
from app.db.session import get_db
from app.models.custom_zone import CustomZone, CustomZoneDevice
from app.models.device import Device, DeviceStatusLatest
from app.models.store import StoreSector
from app.models.zone import ZoneAction, ZoneAutomation
from app.models.user import User
from app.api.v1.auth import get_current_user, require_role
from app.services.audit_service import log_action
from app.schemas.zone import CustomZoneCreate, CustomZoneUpdate, ZoneGuardrailsUpdate, ZoneModeUpdate
from app.services.zone_controller import (
    KILL_SWITCH_KEY,
    LOCAL_TZ,
    ZONE_COOLDOWN_SECONDS,
    ZONES,
    ZoneConfig,
    _check_guardrails,
    _classify,
    _evaluate_zone,
    build_ai_view,
    get_or_create_automation,
    get_zone_last_action,
)

router = APIRouter()

# Modos que cada role pode ativar
_EDITOR_MODES = {"manual", "suggestion", "semi"}
_ADMIN_MODES  = {"manual", "suggestion", "semi", "auto", "maintenance"}


def _cooldown_key(store_id: uuid.UUID, zone_key: str) -> str:
    return f"zone:cooldown:{store_id}:{zone_key}"


async def _cooldown_ttl(store_id: uuid.UUID, zone_key: str) -> int | None:
    ttl = await redis_client.ttl(_cooldown_key(store_id, zone_key))
    return ttl if ttl and ttl > 0 else None


def _action_dict(a: ZoneAction) -> dict:
    return {
        "id": str(a.id),
        "zone_key": a.zone_key,
        "zone_label": a.zone_label,
        "device_id": str(a.device_id) if a.device_id else None,
        "device_name": a.device_name,
        "direction": a.direction,
        "temp_before": a.temp_before,
        "temp_after": a.temp_after,
        "ideal_min": a.ideal_min,
        "ideal_max": a.ideal_max,
        "setpoint_before": a.setpoint_before,
        "setpoint_after": a.setpoint_after,
        "fan_speed_before": getattr(a, "fan_speed_before", None),
        "fan_speed_after": getattr(a, "fan_speed_after", None),
        "reason": a.reason,
        "confidence": a.confidence,
        "mode": a.mode,
        "status": a.status,
        "block_reason": a.block_reason,
        "suggestion_signature": getattr(a, "suggestion_signature", None),
        "attempt_count": a.attempt_count,
        "created_at": a.created_at.isoformat(),
        "verified_at": a.verified_at.isoformat() if a.verified_at else None,
    }


def _automation_dict(
    zone_key: str,
    zone_cfg,
    automation: ZoneAutomation | None,
    last_action: ZoneAction | None,
    cooldown_ttl: int | None,
    daily_count: int,
    consecutive_fail: int,
    guardrail_reason: str | None,
) -> dict:
    return {
        "zone_key": zone_key,
        "zone_label": zone_cfg.label,
        "zone_type": zone_cfg.zone_type,
        "sector_names": zone_cfg.sector_names,
        "ideal_min": zone_cfg.ideal_min,
        "ideal_max": zone_cfg.ideal_max,
        "mode": automation.mode if automation else "manual",
        "setpoint_min": automation.setpoint_min if automation else 18,
        "setpoint_max": automation.setpoint_max if automation else 28,
        "daily_count": daily_count,
        "consecutive_failures": consecutive_fail,
        "cooldown_remaining_s": cooldown_ttl,
        "last_action": _action_dict(last_action) if last_action else None,
        # guardrails temporais
        "allowed_start_hour": automation.allowed_start_hour if automation else 7,
        "allowed_start_minute": automation.allowed_start_minute if automation else 30,
        "allowed_end_hour": automation.allowed_end_hour if automation else 18,
        "allowed_end_minute": automation.allowed_end_minute if automation else 30,
        "allowed_end_next_day": automation.allowed_end_next_day if automation else False,
        "allow_auto_power_off": automation.allow_auto_power_off if automation else True,
        "is_critical_zone": automation.is_critical_zone if automation else False,
        "guardrail_active": guardrail_reason is not None,
        "guardrail_reason": guardrail_reason,
        "reading_confidence": automation.reading_confidence if automation else 1.0,
        "priority": automation.priority if automation else "conforto",
        # manutenção
        "blocked_reason": automation.blocked_reason if automation else None,
        "blocked_until": automation.blocked_until.isoformat() if automation and automation.blocked_until else None,
        "blocked_by_user_name": automation.blocked_by_user_name if automation else None,
        "blocked_at": automation.blocked_at.isoformat() if automation and automation.blocked_at else None,
    }


async def _custom_zone_config(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession,
) -> ZoneConfig | None:
    result = await db.execute(
        select(
            CustomZone.zone_key,
            CustomZone.name,
            CustomZone.ideal_min,
            CustomZone.ideal_max,
            CustomZone.zone_type,
            CustomZoneDevice.device_id,
        )
        .outerjoin(
            CustomZoneDevice,
            (CustomZone.id == CustomZoneDevice.zone_id)
            & (CustomZoneDevice.active == True)
            & (CustomZoneDevice.binding_mode != "conflict_overlap"),
        )
        .where(CustomZone.store_id == store_id, CustomZone.zone_key == zone_key, CustomZone.active == True)
    )
    rows = result.all()
    if not rows:
        return None

    first = rows[0]
    device_ids = [row.device_id for row in rows if row.device_id is not None]
    return ZoneConfig(
        key=first.zone_key,
        label=first.name,
        sector_names=[],
        ideal_min=first.ideal_min,
        ideal_max=first.ideal_max,
        zone_type=first.zone_type,
        device_ids=device_ids,
    )


async def _resolve_zone_config(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession,
) -> ZoneConfig:
    zone_cfg = ZONES.get(zone_key)
    if zone_cfg:
        return zone_cfg

    custom_cfg = await _custom_zone_config(store_id, zone_key, db)
    if custom_cfg:
        return custom_cfg

    raise HTTPException(404, "Zona não encontrada")


async def _custom_zone_configs(store_id: uuid.UUID, db: AsyncSession) -> dict[str, ZoneConfig]:
    result = await db.execute(
        select(
            CustomZone.zone_key,
            CustomZone.name,
            CustomZone.ideal_min,
            CustomZone.ideal_max,
            CustomZone.zone_type,
            CustomZoneDevice.device_id,
        )
        .outerjoin(CustomZoneDevice, CustomZone.id == CustomZoneDevice.zone_id)
        .where(CustomZone.store_id == store_id, CustomZone.active == True)
    )
    zones: dict[str, ZoneConfig] = {}
    for zone_key, name, ideal_min, ideal_max, zone_type, device_id in result.all():
        if zone_key not in zones:
            zones[zone_key] = ZoneConfig(
                key=zone_key,
                label=name,
                sector_names=[],
                ideal_min=ideal_min,
                ideal_max=ideal_max,
                zone_type=zone_type,
                device_ids=[],
            )
        if device_id is not None:
            zones[zone_key].device_ids.append(device_id)  # type: ignore[union-attr]
    return zones


async def _batch_last_actions(
    store_id: uuid.UUID, zone_keys: list[str], db: AsyncSession
) -> dict[str, ZoneAction]:
    """Retorna a última ZoneAction de cada zona em uma única query via subquery."""
    if not zone_keys:
        return {}
    sub = (
        select(ZoneAction.zone_key, func.max(ZoneAction.created_at).label("max_at"))
        .where(ZoneAction.store_id == store_id, ZoneAction.zone_key.in_(zone_keys))
        .group_by(ZoneAction.zone_key)
    ).subquery()
    result = await db.execute(
        select(ZoneAction).join(
            sub,
            (ZoneAction.zone_key == sub.c.zone_key)
            & (ZoneAction.created_at == sub.c.max_at),
        ).where(ZoneAction.store_id == store_id)
    )
    return {a.zone_key: a for a in result.scalars().all()}


async def _batch_daily_counts(
    store_id: uuid.UUID, zone_keys: list[str], db: AsyncSession
) -> dict[str, int]:
    """Retorna contagem de ajustes do dia para todas as zonas em uma única query."""
    if not zone_keys:
        return {}
    from datetime import timezone as _tz
    now_local = datetime.now(LOCAL_TZ)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_utc = midnight_local.astimezone(_tz.utc).replace(tzinfo=None)
    result = await db.execute(
        select(ZoneAction.zone_key, func.count(ZoneAction.id).label("cnt"))
        .where(
            ZoneAction.store_id == store_id,
            ZoneAction.zone_key.in_(zone_keys),
            ZoneAction.status.in_(["pending_verification", "executed", "verified_success"]),
            ZoneAction.created_at >= midnight_utc,
        )
        .group_by(ZoneAction.zone_key)
    )
    return {row.zone_key: row.cnt for row in result.all()}


async def _batch_consecutive_failures(
    store_id: uuid.UUID, zone_keys: list[str], db: AsyncSession
) -> dict[str, int]:
    """Retorna falhas consecutivas por zona usando window function (uma query)."""
    if not zone_keys:
        return {}
    row_num = func.row_number().over(
        partition_by=ZoneAction.zone_key,
        order_by=ZoneAction.created_at.desc(),
    ).label("rn")
    subq = (
        select(ZoneAction.zone_key, ZoneAction.status, row_num)
        .where(
            ZoneAction.store_id == store_id,
            ZoneAction.zone_key.in_(zone_keys),
            ZoneAction.status.in_(["verified_success", "verified_failure"]),
        )
    ).subquery()
    result = await db.execute(
        select(subq.c.zone_key, subq.c.status)
        .where(subq.c.rn <= 5)
        .order_by(subq.c.zone_key, subq.c.rn)
    )
    rows = result.all()
    zone_rows: dict[str, list[str]] = {}
    for zone_key, status in rows:
        zone_rows.setdefault(zone_key, []).append(status)
    counts: dict[str, int] = {}
    for zk, statuses in zone_rows.items():
        count = 0
        for s in statuses:
            if s == "verified_failure":
                count += 1
            else:
                break
        counts[zk] = count
    return counts


@router.get("/{store_id}")
async def list_zones(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Retorna estado de automação de todas as zonas. Leitura pública (requer autenticação via middleware)."""
    result = await db.execute(
        select(ZoneAutomation).where(ZoneAutomation.store_id == store_id)
    )
    existing: dict[str, ZoneAutomation] = {a.zone_key: a for a in result.scalars().all()}

    all_zones = await _custom_zone_configs(store_id, db)
    zone_keys = list(all_zones.keys())

    # Carrega todas as métricas de zonas em batch — evita N+1 queries
    last_actions  = await _batch_last_actions(store_id, zone_keys, db)
    daily_counts  = await _batch_daily_counts(store_id, zone_keys, db)
    consec_fails  = await _batch_consecutive_failures(store_id, zone_keys, db)

    zones_out: list[dict] = []
    for zone_key, zone_cfg in all_zones.items():
        automation = existing.get(zone_key)
        cooldown   = await _cooldown_ttl(store_id, zone_key)

        guardrail_reason: str | None = None
        if automation and automation.mode not in ("manual", "maintenance"):
            guardrail_reason = await _check_guardrails(automation)

        zones_out.append(_automation_dict(
            zone_key, zone_cfg, automation,
            last_actions.get(zone_key),
            cooldown,
            daily_counts.get(zone_key, 0),
            consec_fails.get(zone_key, 0),
            guardrail_reason,
        ))

    return zones_out


@router.put("/{store_id}/{zone_key}/mode")
async def set_zone_mode(
    store_id: uuid.UUID,
    zone_key: str,
    data: ZoneModeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Altera o modo de automação de uma zona.
    - VIEWER: proibido (403)
    - EDITOR: manual | suggestion | semi
    - ADMIN:  manual | suggestion | semi | auto | maintenance
    """
    if current_user.role == "VIEWER":
        raise HTTPException(403, "Visualizadores não podem alterar o modo de automação.")

    mode = data.mode

    if current_user.role == "EDITOR" and mode not in _EDITOR_MODES:
        raise HTTPException(
            403,
            f"EDITOR não pode ativar o modo '{mode}'. "
            f"Modos permitidos: {', '.join(sorted(_EDITOR_MODES))}.",
        )
    if mode not in _ADMIN_MODES:
        raise HTTPException(400, f"Modo inválido. Opções: {', '.join(sorted(_ADMIN_MODES))}")

    zone_cfg = await _resolve_zone_config(store_id, zone_key, db)

    automation = await get_or_create_automation(store_id, zone_key, db)
    old_mode = automation.mode
    automation.mode = mode

    fields_set = data.model_fields_set
    new_min = data.setpoint_min if "setpoint_min" in fields_set else automation.setpoint_min
    new_max = data.setpoint_max if "setpoint_max" in fields_set else automation.setpoint_max
    if new_min >= new_max:
        raise HTTPException(400, "setpoint_min deve ser menor que setpoint_max")
    automation.setpoint_min = new_min
    automation.setpoint_max = new_max
    if data.priority is not None:
        automation.priority = data.priority

    # Campos de manutenção
    if mode == "maintenance":
        automation.blocked_reason = data.blocked_reason or "Manutenção solicitada."
        automation.blocked_by_user_name = current_user.name
        automation.blocked_at = datetime.utcnow()
        automation.blocked_until = data.blocked_until.replace(tzinfo=None) if data.blocked_until else None
    else:
        # Saindo de manutenção: limpa os campos de bloqueio
        if old_mode == "maintenance":
            automation.blocked_reason = None
            automation.blocked_until = None
            automation.blocked_by_user_name = None
            automation.blocked_at = None

    zone_label = zone_cfg.label
    await log_action(
        db, "zone_mode_change",
        f"Modo da zona '{zone_label}' alterado: {old_mode} → {mode}",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
        old_value=old_mode,
        new_value=mode,
    )
    await db.commit()

    # Fencing token (P0.4): incrementa epoch da loja para invalidar planos em curso
    # nos workers do zone_controller que usaram o snapshot anterior.
    from app.services.store_epochs import bump_epoch
    await bump_epoch(store_id, db)

    # Broadcast em tempo real para todos os usuários conectados
    event_payload = {
        "store_id": str(store_id),
        "zone_key": zone_key,
        "zone_label": zone_label,
        "old_mode": old_mode,
        "new_mode": mode,
        "priority": automation.priority,
        "changed_by": current_user.name,
        "changed_at": datetime.utcnow().isoformat(),
        "blocked_reason": automation.blocked_reason,
        "blocked_until": automation.blocked_until.isoformat() if automation.blocked_until else None,
    }
    await redis_client.publish("zone.automation.mode.changed", event_payload)

    return {"zone_key": zone_key, "mode": mode, "priority": automation.priority}


@router.get("/{store_id}/{zone_key}/ai-view")
async def zone_ai_view(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Devolve a 'Visão da IA' sobre a zona: aparelhos considerados, descartados
    com motivo, status térmico, ação recomendada e bloqueios — read-only."""
    zone = await _resolve_zone_config(store_id, zone_key, db)
    automation = await get_or_create_automation(store_id, zone_key, db)
    return await build_ai_view(store_id, zone_key, zone, automation, db)


@router.get("/{store_id}/{zone_key}/history")
async def zone_history(
    store_id: uuid.UUID,
    zone_key: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _resolve_zone_config(store_id, zone_key, db)

    result = await db.execute(
        select(ZoneAction)
        .where(ZoneAction.store_id == store_id, ZoneAction.zone_key == zone_key)
        .order_by(ZoneAction.created_at.desc())
        .limit(min(limit, 100))
    )
    return [_action_dict(a) for a in result.scalars().all()]


@router.post("/{store_id}/{zone_key}/trigger")
async def trigger_zone(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
) -> dict:
    """Dispara avaliação manual de uma zona (ignora cooldown). Requer EDITOR ou ADMIN."""
    zone_cfg = await _resolve_zone_config(store_id, zone_key, db)

    automation = await get_or_create_automation(store_id, zone_key, db)
    if automation.mode == "maintenance":
        raise HTTPException(409, "Zona em manutenção — disparo manual bloqueado.")
    await db.commit()

    await redis_client.delete(_cooldown_key(store_id, zone_key))

    try:
        await _evaluate_zone(automation, zone_override=zone_cfg)
    except Exception as exc:
        raise HTTPException(500, f"Erro ao avaliar zona: {exc}")

    last_action = await get_zone_last_action(store_id, zone_key, db)
    await log_action(
        db, "zone_trigger",
        f"{current_user.name} disparou avaliação da zona '{zone_cfg.label}'",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
        extra_data={"last_action_id": str(last_action.id) if last_action else None},
    )
    await db.commit()
    return {
        "triggered": True,
        "last_action": _action_dict(last_action) if last_action else None,
    }


@router.put("/{store_id}/{zone_key}/guardrails")
async def update_zone_guardrails(
    store_id: uuid.UUID,
    zone_key: str,
    data: ZoneGuardrailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> dict:
    """Atualiza guardrails de uma zona. Requer ADMIN."""
    await _resolve_zone_config(store_id, zone_key, db)

    automation = await get_or_create_automation(store_id, zone_key, db)

    def _parse_time(val: str) -> tuple[int, int]:
        try:
            parts = str(val).split(":")
            h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError
            return h, m
        except (ValueError, IndexError):
            raise HTTPException(400, f"Horário inválido '{val}'. Use HH:MM (ex: 07:30)")

    if data.allowed_start_time is not None:
        h, m = _parse_time(data.allowed_start_time)
        automation.allowed_start_hour, automation.allowed_start_minute = h, m

    if data.allowed_end_time is not None:
        h, m = _parse_time(data.allowed_end_time)
        automation.allowed_end_hour, automation.allowed_end_minute = h, m

    if data.is_critical_zone is not None:
        automation.is_critical_zone = data.is_critical_zone

    if data.allow_auto_power_off is not None:
        automation.allow_auto_power_off = data.allow_auto_power_off

    if data.allowed_end_next_day is not None:
        automation.allowed_end_next_day = data.allowed_end_next_day

    start_total = automation.allowed_start_hour * 60 + automation.allowed_start_minute
    end_total   = automation.allowed_end_hour   * 60 + automation.allowed_end_minute
    # Para janelas que cruzam a meia-noite (ex: Farma Flores 07:00–01:00) é
    # esperado que end_total < start_total. A validação só vale para janelas
    # do mesmo dia. Não permitir janela vazia (start == end).
    if not automation.allowed_end_next_day:
        if start_total >= end_total:
            raise HTTPException(400, "Horário de início deve ser anterior ao de fim")
    elif start_total == end_total:
        raise HTTPException(400, "Horário de início e fim não podem ser iguais")

    await log_action(
        db, "zone_guardrails_change",
        f"Guardrails da zona '{zone_key}' atualizados por {current_user.name}",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
        extra_data=data.model_dump(exclude_unset=True),
    )
    await db.commit()
    return {
        "zone_key": zone_key,
        "allowed_start_time": f"{automation.allowed_start_hour:02d}:{automation.allowed_start_minute:02d}",
        "allowed_end_time":   f"{automation.allowed_end_hour:02d}:{automation.allowed_end_minute:02d}",
        "allowed_end_next_day": automation.allowed_end_next_day,
        "is_critical_zone": automation.is_critical_zone,
        "allow_auto_power_off": automation.allow_auto_power_off,
    }


# ── Zonas personalizadas (CRUD) ───────────────────────────────────────────────

async def _device_position(device_id: uuid.UUID, db: AsyncSession) -> tuple[float | None, float | None]:
    res = await db.execute(select(Device.position_x, Device.position_y).where(Device.id == device_id))
    row = res.one_or_none()
    return (row[0], row[1]) if row else (None, None)


def _on_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> bool:
    """True se (px,py) está sobre o segmento (ax,ay)-(bx,by) — semântica ST_Covers."""
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-9:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    len_sq = (bx - ax) ** 2 + (by - ay) ** 2
    return 0.0 <= dot <= len_sq


def _point_in_geometry(px: float, py: float, geometry: dict, viewbox_w: float = 800, viewbox_h: float = 556) -> bool:
    """PIP inclusivo (equivalente a ST_Covers): interior OU na fronteira."""
    pts = geometry.get("points", [])
    if len(pts) < 3:
        return False
    poly = [{"x": p["x"] / 100 * viewbox_w, "y": p["y"] / 100 * viewbox_h} for p in pts]
    # 1. Fronteira — verifica cada aresta
    j = len(poly) - 1
    for i, pt in enumerate(poly):
        if _on_segment(px, py, poly[j]["x"], poly[j]["y"], pt["x"], pt["y"]):
            return True
        j = i
    # 2. Interior — ray casting
    inside = False
    j = len(poly) - 1
    for i, pt in enumerate(poly):
        xi, yi, xj, yj = pt["x"], pt["y"], poly[j]["x"], poly[j]["y"]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


async def _device_has_active_conflict(device_id: uuid.UUID, excluding_zone_id: uuid.UUID, db: AsyncSession) -> bool:
    """True se o device já tem binding activo noutra zona — detecta conflict_overlap."""
    count = await db.scalar(
        select(func.count()).where(
            CustomZoneDevice.device_id == device_id,
            CustomZoneDevice.zone_id != excluding_zone_id,
            CustomZoneDevice.active == True,
        )
    )
    return (count or 0) > 0


def _binding_mode_and_shape(
    device_id: uuid.UUID,
    geometry: dict | None,
    position: tuple[float | None, float | None],
) -> tuple[str, bool]:
    px, py = position
    if px is None or py is None:
        return "manual_pending", False
    if geometry and geometry.get("unit") == "percent":
        inside = _point_in_geometry(px, py, geometry)
        return "spatial_auto", not inside
    return "spatial_auto", False


def _zone_key_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")[:30]
    return f"cz-{slug}-{uuid.uuid4().hex[:6]}"


async def _cz_current_temp(cz: CustomZone, db: AsyncSession) -> tuple[float | None, str]:
    """Retorna (temperatura_média, status_térmico) atual dos devices da zona."""
    dev_ids_res = await db.execute(
        select(CustomZoneDevice.device_id).where(
            CustomZoneDevice.zone_id == cz.id,
            CustomZoneDevice.active == True,
            CustomZoneDevice.binding_mode != "conflict_overlap",
        )
    )
    dev_ids = [r[0] for r in dev_ids_res.all()]
    if not dev_ids:
        return None, "NO_READING"
    temps_res = await db.execute(
        select(DeviceStatusLatest.temperature)
        .join(Device, Device.id == DeviceStatusLatest.device_id)
        .where(Device.active == True, Device.id.in_(dev_ids), DeviceStatusLatest.temperature.is_not(None))
    )
    temps = [float(r[0]) for r in temps_res.all()]
    if not temps:
        return None, "NO_READING"
    avg = round(mean(temps), 1)
    return avg, _classify(avg, cz.ideal_min, cz.ideal_max)


def _cz_dict(cz: CustomZone, device_ids: list[uuid.UUID], current_temp: float | None, temp_status: str) -> dict:
    return {
        "id": str(cz.id),
        "store_id": str(cz.store_id),
        "zone_key": cz.zone_key,
        "name": cz.name,
        "zone_type": cz.zone_type,
        "ideal_min": cz.ideal_min,
        "ideal_max": cz.ideal_max,
        "geometry": cz.geometry,
        "floor": cz.floor,
        "color": cz.color,
        "created_by_name": cz.created_by_name,
        "created_at": cz.created_at.isoformat(),
        "device_ids": [str(d) for d in device_ids],
        "current_temp": current_temp,
        "temp_status": temp_status,
        "is_custom": True,
    }


@router.get("/{store_id}/custom")
async def list_custom_zones(store_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Lista zonas personalizadas com temperatura atual."""
    result = await db.execute(select(CustomZone).where(CustomZone.store_id == store_id, CustomZone.active == True))
    czs = result.scalars().all()
    out = []
    for cz in czs:
        dev_res = await db.execute(
            select(CustomZoneDevice.device_id).where(
                CustomZoneDevice.zone_id == cz.id,
                CustomZoneDevice.active == True,
                CustomZoneDevice.binding_mode != "conflict_overlap",
            )
        )
        dev_ids = [r[0] for r in dev_res.all()]
        current_temp, temp_status = await _cz_current_temp(cz, db)
        out.append(_cz_dict(cz, dev_ids, current_temp, temp_status))
    return out


_EDITOR_ALLOWED_MODES = {"manual", "suggestion", "semi"}

@router.post("/{store_id}/custom")
async def create_custom_zone(
    store_id: uuid.UUID,
    data: CustomZoneCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
) -> dict:
    """Cria zona personalizada e sua automação inicial."""
    # Bug 1: EDITOR não pode criar zona em modo admin
    if current_user.role != "ADMIN" and data.mode not in _EDITOR_ALLOWED_MODES:
        raise HTTPException(403, f"Perfil {current_user.role} não pode criar zona no modo '{data.mode}'")

    name = data.name.strip()
    ideal_min = data.ideal_min
    ideal_max = data.ideal_max
    zone_type = data.zone_type
    device_ids = data.device_ids

    # Bug 10: valida devices garantindo store_id (evita vazar device de outra loja)
    if device_ids:
        valid = await db.execute(
            select(Device.id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .where(StoreSector.store_id == store_id, Device.id.in_(device_ids), Device.active == True)
        )
        valid_ids = {r[0] for r in valid.all()}
        if valid_ids != set(device_ids):
            raise HTTPException(400, "Todos os equipamentos da zona devem pertencer à loja informada")
    else:
        valid_ids = set()

    zone_key = _zone_key_from_name(name)
    cz = CustomZone(
        store_id=store_id,
        zone_key=zone_key,
        name=name,
        zone_type=zone_type,
        ideal_min=ideal_min,
        ideal_max=ideal_max,
        geometry=data.geometry,
        floor=data.floor,
        color=data.color,
        created_by_name=current_user.name,
    )
    db.add(cz)
    await db.flush()

    geo = data.geometry
    for dev_id in valid_ids:
        mode, out = _binding_mode_and_shape(dev_id, geo, await _device_position(dev_id, db))
        if mode != "manual_pending" and await _device_has_active_conflict(dev_id, cz.id, db):
            mode = "conflict_overlap"
        active = mode != "conflict_overlap"
        db.add(CustomZoneDevice(zone_id=cz.id, device_id=dev_id, binding_mode=mode, out_of_shape=out, active=active))

    automation = ZoneAutomation(
        store_id=store_id, zone_key=zone_key, mode=data.mode,
        setpoint_min=ideal_min - 2, setpoint_max=ideal_max + 2,
    )
    db.add(automation)
    # Auditoria antes do commit para garantir atomicidade
    await log_action(db,
        action_type="custom_zone_created",
        description=f"Zona '{name}' criada com {len(valid_ids)} equipamento(s)",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
        new_value=f"ideal {ideal_min}-{ideal_max}°C, modo {data.mode}",
    )
    await db.commit()

    current_temp, temp_status = await _cz_current_temp(cz, db)
    return _cz_dict(cz, list(valid_ids), current_temp, temp_status)


@router.put("/{store_id}/custom/{zone_key}")
async def update_custom_zone(
    store_id: uuid.UUID,
    zone_key: str,
    data: CustomZoneUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
) -> dict:
    """Atualiza nome, faixa de temperatura e equipamentos de uma zona personalizada."""
    result = await db.execute(
        select(CustomZone).where(CustomZone.zone_key == zone_key, CustomZone.store_id == store_id)
    )
    cz = result.scalar_one_or_none()
    if not cz:
        raise HTTPException(404, "Zona personalizada não encontrada")

    fields_set = data.model_fields_set
    if "name" in fields_set and data.name is not None:
        cz.name = data.name.strip()
    if "ideal_min" in fields_set and data.ideal_min is not None:
        cz.ideal_min = data.ideal_min
    if "ideal_max" in fields_set and data.ideal_max is not None:
        cz.ideal_max = data.ideal_max
    if cz.ideal_min >= cz.ideal_max:
        raise HTTPException(400, "ideal_min deve ser menor que ideal_max")
    if "zone_type" in fields_set and data.zone_type is not None:
        cz.zone_type = data.zone_type
    for field in ("geometry", "floor", "color"):
        if field in fields_set:
            setattr(cz, field, getattr(data, field))
    if "geometry" in fields_set or "name" in fields_set:
        cz.updated_by_name = current_user.name

    if "device_ids" in fields_set and data.device_ids is not None:
        new_ids = data.device_ids
        valid = await db.execute(
            select(Device.id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .where(StoreSector.store_id == store_id, Device.id.in_(new_ids))
        )
        valid_ids = {r[0] for r in valid.all()}
        if valid_ids != set(new_ids):
            raise HTTPException(400, "Todos os equipamentos da zona devem pertencer à loja informada")
        await db.execute(
            CustomZoneDevice.__table__.delete().where(CustomZoneDevice.zone_id == cz.id)
        )
        geo = cz.geometry  # geometry já actualizada acima
        for dev_id in new_ids:
            mode, out = _binding_mode_and_shape(dev_id, geo, await _device_position(dev_id, db))
            if mode != "manual_pending" and await _device_has_active_conflict(dev_id, cz.id, db):
                mode = "conflict_overlap"
            active = mode != "conflict_overlap"
            db.add(CustomZoneDevice(zone_id=cz.id, device_id=dev_id, binding_mode=mode, out_of_shape=out, active=active))

    # Sincroniza ideal_min/max na automação
    auto_res = await db.execute(
        select(ZoneAutomation).where(ZoneAutomation.zone_key == zone_key, ZoneAutomation.store_id == store_id)
    )
    auto = auto_res.scalar_one_or_none()
    if auto:
        auto.setpoint_min = cz.ideal_min - 2
        auto.setpoint_max = cz.ideal_max + 2

    await log_action(db,
        action_type="custom_zone_updated",
        description=f"Zona '{cz.name}' atualizada: {', '.join(fields_set)}",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
    )
    await db.commit()

    dev_res = await db.execute(
        select(CustomZoneDevice.device_id).where(CustomZoneDevice.zone_id == cz.id)
    )
    dev_ids = [r[0] for r in dev_res.all()]
    current_temp, temp_status = await _cz_current_temp(cz, db)
    return _cz_dict(cz, dev_ids, current_temp, temp_status)


@router.delete("/{store_id}/custom/{zone_key}")
async def delete_custom_zone(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("EDITOR", "ADMIN")),
) -> dict:
    """Remove zona personalizada e sua automação."""
    result = await db.execute(
        select(CustomZone).where(CustomZone.zone_key == zone_key, CustomZone.store_id == store_id)
    )
    cz = result.scalar_one_or_none()
    if not cz:
        raise HTTPException(404, "Zona personalizada não encontrada")

    # Bug 6: soft delete — preserva histórico de ZoneActions
    cz.active = False
    cz.updated_at = datetime.utcnow()
    cz.updated_by_name = current_user.name

    # Libera os bindings para que os devices possam ser vinculados a outras zonas
    await db.execute(
        CustomZoneDevice.__table__.update()
        .where(CustomZoneDevice.zone_id == cz.id)
        .values(active=False)
    )

    # Inativa a automação (não apaga)
    auto_res = await db.execute(
        select(ZoneAutomation).where(ZoneAutomation.zone_key == zone_key, ZoneAutomation.store_id == store_id)
    )
    auto = auto_res.scalar_one_or_none()
    if auto:
        auto.mode = "manual"

    await log_action(db,
        action_type="custom_zone_deleted",
        description=f"Zona '{cz.name}' desativada (soft delete)",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
    )
    await db.commit()

    return {"deleted": zone_key}


@router.post("/{store_id}/custom/{zone_key}/restore")
async def restore_custom_zone(
    store_id: uuid.UUID, zone_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
) -> dict:
    """Restaura zona que foi soft-deletada."""
    result = await db.execute(
        select(CustomZone).where(CustomZone.zone_key == zone_key, CustomZone.store_id == store_id)
    )
    cz = result.scalar_one_or_none()
    if not cz:
        raise HTTPException(404, "Zona não encontrada")
    cz.active = True
    cz.updated_at = datetime.utcnow()

    # Reactiva apenas os bindings cujo device não está já activo noutras zonas
    binding_res = await db.execute(
        select(CustomZoneDevice.device_id).where(CustomZoneDevice.zone_id == cz.id)
    )
    bound_ids = [r[0] for r in binding_res.all()]
    for dev_id in bound_ids:
        # Verifica se o device tem binding activo noutras zonas
        conflict = await db.execute(
            select(CustomZoneDevice.zone_id)
            .where(CustomZoneDevice.device_id == dev_id, CustomZoneDevice.active == True)
        )
        if not conflict.scalar_one_or_none():
            await db.execute(
                CustomZoneDevice.__table__.update()
                .where(CustomZoneDevice.zone_id == cz.id, CustomZoneDevice.device_id == dev_id)
                .values(active=True)
            )

    await log_action(db,
        action_type="custom_zone_restored",
        description=f"Zona '{cz.name}' restaurada",
        user=current_user,
        store_id=store_id,
        zone_key=zone_key,
    )
    await db.commit()
    return {"restored": zone_key}


@router.get("/{store_id}/suggestions")
async def zone_suggestions(
    store_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Sugestões da IA para criação/ajuste de zonas — nunca executa automaticamente.
    O usuário revisa e confirma antes de qualquer ação.
    """
    from app.models.custom_zone import CustomZoneDevice

    # Devices ativos da loja
    all_devices_res = await db.execute(
        select(Device, DeviceStatusLatest)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .where(StoreSector.store_id == store_id, Device.active == True, Device.source_url.is_(None))
    )
    all_devices = all_devices_res.all()

    # Devices já vinculados a alguma zona ativa
    linked_res = await db.execute(
        select(CustomZoneDevice.device_id)
        .join(CustomZone, CustomZoneDevice.zone_id == CustomZone.id)
        .where(CustomZone.store_id == store_id, CustomZone.active == True)
    )
    linked_ids = {r[0] for r in linked_res.all()}

    suggestions = []

    # Sugestão 1: aparelhos sem zona
    orphan_devices = [
        {"device_id": str(d.id), "name": d.name, "sector": None}
        for d, _s in all_devices if d.id not in linked_ids
    ]
    if orphan_devices:
        suggestions.append({
            "type": "orphan_devices",
            "severity": "WARNING",
            "title": f"{len(orphan_devices)} equipamento(s) sem zona",
            "description": "Estes aparelhos não estão vinculados a nenhuma zona térmica ativa.",
            "devices": orphan_devices[:10],
            "action": "Desenhe uma zona no mapa e vincule estes aparelhos.",
        })

    # Sugestão 2: zonas sem equipamento
    zones_res = await db.execute(
        select(CustomZone).where(CustomZone.store_id == store_id, CustomZone.active == True)
    )
    zones = zones_res.scalars().all()
    for zone in zones:
        dev_count_res = await db.execute(
            select(func.count(CustomZoneDevice.device_id)).where(CustomZoneDevice.zone_id == zone.id)
        )
        dev_count = dev_count_res.scalar() or 0
        if dev_count == 0:
            suggestions.append({
                "type": "zone_no_devices",
                "severity": "WARNING",
                "title": f"Zona '{zone.name}' sem equipamentos",
                "description": "Esta zona não tem aparelhos vinculados — não há como controlar a temperatura.",
                "zone_key": zone.zone_key,
                "action": "Vincule pelo menos um ar-condicionado a esta zona.",
            })

    # Sugestão 3: aparelhos sem leitura há muito tempo dentro de zona
    from app.rules.classifier import NO_READING_THRESHOLD_MINUTES
    from datetime import datetime
    now = datetime.utcnow()
    stale_threshold = NO_READING_THRESHOLD_MINUTES * 2
    for device, status in all_devices:
        if device.id in linked_ids and status and status.updated_at:
            mins = (now - status.updated_at).total_seconds() / 60
            if mins > stale_threshold:
                suggestions.append({
                    "type": "device_stale",
                    "severity": "INFO",
                    "title": f"'{device.name}' sem leitura há {int(mins)} min",
                    "description": "Aparelho vinculado a uma zona mas sem leitura recente.",
                    "device_id": str(device.id),
                    "device_name": device.name,
                    "action": "Verifique se o aparelho está ligado e comunicando com a API Brise.",
                })

    return {"suggestions": suggestions, "total": len(suggestions)}
