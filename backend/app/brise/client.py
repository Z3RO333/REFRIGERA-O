import asyncio
import logging
import httpx
from tenacity import RetryError, retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from app.config import settings
from app.brise.token_manager import token_manager
from app.brise.schemas import BriseVariables, BriseParameters, BriseConfig, BriseSchedule

logger = logging.getLogger(__name__)


class BriseAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message

    def __str__(self) -> str:
        return f"BriseAPIError({self.status_code}): {self.message}"


class BriseClient:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_polls)
        self._client: httpx.AsyncClient | None = None

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=settings.brise_verify_tls,
            timeout=httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._build_client()
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get_headers(self) -> dict:
        token = await token_manager.get_token()
        return {"Authorization": f"Bearer {token}"}

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def _request(self, method: str, path: str, **kwargs) -> dict | None:
        async with self._semaphore:
            headers = await self._get_headers()
            try:
                resp = await self.client.request(
                    method,
                    f"{settings.brise_base_url}{path}",
                    headers=headers,
                    **kwargs,
                )
            except httpx.TransportError:
                raise  # tenacity vai capturar e fazer retry
            except httpx.HTTPError as exc:
                logger.warning("Brise HTTP error em %s %s: %s", method, path, exc)
                raise BriseAPIError(0, str(exc)) from exc

            if resp.status_code in (202, 204) or not resp.content:
                return None

            if resp.status_code == 401:
                # Token expirou no servidor; invalida cache e tenta reautenticar uma vez
                await token_manager.invalidate_token()
                new_headers = await self._get_headers()
                resp = await self.client.request(
                    method,
                    f"{settings.brise_base_url}{path}",
                    headers=new_headers,
                    **kwargs,
                )
                if resp.status_code == 401:
                    logger.error("Brise 401 persistente após reautenticação em %s %s", method, path)
                    raise BriseAPIError(401, "Unauthorized after token refresh")

            if resp.status_code == 403:
                logger.warning("Brise 403 Forbidden em %s %s", method, path)
                raise BriseAPIError(403, "Forbidden")

            resp.raise_for_status()
            return resp.json()

    async def get_variables(self, device_id: str) -> BriseVariables | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/variables")
            return BriseVariables(**data) if data else None
        except RetryError:
            raise
        except BriseAPIError as exc:
            logger.warning("get_variables(%s) falhou: %s", device_id, exc)
            return None
        except Exception as exc:
            logger.warning("get_variables(%s) erro inesperado: %s", device_id, exc)
            return None

    async def get_parameters(self, device_id: str) -> BriseParameters | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/parameters")
            return BriseParameters(**data) if data else None
        except BriseAPIError as exc:
            logger.warning("get_parameters(%s) falhou: %s", device_id, exc)
            return None
        except Exception as exc:
            logger.warning("get_parameters(%s) erro inesperado: %s", device_id, exc)
            return None

    async def get_configs(self, device_id: str) -> BriseConfig | None:
        try:
            data = await self._request("GET", f"/device/{device_id}/configs")
            return BriseConfig(**data) if data else None
        except BriseAPIError as exc:
            logger.warning("get_configs(%s) falhou: %s", device_id, exc)
            return None
        except Exception as exc:
            logger.warning("get_configs(%s) erro inesperado: %s", device_id, exc)
            return None

    async def put_parameters(self, device_id: str, params: dict) -> bool:
        try:
            await self._request("PUT", f"/device/{device_id}/parameters", json=params)
            return True
        except BriseAPIError as exc:
            logger.error("put_parameters(%s) falhou: %s", device_id, exc)
            return False
        except Exception as exc:
            logger.error("put_parameters(%s) erro inesperado: %s", device_id, exc)
            return False

    async def get_schedules(self, device_id: str) -> list[BriseSchedule]:
        try:
            data = await self._request("GET", f"/device/{device_id}/schedules")
            if not data:
                return []
            return [BriseSchedule(**s) for s in data.get("schedules", [])]
        except BriseAPIError as exc:
            logger.warning("get_schedules(%s) falhou: %s", device_id, exc)
            return []
        except Exception as exc:
            logger.warning("get_schedules(%s) erro inesperado: %s", device_id, exc)
            return []

    async def get_user_devices(self) -> list:
        try:
            data = await self._request("GET", "/user/devices")
            return data.get("devices", []) if data else []
        except BriseAPIError as exc:
            logger.warning("get_user_devices() falhou: %s", exc)
            return []
        except Exception as exc:
            logger.warning("get_user_devices() erro inesperado: %s", exc)
            return []


brise_client = BriseClient()
