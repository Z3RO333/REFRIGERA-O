# Automação Contínua — Sem Limite Diário


> **Status atual (2026-05-25):** implementação aplicada. O limite diário 6/6 saiu do fluxo de bloqueio; `daily_count` permanece só como métrica. O controle roda a cada 5 min, há janela curta por device, timings `decision_ms/api_ms` em ações com decisão, IA paralelizada e painel sem card 6/6. A coluna legada `max_daily_adjustments` é tratada de forma compatível em migration somente se existir.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover o limite diário fixo de 6 automações por zona, substituir por proteções inteligentes por janela curta, reduzir latência do ciclo de controle de 15 min para 5 min, paralelizar análise da IA e atualizar o painel com indicadores operacionais reais.

**Architecture:** O `zone_controller` já é 100% determinístico — a IA (run_zone_analysis) roda em job separado no scheduler e nunca bloqueia controle. Os problemas são: (1) `_daily_count >= max_daily_adjustments` bloqueia a automação após 6 ações; (2) o scheduler dispara o zone_controller a cada **15 minutos**, causando latência alta na detecção de temperatura elevada; (3) o `analyze_anomalies` chama o LLM **sequencialmente** com timeout de 360s; (4) o frontend exibe `6/6` como se fosse cota de plano.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, APScheduler, Redis (via `redis_client`), httpx, pytest + pytest-asyncio (a adicionar), React/TypeScript.

---

## Mapa de arquivos

| Arquivo | O que muda |
|---|---|
| `backend/app/services/zone_controller.py` | Remove check diário; add window rate-limit por device; add timing por ciclo |
| `backend/app/models/zone.py` | Remove `max_daily_adjustments`; add `decision_ms` + `api_ms` em ZoneAction |
| `backend/app/db/migrations.py` | ADD COLUMN decision_ms, api_ms; mantém coluna legada max_daily_adjustments apenas se existir, sem drop em produção |
| `backend/app/polling/scheduler.py` | zone_controller: 15 min → 5 min; lock: 840 → 280 |
| `backend/app/ai/analyzer.py` | Semáforo 1 → 3; loop serial → gather; timeout LLM 360 → 30s |
| `backend/app/api/v1/zones.py` | Remove max_daily_adjustments do payload; add daily_count sem limite |
| `backend/app/schemas/zone.py` | Remove max_daily_adjustments |
| `backend/requirements.txt` | Add pytest, pytest-asyncio, pytest-mock |
| `backend/tests/conftest.py` | Criar: fixtures de DB, automação, zona |
| `backend/tests/test_zone_controller.py` | Criar: testes unitários determinísticos |
| `backend/tests/test_classifier.py` | Criar: testes de classify_status |
| `frontend/src/types/index.ts` | Remove max_daily_adjustments; add ai_status, last_analysis_at |
| `frontend/src/api/client.ts` | Remove max_daily_adjustments do tipo |
| `frontend/src/pages/ThermalComfortMap.tsx` | Substituir card 6/6 por métricas operacionais |
| `frontend/src/pages/ZoneControlPanel.tsx` | Remove "X/6 ajustes hoje" |
| `frontend/src/pages/DigitalTwinPage.tsx` | Remove "X/6 ajustes hoje" |

---

## Task 1 — Remover limite diário no backend (zone_controller)

**Files:**
- Modify: `backend/app/services/zone_controller.py`

- [ ] **Step 1.1 — Localizar o bloco de limite diário**

No arquivo `backend/app/services/zone_controller.py`, as linhas relevantes são:

```python
# Limite diário
today_count = await _daily_count(automation.store_id, zone.key, session)
if today_count >= automation.max_daily_adjustments:
    await _log_blocked(
        automation, zone, avg_temp,
        f"Limite diário de {automation.max_daily_adjustments} ajustes atingido",
        session,
    )
    return
```

- [ ] **Step 1.2 — Remover o bloco de limite diário**

Substituir o bloco acima (incluindo o comentário `# Limite diário`) por **nada** — simplesmente deletar as 8 linhas.

Após a remoção, a sequência deve ir direto de `# Falhas consecutivas` para a lógica de direção:

```python
        # Falhas consecutivas (≥3 → alerta manutenção)
        if await _consecutive_failures(automation.store_id, zone.key, session) >= 3:
            await _raise_zone_alert(automation, zone, avg_temp, session)
            return

        direction = "down" if status in ("WARM", "HOT", "CRITICAL") else "up"
```

- [ ] **Step 1.3 — Adicionar constantes de proteção por janela curta**

No topo do arquivo `zone_controller.py`, logo após `ZONE_COOLDOWN_SECONDS = 900`, adicionar:

```python
# Proteção por janela curta — evita rajadas sem bloquear o dia inteiro
DEVICE_WINDOW_SECONDS = 900      # janela de 15 min por device
DEVICE_WINDOW_MAX_CMDS = 4       # máximo de 4 comandos por device por janela
ZONE_WINDOW_SECONDS   = 900      # janela de 15 min por zona  (já coberto pelo cooldown)
```

- [ ] **Step 1.4 — Implementar `_device_window_ok`**

Adicionar a função abaixo logo depois da função `_daily_count` (que será removida no Task 5, por ora mantemos):

```python
async def _device_window_ok(device_id: uuid.UUID) -> bool:
    """Retorna True se o device pode receber mais um comando na janela de 15 min.
    Usa Redis INCR + EXPIRE para contagem atômica sem transação."""
    key = f"device:cmd_window:{device_id}"
    count = await redis_client.incr(key)
    if count == 1:
        await redis_client.expire(key, DEVICE_WINDOW_SECONDS)
    if count > DEVICE_WINDOW_MAX_CMDS:
        # Decrementar para não acumular indefinidamente
        await redis_client.client.decrby(key, 1)
        return False
    return True
```

- [ ] **Step 1.5 — Usar `_device_window_ok` antes de executar power_on**

Dentro do bloco `if automation.mode in ("auto", "semi"):` para power_on (por volta da linha 479), adicionar verificação **antes** de `acquire_lock`:

```python
            if automation.mode in ("auto", "semi"):
                # Proteção por janela curta (substitui limite diário)
                if not await _device_window_ok(power_device.device.id):
                    action_status = "blocked"
                    block_reason = (
                        f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                        f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                        f"{power_device.device.name}"
                    )
                elif not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                    return
                else:
                    ok = await _execute_power_on(power_device.device, power_params, session)
                    ...
```

> **Atenção:** o bloco acima precisa encapsular o fluxo existente de `acquire_lock` + `_execute_power_on`. Leia o trecho de 479 a 510 antes de editar para ajustar o if/else correto sem quebrar a lógica.

- [ ] **Step 1.6 — Usar `_device_window_ok` antes de executar setpoint**

Dentro do bloco de execução de setpoint (por volta de linha 587-602), adicionar antes de `acquire_lock`:

```python
            if automation.mode in ("auto", "semi"):
                if not await _device_window_ok(best_device.device.id):
                    await _log_blocked(
                        automation, zone, avg_temp,
                        f"Limite de {DEVICE_WINDOW_MAX_CMDS} comandos em "
                        f"{DEVICE_WINDOW_SECONDS // 60} min atingido para "
                        f"{best_device.device.name}",
                        session,
                    )
                    return
                if not await redis_client.acquire_lock(cooldown_key, ttl=ZONE_COOLDOWN_SECONDS):
                    return
```

- [ ] **Step 1.7 — Commit**

```bash
git add backend/app/services/zone_controller.py
git commit -m "feat: remove limite diário 6/6 e adiciona window rate-limit por device (15min/4cmds)"
```

---

## Task 2 — Timing de ciclo no ZoneAction

Adicionar métricas de latência ao model e ao controller para saber onde o ciclo está lento.

**Files:**
- Modify: `backend/app/models/zone.py`
- Modify: `backend/app/db/migrations.py`
- Modify: `backend/app/services/zone_controller.py`

- [ ] **Step 2.1 — Adicionar colunas de timing ao modelo ZoneAction**

Em `backend/app/models/zone.py`, na classe `ZoneAction`, adicionar após `verified_at`:

```python
    # Métricas de latência (ms)
    decision_ms: Mapped[int | None] = mapped_column(Integer)   # tempo total da decisão
    api_ms:      Mapped[int | None] = mapped_column(Integer)   # tempo da chamada à Brise API
```

- [ ] **Step 2.2 — Adicionar migration para as novas colunas**

Em `backend/app/db/migrations.py`, na lista `MIGRATIONS`, adicionar:

```python
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS decision_ms INTEGER",
    "ALTER TABLE zone_actions ADD COLUMN IF NOT EXISTS api_ms INTEGER",
```

- [ ] **Step 2.3 — Capturar timing na função `run_zone_controller`**

Em `zone_controller.py`, no início da função principal de execução de zona (a que chama `_get_zone_devices`), adicionar:

```python
import time

# No início do loop de cada zona:
_t0_decision = time.monotonic()
```

E ao criar o `ZoneAction` (power_on e setpoint), passar os campos:

```python
ZoneAction(
    ...
    decision_ms=int((time.monotonic() - _t0_decision) * 1000),
    api_ms=int(api_elapsed_ms),   # ver step 2.4
)
```

- [ ] **Step 2.4 — Medir tempo da chamada à Brise API**

Na função `_execute_power_on` e na função equivalente de setpoint (`_execute_setpoint`), envolver a chamada `brise_client.put_parameters` com medição:

```python
_t_api = time.monotonic()
ok = await brise_client.put_parameters(device.brise_device_id, payload)
api_elapsed_ms = int((time.monotonic() - _t_api) * 1000)
```

Retornar `api_elapsed_ms` junto com `ok`:

```python
async def _execute_power_on(...) -> tuple[bool, int]:
    ...
    return ok, api_elapsed_ms
```

Ajustar todos os call sites que atualmente recebem só `ok`.

- [ ] **Step 2.5 — Adicionar log de timing após cada ciclo de zona**

Ao final do processamento de cada zona em `run_zone_controller`, adicionar:

```python
logger.info(
    "Zone %s: ciclo completo em %dms (api: %dms)",
    zone.key,
    int((time.monotonic() - _t0_decision) * 1000),
    api_elapsed_ms if api_elapsed_ms else 0,
)
```

- [ ] **Step 2.6 — Commit**

```bash
git add backend/app/models/zone.py backend/app/db/migrations.py backend/app/services/zone_controller.py
git commit -m "feat: adiciona decision_ms e api_ms em ZoneAction para rastrear latência"
```

---

## Task 3 — Reduzir intervalo do zone_controller de 15 min para 5 min

**Files:**
- Modify: `backend/app/polling/scheduler.py`

- [ ] **Step 3.1 — Alterar intervalo e lock TTL**

Em `backend/app/polling/scheduler.py`:

Alterar o `_JOB_LOCK_TTL`:
```python
# Antes:
"zone_controller":       840,   # interval 15 min → lock 14 min
# Depois:
"zone_controller":       280,   # interval 5 min  → lock ~4.5 min
```

Alterar o `add_job`:
```python
# Antes:
scheduler.add_job(
    _job_zone_controller,
    trigger=IntervalTrigger(minutes=15),
    id="zone_controller", replace_existing=True, max_instances=1,
)
# Depois:
scheduler.add_job(
    _job_zone_controller,
    trigger=IntervalTrigger(minutes=5),
    id="zone_controller", replace_existing=True, max_instances=1,
)
```

- [ ] **Step 3.2 — Commit**

```bash
git add backend/app/polling/scheduler.py
git commit -m "perf: zone_controller a cada 5 min (era 15 min) — reduz latência de detecção"
```

---

## Task 4 — Paralelizar análise da IA e reduzir timeout do LLM

**Files:**
- Modify: `backend/app/ai/analyzer.py`

- [ ] **Step 4.1 — Aumentar semáforo de 1 para 3**

Em `backend/app/ai/analyzer.py`, linha 21:

```python
# Antes:
_SEM = asyncio.Semaphore(1)
# Depois:
_SEM = asyncio.Semaphore(3)
```

- [ ] **Step 4.2 — Paralelizar `analyze_anomalies` com `gather`**

Substituir o loop serial:

```python
# Antes:
async def analyze_anomalies(devices_data: list[dict]) -> list[DeviceAnalysis]:
    results: list[DeviceAnalysis] = []
    rule_based = [d for d in devices_data if d["status"] in ("SEM_LEITURA", "DESLIGADO")]
    needs_llm  = [d for d in devices_data if d["status"] not in ("SEM_LEITURA", "DESLIGADO")]
    for d in rule_based:
        results.append(analyze_no_reading(d))
    for device in needs_llm:
        analysis = await _analyze_one(device)
        if analysis:
            results.append(analysis)
    return results
```

Por versão paralela:

```python
async def analyze_anomalies(devices_data: list[dict]) -> list[DeviceAnalysis]:
    rule_based = [d for d in devices_data if d["status"] in ("SEM_LEITURA", "DESLIGADO")]
    needs_llm  = [d for d in devices_data if d["status"] not in ("SEM_LEITURA", "DESLIGADO")]

    results: list[DeviceAnalysis] = [analyze_no_reading(d) for d in rule_based]

    if needs_llm:
        llm_outcomes = await asyncio.gather(
            *[_analyze_one(d) for d in needs_llm],
            return_exceptions=True,
        )
        for outcome in llm_outcomes:
            if isinstance(outcome, DeviceAnalysis):
                results.append(outcome)
            elif isinstance(outcome, Exception):
                logger.warning("analyze_anomalies: exceção em dispositivo: %s", outcome)

    return results
```

- [ ] **Step 4.3 — Reduzir timeout do LLM de 360s para 30s**

Em `_call_llm` (linha ~213):

```python
# Antes:
async with httpx.AsyncClient(timeout=360) as client:
# Depois:
async with httpx.AsyncClient(timeout=30) as client:
```

Em `_call_zone_llm` (linha ~511):

```python
# Antes:
async with httpx.AsyncClient(timeout=360) as client:
# Depois:
async with httpx.AsyncClient(timeout=60) as client:  # zona tem mais contexto → 60s
```

- [ ] **Step 4.4 — Adicionar timeout de fallback total em `run_ai_analysis`**

Em `backend/app/ai/job.py`, na função `run_ai_analysis`, envolver `analyze_anomalies` com timeout:

```python
import asyncio

try:
    analyses = await asyncio.wait_for(
        analyze_anomalies(devices_data),
        timeout=120,  # 2 min max para análise completa do batch
    )
except asyncio.TimeoutError:
    logger.warning("AI analysis: timeout de 120s atingido — usando fallback para todos")
    from app.ai.analyzer import _fallback_analysis
    analyses = [_fallback_analysis(d) for d in devices_data]
```

- [ ] **Step 4.5 — Commit**

```bash
git add backend/app/ai/analyzer.py backend/app/ai/job.py
git commit -m "perf: paraleliza analyze_anomalies (gather+sem=3), timeout LLM 360→30s, batch timeout 120s"
```

---

## Task 5 — Limpar model e migrations (remover max_daily_adjustments)

**Files:**
- Modify: `backend/app/models/zone.py`
- Modify: `backend/app/db/migrations.py`
- Modify: `backend/app/schemas/zone.py`
- Modify: `backend/app/api/v1/zones.py`
- Modify: `backend/app/services/zone_controller.py`

- [ ] **Step 5.1 — Remover campo do modelo ZoneAutomation**

Em `backend/app/models/zone.py`, na classe `ZoneAutomation`, remover a linha:

```python
    max_daily_adjustments: Mapped[int] = mapped_column(Integer, default=6)
```

> A coluna continuará existindo no banco (não dropamos dado em prod sem cuidado), mas o ORM não a lerá mais. A migration abaixo seta um default enorme para segurança.

- [ ] **Step 5.2 — Adicionar migration de segurança**

Em `backend/app/db/migrations.py`, adicionar no final da lista:

```python
    # Desabilita limite diário — seta para valor alto sem dropar coluna (backwards-compat)
    "UPDATE zone_automations SET max_daily_adjustments = 9999 WHERE max_daily_adjustments < 9999",
```

- [ ] **Step 5.3 — Remover campo do schema**

Em `backend/app/schemas/zone.py`, remover:

```python
    max_daily_adjustments: int | None = Field(default=None, ge=0, le=50)
```

- [ ] **Step 5.4 — Remover campo da API de zonas**

Em `backend/app/api/v1/zones.py`:

1. Remover `"max_daily_adjustments": automation.max_daily_adjustments if automation else 6,` do dict de resposta.
2. Remover `if "max_daily_adjustments" in fields_set and data.max_daily_adjustments is not None: automation.max_daily_adjustments = data.max_daily_adjustments`
3. Manter `"daily_count": daily_count` — útil como métrica informativa.

- [ ] **Step 5.5 — Remover referência remanescente no zone_controller**

Em `zone_controller.py`, a função `_daily_count` pode ser mantida (usada para métricas no painel), mas o BLOQUEIO já foi removido no Task 1. Confirmar que não há mais nenhuma referência a `automation.max_daily_adjustments`.

```bash
grep -n "max_daily_adjustments" backend/app/services/zone_controller.py
# Deve retornar vazio
```

- [ ] **Step 5.6 — Commit**

```bash
git add backend/app/models/zone.py backend/app/db/migrations.py backend/app/schemas/zone.py backend/app/api/v1/zones.py backend/app/services/zone_controller.py
git commit -m "feat: remove max_daily_adjustments do ORM e API; migration seta 9999 para backwards-compat"
```

---

## Task 6 — Atualizar frontend: substituir card 6/6 por métricas operacionais

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/pages/ThermalComfortMap.tsx`
- Modify: `frontend/src/pages/ZoneControlPanel.tsx`
- Modify: `frontend/src/pages/DigitalTwinPage.tsx`

- [ ] **Step 6.1 — Atualizar tipo ZoneAutomationState**

Em `frontend/src/types/index.ts`, na interface `ZoneAutomationState` (linha ~170), **remover**:

```typescript
  max_daily_adjustments: number
```

Manter `daily_count: number` — será exibido como "Automações hoje" sem limite visual.

- [ ] **Step 6.2 — Atualizar tipo no client.ts**

Em `frontend/src/api/client.ts`, remover `max_daily_adjustments?: number` do tipo de automação.

- [ ] **Step 6.3 — Substituir card 6/6 no ThermalComfortMap**

Em `frontend/src/pages/ThermalComfortMap.tsx`, localizar o bloco Stats (por volta das linhas 1342-1362):

```tsx
{/* Stats */}
<div className="grid grid-cols-3 gap-2">
  <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
    <div className="text-xs text-gray-500">Hoje</div>
    <div className={cn('text-sm font-semibold', dailyCount >= maxDaily ? 'text-red-500' : 'text-gray-900 dark:text-white')}>
      {dailyCount}/{maxDaily}
    </div>
  </div>
  ...
</div>
```

Substituir por:

```tsx
{/* Stats operacionais */}
<div className="grid grid-cols-3 gap-2">
  <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
    <div className="text-xs text-gray-500">Ações hoje</div>
    <div className="text-sm font-semibold text-gray-900 dark:text-white">
      {automation?.daily_count ?? 0}
    </div>
  </div>
  <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
    <div className="text-xs text-gray-500">Falhas</div>
    <div className={cn('text-sm font-semibold', consecFail >= 3 ? 'text-red-500' : 'text-gray-900 dark:text-white')}>
      {consecFail}
    </div>
  </div>
  <div className="rounded bg-gray-50 dark:bg-gray-950 p-2 text-center">
    <div className="text-xs text-gray-500">Cooldown</div>
    <div className={cn('text-sm font-semibold', cooldownS ? 'text-amber-500' : 'text-green-500')}>
      {cooldownS ? `${Math.ceil(cooldownS / 60)}m` : 'Livre'}
    </div>
  </div>
</div>
```

Remover as variáveis não mais usadas:
```tsx
// Remover estas duas linhas:
const dailyCount = automation?.daily_count ?? 0
const maxDaily = automation?.max_daily_adjustments ?? 6
```

- [ ] **Step 6.4 — Remover "X/6 ajustes hoje" do ZoneControlPanel**

Em `frontend/src/pages/ZoneControlPanel.tsx`, linha 154, remover:

```tsx
{automation && ` · ${automation.daily_count}/${automation.max_daily_adjustments} ajustes hoje`}
```

Substituir por:

```tsx
{automation && automation.daily_count > 0 && ` · ${automation.daily_count} ações hoje`}
```

- [ ] **Step 6.5 — Remover "X/6 ajustes hoje" do DigitalTwinPage**

Em `frontend/src/pages/DigitalTwinPage.tsx`, linha 173, mesmo padrão:

```tsx
// Antes:
{automation && ` · ${automation.daily_count}/${automation.max_daily_adjustments} ajustes hoje`}
// Depois:
{automation && automation.daily_count > 0 && ` · ${automation.daily_count} ações hoje`}
```

- [ ] **Step 6.6 — Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/client.ts \
        frontend/src/pages/ThermalComfortMap.tsx \
        frontend/src/pages/ZoneControlPanel.tsx \
        frontend/src/pages/DigitalTwinPage.tsx
git commit -m "feat: remove card 6/6 do painel; exibe ações hoje sem limite visual"
```

---

## Task 7 — Testes automatizados

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_zone_controller_limits.py`
- Create: `backend/tests/test_classifier.py`

- [ ] **Step 7.1 — Adicionar dependências de teste**

Em `backend/requirements.txt`, adicionar ao final:

```
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-mock==3.14.0
```

- [ ] **Step 7.2 — Criar `backend/tests/__init__.py`**

```python
# vazio
```

- [ ] **Step 7.3 — Criar `backend/tests/conftest.py`**

```python
"""Fixtures compartilhadas para todos os testes."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.zone import ZoneAutomation


@pytest.fixture
def store_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def zone_key() -> str:
    return "FARMA"


@pytest.fixture
def automation(store_id) -> ZoneAutomation:
    a = ZoneAutomation()
    a.id = uuid.uuid4()
    a.store_id = store_id
    a.zone_key = "FARMA"
    a.mode = "auto"
    a.setpoint_min = 18
    a.setpoint_max = 28
    a.allowed_start_hour = 0
    a.allowed_end_hour = 23
    a.allowed_start_minute = 0
    a.allowed_end_minute = 59
    a.is_critical_zone = False
    a.priority = "conforto"
    a.zone_type = "ABERTA"
    a.reading_confidence = 1.0
    a.blocked_reason = None
    a.blocked_until = None
    a.blocked_by_user_name = None
    a.blocked_at = None
    return a


@pytest.fixture
def mock_redis():
    m = MagicMock()
    m.exists = AsyncMock(return_value=False)
    m.set = AsyncMock()
    m.acquire_lock = AsyncMock(return_value=True)
    m.release_lock = AsyncMock()
    m.incr = AsyncMock(return_value=1)
    m.expire = AsyncMock()
    m.client = MagicMock()
    m.client.decrby = AsyncMock()
    return m
```

- [ ] **Step 7.4 — Criar `backend/tests/test_zone_controller_limits.py`**

```python
"""Testes para proteções de rate-limit e remoção do limite diário."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.zone_controller import (
    DEVICE_WINDOW_MAX_CMDS,
    DEVICE_WINDOW_SECONDS,
    _device_window_ok,
)


@pytest.mark.asyncio
async def test_device_window_permite_primeiro_comando(mock_redis):
    """Primeiro comando no device deve ser permitido."""
    mock_redis.incr = AsyncMock(return_value=1)
    device_id = uuid.uuid4()

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is True
    mock_redis.expire.assert_awaited_once_with(
        f"device:cmd_window:{device_id}", DEVICE_WINDOW_SECONDS
    )


@pytest.mark.asyncio
async def test_device_window_permite_ate_limite(mock_redis):
    """Exatamente DEVICE_WINDOW_MAX_CMDS comandos devem ser permitidos."""
    device_id = uuid.uuid4()
    mock_redis.incr = AsyncMock(return_value=DEVICE_WINDOW_MAX_CMDS)

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is True


@pytest.mark.asyncio
async def test_device_window_bloqueia_apos_limite(mock_redis):
    """Comando além do limite deve ser bloqueado."""
    device_id = uuid.uuid4()
    mock_redis.incr = AsyncMock(return_value=DEVICE_WINDOW_MAX_CMDS + 1)

    with patch("app.services.zone_controller.redis_client", mock_redis):
        result = await _device_window_ok(device_id)

    assert result is False
    mock_redis.client.decrby.assert_awaited_once()


@pytest.mark.asyncio
async def test_device_window_nao_expira_se_ja_existe(mock_redis):
    """Se count > 1, o TTL já foi definido — não deve chamar expire novamente."""
    device_id = uuid.uuid4()
    mock_redis.incr = AsyncMock(return_value=2)

    with patch("app.services.zone_controller.redis_client", mock_redis):
        await _device_window_ok(device_id)

    mock_redis.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_sem_limite_diario_nao_existe_mais():
    """Confirma que a função _daily_count não é mais usada como guard no controller.
    Este teste verifica que o source não contém a string de bloqueio por limite diário."""
    import inspect
    from app.services import zone_controller

    source = inspect.getsource(zone_controller)
    assert "Limite diário de" not in source, (
        "O bloqueio por limite diário ainda está presente em zone_controller.py"
    )
    assert "max_daily_adjustments" not in source or source.count("max_daily_adjustments") == 0, (
        "Referência a max_daily_adjustments encontrada em zone_controller"
    )
```

- [ ] **Step 7.5 — Criar `backend/tests/test_classifier.py`**

```python
"""Testes para classify_status — comportamento determinístico."""
from datetime import datetime, timedelta

import pytest

from app.rules.classifier import (
    STATUS_NORMAL,
    STATUS_OFF,
    STATUS_NO_READING,
    STATUS_WARNING,
    STATUS_CRITICAL,
    classify_status,
)


def _base_kwargs(**overrides):
    return {
        "state": True,
        "temperature": 24.0,
        "setpoint_cool": 24,
        "mode_ac": 0,
        "btu": 12000,
        "consumption_estimated": None,
        "last_reading_time": None,
        "consecutive_count": 3,
        "current_status": None,
        **overrides,
    }


def test_state_false_classifica_como_desligado():
    """state=False deve retornar STATUS_OFF independente da temperatura."""
    status, delta, eff = classify_status(**_base_kwargs(state=False, temperature=25.0))
    assert status == STATUS_OFF
    assert delta is None
    assert eff is None


def test_temperatura_none_classifica_sem_leitura():
    """Temperatura None com state=True deve retornar STATUS_NO_READING."""
    status, _, _ = classify_status(**_base_kwargs(temperature=None))
    assert status == STATUS_NO_READING


def test_leitura_antiga_classifica_sem_leitura():
    """Leitura com mais de 15 min deve retornar STATUS_NO_READING."""
    old_time = datetime.utcnow() - timedelta(minutes=20)
    status, _, _ = classify_status(**_base_kwargs(last_reading_time=old_time))
    assert status == STATUS_NO_READING


def test_temperatura_dentro_da_faixa_normal():
    """Temperatura dentro da faixa ideal deve ser NORMAL."""
    status, _, _ = classify_status(
        **_base_kwargs(temperature=23.0, zone_ideal_min=22.0, zone_ideal_max=24.0)
    )
    assert status == STATUS_NORMAL


def test_temperatura_acima_da_faixa_critica():
    """Temperatura muito acima da faixa com leituras consecutivas deve ser CRITICAL."""
    status, _, _ = classify_status(
        **_base_kwargs(
            temperature=29.0,  # 5°C acima do ideal_max=24
            zone_ideal_min=22.0,
            zone_ideal_max=24.0,
            consecutive_count=5,
        )
    )
    assert status == STATUS_CRITICAL


def test_modo_fan_only_classifica_normal():
    """AC em modo fan (mode_ac != 0 e != 2) não deve ser classificado como crítico."""
    status, delta, eff = classify_status(
        **_base_kwargs(temperature=30.0, mode_ac=1)  # modo fan-only
    )
    assert status == STATUS_NORMAL
    assert delta is None
    assert eff is None
```

- [ ] **Step 7.6 — Verificar que os testes passam**

```bash
cd backend && pip install pytest pytest-asyncio pytest-mock && pytest tests/ -v
```

Saída esperada: todos os testes passando. Se algum falhar por import, ajustar `PYTHONPATH`:

```bash
cd backend && PYTHONPATH=. pytest tests/ -v
```

- [ ] **Step 7.7 — Commit**

```bash
git add backend/requirements.txt backend/tests/
git commit -m "test: adiciona pytest + testes de window rate-limit, classifier e ausência de limite diário"
```

---

## Task 8 — Deploy

- [ ] **Step 8.1 — Verificar que não há erros de importação**

```bash
cd backend && python -c "from app.services.zone_controller import run_zone_controller; print('OK')"
cd backend && python -c "from app.ai.analyzer import analyze_anomalies; print('OK')"
```

- [ ] **Step 8.2 — Rodar todos os testes**

```bash
cd backend && PYTHONPATH=. pytest tests/ -v --tb=short
```

- [ ] **Step 8.3 — Build e deploy para Azure**

```bash
cd /home/21664@bemol.local/SISTEMA\ DE\ REFRIGERAÇÃO && bash deploy.sh latest
```

- [ ] **Step 8.4 — Verificar health do backend após deploy**

```bash
curl -s https://hvac-bemol-monitor.azurewebsites.net/api/v1/health | python3 -m json.tool
```

Saída esperada: `{"status": "ok", ...}`

---

## Self-Review — Cobertura da spec

| Requisito | Task |
|---|---|
| Remover limite diário rígido 6/6 | Task 1 (remove check), Task 5 (remove campo) |
| Cooldown por aparelho (window 15min) | Task 1.3 → 1.6 |
| Cooldown por zona (existente, 15min) | Já implementado — ZONE_COOLDOWN_SECONDS |
| Bloqueio de no-op | Já implementado em zone_controller (guard efetivo == atual) |
| Limite por janela curta (não por dia) | Task 1: DEVICE_WINDOW_MAX_CMDS=4 em 15 min |
| Prioridade para comando manual | Já implementado: modo `suggestion`/`semi`/`auto` controla quem executa |
| Detecção de temperatura elevada rápida | Task 3: zone_controller 15min → 5min |
| IA não bloqueia controle (já OK) | Confirmado: AI job é async, não bloqueia zone_controller |
| Paralelismo na análise IA | Task 4: gather + sem=3 |
| Timeout curto na IA | Task 4: 360s → 30s (device), 60s (zona) |
| Painel sem card 6/6 | Task 6 |
| Painel com métricas reais | Task 6: "Ações hoje", Falhas, Cooldown |
| Métricas de latência | Task 2: decision_ms, api_ms em ZoneAction + logs |
| Testes obrigatórios | Task 7 |
| Limite diário ausente em testes | Task 7.4: `test_sem_limite_diario_nao_existe_mais` |
| Cooldown bloqueia repetição | Task 7.4: `test_device_window_bloqueia_apos_limite` |
| zone quente sem IA | Já ok (zone_controller é determinístico) |
| IA lenta não derruba automação | Task 4.4: asyncio.wait_for timeout=120s com fallback |
