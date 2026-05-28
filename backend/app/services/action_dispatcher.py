"""
ActionDispatcher — circuit breaker Redis-backed para a Brise API.

Estados:
  CLOSED    → operação normal, comandos passam direto
  OPEN      → muitos erros recentes; bloqueia por OPEN_TIMEOUT_SECONDS
  HALF_OPEN → teste único: deixa um comando passar para verificar se a API voltou

Uso:
    from app.services.action_dispatcher import brise_dispatcher

    if not await brise_dispatcher.can_execute():
        raise RuntimeError("Brise API temporariamente bloqueada (circuit breaker OPEN)")
    try:
        ok = await brise_client.put_parameters(...)
        if ok:
            await brise_dispatcher.on_success()
        else:
            await brise_dispatcher.on_failure()
    except Exception:
        await brise_dispatcher.on_failure()
        raise
"""
from __future__ import annotations

import logging
import time
from enum import Enum

from app.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

# Quantas falhas dentro de FAILURE_WINDOW_SECONDS para abrir o circuito
FAILURE_THRESHOLD = 5
FAILURE_WINDOW_SECONDS = 120

# Tempo (s) que o circuito permanece OPEN antes de tentar HALF_OPEN
OPEN_TIMEOUT_SECONDS = 300

_CB_PREFIX = "dispatcher:cb"


class CBState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ActionDispatcher:
    """Circuit breaker Redis-backed para um endpoint externo (ex.: Brise API)."""

    def __init__(self, name: str = "brise") -> None:
        self._name = name
        self._state_key = f"{_CB_PREFIX}:{name}:state"
        self._failures_key = f"{_CB_PREFIX}:{name}:failures"
        self._open_at_key = f"{_CB_PREFIX}:{name}:open_at"

    # ── estado ────────────────────────────────────────────────────────────────

    async def state(self) -> CBState:
        raw = await redis_client.get(self._state_key)
        if raw is None:
            return CBState.CLOSED
        try:
            return CBState(raw)
        except ValueError:
            return CBState.CLOSED

    async def _set_state(self, state: CBState, ttl: int | None = None) -> None:
        await redis_client.set(self._state_key, state.value, ttl=ttl)

    # ── contagem de falhas ────────────────────────────────────────────────────

    async def _record_failure(self) -> int:
        """Incrementa contador de falhas atomicamente. Retorna novo total."""
        try:
            async with redis_client.client.pipeline(transaction=True) as pipe:
                await pipe.incr(self._failures_key)
                await pipe.expire(self._failures_key, FAILURE_WINDOW_SECONDS)
                results = await pipe.execute()
            return int(results[0])
        except Exception as exc:
            logger.warning("ActionDispatcher[%s]: erro ao contar falha no Redis: %s", self._name, exc)
            return 0

    async def _clear_failures(self) -> None:
        await redis_client.client.delete(self._failures_key)

    # ── interface pública ─────────────────────────────────────────────────────

    async def can_execute(self) -> bool:
        """Retorna True se o comando pode ser enviado agora."""
        current = await self.state()

        if current == CBState.CLOSED:
            return True

        if current == CBState.OPEN:
            open_at_raw = await redis_client.get(self._open_at_key)
            if open_at_raw is not None:
                elapsed = time.time() - float(open_at_raw)
                if elapsed >= OPEN_TIMEOUT_SECONDS:
                    logger.info("ActionDispatcher[%s]: OPEN → HALF_OPEN (elapsed=%.0fs)", self._name, elapsed)
                    await self._set_state(CBState.HALF_OPEN)
                    return True
            return False

        # HALF_OPEN: deixa exatamente um teste passar
        return True

    async def on_success(self) -> None:
        """Registrar sucesso — fecha o circuito."""
        current = await self.state()
        if current != CBState.CLOSED:
            logger.info("ActionDispatcher[%s]: %s → CLOSED (sucesso)", self._name, current)
        await self._clear_failures()
        await self._set_state(CBState.CLOSED)

    async def on_failure(self) -> None:
        """Registrar falha — abre o circuito se limite atingido."""
        failures = await self._record_failure()
        current = await self.state()

        if current == CBState.HALF_OPEN:
            logger.warning("ActionDispatcher[%s]: HALF_OPEN → OPEN (teste falhou)", self._name)
            await redis_client.set(self._open_at_key, str(time.time()))
            await self._set_state(CBState.OPEN, ttl=OPEN_TIMEOUT_SECONDS * 2)

        elif current == CBState.CLOSED and failures >= FAILURE_THRESHOLD:
            logger.warning(
                "ActionDispatcher[%s]: CLOSED → OPEN (%d falhas em %ds)",
                self._name, failures, FAILURE_WINDOW_SECONDS,
            )
            await redis_client.set(self._open_at_key, str(time.time()))
            await self._set_state(CBState.OPEN, ttl=OPEN_TIMEOUT_SECONDS * 2)

    async def status_dict(self) -> dict:
        """Retorna estado atual para endpoints de health/debug."""
        current = await self.state()
        open_at_raw = await redis_client.get(self._open_at_key)
        open_at = float(open_at_raw) if open_at_raw else None
        failures_raw = await redis_client.get(self._failures_key)
        failures = int(failures_raw) if failures_raw else 0
        return {
            "name": self._name,
            "state": current.value,
            "failure_count": failures,
            "failure_threshold": FAILURE_THRESHOLD,
            "open_timeout_seconds": OPEN_TIMEOUT_SECONDS,
            "open_at": open_at,
            "seconds_until_half_open": (
                max(0.0, OPEN_TIMEOUT_SECONDS - (time.time() - open_at))
                if open_at and current == CBState.OPEN else None
            ),
        }


# Instância global — usada pelo zone_controller e pode ser usada pelo brise_client
brise_dispatcher = ActionDispatcher("brise")
