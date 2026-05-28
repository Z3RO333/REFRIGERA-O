"""
store_epochs — fencing tokens monotónicos por loja.

Cada vez que o planeador toma um snapshot, obtém o epoch atual da loja.
Antes de executar um plano, verifica se o epoch ainda é o mesmo; se a loja
sofreu reset ou intervenção manual entre o snapshot e a execução, o plano
é rejeitado como antigo (stale plan protection).

Uso típico:
    # No início do ciclo de planeamento:
    epoch = await get_epoch(store_id, session)

    # Após calcular o plano, antes de executar:
    if not await epoch_still_valid(store_id, epoch, session):
        raise StalePlanError("Epoch mudou — plano descartado")

    # Ao registar intervenção manual ou reinício de zona:
    await bump_epoch(store_id, session)
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class StalePlanError(RuntimeError):
    """Lançado quando o epoch mudou desde que o plano foi calculado."""


async def get_epoch(store_id: uuid.UUID, session: AsyncSession) -> int:
    """Retorna o epoch atual da loja (0 se ainda não existir)."""
    result = await session.execute(
        text("SELECT epoch FROM store_epochs WHERE store_id = :sid"),
        {"sid": store_id},
    )
    row = result.one_or_none()
    return int(row[0]) if row else 0


async def bump_epoch(store_id: uuid.UUID, session: AsyncSession) -> int:
    """Incrementa o epoch e retorna o novo valor. Cria o registo se necessário."""
    result = await session.execute(
        text("""
            INSERT INTO store_epochs (store_id, epoch, updated_at)
            VALUES (:sid, 1, now())
            ON CONFLICT (store_id) DO UPDATE
              SET epoch      = store_epochs.epoch + 1,
                  updated_at = now()
            RETURNING epoch
        """),
        {"sid": store_id},
    )
    await session.commit()
    return int(result.scalar_one())


async def epoch_still_valid(
    store_id: uuid.UUID,
    expected: int,
    session: AsyncSession,
) -> bool:
    """Retorna True se o epoch actual da loja é igual ao esperado."""
    current = await get_epoch(store_id, session)
    return current == expected


async def get_all_epochs(session: AsyncSession) -> dict[uuid.UUID, int]:
    """Carrega todos os epochs num único SELECT para uso no batch planner."""
    result = await session.execute(
        text("SELECT store_id, epoch FROM store_epochs")
    )
    return {row[0]: int(row[1]) for row in result.all()}
