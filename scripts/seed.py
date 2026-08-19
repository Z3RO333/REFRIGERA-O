"""
Script de seed inicial para ambiente local.

Variáveis obrigatórias:
- SEED_ADMIN_EMAIL
- SEED_ADMIN_PASSWORD

Uso:
  SEED_ADMIN_EMAIL=admin@example.com SEED_ADMIN_PASSWORD='use-a-strong-password' python scripts/seed.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

async def main():
    admin_email = os.getenv("SEED_ADMIN_EMAIL")
    admin_password = os.getenv("SEED_ADMIN_PASSWORD")

    if not admin_email or not admin_password:
        raise RuntimeError(
            "Defina SEED_ADMIN_EMAIL e SEED_ADMIN_PASSWORD antes de executar o seed."
        )
    if len(admin_password) < 12:
        raise RuntimeError("SEED_ADMIN_PASSWORD deve ter pelo menos 12 caracteres.")

    os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
    sys.path.insert(0, ".")

    from app.db.session import engine, Base, AsyncSessionLocal
    import app.models
    from app.models.store import Store, StoreSector
    from app.models.user import User
    import bcrypt

    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select

        existing = await session.execute(select(User).where(User.email == admin_email))
        if not existing.scalar_one_or_none():
            admin = User(
                name="Administrador",
                email=admin_email,
                hashed_password=hash_password(admin_password),
                role="ADMIN",
            )
            session.add(admin)
            print(f"✓ Usuário admin criado: {admin_email}")

        existing_store = await session.execute(select(Store).where(Store.code == "DEMO"))
        if not existing_store.scalar_one_or_none():
            store = Store(
                name="Unidade de Demonstração",
                code="DEMO",
                city="Manaus",
                state="AM",
                timezone=-4,
            )
            session.add(store)
            await session.flush()

            setores = [
                StoreSector(store_id=store.id, name="Setor A", floor=1),
                StoreSector(store_id=store.id, name="Setor B", floor=1),
                StoreSector(store_id=store.id, name="Setor C", floor=1, is_critical=True),
            ]
            for setor in setores:
                session.add(setor)
            print(f"✓ Unidade de demonstração criada com {len(setores)} setores")

        await session.commit()

    print("\n✅ Seed concluído!")

if __name__ == "__main__":
    asyncio.run(main())
