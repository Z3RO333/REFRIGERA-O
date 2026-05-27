import asyncio
import logging
import time
import httpx
from sqlalchemy import text
from app.config import settings
from app.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

REDIS_TOKEN_KEY = "brise:token:access"
REDIS_REFRESH_KEY = "brise:token:refresh"
REDIS_EXPIRY_KEY = "brise:token:expiry"


class BriseTokenManager:
    """
    Fluxo de autenticação Brise (dois passos):
      1. POST /request-authkey  {username, password, grant_type:"authorization"}
         → {code: "..."}
      2. POST /exchange-code  {grant_type:"authorization_code", code, client_id, client_secret, redirect_uri}
         → {access_token, refresh_token, expires_in}

    Persistência dupla: Redis (cache rápido) + PostgreSQL (sobrevive restart).
    """

    def __init__(self):
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        token = await redis_client.get(REDIS_TOKEN_KEY)
        expiry = await redis_client.get(REDIS_EXPIRY_KEY)
        if token and expiry and float(expiry) > time.time() + 300:
            return token
        # Redis vazio (restart do container) — tenta carregar do banco antes de re-autenticar
        await self._load_from_db_into_redis()
        token = await redis_client.get(REDIS_TOKEN_KEY)
        expiry = await redis_client.get(REDIS_EXPIRY_KEY)
        if token and expiry and float(expiry) > time.time() + 300:
            return token
        return await self._acquire_token()

    async def invalidate_token(self) -> None:
        """Força a expiração do token em cache (chamado após 401 do servidor)."""
        await redis_client.delete(REDIS_TOKEN_KEY)
        await redis_client.delete(REDIS_EXPIRY_KEY)
        await self._db_delete("brise:token:access")
        await self._db_delete("brise:token:expiry")
        logger.info("Brise token invalidado por resposta 401")

    async def _acquire_token(self) -> str:
        async with self._lock:
            # Double-check dentro do lock local (protege workers no mesmo processo)
            token = await redis_client.get(REDIS_TOKEN_KEY)
            expiry = await redis_client.get(REDIS_EXPIRY_KEY)
            if token and expiry and float(expiry) > time.time() + 300:
                return token

            # Lock distribuído protege múltiplos processos/workers
            lock_token = await redis_client.acquire_lock("brise:token:refresh_lock", ttl=30)
            if not lock_token:
                await asyncio.sleep(3)
                token = await redis_client.get(REDIS_TOKEN_KEY)
                if token:
                    return token

            try:
                refresh = await redis_client.get(REDIS_REFRESH_KEY)
                if refresh:
                    try:
                        token = await self._exchange_refresh(refresh)
                        logger.info("Brise token renovado via refresh_token")
                        return token
                    except Exception as exc:
                        logger.warning("Refresh token Brise falhou (%s), tentando auth completo", exc)
                token = await self._full_auth()
                logger.info("Brise token obtido via auth completo")
                return token
            finally:
                if lock_token:
                    await redis_client.release_lock("brise:token:refresh_lock", lock_token)

    async def _full_auth(self) -> str:
        async with httpx.AsyncClient(verify=settings.brise_verify_tls, timeout=30) as client:
            r1 = await client.post(
                settings.brise_authkey_url,
                json={
                    "username": settings.brise_username,
                    "password": settings.brise_password,
                    "grant_type": "authorization",
                },
            )
            r1.raise_for_status()
            code = r1.json()["code"]

            r2 = await client.post(
                settings.brise_token_url,
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.brise_client_id,
                    "client_secret": settings.brise_client_secret,
                    "redirect_uri": "https://nada.com",
                },
            )
            r2.raise_for_status()
            return await self._store_tokens(r2.json())

    async def _exchange_refresh(self, refresh_token: str) -> str:
        async with httpx.AsyncClient(verify=settings.brise_verify_tls, timeout=30) as client:
            r = await client.post(
                settings.brise_token_url,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": settings.brise_client_id,
                    "client_secret": settings.brise_client_secret,
                },
            )
            r.raise_for_status()
            return await self._store_tokens(r.json())

    async def _store_tokens(self, data: dict) -> str:
        access = data["access_token"]
        expires_in = data.get("expires_in", 15768000)
        refresh = data.get("refresh_token")
        expiry_ts = time.time() + expires_in
        ttl = max(expires_in - 300, 60)

        await redis_client.set(REDIS_TOKEN_KEY, access, ttl=ttl)
        await redis_client.set(REDIS_EXPIRY_KEY, str(expiry_ts), ttl=ttl)
        if refresh:
            await redis_client.set(REDIS_REFRESH_KEY, refresh, ttl=ttl + 86400)

        # persistência no banco — sobrevive ao restart do container
        await self._db_upsert("brise:token:access", access, expiry_ts)
        await self._db_upsert("brise:token:expiry", str(expiry_ts), expiry_ts)
        if refresh:
            await self._db_upsert("brise:token:refresh", refresh, expiry_ts + 86400)

        return access

    async def _load_from_db_into_redis(self) -> None:
        """Carrega tokens do banco para o Redis após restart do container."""
        try:
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                rows = await session.execute(
                    text("SELECT key, value, expires_at FROM brise_tokens WHERE key IN ('brise:token:access','brise:token:expiry','brise:token:refresh')")
                )
                data = {row.key: (row.value, row.expires_at) for row in rows}

            now = time.time()
            access_row = data.get("brise:token:access")
            expiry_row = data.get("brise:token:expiry")

            if not access_row or not expiry_row:
                return

            expiry_ts = float(expiry_row[0])
            if expiry_ts <= now + 300:
                return  # expirado — não vale restaurar

            ttl = int(expiry_ts - now - 300)
            await redis_client.set(REDIS_TOKEN_KEY, access_row[0], ttl=max(ttl, 60))
            await redis_client.set(REDIS_EXPIRY_KEY, expiry_row[0], ttl=max(ttl, 60))

            refresh_row = data.get("brise:token:refresh")
            if refresh_row:
                await redis_client.set(REDIS_REFRESH_KEY, refresh_row[0], ttl=max(ttl + 86400, 60))

            logger.info("Brise tokens restaurados do banco após restart (expira em %.0fh)", ttl / 3600)
        except Exception as exc:
            logger.warning("Não foi possível restaurar tokens Brise do banco: %s", exc)

    async def _db_upsert(self, key: str, value: str, expiry_ts: float) -> None:
        try:
            from app.db.session import AsyncSessionLocal
            import datetime
            expires_at = datetime.datetime.utcfromtimestamp(expiry_ts)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        "INSERT INTO brise_tokens (key, value, expires_at) VALUES (:k, :v, :e) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, expires_at = EXCLUDED.expires_at"
                    ),
                    {"k": key, "v": value, "e": expires_at},
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Falha ao persistir token Brise no banco (%s): %s", key, exc)

    async def _db_delete(self, key: str) -> None:
        try:
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                await session.execute(text("DELETE FROM brise_tokens WHERE key = :k"), {"k": key})
                await session.commit()
        except Exception as exc:
            logger.warning("Falha ao deletar token Brise do banco (%s): %s", key, exc)


token_manager = BriseTokenManager()
