import asyncio
import time
import httpx
from app.config import settings
from app.cache.redis_client import redis_client

REDIS_TOKEN_KEY = "brise:token:access"
REDIS_REFRESH_KEY = "brise:token:refresh"
REDIS_EXPIRY_KEY = "brise:token:expiry"


class BriseTokenManager:
    """
    Fluxo de autenticação Brise (dois passos descobertos via JS do reqwithlogin):
      1. POST /request-authkey  {username, password, grant_type:"authorization"}
         → {code: "..."}
      2. POST /exchange-code  {grant_type:"authorization_code", code, client_id, client_secret, redirect_uri}
         → {access_token, refresh_token, expires_in}

    O token expira em ~6 meses (15768000s), mas renovamos via refresh_token
    quando estiver a menos de 5 minutos do vencimento.
    """

    def __init__(self):
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        token = await redis_client.get(REDIS_TOKEN_KEY)
        expiry = await redis_client.get(REDIS_EXPIRY_KEY)
        if token and expiry and float(expiry) > time.time() + 300:
            return token
        return await self._acquire_token()

    async def _acquire_token(self) -> str:
        async with self._lock:
            # Double-check dentro do lock local (protege workers no mesmo processo)
            token = await redis_client.get(REDIS_TOKEN_KEY)
            expiry = await redis_client.get(REDIS_EXPIRY_KEY)
            if token and expiry and float(expiry) > time.time() + 300:
                return token

            # Lock distribuído protege múltiplos processos/workers
            acquired = await redis_client.acquire_lock("brise:token:refresh_lock", ttl=30)
            if not acquired:
                # Outro processo já está renovando; aguarda e retorna o token novo
                await asyncio.sleep(3)
                token = await redis_client.get(REDIS_TOKEN_KEY)
                if token:
                    return token

            try:
                refresh = await redis_client.get(REDIS_REFRESH_KEY)
                if refresh:
                    try:
                        return await self._exchange_refresh(refresh)
                    except Exception:
                        pass
                return await self._full_auth()
            finally:
                if acquired:
                    await redis_client.release_lock("brise:token:refresh_lock")

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
        return access


token_manager = BriseTokenManager()
