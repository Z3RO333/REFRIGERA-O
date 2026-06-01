# HVAC Weekend Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limitar a automação de zonas térmicas nos fins de semana: máximo de ACs ligados por zona reduzido e faixa de conforto 2°C mais tolerante.

**Architecture:** Dois helpers puros adicionados a `zone_controller.py`; dois pontos de intervenção em `_evaluate_zone` — um aplica o offset de temperatura, outro bloqueia `power_on` quando o limite de fim de semana é atingido. Sem migração de banco.

**Tech Stack:** Python 3.12, pytest, unittest.mock. Toda mudança em `backend/app/services/zone_controller.py` e `backend/tests/test_zone_controller_limits.py`.

---

## Arquivos

| Ação | Arquivo |
|---|---|
| Modificar | `backend/app/services/zone_controller.py` |
| Modificar | `backend/tests/test_zone_controller_limits.py` |

---

## Task 1: Helpers `_is_weekend_now` e `_weekend_max_devices`

**Files:**
- Modify: `backend/app/services/zone_controller.py` (linha 20 e após as constantes, ~linha 83)
- Modify: `backend/tests/test_zone_controller_limits.py`

- [ ] **Step 1: Escrever os testes com falha esperada**

Adicionar ao final de `backend/tests/test_zone_controller_limits.py`:

```python
# ── Fim de semana ─────────────────────────────────────────────────────────────

def test_weekend_max_devices_zona_1_ac():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(1) == 0


def test_weekend_max_devices_zona_2_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(2) == 1


def test_weekend_max_devices_zona_3_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(3) == 2


def test_weekend_max_devices_zona_4_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(4) == 2


def test_weekend_max_devices_zona_0_acs():
    from app.services.zone_controller import _weekend_max_devices
    assert _weekend_max_devices(0) == 0


def test_is_weekend_now_sabado():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    mock_now = MagicMock()
    mock_now.weekday.return_value = 5  # sábado

    with patch("app.services.zone_controller.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        assert _is_weekend_now() is True


def test_is_weekend_now_domingo():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    mock_now = MagicMock()
    mock_now.weekday.return_value = 6  # domingo

    with patch("app.services.zone_controller.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        assert _is_weekend_now() is True


def test_is_weekend_now_dia_util():
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _is_weekend_now

    for weekday in range(5):  # segunda a sexta
        mock_now = MagicMock()
        mock_now.weekday.return_value = weekday

        with patch("app.services.zone_controller.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert _is_weekend_now() is False, f"weekday={weekday} deveria retornar False"
```

- [ ] **Step 2: Rodar os testes para confirmar falha**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/test_zone_controller_limits.py::test_weekend_max_devices_zona_1_ac -v
```

Esperado: `ImportError` ou `AttributeError` — função ainda não existe.

- [ ] **Step 3: Adicionar `replace` ao import de dataclasses**

Em `backend/app/services/zone_controller.py`, linha 20, trocar:

```python
from dataclasses import dataclass
```

por:

```python
from dataclasses import dataclass, replace
```

- [ ] **Step 4: Adicionar os dois helpers após as constantes**

Em `backend/app/services/zone_controller.py`, logo após o bloco de constantes (após a linha `SUGGESTION_DEDUPE_SECONDS = 1800`, por volta da linha 83), inserir:

```python

# ── Regras de fim de semana ───────────────────────────────────────────────────

def _is_weekend_now() -> bool:
    """Retorna True se o horário atual de Manaus é sábado ou domingo."""
    return datetime.now(tz=LOCAL_TZ).weekday() >= 5


def _weekend_max_devices(total_ac_devices: int) -> int:
    """Máximo de ACs que a automação pode ligar automaticamente no fim de semana.

    total=0 → 0  (nada a controlar)
    total=1 → 0  (só manual)
    total=2 → 1
    total=3+ → 2
    """
    return min(2, max(0, total_ac_devices - 1))
```

- [ ] **Step 5: Rodar todos os testes dos helpers**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/test_zone_controller_limits.py -k "weekend" -v
```

Esperado: todos os 8 testes novos PASS.

- [ ] **Step 6: Rodar a suíte completa para garantir sem regressão**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/ -v
```

Esperado: todos PASS.

- [ ] **Step 7: Commit**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO"
git add backend/app/services/zone_controller.py backend/tests/test_zone_controller_limits.py
git commit -m "feat: helpers _is_weekend_now e _weekend_max_devices para regras de fim de semana"
```

---

## Task 2: Offset de +2°C no `ideal_max` no fim de semana

**Files:**
- Modify: `backend/app/services/zone_controller.py` (em `_evaluate_zone`, após `_sync_zone_parameters_from_brise`)
- Modify: `backend/tests/test_zone_controller_limits.py`

- [ ] **Step 1: Escrever o teste com falha esperada**

Adicionar ao final de `backend/tests/test_zone_controller_limits.py`:

```python
def test_weekend_ideal_max_offset_aplicado():
    """No fim de semana, _evaluate_zone deve usar ideal_max + 2.0 ao classificar."""
    from unittest.mock import patch, MagicMock
    from app.services.zone_controller import _classify

    ideal_max_original = 24.0
    temp = 25.5  # 1.5°C acima do ideal_max original → seria WARM
                 # mas com offset (+2°C) ideal_max vira 26.0 → COMFORT

    # Sem offset (dia útil): 25.5 - 24.0 = 1.5 → WARM
    assert _classify(temp, 22.0, ideal_max_original) == "WARM"

    # Com offset (fim de semana): 25.5 - 26.0 = -0.5 → COMFORT
    assert _classify(temp, 22.0, ideal_max_original + 2.0) == "COMFORT"
```

> Nota: este teste valida a lógica do offset via `_classify` diretamente. O teste cobre o comportamento esperado sem precisar montar `_evaluate_zone` inteiro.

- [ ] **Step 2: Rodar o teste para confirmar que passa (valida premissa)**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/test_zone_controller_limits.py::test_weekend_ideal_max_offset_aplicado -v
```

Esperado: PASS — confirma que o offset de 2°C move a classificação de WARM para COMFORT.

- [ ] **Step 3: Inserir o offset em `_evaluate_zone`**

Em `backend/app/services/zone_controller.py`, localizar em `_evaluate_zone` o trecho (por volta da linha 987):

```python
        devices, params_map = await _get_zone_devices(automation.store_id, zone, session)
        await _sync_zone_parameters_from_brise(devices, params_map, session)

        # Fontes de temperatura:
```

Inserir entre `_sync_zone_parameters_from_brise` e o comentário `# Fontes de temperatura`:

```python
        if _is_weekend_now():
            zone = replace(zone, ideal_max=zone.ideal_max + 2.0)

```

O trecho completo após a edição deve ficar:

```python
        devices, params_map = await _get_zone_devices(automation.store_id, zone, session)
        await _sync_zone_parameters_from_brise(devices, params_map, session)

        if _is_weekend_now():
            zone = replace(zone, ideal_max=zone.ideal_max + 2.0)

        # Fontes de temperatura: ACs ativos + sensores externos + ACs desligados que
        # ainda reportam temperatura. DESLIGADO observa o hotspot, mas nao recebe setpoint.
        temp_sources = [d for d in devices if _is_thermal_observation_source(d)]
```

- [ ] **Step 4: Rodar a suíte para garantir sem regressão**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/ -v
```

Esperado: todos PASS.

- [ ] **Step 5: Commit**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO"
git add backend/app/services/zone_controller.py backend/tests/test_zone_controller_limits.py
git commit -m "feat: aplicar offset +2°C no ideal_max durante fins de semana"
```

---

## Task 3: Bloquear `power_on` quando limite de fim de semana atingido

**Files:**
- Modify: `backend/app/services/zone_controller.py` (dois pontos em `_evaluate_zone`)
- Modify: `backend/tests/test_zone_controller_limits.py`

- [ ] **Step 1: Escrever testes com falha esperada**

Adicionar ao final de `backend/tests/test_zone_controller_limits.py`:

```python
def test_weekend_bloqueio_power_on_zona_1_ac():
    """Zona com 1 AC: limite = 0 → power_on sempre bloqueado no fim de semana."""
    from app.services.zone_controller import _weekend_max_devices

    total = 1
    devices_on = 0  # nenhum ligado, mas máximo é 0
    max_on = _weekend_max_devices(total)
    assert devices_on >= max_on  # condição de bloqueio deve ser verdadeira


def test_weekend_bloqueio_power_on_zona_2_acs_ja_tem_1():
    """Zona com 2 ACs: limite = 1 → bloqueado quando 1 já está ligado."""
    from app.services.zone_controller import _weekend_max_devices

    total = 2
    devices_on = 1
    max_on = _weekend_max_devices(total)
    assert devices_on >= max_on  # deve bloquear


def test_weekend_permite_power_on_zona_2_acs_nenhum_ligado():
    """Zona com 2 ACs: limite = 1 → permitido quando nenhum está ligado."""
    from app.services.zone_controller import _weekend_max_devices

    total = 2
    devices_on = 0
    max_on = _weekend_max_devices(total)
    assert devices_on < max_on  # deve permitir


def test_weekend_bloqueio_power_on_zona_3_acs_tem_2():
    """Zona com 3 ACs: limite = 2 → bloqueado quando 2 já estão ligados."""
    from app.services.zone_controller import _weekend_max_devices

    total = 3
    devices_on = 2
    max_on = _weekend_max_devices(total)
    assert devices_on >= max_on  # deve bloquear


def test_weekend_permite_power_on_zona_3_acs_tem_1():
    """Zona com 3 ACs: limite = 2 → permitido quando apenas 1 está ligado."""
    from app.services.zone_controller import _weekend_max_devices

    total = 3
    devices_on = 1
    max_on = _weekend_max_devices(total)
    assert devices_on < max_on  # deve permitir
```

- [ ] **Step 2: Rodar os testes para confirmar que passam (validam a lógica da condição)**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/test_zone_controller_limits.py -k "bloqueio_power_on or permite_power_on" -v
```

Esperado: todos PASS — esses testes verificam a condição de bloqueio, não a integração com `_evaluate_zone`.

- [ ] **Step 3: Inserir o guardrail de fim de semana — bloco 1 (hotspot em COMFORT)**

Em `backend/app/services/zone_controller.py`, dentro de `_evaluate_zone`, localizar o trecho onde `status == "COMFORT"` e há hotspot local. O código é (por volta da linha 1178):

```python
                power_candidates = _build_power_on_candidates(
                    devices, params_map, hotspot=hotspot, strategy=energy_strategy
                )
                power_on_candidate = (
                    (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
                )
                if power_on_candidate is not None:
                    power_device, power_params = power_on_candidate
```

Inserir **antes** de `power_candidates = _build_power_on_candidates(...)` (o primeiro, dentro do bloco `if local_status is not None`):

```python
                if _is_weekend_now():
                    _wk_ac = [d for d in devices if not d.device.dnd and not d.device.source_url]
                    _wk_on = sum(1 for d in _wk_ac if _device_is_on(d, params_map.get(d.device.id)))
                    _wk_max = _weekend_max_devices(len(_wk_ac))
                    if _wk_on >= _wk_max:
                        await _log_blocked(
                            automation, zone, avg_temp,
                            f"Fim de semana: limite de {_wk_max} AC(s) por zona atingido "
                            f"({_wk_on}/{len(_wk_ac)} ligados). Ligue manualmente se necessário.",
                            session,
                        )
                        return

```

O contexto do trecho completo após a edição deve ficar:

```python
                if _is_weekend_now():
                    _wk_ac = [d for d in devices if not d.device.dnd and not d.device.source_url]
                    _wk_on = sum(1 for d in _wk_ac if _device_is_on(d, params_map.get(d.device.id)))
                    _wk_max = _weekend_max_devices(len(_wk_ac))
                    if _wk_on >= _wk_max:
                        await _log_blocked(
                            automation, zone, avg_temp,
                            f"Fim de semana: limite de {_wk_max} AC(s) por zona atingido "
                            f"({_wk_on}/{len(_wk_ac)} ligados). Ligue manualmente se necessário.",
                            session,
                        )
                        return

                power_candidates = _build_power_on_candidates(
                    devices, params_map, hotspot=hotspot, strategy=energy_strategy
                )
                power_on_candidate = (
                    (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
                )
                if power_on_candidate is not None:
                    power_device, power_params = power_on_candidate
```

- [ ] **Step 4: Inserir o guardrail de fim de semana — bloco 2 (zona WARM/HOT/CRITICAL)**

Em `backend/app/services/zone_controller.py`, dentro de `_evaluate_zone`, localizar o trecho fora do bloco `COMFORT` (por volta da linha 1480):

```python
        direction = "down" if status in ("WARM", "HOT", "CRITICAL") else "up"
        step = _step_size(status)

        power_candidates = (
            _build_power_on_candidates(devices, params_map, hotspot=hotspot, strategy=energy_strategy)
            if direction == "down" else []
        )
        power_on_candidate = (
            (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
        )
        if power_on_candidate is not None:
            power_device, power_params = power_on_candidate
```

Inserir **entre** `step = _step_size(status)` e `power_candidates = (`:

```python
        if direction == "down" and _is_weekend_now():
            _wk_ac = [d for d in devices if not d.device.dnd and not d.device.source_url]
            _wk_on = sum(1 for d in _wk_ac if _device_is_on(d, params_map.get(d.device.id)))
            _wk_max = _weekend_max_devices(len(_wk_ac))
            if _wk_on >= _wk_max:
                await _log_blocked(
                    automation, zone, avg_temp,
                    f"Fim de semana: limite de {_wk_max} AC(s) por zona atingido "
                    f"({_wk_on}/{len(_wk_ac)} ligados). Ligue manualmente se necessário.",
                    session,
                )
                return

```

O contexto completo após a edição deve ficar:

```python
        direction = "down" if status in ("WARM", "HOT", "CRITICAL") else "up"
        step = _step_size(status)

        if direction == "down" and _is_weekend_now():
            _wk_ac = [d for d in devices if not d.device.dnd and not d.device.source_url]
            _wk_on = sum(1 for d in _wk_ac if _device_is_on(d, params_map.get(d.device.id)))
            _wk_max = _weekend_max_devices(len(_wk_ac))
            if _wk_on >= _wk_max:
                await _log_blocked(
                    automation, zone, avg_temp,
                    f"Fim de semana: limite de {_wk_max} AC(s) por zona atingido "
                    f"({_wk_on}/{len(_wk_ac)} ligados). Ligue manualmente se necessário.",
                    session,
                )
                return

        power_candidates = (
            _build_power_on_candidates(devices, params_map, hotspot=hotspot, strategy=energy_strategy)
            if direction == "down" else []
        )
        power_on_candidate = (
            (power_candidates[0].row, power_candidates[0].params) if power_candidates else None
        )
        if power_on_candidate is not None:
            power_device, power_params = power_on_candidate
```

- [ ] **Step 5: Rodar a suíte completa**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO/backend"
python -m pytest tests/ -v
```

Esperado: todos PASS.

- [ ] **Step 6: Commit final**

```bash
cd "/home/21664@bemol.local/SISTEMA DE REFRIGERAÇÃO"
git add backend/app/services/zone_controller.py backend/tests/test_zone_controller_limits.py
git commit -m "feat: bloquear power_on automático quando limite de fim de semana atingido"
```
