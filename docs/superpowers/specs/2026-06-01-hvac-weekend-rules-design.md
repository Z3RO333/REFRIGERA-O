# Design: Regras de fim de semana para automação de zonas térmicas

**Data:** 2026-06-01  
**Projeto:** HVAC Monitor — Sistema de Refrigeração Bemol  
**Escopo:** `backend/app/services/zone_controller.py`

---

## Contexto

No escritório, fins de semana têm poucos funcionários. A automação atual trata sábado e domingo da mesma forma que dias úteis, podendo ligar vários ACs desnecessariamente. A solução deve limitar o número de aparelhos ligados automaticamente e tolerar temperaturas ligeiramente mais altas nesses dias.

Feriados ficam fora do escopo desta versão e podem ser adicionados ao mesmo helper futuramente.

---

## Comportamento esperado

| Situação | Dias úteis | Fim de semana |
|---|---|---|
| Zona com 1 AC | liga automaticamente | **não liga** (só manual) |
| Zona com 2 ACs | liga ambos se necessário | **máximo 1 ligado** automaticamente |
| Zona com 3+ ACs | liga quantos precisar | **máximo 2 ligados** automaticamente |
| Ajuste de setpoint em ACs já ligados | normal | **normal** (sem restrição) |
| Faixa de conforto (ideal_max) | padrão | **+2°C** (mais tolerante) |

---

## Arquitetura

Toda a lógica fica em `zone_controller.py`. Dois helpers novos e dois pontos de intervenção em `_evaluate_zone`. Sem migração de banco, sem endpoint novo.

### Helpers novos

```python
def _is_weekend_now() -> bool:
    """Retorna True se o horário atual de Manaus é sábado ou domingo."""
    return datetime.now(tz=LOCAL_TZ).weekday() >= 5

def _weekend_max_devices(total_ac_devices: int) -> int:
    """Máximo de ACs que a automação pode ligar automaticamente no fim de semana.

    total=1 → 0  (só manual)
    total=2 → 1
    total=3+ → 2
    """
    return min(2, max(0, total_ac_devices - 1))
```

### Ponto 1 — Offset de conforto em `_evaluate_zone`

Logo após `devices, params_map` serem carregados, antes da classificação térmica:

```python
from dataclasses import replace

if _is_weekend_now():
    zone = replace(zone, ideal_max=zone.ideal_max + 2.0)
```

Isso faz o classificador interno (`_classify`) e o guardrail de faixa considerar 2°C a mais antes de classificar a zona como WARM/HOT.

### Ponto 2 — Bloqueio de power_on em `_evaluate_zone`

Imediatamente antes de qualquer bloco que execute ou sugira `power_on` (duas ocorrências: hotspot local e zona quente), inserir:

```python
if _is_weekend_now():
    _ac_total = [d for d in devices if not d.device.dnd and not d.device.source_url]
    _devices_on = sum(1 for d in _ac_total if _device_is_on(d, params_map.get(d.device.id)))
    _max_on = _weekend_max_devices(len(_ac_total))
    if _devices_on >= _max_on:
        await _log_blocked(
            automation, zone, avg_temp,
            f"Fim de semana: limite de {_max_on} AC(s) por zona atingido "
            f"({_devices_on}/{len(_ac_total)} ligados). Ligue manualmente se necessário.",
            session,
        )
        return
```

Ajustes de setpoint e fan speed nos ACs já ligados seguem normais — o bloqueio é exclusivo para `power_on`.

---

## Fluxo de decisão no fim de semana

```
_evaluate_zone chamado
  ↓
_check_guardrails (inalterado)
  ↓
Carrega devices + params_map
  ↓
[NOVO] Se fim de semana → ideal_max += 2.0
  ↓
Classifica status (COMFORT / WARM / HOT / CRITICAL)
  ↓
Se status == COMFORT → lógica de hotspot local
    [NOVO] Se fim de semana e devices_on >= max → log_blocked + return
    Se ok → executa power_on / ajuste setpoint (normal)
  ↓
Se status != COMFORT → lógica de zona quente
    [NOVO] Se fim de semana e devices_on >= max → log_blocked + return
    Se ok → executa power_on / ajuste setpoint (normal)
```

---

## O que NÃO muda

- Ajuste de setpoint e fan speed nos ACs já ligados
- Guardrails existentes (kill switch, manutenção, janela de horário)
- Alertas de manutenção por falhas consecutivas
- Lógica de recuperação térmica
- Polling e classificação de status dos devices

---

## Fora do escopo desta versão

- Feriados nacionais (o helper `_is_weekend_now` pode ser estendido depois)
- Configuração por zona via UI (regra global por ora)
- Notificação ao operador sobre o modo fim de semana ativo
