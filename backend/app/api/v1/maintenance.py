from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.device import Device, DeviceStatusLatest
from app.models.alert import Alert
from app.models.store import StoreSector, Store
from app.rules.maintenance_scorer import compute_maintenance_score

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
    ranking = []
    for device, status, sector, store in rows:
        alerts_result = await db.execute(
            select(Alert.severity)
            .where(Alert.device_id == device.id, Alert.opened_at >= since_30d)
        )
        alerts = [{"severity": row.severity} for row in alerts_result.all()]
        eff = status.efficiency_score if status and status.efficiency_score else 0.8
        score = compute_maintenance_score(
            alerts_30d=alerts,
            hours_in_warning_critical=len([a for a in alerts if a["severity"] in ("P1", "P2")]) * 0.5,
            hours_total_on=720,
            avg_efficiency_7d=eff,
            hours_on_30d=600,
            last_maintenance=device.last_maintenance,
        )
        reasons = []
        if score > 70:
            reasons.append("Múltiplos alertas críticos recentes")
        if eff < 0.6:
            reasons.append("Baixa eficiência energética detectada")
        if not device.last_maintenance or (datetime.utcnow() - device.last_maintenance).days > 150:
            reasons.append("Manutenção preventiva vencida")
        ranking.append({
            "device_id": str(device.id),
            "device_name": device.name,
            "store_name": store.name if store else None,
            "sector_name": sector.name if sector else None,
            "btu": device.btu,
            "score": score,
            "status": status.status_classification if status else "SEM_LEITURA",
            "efficiency_score": eff,
            "alerts_30d": len(alerts),
            "last_maintenance": device.last_maintenance.isoformat() if device.last_maintenance else None,
            "reasons": reasons,
            "recommended_action": "Manutenção corretiva urgente" if score > 70 else "Verificação preventiva",
        })
    ranking.sort(key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(ranking):
        item["rank"] = i + 1
    return {"ranking": ranking}
