"""
Aplica a primeira planta 2D da Matriz/Escritório ao 1º andar.

Este script não posiciona aparelhos automaticamente. Ele limpa posições
estimadas do 1º andar para que a operação cadastre os pontos manualmente
pela tela do mapa.

Uso:
  cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO"
  backend/.venv/bin/python scripts/apply_matriz_floor1_map.py
"""
import asyncio
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
os.chdir(os.path.join(ROOT, "backend"))
sys.path.insert(0, ".")

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

FLOOR_PLAN_URL = "/floorplans/matriz-escritorio-area-convivencia.png"


async def main() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            UPDATE stores
            SET name = 'Escritório Matriz', updated_at = NOW()
            WHERE code = 'MATRIZ'
        """))

        await session.execute(text("""
            UPDATE store_sectors
            SET floor_plan_url = :floor_plan_url
            WHERE store_id = (SELECT id FROM stores WHERE code = 'MATRIZ')
              AND floor = 1
        """), {"floor_plan_url": FLOOR_PLAN_URL})

        await session.execute(text("""
            UPDATE devices d
            SET position_x = NULL,
                position_y = NULL,
                updated_at = NOW()
            FROM store_sectors ss, stores st
            WHERE d.sector_id = ss.id
              AND ss.store_id = st.id
              AND st.code = 'MATRIZ'
              AND ss.floor = 1
              AND d.active = TRUE
        """))

        await session.commit()

    print("Planta do 1º andar aplicada à Matriz; posições dos aparelhos limpas.")


if __name__ == "__main__":
    asyncio.run(main())
