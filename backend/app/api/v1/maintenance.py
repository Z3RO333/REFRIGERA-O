from collections import defaultdict
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.device import Device, DeviceStatusLatest
from app.models.alert import Alert
from app.models.store import StoreSector, Store
from app.rules.maintenance_scorer import compute_maintenance_score, maintenance_reasons

router = APIRouter()

@router.get("/ranking")
async def get_maintenance_ranking(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device, DeviceStatusLatest, StoreSector, Store)
        .outerjoin(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
        .outerjoin(StoreSector, Device.sector_id == StoreSector.id)
        .outerjoin(Store, StoreSector.store_id == Store.id)
        .where(Device.active == True)
    )
    rows = result.all()
    since_30d = datetime.utcnow() - timedelta(days=30)

    device_ids = [device.id for device, _, _, _ in rows]
    alerts_bulk = await db.execute(
        select(Alert.device_id, Alert.severity)
        .where(Alert.device_id.in_(device_ids), Alert.opened_at >= since_30d)
    )
    alerts_by_device: dict = defaultdict(list)
    for row in alerts_bulk.all():
        alerts_by_device[row.device_id].append({"severity": row.severity})

    ranking = []
    for device, status, sector, store in rows:
        alerts = alerts_by_device.get(device.id, [])
        eff = status.efficiency_score if status and status.efficiency_score else None

        # Horas reais de operação vindas do hodômetro Brise
        on_min = status.accumulated_on_minutes if status else None
        hours_on_lifetime = round(on_min / 60, 1) if on_min is not None else 0.0

        # Horas na janela de 30 dias: se não temos histórico suficiente, estimamos
        # pelo uptime médio (ON/total * 720h do mês)
        total_min = (on_min or 0) + (status.accumulated_off_minutes or 0) if status else 0
        uptime_ratio = (on_min / total_min) if total_min > 0 and on_min else 0.8
        hours_on_30d = uptime_ratio * 720

        score = compute_maintenance_score(
            alerts_30d=alerts,
            hours_in_warning_critical=len([a for a in alerts if a["severity"] in ("P1", "P2")]) * 0.5,
            hours_total_on=hours_on_lifetime,
            avg_efficiency_7d=eff,
            hours_on_30d=hours_on_30d,
            last_maintenance=device.last_maintenance,
        )
        reasons = maintenance_reasons(
            hours_total_on=hours_on_lifetime,
            last_maintenance=device.last_maintenance,
            avg_efficiency=eff,
            alerts_30d=alerts,
        )

        off_min = status.accumulated_off_minutes if status else None
        total_min_val = (on_min or 0) + (off_min or 0)
        uptime_pct = round((on_min / total_min_val) * 100, 1) if total_min_val > 0 and on_min else None

        ranking.append({
            "device_id": str(device.id),
            "device_name": device.name,
            "store_name": store.name if store else None,
            "sector_name": sector.name if sector else None,
            "btu": device.btu,
            "dnd": device.dnd,
            "score": score,
            "status": status.status_classification if status else "SEM_LEITURA",
            "efficiency_score": eff,
            "alerts_30d": len(alerts),
            "last_maintenance": device.last_maintenance.isoformat() if device.last_maintenance else None,
            "hours_of_operation": hours_on_lifetime,
            "uptime_pct": uptime_pct,
            "reasons": reasons,
            "recommended_action": "Manutenção corretiva urgente" if score > 70 else "Verificação preventiva",
        })
    ranking.sort(key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(ranking):
        item["rank"] = i + 1
    return {"ranking": ranking}
