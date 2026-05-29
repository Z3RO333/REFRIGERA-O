# Modo Recuperação Térmica — Design

**Data:** 2026-05-29
**Status:** Aprovado para implementação
**Escopo:** backend (zone_controller, models, schemas, migrations, learning) + frontend (AIZoneView, ZoneEditor, ThermalComfortMap)

## Motivação

A IA hoje respeita `automation.setpoint_min` como piso absoluto (ex: 20°C). Em zonas HOT/CRITICAL com ACs já no piso e zona ainda quente, a única ação possível é registrar `blocked`. Resultado: a temperatura não cede e o operador é forçado a intervir manualmente.

Operacionalmente, é seguro descer até 18°C **temporariamente** para forçar a recuperação. O que não é seguro é manter 18°C indefinidamente (condensação, sobrecarga, consumo). Este design adiciona uma janela controlada de "recuperação térmica" com saída automática.

## Decisões de design

| Decisão | Valor | Justificativa |
|---------|-------|---------------|
| Configuração | Por zona (ZoneAutomation) | Cada zona tem necessidades distintas — Farma precisa de 18°C mais agressivo que escritório. |
| Estado ativo | Redis com TTL | Auto-expira sem cron; persiste entre restarts; scheduler já usa Redis pra cooldowns. |
| Critério exit | 2 ciclos COMFORT consecutivos | ~10min de validação evita yo-yo sem manter SP baixo desnecessariamente. |
| Ramp-up | +1°C a cada 2 ciclos (~10min) | Sobe 18→22°C em ~40min, dando tempo da zona se estabilizar entre steps. |
| Default duration | 60 min | Suficiente para correção térmica realista; após isso é problema do equipamento. |
| Default recovery_min | 18°C | Valor pedido explicitamente pelo usuário. |
| Default recovery_target | 22°C | Valor pedido explicitamente pelo usuário (centro da faixa ideal típica 20-24). |
| Recovery é só setpoint | Sim, nunca power_off | Compatível com `allow_auto_power_off=False` (Farma/Loja). |
| Granularidade do estado | Por zona | O estado de recovery vive por zona. Quais ACs recebem o SP baixo continua sendo decidido pela lógica de scoring existente (hotspot proximity, BTU, capacidade). A zona "está em recovery"; os ACs específicos que recebem comandos variam ciclo a ciclo. |

## Arquitetura

### Modelo de dados

**Novos campos em `ZoneAutomation` (migrations idempotentes):**

```python
recovery_enabled: bool = True
recovery_min_setpoint: int = 18    # piso temporário durante recovery
recovery_target_setpoint: int = 22 # alvo após ramp-up completo
recovery_max_duration_minutes: int = 60
```

**Estado ativo em Redis:**

```
chave: zone:recovery:{store_id}:{zone_key}
valor (JSON):
  {
    "started_at": ISO8601,
    "reason": "Zona HOT (25.6°C) por 2 ciclos; setpoint piso atingido sem efeito",
    "current_min_setpoint": 18,     # baseline atual durante a janela
    "ramp_state": "active" | "ramping" | "completed",
    "ramp_step_target": 19 | 20 | 21 | 22  # próximo SP do ramp-up
    "comfort_streak": 0 | 1 | 2,
    "last_evaluated_at": ISO8601
  }
TTL: recovery_max_duration_minutes * 60 segundos
```

### Fluxo de decisão

Modificações no `_evaluate_zone` (backend/app/services/zone_controller.py):

```
1. No início, antes do cooldown check, ler estado de recovery do Redis.
2. Branch por status térmico:

   status == WARM | HOT | CRITICAL:
     a. Se recovery_enabled=False ou freshness<0.60 → fluxo normal (sem recovery)
     b. Se NÃO está em recovery e status in (HOT, CRITICAL):
        - Verificar se setpoint dos ACs já está perto do automation.setpoint_min
        - Se sim → INICIAR recovery (set Redis, audit_log)
        - current_min_setpoint = automation.recovery_min_setpoint
        - reason = descreve o gatilho
     c. Se JÁ está em recovery (ramp_state="active"):
        - Permitir setpoint até recovery_min_setpoint via override no _build_setpoint_candidates
        - Zerar comfort_streak (zona voltou a esquentar)
     d. Se ramp_state="ramping" e zona voltou WARM/HOT:
        - Reset: ramp_state="active", current_min_setpoint=recovery_min_setpoint
        - Audit: "recovery_reset por reaquecimento"

   status == COMFORT e em recovery:
     a. comfort_streak += 1
     b. Se comfort_streak < 2 → mantém setpoint atual
     c. Se comfort_streak >= 2 e ramp_state="active":
        - ramp_state="ramping", ramp_step_target = current_setpoint + 1
        - Sobe setpoint dos ACs em recovery em +1°C
     d. Se ramp_state="ramping" e comfort_streak % 2 == 0:
        - Sobe setpoint em +1°C (próximo step)
        - Quando ramp_step_target >= recovery_target_setpoint:
          ramp_state="completed", SAIR do recovery (deletar chave Redis)

   status == COLD:
     - Recovery não se aplica (lógica existente)

3. TTL Redis expirou naturalmente?
   - Próximo ciclo NÃO vai encontrar a chave
   - Detectar via flag "previously_in_recovery" persistida no last_action.reason
   - Se zona ainda WARM/HOT após expiração → gerar AuditLog severity=MEDIUM
     "recovery_unsuccessful: zona X não estabilizou em 60min, possível falha"
   - Voltar a respeitar automation.setpoint_min normal
```

### Componentes alterados

**Backend:**

1. `backend/app/models/zone.py` — adiciona 4 colunas em `ZoneAutomation`.
2. `backend/app/db/migrations.py` — 4 ALTER TABLE IF NOT EXISTS idempotentes.
3. `backend/app/schemas/zone.py` — adiciona campos em `ZoneModeUpdate` (já tem setpoint_min/max — adicionar recovery_*).
4. `backend/app/api/v1/zones.py`:
   - `_automation_dict`: expor os 4 campos novos.
   - `update_zone_mode`: persistir recovery_* quando enviados.
5. `backend/app/services/zone_controller.py`:
   - Helper novo: `_recovery_state(store_id, zone_key) -> dict | None` (lê Redis).
   - Helper novo: `_enter_recovery(automation, zone, reason, session)` (set Redis + audit).
   - Helper novo: `_advance_recovery_ramp(recovery_state, status, automation)` (decide próximo SP).
   - Helper novo: `_exit_recovery(store_id, zone_key, reason)` (delete Redis + audit).
   - `_evaluate_zone`: branch lógica acima.
   - `_build_setpoint_candidates`: aceitar `min_setpoint_override` (vindo do recovery) substituindo `automation.setpoint_min`.
   - `build_ai_view`: incluir campo `recovery` no JSON retornado.
6. `backend/app/services/learning_service.py`:
   - `record_decision`: aceitar `was_in_recovery: bool` (nova coluna em ai_decisions).
7. `backend/app/models/learning.py` + migration: nova coluna `was_in_recovery BOOLEAN DEFAULT false` em ai_decisions.

**Frontend:**

8. `frontend/src/components/zone/AIZoneView.tsx`:
   - Nova seção "Modo Recuperação" quando `data.recovery != null`.
   - Mostra: started_at (há X min), tempo restante, reason, ramp_state, próximo SP.
9. `frontend/src/pages/ThermalComfortMap.tsx`:
   - Badge `🔄 Recuperação · Xmin` no painel da zona quando recovery ativo.
10. `frontend/src/components/map/ZoneEditor.tsx`:
    - Novo bloco "Recuperação térmica" com toggle (recovery_enabled), 3 inputs (recovery_min_setpoint, recovery_target_setpoint, recovery_max_duration_minutes).
11. `frontend/src/api/client.ts`:
    - `zonesApi.setMode`: tipar os 4 campos novos.
12. `frontend/src/types/index.ts`:
    - Tipo `ZoneAutomation` recebe os 4 campos.

### Proteções (todas implementadas no código)

| Proteção | Onde |
|----------|------|
| Não entrar em recovery com `freshness_ratio < 0.60` | guard no início de `_enter_recovery` |
| Não aplicar SP baixo em AC com DND, sem comunicação, source_url | já existe em `_build_setpoint_candidates` e `_device_command_communication_check` |
| Não manter 18°C > duration_minutes | TTL automático do Redis + check explícito |
| Não aplicar em zona já COMFORT (no momento da decisão) | branch lógico requer status in (HOT, CRITICAL) |
| Não aplicar em zona COLD | branch só roda em WARM/HOT/CRITICAL |
| Auditoria completa | `audit_log` em entrada/saída/reset/unsuccessful |
| Compatível com `allow_auto_power_off=False` | recovery é só setpoint, nunca chama power_off |

### Auditoria

Eventos novos em `audit_log`:

- `zone_recovery_entered` — severity LOW, origin AUTOMATION, com reason
- `zone_recovery_ramp_up` — severity LOW, com step atual
- `zone_recovery_exited` — severity LOW, com motivo (success | manual_disable)
- `zone_recovery_reset` — severity LOW, com motivo (zona reaqueceu durante ramp)
- `zone_recovery_unsuccessful` — severity MEDIUM, gera alerta

### Diferenças do comportamento atual

| Cenário | Antes | Agora |
|---------|-------|-------|
| Zona HOT com ACs no setpoint_min=20°C | `blocked` permanente | Entra em recovery, desce pra 18°C por até 60min |
| Após ceder, zona COMFORT | Mantém SP baixo | Ramp-up gradual de volta pra 22°C |
| Recovery não funcionou em 60min | N/A (não existe) | Alerta `recovery_unsuccessful` MEDIUM |
| Zona com `recovery_enabled=False` | igual antes | igual antes (opt-out preserva comportamento) |

## Critérios de aceite

1. Em zona HOT/CRITICAL com ACs no piso, sistema desce pra 18°C automaticamente.
2. Quando zona volta a COMFORT por 2 ciclos, ramp-up começa.
3. Ramp-up sobe 1°C a cada 2 ciclos; reset volta pra 18°C se zona reaquece.
4. Após 60min sem ceder, alerta MEDIUM é gerado e Redis é liberado.
5. UI mostra badge "Recuperação térmica" quando estado ativo.
6. AIZoneView mostra detalhes do recovery atual.
7. Editor de Zona permite editar os 4 campos por zona.
8. Audit log registra todas as transições.
9. Toda a feature respeita `recovery_enabled=False` (opt-out).
10. Compatível com `allow_auto_power_off=False` (não chama power_off).

## Fora de escopo

- Recovery em zonas SALA_FECHADA com regras diferentes (mantém regra global)
- Aplicar recovery em apenas alguns ACs da zona (granularidade por device) — pode vir em V2
- Histograma de tempo em recovery por zona — pode vir como dashboard separado
- Notificações push/email do alerta `recovery_unsuccessful` — usa o sistema de alertas existente
