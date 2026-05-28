"""
Portfolio — centro de comando multi-loja.

GET /portfolio/stores  — resumo por loja com urgência, alertas, zona e binding.
GET /portfolio/kpis    — totais globais para o KPI strip do portfolio.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.db.session import get_db
from app.models.alert import Alert
from app.models.custom_zone import CustomZone, CustomZoneDevice
from app.models.device import Device
from app.models.store import Store, StoreSector
from app.models.zone import ZoneAction, ZoneAutomation

router = APIRouter()


@router.get("/stores")
async def portfolio_stores(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Resumo por loja ordenado por urgência descendente."""
    # ── 1. Lojas activas ─────────────────────────────────────────────────────
    stores_result = await db.execute(
        select(Store).where(Store.active == True).order_by(Store.name)
    )
    stores = stores_result.scalars().all()
    if not stores:
        return []
    store_ids = [s.id for s in stores]

    # ── 2. Alertas abertos P1/P2 por loja ───────────────────────────────────
    alerts_q = await db.execute(
        select(
            StoreSector.store_id,
            Alert.severity,
            func.count(Alert.id).label("cnt"),
        )
        .join(Device, Alert.device_id == Device.id)
        .join(StoreSector, Device.sector_id == StoreSector.id)
        .where(
            Alert.status == "OPEN",
            Alert.severity.in_(["P1", "P2"]),
            StoreSector.store_id.in_(store_ids),
        )
        .group_by(StoreSector.store_id, Alert.severity)
    )
    alert_counts: dict[uuid.UUID, dict[str, int]] = {}
    for sid, sev, cnt in alerts_q.all():
        alert_counts.setdefault(sid, {})[sev] = cnt

    # ── 3. Acções em curso (pending_verification < 30 min) por loja ──────────
    cutoff30 = datetime.utcnow() - timedelta(minutes=30)
    actions_q = await db.execute(
        select(ZoneAction.store_id, func.count(ZoneAction.id).label("cnt"))
        .where(
            ZoneAction.status == "pending_verification",
            ZoneAction.store_id.in_(store_ids),
            ZoneAction.created_at >= cutoff30,
        )
        .group_by(ZoneAction.store_id)
    )
    actions_in_progress: dict[uuid.UUID, int] = {r[0]: r[1] for r in actions_q.all()}

    # ── 4. Modos de automação por loja ───────────────────────────────────────
    modes_q = await db.execute(
        select(
            ZoneAutomation.store_id,
            ZoneAutomation.mode,
            func.count(ZoneAutomation.id).label("cnt"),
        )
        .where(ZoneAutomation.store_id.in_(store_ids))
        .group_by(ZoneAutomation.store_id, ZoneAutomation.mode)
    )
    zone_modes: dict[uuid.UUID, dict[str, int]] = {}
    for sid, mode, cnt in modes_q.all():
        zone_modes.setdefault(sid, {})[mode] = cnt

    # ── 5. Conflitos de binding por loja ─────────────────────────────────────
    conflicts_q = await db.execute(
        select(CustomZone.store_id, func.count(CustomZoneDevice.device_id).label("cnt"))
        .join(CustomZoneDevice, CustomZoneDevice.zone_id == CustomZone.id)
        .where(
            CustomZoneDevice.binding_mode == "conflict_overlap",
            CustomZone.store_id.in_(store_ids),
        )
        .group_by(CustomZone.store_id)
    )
    binding_conflicts: dict[uuid.UUID, int] = {r[0]: r[1] for r in conflicts_q.all()}

    # ── 6. Estado térmico das zonas (última hora) ────────────────────────────
    cutoff1h = datetime.utcnow() - timedelta(hours=1)
    recent_q = await db.execute(
        select(
            ZoneAction.store_id,
            ZoneAction.zone_key,
            ZoneAction.temp_before,
            ZoneAction.ideal_min,
            ZoneAction.ideal_max,
            ZoneAction.created_at,
        )
        .where(
            ZoneAction.store_id.in_(store_ids),
            ZoneAction.temp_before.is_not(None),
            ZoneAction.created_at >= cutoff1h,
        )
        .order_by(ZoneAction.created_at.desc())
    )
    seen_zones: set[tuple] = set()
    store_zone_stats: dict[uuid.UUID, dict] = {}
    for sid, zk, temp, ideal_min, ideal_max, _ in recent_q.all():
        key = (sid, zk)
        if key in seen_zones:
            continue
        seen_zones.add(key)
        st = store_zone_stats.setdefault(sid, {"temps": [], "hot": 0, "warm": 0, "comfort": 0, "cold": 0})
        t = float(temp)
        st["temps"].append(t)
        if ideal_max is not None:
            delta = t - float(ideal_max)
            if delta > 3.5:
                st["hot"] += 1
            elif delta > 1.5:
                st["warm"] += 1
            elif ideal_min is not None and t >= float(ideal_min):
                st["comfort"] += 1
            else:
                st["cold"] += 1

    # ── 7. Monta resposta com score de urgência ───────────────────────────────
    results = []
    for store in stores:
        sid = store.id
        alerts = alert_counts.get(sid, {})
        p1 = alerts.get("P1", 0)
        p2 = alerts.get("P2", 0)
        conflicts = binding_conflicts.get(sid, 0)
        actions = actions_in_progress.get(sid, 0)
        zs = store_zone_stats.get(sid, {"temps": [], "hot": 0, "warm": 0, "comfort": 0, "cold": 0})
        modes = zone_modes.get(sid, {})

        avg_temp = (sum(zs["temps"]) / len(zs["temps"])) if zs["temps"] else None
        total_zones = sum(modes.values())
        auto_zones = modes.get("auto", 0) + modes.get("semi", 0)
        maintenance_zones = modes.get("maintenance", 0)

        # Urgência 0–100
        urgency = min(100, p1 * 30 + p2 * 15 + zs["hot"] * 20 + zs["warm"] * 8 + conflicts * 5)
        risk = (
            "CRITICAL" if urgency >= 60
            else "HIGH" if urgency >= 35
            else "MEDIUM" if urgency >= 10
            else "LOW"
        )

        results.append({
            "store_id": str(sid),
            "store_name": store.name,
            "store_code": store.code,
            "urgency_score": urgency,
            "risk_level": risk,
            "alerts_p1": p1,
            "alerts_p2": p2,
            "zones_hot": zs["hot"],
            "zones_warm": zs["warm"],
            "zones_comfort": zs["comfort"],
            "zones_cold": zs["cold"],
            "zones_total": total_zones,
            "zones_auto": auto_zones,
            "zones_maintenance": maintenance_zones,
            "avg_temperature": round(avg_temp, 1) if avg_temp is not None else None,
            "binding_conflicts": conflicts,
            "actions_in_progress": actions,
        })

    results.sort(key=lambda x: x["urgency_score"], reverse=True)
    return results


@router.get("/kpis")
async def portfolio_kpis(
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """KPIs globais para o strip do centro de comando."""
    total_stores = await db.scalar(
        select(func.count(Store.id)).where(Store.active == True)
    ) or 0

    stores_at_risk = await db.scalar(
        select(func.count(distinct(StoreSector.store_id)))
        .join(Device, Device.sector_id == StoreSector.id)
        .join(Alert, Alert.device_id == Device.id)
        .where(Alert.status == "OPEN", Alert.severity.in_(["P1", "P2"]))
    ) or 0

    binding_conflicts = await db.scalar(
        select(func.count(CustomZoneDevice.device_id))
        .where(CustomZoneDevice.binding_mode == "conflict_overlap")
    ) or 0

    cutoff = datetime.utcnow() - timedelta(minutes=30)
    actions_in_progress = await db.scalar(
        select(func.count(ZoneAction.id))
        .where(
            ZoneAction.status == "pending_verification",
            ZoneAction.created_at >= cutoff,
        )
    ) or 0

    open_p1 = await db.scalar(
        select(func.count(Alert.id)).where(Alert.status == "OPEN", Alert.severity == "P1")
    ) or 0

    open_p2 = await db.scalar(
        select(func.count(Alert.id)).where(Alert.status == "OPEN", Alert.severity == "P2")
    ) or 0

    return {
        "total_stores": total_stores,
        "stores_at_risk": stores_at_risk,
        "binding_conflicts": binding_conflicts,
        "actions_in_progress": actions_in_progress,
        "open_p1": open_p1,
        "open_p2": open_p2,
    }
