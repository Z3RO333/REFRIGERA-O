"""
Importa automaticamente todos os devices da conta Brise para o banco do HVAC Monitor.
Detecta o setor de cada device pelo padrão do nome e cria uma loja "Bemol HQ".

Uso:
  cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
  .venv/bin/python ../scripts/import_brise_devices.py
"""
import asyncio
import sys
import os

os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, ".")

import httpx

BASE = "https://brisev2.agst.com.br:8090/api/v2"
REDIRECT_URI = "https://nada.com"

# ── Mapeamento nome → setor ──────────────────────────────────────────────────
# Cada entry: (prefixos/substrings no nome em minúsculo, nome do setor, is_critical)
SECTOR_RULES = [
    (["farma"],              "Farmácia",                True),
    (["sac"],                "SAC",                     False),
    (["televendas"],         "Televendas",               False),
    (["comercial"],          "Comercial",                False),
    (["contabilidade"],      "Contabilidade",            False),
    (["tesouraria"],         "Tesouraria",               False),
    (["marketing"],          "Marketing",                False),
    (["marketplace"],        "Marketplace",              False),
    (["bemol online"],       "Bemol Online",             False),
    (["conta bemol"],        "Conta Bemol",              False),
    (["gestao risco", "gestao de risco"], "Gestão de Risco", False),
    (["rh "],                "Recursos Humanos",         False),
    (["recepcao", "recepção"], "Recepção",               False),
    (["convivencia", "convivência"], "Convivência",      False),
    (["refeit"],             "Refeitório",               False),
    (["auditorio", "auditório", "corredorauditorio"], "Auditório", False),
    (["cab "],               "CAB",                     False),
    (["montagem"],           "Montagem",                 False),
    (["sl descanso", "sala descanso"], "Salas de Descanso", False),
    (["ar "],                "Geral",                    False),
    (["brise entrada", "brise"],        "Geral",         False),
]

def detect_sector(name: str) -> tuple[str, bool]:
    low = name.lower()
    for patterns, sector, critical in SECTOR_RULES:
        for p in patterns:
            if p in low:
                return sector, critical
    return "Geral", False


async def get_token(
    client: httpx.AsyncClient,
    username: str,
    password: str,
    client_id: str,
    client_secret: str,
) -> str:
    r1 = await client.post(f"{BASE}/request-authkey", json={
        "username": username, "password": password, "grant_type": "authorization"
    })
    r1.raise_for_status()
    code = r1.json()["code"]
    r2 = await client.post(f"{BASE}/exchange-code", json={
        "grant_type": "authorization_code", "code": code,
        "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    })
    r2.raise_for_status()
    return r2.json()["access_token"]


async def main():
    from app.config import settings
    from app.db.session import engine, Base, AsyncSessionLocal
    import app.models
    from app.models.store import Store, StoreSector
    from app.models.device import Device
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with httpx.AsyncClient(verify=False, timeout=20) as http:
        print("🔑 Autenticando na Brise API...")
        token = await get_token(
            http,
            settings.brise_username,
            settings.brise_password,
            settings.brise_client_id,
            settings.brise_client_secret,
        )
        headers = {"Authorization": f"Bearer {token}"}

        print("📋 Buscando lista de devices...")
        r = await http.get(f"{BASE}/user/devices", headers=headers)
        r.raise_for_status()
        brise_devices = r.json()["devices"]
        print(f"   {len(brise_devices)} devices encontrados\n")

        # Busca configs de todos em paralelo
        sem = asyncio.Semaphore(15)

        async def fetch_cfg(d):
            async with sem:
                r = await http.get(f"{BASE}/device/{d['deviceId']}/configs", headers=headers)
                if r.status_code == 200:
                    return d["deviceId"], r.json()
                return d["deviceId"], None

        print("⚙️  Buscando configurações de todos os devices...")
        configs = dict(await asyncio.gather(*[fetch_cfg(d) for d in brise_devices]))

    # Agrupa devices por setor detectado
    sector_map: dict[str, tuple[str, bool, list]] = {}  # sector_name → (name, critical, [device_ids])
    for d in brise_devices:
        did = d["deviceId"]
        cfg = configs.get(did)
        if cfg:
            name = cfg.get("name", f"Device {did}")
            sector, critical = detect_sector(name)
        else:
            name = f"Device {did}"
            sector, critical = "Offline", False

        if sector not in sector_map:
            sector_map[sector] = (sector, critical, [])
        sector_map[sector][2].append((did, name, cfg))

    print(f"\n🏢 Setores detectados ({len(sector_map)}):")
    for sname, (_, crit, devs) in sorted(sector_map.items()):
        crit_tag = " ⚠️ CRÍTICO" if crit else ""
        print(f"   {sname:30s} — {len(devs)} devices{crit_tag}")

    print()

    async with AsyncSessionLocal() as session:
        # Garante as lojas principais
        stores_config = [
            {"name": "CD Manaus", "code": "CDMANAUS"},
            {"name": "Matriz", "code": "MATRIZ"},
            {"name": "Bemol Farma Flores", "code": "FARMA_FLORES"}
        ]
        store_db = {}
        for s_cfg in stores_config:
            res = await session.execute(select(Store).where(Store.code == s_cfg["code"]))
            store = res.scalar_one_or_none()
            if not store:
                store = Store(name=s_cfg["name"], code=s_cfg["code"], city="Manaus", state="AM", timezone=-4)
                session.add(store)
                await session.flush()
                print(f"✓ Loja criada: {store.name}")
            store_db[s_cfg["code"]] = store

        # Cria/reutiliza setores vinculando à loja correta
        # Nota: Como um setor pode existir em várias lojas, o mapeamento agora é (store_id, sector_name)
        sector_db_map: dict[tuple[str, str], StoreSector] = {}

        # Importa devices
        created = skipped = offline_count = 0
        for sname, (_, critical, devs) in sector_map.items():
            for (did, name, cfg) in devs:
                # Decidir a loja pelo nome do device
                lname = name.lower()
                if "montagem" in lname:
                    target_store = store_db["CDMANAUS"]
                elif "rh" in lname:
                    # Exceções: RH PIABA e RH AR 22 são MATRIZ
                    if "piaba" in lname or "ar 22" in lname:
                        target_store = store_db["MATRIZ"]
                    else:
                        target_store = store_db["CDMANAUS"]
                elif "brise" in lname:
                    target_store = store_db["FARMA_FLORES"]
                else:
                    target_store = store_db["MATRIZ"]

                # Garantir setor na loja correta
                s_key = (target_store.id, sname)
                if s_key not in sector_db_map:
                    res = await session.execute(
                        select(StoreSector).where(StoreSector.store_id == target_store.id, StoreSector.name == sname)
                    )
                    sector_obj = res.scalar_one_or_none()
                    if not sector_obj:
                        sector_obj = StoreSector(store_id=target_store.id, name=sname, floor=1, is_critical=critical)
                        session.add(sector_obj)
                        await session.flush()
                    sector_db_map[s_key] = sector_obj

                sector_obj = sector_db_map[s_key]

                res = await session.execute(
                    select(Device).where(Device.brise_device_id == str(did))
                )
                if res.scalar_one_or_none():
                    skipped += 1
                    continue

                if cfg is None:
                    offline_count += 1
                    btu = 9000
                else:
                    btu = cfg.get("btu") or 9000

                device = Device(
                    brise_device_id=str(did),
                    name=name,
                    sector_id=sector_obj.id,
                    btu=btu,
                    is_critical_environment=critical,
                    active=True,
                )
                session.add(device)
                created += 1

        await session.commit()

    print(f"\n✅ Importação concluída!")
    print(f"   Criados:   {created}")
    print(f"   Ignorados (já existiam): {skipped}")
    print(f"   Offline (sem config):    {offline_count}")
    print(f"\n   O polling vai iniciar automaticamente na próxima execução do backend.")

if __name__ == "__main__":
    asyncio.run(main())
