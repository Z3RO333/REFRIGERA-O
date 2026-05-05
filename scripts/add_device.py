"""
Adiciona um dispositivo Brise ao sistema e o vincula a um setor.
Uso: python scripts/add_device.py

Edite as variáveis na seção CONFIG antes de executar.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── CONFIG ──────────────────────────────────────────────────────────────────
BRISE_DEVICE_ID = "100000"       # Número de série do dispositivo Brise
DEVICE_NAME     = "AC-01"        # Nome amigável
SECTOR_NAME     = "Informática"  # Nome do setor (deve existir no banco)
STORE_CODE      = "MATRIZ"       # Código da loja
BTU             = 12000          # Capacidade em BTU
IS_CRITICAL_ENV = False          # True para ambientes críticos (alimentos, etc.)
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
    sys.path.insert(0, ".")

    from app.db.session import engine, Base, AsyncSessionLocal
    from app.models.store import Store, StoreSector
    from app.models.device import Device
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        store_result = await session.execute(select(Store).where(Store.code == STORE_CODE))
        store = store_result.scalar_one_or_none()
        if not store:
            print(f"✗ Loja '{STORE_CODE}' não encontrada. Execute seed.py primeiro.")
            return

        sector_result = await session.execute(
            select(StoreSector).where(StoreSector.store_id == store.id, StoreSector.name == SECTOR_NAME)
        )
        sector = sector_result.scalar_one_or_none()
        if not sector:
            print(f"✗ Setor '{SECTOR_NAME}' não encontrado na loja '{STORE_CODE}'.")
            return

        existing = await session.execute(select(Device).where(Device.brise_device_id == BRISE_DEVICE_ID))
        if existing.scalar_one_or_none():
            print(f"✗ Dispositivo Brise ID '{BRISE_DEVICE_ID}' já cadastrado.")
            return

        device = Device(
            brise_device_id=BRISE_DEVICE_ID,
            name=DEVICE_NAME,
            sector_id=sector.id,
            btu=BTU,
            is_critical_environment=IS_CRITICAL_ENV,
        )
        session.add(device)
        await session.commit()
        print(f"✓ Dispositivo '{DEVICE_NAME}' (Brise ID: {BRISE_DEVICE_ID}) adicionado ao setor '{SECTOR_NAME}' da loja '{STORE_CODE}'.")

if __name__ == "__main__":
    asyncio.run(main())
