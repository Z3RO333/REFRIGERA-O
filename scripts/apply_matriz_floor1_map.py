"""
Aplica a primeira planta 2D da Matriz/Escritório ao 1º andar.

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

SECTOR_POSITIONS = {
    "Alimentos": (170.0, 205.0),
    "Auditório": (245.0, 170.0),
    "Bemol Online": (255.0, 455.0),
    "CAB": (520.0, 360.0),
    "Celulares": (535.0, 205.0),
    "Comercial": (615.0, 370.0),
    "Conta Bemol": (565.0, 250.0),
    "Contabilidade": (465.0, 455.0),
    "Convivência": (315.0, 125.0),
    "Eletrodomésticos": (680.0, 375.0),
    "Farmácia": (575.0, 195.0),
    "Geral": (395.0, 285.0),
    "Gestão de Risco": (645.0, 315.0),
    "Informática": (565.0, 325.0),
    "Marketing": (345.0, 225.0),
    "Marketplace": (610.0, 455.0),
    "Recepção": (430.0, 320.0),
    "Recursos Humanos": (300.0, 390.0),
    "Refeitório": (375.0, 120.0),
    "SAC": (225.0, 300.0),
    "Salas de Descanso": (315.0, 170.0),
    "Televendas": (250.0, 505.0),
    "Tesouraria": (425.0, 350.0),
    "Têxtil": (675.0, 480.0),
}


async def main() -> None:
    values_sql = ",\n".join(
        f"('{name}', {x}, {y})" for name, (x, y) in SECTOR_POSITIONS.items()
    )

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

        await session.execute(text(f"""
            WITH sector_positions(name, base_x, base_y) AS (
              VALUES
                {values_sql}
            ), ranked AS (
              SELECT
                d.id,
                sp.base_x + (((ROW_NUMBER() OVER (PARTITION BY ss.name ORDER BY d.name)) - 1) % 4) * 16 - 24 AS x,
                sp.base_y + FLOOR(((ROW_NUMBER() OVER (PARTITION BY ss.name ORDER BY d.name)) - 1) / 4) * 16 - 8 AS y
              FROM devices d
              JOIN store_sectors ss ON ss.id = d.sector_id
              JOIN stores st ON st.id = ss.store_id
              JOIN sector_positions sp ON sp.name = ss.name
              WHERE st.code = 'MATRIZ'
                AND ss.floor = 1
                AND d.active = TRUE
            )
            UPDATE devices d
            SET position_x = ranked.x,
                position_y = ranked.y,
                updated_at = NOW()
            FROM ranked
            WHERE d.id = ranked.id
        """))

        await session.commit()

    print("Planta do 1º andar aplicada à Matriz.")


if __name__ == "__main__":
    asyncio.run(main())
