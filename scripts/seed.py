"""
Script de seed inicial: cria usuário admin e uma loja de exemplo.
Uso: python scripts/seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

async def main():
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
    sys.path.insert(0, ".")

    from app.db.session import engine, Base, AsyncSessionLocal
    import app.models  # garante que todos os models estão registrados no metadata
    from app.models.store import Store, StoreSector
    from app.models.user import User
    import bcrypt

    def hash_password(p): return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        # Usuário admin padrão
        from sqlalchemy import select
        existing = await session.execute(select(User).where(User.email == "admin@bemol.com.br"))
        if not existing.scalar_one_or_none():
            admin = User(
                name="Administrador",
                email="admin@bemol.com.br",
                hashed_password=hash_password("admin123"),
                role="ADMIN",
            )
            session.add(admin)
            print("✓ Usuário admin criado: admin@bemol.com.br / admin123")

        # Loja de exemplo
        existing_store = await session.execute(select(Store).where(Store.code == "MATRIZ"))
        if not existing_store.scalar_one_or_none():
            store = Store(
                name="Escritório Matriz",
                code="MATRIZ",
                city="Manaus",
                state="AM",
                timezone=-4,
            )
            session.add(store)
            await session.flush()

            setores = [
                StoreSector(store_id=store.id, name="Eletrodomésticos", floor=1),
                StoreSector(store_id=store.id, name="Informática", floor=1),
                StoreSector(store_id=store.id, name="Têxtil", floor=1),
                StoreSector(store_id=store.id, name="Celulares", floor=1),
                StoreSector(store_id=store.id, name="Alimentos", floor=1, is_critical=True),
            ]
            for s in setores:
                session.add(s)
            print(f"✓ Escritório Matriz criado com {len(setores)} setores")

        await session.commit()
    print("\n✅ Seed concluído!")

if __name__ == "__main__":
    asyncio.run(main())
