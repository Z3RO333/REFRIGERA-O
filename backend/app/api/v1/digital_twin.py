import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.digital_twin import compute_store_twin, compute_zone_twin
from app.services.zone_controller import ZONES, _load_all_custom_zones

router = APIRouter()


@router.get("/stores/{store_id}")
async def store_digital_twin(
    store_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Retorna o digital twin operacional de todas as zonas da loja."""
    return await compute_store_twin(store_id, db)


@router.get("/stores/{store_id}/zones/{zone_key}")
async def zone_digital_twin(
    store_id: uuid.UUID,
    zone_key: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Retorna o digital twin de uma zona específica."""
    zone = ZONES.get(zone_key)
    if not zone:
        custom_zones = await _load_all_custom_zones(db)
        from app.models.custom_zone import CustomZone
        exists = await db.execute(
            select(CustomZone.zone_key).where(
                CustomZone.store_id == store_id,
                CustomZone.zone_key == zone_key,
            )
        )
        if exists.scalar_one_or_none():
            zone = custom_zones.get(zone_key)
    if not zone:
        raise HTTPException(status_code=404, detail="Zona não encontrada")
    return await compute_zone_twin(store_id, zone, db)
