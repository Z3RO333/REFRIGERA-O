import asyncio
import sys
import os
import uuid

# Ajusta path para carregar app
backend_dir = "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
os.chdir(backend_dir)
sys.path.insert(0, backend_dir)

from app.db.session import AsyncSessionLocal
from app.models.store import Store, StoreSector
from app.models.device import Device
from sqlalchemy import select, update

async def reorganize():
    async with AsyncSessionLocal() as session:
        # 1. Garantir as Lojas
        stores_data = [
            {"name": "CD Manaus", "code": "CDMANAUS"},
            {"name": "Matriz", "code": "MATRIZ"},
            {"name": "Bemol Farma Flores", "code": "FARMA_FLORES"}
        ]

        store_map = {}
        for s in stores_data:
            res = await session.execute(select(Store).where(Store.code == s["code"]))
            obj = res.scalar_one_or_none()
            if not obj:
                # Se encontrar a loja antiga, vamos renomear para manter o histórico
                res_old = await session.execute(select(Store).where(Store.code == "FARMA_TARUMA"))
                old_obj = res_old.scalar_one_or_none()
                if old_obj and s["code"] == "FARMA_FLORES":
                    old_obj.name = s["name"]
                    old_obj.code = s["code"]
                    obj = old_obj
                    print(f"Renomeando loja antiga para: {obj.name}")
                else:
                    obj = Store(name=s["name"], code=s["code"], city="Manaus", state="AM", timezone=-4)
                    session.add(obj)
                    await session.flush()
                    print(f"Loja criada: {obj.name}")
            store_map[s["code"]] = obj
            print(f"Loja: {obj.name} (ID: {obj.id})")

        # 2. Buscar todos os dispositivos e setores
        res_devs = await session.execute(select(Device))
        devices = res_devs.scalars().all()

        # 3. Processar cada dispositivo
        for dev in devices:
            name = dev.name.lower()
            target_store_code = "MATRIZ" # Default

            # Regras de Negócio
            if "montagem" in name:
                target_store_code = "CDMANAUS"
            elif "rh" in name:
                # Exceções solicitadas: RH PIABA e RH AR 22 são MATRIZ
                if "piaba" in name or "ar 22" in name:
                    target_store_code = "MATRIZ"
                else:
                    target_store_code = "CDMANAUS"
            elif "brise" in name:
                target_store_code = "FARMA_FLORES"

            target_store = store_map[target_store_code]

            # Verificar o setor atual do device
            sector = await session.get(StoreSector, dev.sector_id)
            if sector:
                if sector.store_id != target_store.id:
                    # Precisamos mover o setor para a loja certa ou criar um setor igual na loja certa
                    # Para simplificar e evitar bagunça, vamos criar/reutilizar o setor na loja alvo
                    res_s = await session.execute(
                        select(StoreSector).where(
                            StoreSector.store_id == target_store.id,
                            StoreSector.name == sector.name
                        )
                    )
                    new_sector = res_s.scalar_one_or_none()
                    if not new_sector:
                        new_sector = StoreSector(
                            store_id=target_store.id,
                            name=sector.name,
                            floor=sector.floor,
                            is_critical=sector.is_critical
                        )
                        session.add(new_sector)
                        await session.flush()

                    dev.sector_id = new_sector.id
                    print(f"Movendo device '{dev.name}' para loja '{target_store.name}' no setor '{new_sector.name}'")

        await session.commit()
        print("\nReorganização concluída com sucesso!")

if __name__ == "__main__":
    asyncio.run(reorganize())
