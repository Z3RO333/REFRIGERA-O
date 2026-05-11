import asyncio
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings
from app.brise.token_manager import token_manager
from app.brise.schemas import BriseVariables, BriseParameters, BriseConfig, BriseSchedule

class BriseAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message

class BriseClient:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_polls)

    async def _get_headers(self) -> dict:
        token = await token_manager.get_token()
        return {"Authorization": f"Bearer {token}"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
    )
    async def _request(self, method: str, path: str, **kwargs) -> dict | None:
        async with self._semaphore:
            headers = await self._get_headers()
            async with httpx.AsyncClient(verify=settings.brise_verify_tls, timeout=20) as client:
                resp = await client.request(
                    method,
                    f"{settings.brise_base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
                if resp.status_code == 204:
                    return None
                if resp.status_code in (401, 403):
                    raise BriseAPIError(resp.status_code, "Auth error")
                resp.raise_for_status()
                return resp.json()

    async def get_variables(self, device_id: str) -> BriseVariables | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/variables")
            return BriseVariables(**data) if data else None
        except Exception:
            return None

    async def get_parameters(self, device_id: str) -> BriseParameters | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/parameters")
            return BriseParameters(**data) if data else None
        except Exception:
            return None

    async def get_configs(self, device_id: str) -> BriseConfig | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/configs")
            return BriseConfig(**data) if data else None
        except Exception:
            return None

    async def put_parameters(self, device_id: str, params: dict) -> bool:
        try:
            await self._request("PUT", f"/device/{device_id}/parameters", json=params)
            return True
        except Exception:
            return False

    async def get_schedules(self, device_id: str) -> list[BriseSchedule]:
        try:
            data = await self._request("GET", f"/device/{device_id}/schedules")
            if not data:
                return []
            return [BriseSchedule(**s) for s in data.get("schedules", [])]
        except Exception:
            return []

    async def get_user_devices(self) -> list:
        try:
            data = await self._request("GET", "/user/devices")
            return data.get("devices", []) if data else []
        except Exception:
            return []

brise_client = BriseClient()
