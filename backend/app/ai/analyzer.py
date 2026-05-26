"""
Análise de anomalias de refrigeração via Ollama.

Estratégia de modelos:
- SEM_LEITURA / LEITURA_STALE / DESLIGADO  → regra determinística (instantâneo)
- ATENÇÃO / CRÍTICO / BAIXA_EFICIÊNCIA → Nemotron-9B (análise rica)
  └─ fallback: llama3.2:3b → fallback: regras determinísticas
"""
import asyncio
import json
import logging
import re

import httpx
from pydantic import BaseModel, field_validator

from app.config import settings

logger = logging.getLogger(__name__)

_SEM = asyncio.Semaphore(3)

SYSTEM_PROMPT = """Você é um especialista em diagnóstico de sistemas de ar-condicionado para ambientes comerciais de varejo.

Sua função é analisar UM EQUIPAMENTO por vez, usando dados em tempo real, histórico e contexto operacional, para identificar falhas, baixa eficiência, risco de desconforto térmico e necessidade de manutenção.

Responda SOMENTE com JSON puro, sem markdown, sem explicações fora do JSON.

Regras obrigatórias:

1. Não confunda equipamento com sensor.
   - Se o item analisado for apenas sensor externo, sensor de ambiente ou medidor, NUNCA sugira ligar, desligar ou alterar setpoint.
   - Comandos só podem ser recomendados para equipamentos de ar-condicionado controláveis.

2. Não confunda ausência de leitura com equipamento desligado.
   - "sem leitura" significa dado insuficiente, comunicação ausente ou leitura stale.
   - "desligado" só pode ser afirmado se houver status explícito de power/off.
   - "sem comunicação" deve ser tratado como problema de telemetria/API, não como falha térmica confirmada.

3. Não recomende ação inútil.
   - Nunca sugerir alterar setpoint para o mesmo valor atual.
   - Nunca sugerir ligar equipamento já ligado.
   - Nunca sugerir desligar equipamento já desligado.
   - Nunca sugerir comando se o equipamento não for controlável remotamente.

4. Priorize conforto térmico por zona.
   - Avalie o equipamento considerando a zona onde ele está.
   - Se a zona está quente, mas este equipamento está desligado e disponível, a recomendação pode ser ligar o equipamento.
   - Se a zona está quente e o equipamento já está ligado, avalie eficiência, delta, setpoint, tendência e histórico.
   - Se a zona está sem leitura confiável, não conclua falha térmica com alta certeza.

5. Diferencie causa raiz.
   Classifique a causa provável como uma destas categorias quando aplicável:
   - equipamento_desligado
   - setpoint_inadequado
   - baixa_eficiencia
   - possivel_falta_de_gas
   - filtro_sujo
   - evaporadora_obstruida
   - condensadora_obstruida
   - sensor_sem_leitura
   - comunicacao_indisponivel
   - leitura_stale
   - dados_insuficientes
   - carga_termica_alta
   - zona_mal_balanceada
   - manutencao_vencida

6. Severidade:
   - CRITICAL: risco operacional alto, ambiente muito fora da faixa, equipamento crítico sem resposta ou tendência muito rápida.
   - HIGH: desconforto relevante, baixa eficiência clara, temperatura acima da faixa por tempo relevante ou falha provável.
   - MEDIUM: alerta preventivo, tendência ruim, manutenção vencida ou perda moderada de eficiência.
   - LOW: observação leve, sem impacto imediato.

7. email_worthy só deve ser true quando:
   - houver impacto real no conforto da loja;
   - houver falha provável de equipamento;
   - houver risco de manutenção;
   - houver comunicação perdida em equipamento importante;
   - ou a severidade for HIGH/CRITICAL.

8. Quando os dados forem insuficientes:
   - issue_detected pode ser true se houver problema de telemetria;
   - severity deve ser LOW ou MEDIUM, exceto se o equipamento for crítico;
   - root_cause deve indicar "dados_insuficientes", "sensor_sem_leitura", "comunicacao_indisponivel" ou "leitura_stale";
   - recommended_action deve pedir verificação de leitura/comunicação, não comando de climatização.

Retorne exatamente o JSON solicitado no prompt do usuário."""

_SEVERITY_RULES = {
    "CRITICAL": {"label": "CRITICAL", "email": True},
    "HIGH":     {"label": "HIGH",     "email": True},
    "MEDIUM":   {"label": "MEDIUM",   "email": False},
    "LOW":      {"label": "LOW",      "email": False},
}


class DeviceAnalysis(BaseModel):
    device_id: str
    device_name: str
    issue_detected: bool = False
    severity: str | None = None
    root_cause: str = ""
    diagnosis: str = ""
    recommended_action: str = ""
    urgency_hours: int = 48
    email_worthy: bool = False
    analysis_source: str = "llm"  # "llm" | "fallback" | "deterministic"

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v) -> str | None:
        if not v:
            return None
        v = str(v).upper().strip()
        return v if v in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else "MEDIUM"

    @field_validator("urgency_hours", mode="before")
    @classmethod
    def validate_urgency(cls, v) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 48


# ── Análise determinística para SEM_LEITURA / LEITURA_STALE / DESLIGADO ─────

def analyze_no_reading(device: dict) -> DeviceAnalysis:
    status = device.get("status", "SEM_LEITURA")
    is_crit = device.get("is_critical_environment", False)

    if status == "DESLIGADO":
        return DeviceAnalysis(
            device_id=device["device_id"],
            device_name=device["device_name"],
            issue_detected=True,
            severity="HIGH" if is_crit else "LOW",
            root_cause="Equipamento desligado durante horário de monitoramento.",
            diagnosis="Equipamento detectado como desligado.",
            recommended_action="Confirmar se o desligamento foi intencional. Se não, religar e verificar disjuntor e controle remoto.",
            urgency_hours=0 if is_crit else 24,
            email_worthy=is_crit,
            analysis_source="deterministic",
        )

    return DeviceAnalysis(
        device_id=device["device_id"],
        device_name=device["device_name"],
        issue_detected=True,
        severity="HIGH" if is_crit else "MEDIUM",
        root_cause="Falha de comunicação, sensor offline ou equipamento sem energia.",
        diagnosis="Sem leitura há mais de 15 minutos.",
        recommended_action="Verificar alimentação elétrica, conectividade Wi-Fi/Brise e estado físico do equipamento.",
        urgency_hours=2 if is_crit else 8,
        email_worthy=is_crit,
        analysis_source="deterministic",
    )


# ── Pipeline principal ────────────────────────────────────────────────────────

async def analyze_anomalies(devices_data: list[dict]) -> list[DeviceAnalysis]:
    rule_based = [d for d in devices_data if d["status"] in ("SEM_LEITURA", "LEITURA_STALE", "DESLIGADO")]
    needs_llm  = [d for d in devices_data if d["status"] not in ("SEM_LEITURA", "LEITURA_STALE", "DESLIGADO")]

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


# ── Análise LLM com fallback em cadeia ───────────────────────────────────────

async def _analyze_one(device: dict) -> DeviceAnalysis | None:
    """Análise em tempo real — usa o modelo rápido com contexto rico."""
    async with _SEM:
        result = await _call_llm(device, model=settings.ollama_model, max_tokens=400)
        if result:
            return result

    logger.warning("LLM indisponível para %s — usando regras", device["device_name"])
    result = _fallback_analysis(device)
    result.analysis_source = "fallback"
    return result


async def analyze_one_deep(device: dict) -> DeviceAnalysis | None:
    """Análise aprofundada sob demanda — usa o modelo pesado (qwen/nemotron).
    Chamada apenas pelo endpoint /ai/deep-analysis, não pelo polling automático."""
    async with _SEM:
        result = await _call_llm(device, model=settings.ollama_model_deep, max_tokens=600)
        if result:
            logger.info("Deep analysis %s → %s", device["device_name"], result.severity)
            return result
        result = await _call_llm(device, model=settings.ollama_model, max_tokens=400)
        if result:
            return result

    return _fallback_analysis(device)


async def _call_llm(device: dict, model: str, max_tokens: int) -> DeviceAnalysis | None:
    msg = _build_prompt(device)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.ollama_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": msg},
                    ],
                    "temperature": 0.15,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "options": {"num_ctx": 4096},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        return _parse_response(content, device)
    except Exception as exc:
        logger.warning("LLM %s falhou para %s: %s", model, device["device_name"], exc)
        return None


def _build_prompt(device: dict) -> str:
    temp      = device.get("temperature")
    setpoint  = device.get("setpoint_cool") or 24
    delta     = round(temp - setpoint, 1) if temp is not None else None
    eff       = device.get("efficiency_score")
    humidity  = device.get("humidity")
    is_crit   = device.get("is_critical_environment", False)
    h_avg     = device.get("historical_avg")
    trend     = device.get("temperature_trend")      # "subindo" | "estável" | "caindo"
    trend_val = device.get("temperature_trend_delta") # delta em °C na última hora
    hours_on  = device.get("hours_of_operation")     # horas acumuladas de operação
    days_maint = device.get("days_since_maintenance") # dias sem manutenção
    alerts_30d = device.get("alerts_30d", 0)
    uptime    = device.get("uptime_pct")
    device_type = device.get("device_type", "ar_condicionado")
    is_sensor = bool(device.get("is_external_sensor"))
    remote_ok = bool(device.get("remote_control_enabled"))
    blocked = bool(device.get("blocked"))
    comm_ok = bool(device.get("communication_ok"))
    reading_age = device.get("reading_age_minutes")
    state = device.get("state")
    mode_device = device.get("mode_device")

    zone = device.get("zone") or {}
    zone_label    = zone.get("zone_label") or device.get("sector_name", "?")
    zone_ideal_min = zone.get("ideal_min")
    zone_ideal_max = zone.get("ideal_max")
    zone_avg      = zone.get("avg_temperature")
    zone_mode     = zone.get("automation_mode", "manual")
    zone_type     = zone.get("zone_type", "ABERTA")

    # Delta em relação ao conforto da zona (positivo = acima do ideal)
    zone_delta = round(temp - zone_ideal_max, 1) if temp is not None and zone_ideal_max is not None else None

    lines = [
        f"Equipamento: {device['device_name']}",
        f"Tipo do dispositivo: {device_type}",
        f"Sensor externo/medidor: {'SIM' if is_sensor else 'NÃO'}",
        f"Aceita comando remoto: {'SIM' if remote_ok else 'NÃO'}",
        f"Bloqueado/DND: {'SIM' if blocked else 'NÃO'}",
        f"Comunicação/leitura confiável: {'SIM' if comm_ok else 'NÃO'}",
        f"Idade da última leitura: {f'{reading_age:.1f} min' if reading_age is not None else 'sem leitura'}",
        f"Local: {device.get('store_name','?')} › {zone_label}",
        f"Ambiente crítico: {'SIM' if is_crit else 'NÃO'}",
        f"Status atual: {device['status']}",
        f"Estado power explícito: {'ligado' if state is True else ('desligado' if state is False else 'desconhecido')} | mode_device={mode_device if mode_device is not None else 'desconhecido'}", 
        "",
        "── Zona térmica ──",
        f"Tipo de área: {zone_type}",
        f"Faixa de conforto da zona: {f'{zone_ideal_min}–{zone_ideal_max}°C' if zone_ideal_min and zone_ideal_max else 'não configurada'}",
        f"Temperatura média da zona: {f'{zone_avg:.1f}°C' if zone_avg is not None else 'sem dados'}",
        f"Delta em relação ao conforto: {f'+{zone_delta}°C acima do limite' if zone_delta and zone_delta > 0 else (f'{zone_delta}°C abaixo' if zone_delta and zone_delta < 0 else 'dentro da faixa')}",
        f"Modo de automação da zona: {zone_mode}",
        "",
        "── Leitura do equipamento ──",
        f"Temperatura: {f'{temp:.1f}°C' if temp is not None else '—'}",
        f"Setpoint: {setpoint}°C  |  Delta do setpoint: {f'+{delta}°C' if delta and delta > 0 else (f'{delta}°C' if delta is not None else '—')}",
        f"Umidade: {f'{humidity:.0f}%' if humidity is not None else '—'}",
        f"Eficiência energética: {f'{round(eff*100)}%' if eff is not None else '—'}",
        f"BTU: {device.get('btu', '?')}",
        "",
        "── Contexto histórico ──",
        f"Média histórica (mesma hora, últimos 7 dias): {f'{h_avg:.1f}°C' if h_avg is not None else 'sem dados'}",
        f"Desvio da média histórica: {f'+{round(temp-h_avg,1)}°C' if temp and h_avg else '—'}",
        f"Tendência da última hora: {trend or 'desconhecida'} ({f'{trend_val:+.1f}°C' if trend_val is not None else '?'})",
        f"Disponibilidade (uptime): {f'{uptime}%' if uptime is not None else 'sem dados'}",
        "",
        "── Histórico de manutenção ──",
        f"Horas de operação acumuladas: {f'{hours_on:.0f}h' if hours_on else 'sem dados'}",
        f"Dias desde última manutenção: {days_maint if days_maint is not None else 'nunca registrada'}",
        f"Alertas nos últimos 30 dias: {alerts_30d}",
    ]

    schema = (
        '{"device_id":"' + device["device_id"] + '",'
        '"device_name":"' + device["device_name"] + '",'
        '"issue_detected":true,'
        '"severity":"HIGH",'
        '"root_cause":"causa raiz em 1 frase",'
        '"diagnosis":"descrição técnica do problema",'
        '"recommended_action":"ação específica para o técnico",'
        '"urgency_hours":8,'
        '"email_worthy":true}'
    )

    lines += [
        "",
        "Categorias recomendadas para root_cause quando aplicável: equipamento_desligado, setpoint_inadequado, baixa_eficiencia, possivel_falta_de_gas, filtro_sujo, evaporadora_obstruida, condensadora_obstruida, sensor_sem_leitura, comunicacao_indisponivel, leitura_stale, dados_insuficientes, carga_termica_alta, zona_mal_balanceada, manutencao_vencida.",
        "Com base em todos os dados acima, analise o problema e retorne o JSON:",
        schema,
    ]

    return "\n".join(lines)


def _parse_response(raw: str, device: dict) -> DeviceAnalysis | None:
    # Remove blocos de raciocínio interno (<think>...</think>) gerados por modelos R1/Nemotron
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"```(?:json)?", "", cleaned).strip()
    # Extrai o primeiro objeto JSON completo
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        logger.debug("Sem JSON na resposta para %s: %r", device["device_name"], raw[:200])
        return None
    try:
        data = json.loads(match.group())
        analysis = DeviceAnalysis(**data)
        if not analysis.issue_detected or not analysis.severity:
            return None
        # Garante email_worthy coerente com severity
        if analysis.severity in ("HIGH", "CRITICAL"):
            analysis.email_worthy = True
        return analysis
    except Exception as exc:
        logger.debug("Parse falhou para %s: %s | raw: %r", device["device_name"], exc, raw[:200])
        return None


def _fallback_analysis(device: dict) -> DeviceAnalysis:
    delta    = device.get("delta_temp") or 0
    status   = device.get("status", "ATENÇÃO")
    is_crit  = device.get("is_critical_environment", False)
    hours_on = device.get("hours_of_operation") or 0

    if status == "CRÍTICO" or delta > 6:
        severity, email, urgency = "CRITICAL", True, 0
    elif delta > 3 or is_crit:
        severity, email, urgency = "HIGH", True, 8
    elif delta > 1.5:
        severity, email, urgency = "MEDIUM", False, 48
    else:
        severity, email, urgency = "LOW", False, 168

    root = "LLM indisponível — análise por regras."
    if hours_on > 5000:
        root = "Alta probabilidade de filtro sujo ou baixo nível de gás (>5.000h de operação)."
    elif hours_on > 2000:
        root = "Possível filtro com restrição de fluxo (>2.000h sem manutenção)."

    return DeviceAnalysis(
        device_id=device["device_id"],
        device_name=device["device_name"],
        issue_detected=True,
        severity=severity,
        root_cause=root,
        diagnosis=f"Status {status} com {f'+{delta:.1f}°C' if delta else 'temperatura anômala'} acima do setpoint de {device.get('setpoint_cool',24)}°C.",
        recommended_action="Verificar filtros, nível de gás refrigerante e carga térmica do ambiente.",
        urgency_hours=urgency,
        email_worthy=email,
    )


# ── Análise de zona ───────────────────────────────────────────────────────────

ZONE_SYSTEM_PROMPT = """Você é um especialista em climatização de ambientes comerciais de varejo.

Sua função é analisar UMA ZONA TÉRMICA completa, considerando sensores, aparelhos de ar-condicionado, leituras, tendência, faixa ideal e qualidade dos dados.

Responda SOMENTE com JSON puro, sem markdown e sem texto fora do JSON.

Objetivo principal:
Avaliar conforto térmico da zona e indicar a melhor ação operacional ou técnica, sem confundir ausência de leitura com ausência de aparelho.

Regras obrigatórias:

1. Analise a zona, não apenas equipamentos isolados.
   Considere temperatura média, faixa ideal, tendência, tipo da zona, confiança da leitura, sensores, aparelhos vinculados, aparelhos ligados/desligados, bloqueados, sem comunicação, sem permissão de comando e anomalias.

2. Nunca conclua que a zona não possui ar-condicionado apenas porque está sem leitura térmica.
   Estados diferentes precisam ser tratados separadamente:
   - zona_sem_leitura_termica
   - zona_sem_sensor
   - zona_sem_aparelhos_vinculados
   - aparelhos_sem_comunicacao
   - aparelhos_bloqueados
   - aparelhos_nao_controlaveis
   - api_com_erro
   - leitura_stale
   - dados_insuficientes

3. Para zona quente:
   Se temperatura_media > faixa_ideal_max:
   - primeiro verifique se existem aparelhos desligados, disponíveis, comunicando e controláveis;
   - se existirem, recomende ligar aparelho(s) antes de reduzir setpoint;
   - só recomende reduzir setpoint se os aparelhos disponíveis já estiverem ligados;
   - nunca recomende reduzir setpoint se o novo valor for igual ao atual;
   - se não houver ação segura, informe o motivo técnico.

3b. Para hotspot local:
   - se houver aparelho desligado, comunicando e controlável perto do hotspot, recomende ligar esse aparelho;
   - se todos os aparelhos próximos já estiverem ligados, NUNCA recomende ligar outro aparelho;
   - nesse caso, avalie reduzir setpoint real dos aparelhos próximos se current_setpoint > min_allowed_setpoint;
   - se todos já estiverem no limite mínimo ou sem comunicação/controle, recomende verificação técnica de balanceamento, insuflação, retorno de ar, carga térmica ou manutenção;
   - nunca use faixa_ideal_min/target_min como current_setpoint.

4. Para zona fria:
   Se temperatura_media < faixa_ideal_min:
   - primeiro recomende aumentar setpoint dos aparelhos ligados;
   - depois avalie desligar aparelhos excedentes;
   - nunca recomende desligar aparelho já desligado;
   - nunca recomende comando sem mudança real.

5. Para zona sem leitura confiável:
   - não gere comando automático agressivo;
   - use última leitura válida apenas se estiver marcada como stale;
   - reduza a confiança do diagnóstico;
   - recomende verificar sensor/API/telemetria;
   - mantenha os aparelhos vinculados visíveis no diagnóstico.

6. Para zona com aparelhos mas nenhum ajustável, explique o motivo: todos bloqueados, todos sem comunicação, todos não controláveis, todos já no limite operacional, falta permissão de comando, API indisponível ou dados insuficientes.

7. Severidade:
   - CRITICAL: zona muito fora da faixa, tendência rápida, área crítica ou sem controle operacional.
   - HIGH: zona fora da faixa com impacto real e ação necessária.
   - MEDIUM: zona próxima do limite, tendência ruim ou alerta preventivo.
   - LOW: observação sem impacto imediato.

8. recommended_action deve ser uma recomendação clara para operador ou técnico.

9. Não invente IDs, aparelhos, sensores ou valores. Use apenas dados recebidos. Se faltarem dados, indique dados_insuficientes.

Retorne exatamente o JSON solicitado no prompt do usuário."""


class ZoneAnalysis(BaseModel):
    zone_key: str
    zone_label: str
    store_id: str
    issue_detected: bool = False
    severity: str | None = None
    root_cause: str = ""
    diagnosis: str = ""
    recommended_action: str = ""
    urgency_hours: int = 24
    analysis_source: str = "llm"
    devices_analyzed: int = 0
    zone_status: str = ""
    trend_c_per_hour: float | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v) -> str | None:
        if not v:
            return None
        v = str(v).upper().strip()
        return v if v in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else "MEDIUM"

    @field_validator("urgency_hours", mode="before")
    @classmethod
    def validate_urgency(cls, v) -> int:
        try:
            return max(0, int(v))
        except (TypeError, ValueError):
            return 24


async def analyze_zone(twin: dict) -> ZoneAnalysis:
    """Análise LLM da zona com fallback para regras heurísticas."""
    async with _SEM:
        result = await _call_zone_llm(twin, model=settings.ollama_model, max_tokens=400)
        if result:
            return result

    logger.warning("LLM indisponível para zona %s — usando fallback", twin.get("zone_label"))
    return _fallback_zone_analysis(twin)


async def analyze_zone_deep(twin: dict) -> ZoneAnalysis:
    """Análise aprofundada de zona (modelo pesado, on-demand)."""
    async with _SEM:
        result = await _call_zone_llm(twin, model=settings.ollama_model_deep, max_tokens=600)
        if result:
            return result
        result = await _call_zone_llm(twin, model=settings.ollama_model, max_tokens=400)
        if result:
            return result
    return _fallback_zone_analysis(twin)


async def _call_zone_llm(twin: dict, model: str, max_tokens: int) -> ZoneAnalysis | None:
    msg = _build_zone_prompt(twin)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{settings.ollama_url}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": ZONE_SYSTEM_PROMPT},
                        {"role": "user",   "content": msg},
                    ],
                    "temperature": 0.15,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "options": {"num_ctx": 4096},
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        return _parse_zone_response(content, twin)
    except Exception as exc:
        logger.warning("LLM %s falhou para zona %s: %s", model, twin.get("zone_label"), exc)
        return None


def _build_zone_prompt(twin: dict) -> str:
    status    = twin.get("current_status", "NO_READING")
    avg       = twin.get("current_avg_temp")
    trend     = twin.get("trend_c_per_hour")
    risk      = twin.get("risk_level", "LOW")
    ideal_min = twin.get("ideal_min")
    ideal_max = twin.get("ideal_max")
    zone_type = twin.get("zone_type", "ABERTA")
    early     = twin.get("early_warning", False)
    confidence= twin.get("confidence", 0)
    devices   = twin.get("contributing_devices", [])
    p30       = twin.get("predicted_temp_30m")

    ac_devices = [d for d in devices if not d.get("is_external_sensor")]
    sensors = [d for d in devices if d.get("is_external_sensor")]
    active = [d for d in ac_devices if d.get("state") is True or (d.get("state") is None and d.get("status") not in ("DESLIGADO", "SEM_LEITURA", "LEITURA_STALE", "UNKNOWN", None))]
    off_devices = [d for d in ac_devices if d.get("state") is False or d.get("status") == "DESLIGADO"]
    blocked_devices = [d for d in ac_devices if d.get("blocked")]
    no_comm_devices = [d for d in ac_devices if not d.get("communication_ok", True)]
    controllable_devices = [d for d in ac_devices if d.get("controllable") and d.get("communication_ok", True) and not d.get("blocked")]
    all_devices_on = len(ac_devices) > 0 and len(off_devices) == 0
    adjustable_setpoint = [
        d for d in active
        if d.get("controllable")
        and d.get("communication_ok", True)
        and not d.get("blocked")
        and d.get("setpoint_cool") is not None
        and d.get("setpoint_min", ideal_min if ideal_min is not None else 18) is not None
        and d.get("setpoint_cool") > d.get("setpoint_min", ideal_min if ideal_min is not None else 18)
    ]
    stale_devices = [d for d in devices if d.get("is_stale")]
    sensors_no_reading = [d for d in sensors if d.get("status") in ("SEM_LEITURA", "LEITURA_STALE", "UNKNOWN") or d.get("temperature") is None]
    anomalous = [d for d in active if d.get("status") not in ("NORMAL",)]

    lines = [
        f"Zona: {twin.get('zone_label', twin.get('zone_key', '?'))}",
        f"Tipo: {zone_type}",
        f"Faixa de conforto: {f'{ideal_min}–{ideal_max}°C' if ideal_min and ideal_max else 'não configurada'}",
        "",
        "── Estado atual ──",
        f"Temperatura média: {f'{avg:.1f}°C' if avg is not None else 'sem leitura'}",
        f"Previsão 30 min: {f'{p30:.1f}°C' if p30 is not None else 'desconhecida'}",
        f"Status da zona: {status}",
        f"Tendência: {f'{trend:+.1f}°C/hora' if trend is not None else 'desconhecida'}",
        f"Nível de risco: {risk}",
        f"Alerta preemptivo: {'SIM — zona confortável mas aquecendo rapidamente' if early else 'Não'}",
        f"Confiança da leitura: {round(confidence * 100)}%",
        "",
        "── Inventário operacional ──",
        f"Aparelhos vinculados: {len(ac_devices)}",
        f"Aparelhos ligados: {len(active)}",
        f"Aparelhos desligados: {len(off_devices)}",
        f"Aparelhos bloqueados: {len(blocked_devices)}",
        f"Aparelhos sem comunicação/leitura confiável: {len(no_comm_devices)}",
        f"Aparelhos controláveis agora: {len(controllable_devices)}",
        f"Todos os aparelhos ligados: {'SIM' if all_devices_on else 'NÃO'}",
        f"Aparelhos ligados com margem para reduzir setpoint: {len(adjustable_setpoint)}",
        f"Sensores ativos/vinculados: {len(sensors)}",
        f"Sensores sem leitura: {len(sensors_no_reading)}",
        f"Leituras stale: {len(stale_devices)}",
        "",
        f"── Dispositivos ({len(devices)} total, {len(active)} ACs ativos, {len(anomalous)} com anomalia) ──",
    ]

    for d in devices:
        temp_s = f"{d['temperature']:.1f}°C" if d.get("temperature") is not None else "—"
        eff_s  = f"{round(d['efficiency_score'] * 100)}%" if d.get("efficiency_score") is not None else "—"
        ext    = " [sensor externo]" if d.get("is_external_sensor") else ""
        state_s = "ligado" if d.get("state") is True else ("desligado" if d.get("state") is False else "estado desconhecido")
        ctrl_s = "controlável" if d.get("controllable") else "não controlável"
        comm_s = "comunicando" if d.get("communication_ok", True) else "sem comunicação/leitura confiável"
        setpoint_s = f", setpoint_real={d.get('setpoint_cool')}°C" if d.get("setpoint_cool") is not None else ", setpoint_real=sem leitura"
        min_s = f", minimo_operacional={d.get('setpoint_min')}°C" if d.get("setpoint_min") is not None else ""
        stale_s = ", stale" if d.get("is_stale") else ""
        lines.append(f"  • {d['name']}: {temp_s}, status={d['status']}, {state_s}, {ctrl_s}, {comm_s}{setpoint_s}{min_s}{stale_s}, efic.={eff_s}{ext}")

    schema = (
        f'{{"zone_key":"{twin["zone_key"]}",'
        f'"zone_label":"{twin.get("zone_label", twin["zone_key"])}",'
        '"issue_detected":true,'
        '"severity":"HIGH",'
        '"root_cause":"causa raiz da anomalia térmica na zona em 1 frase",'
        '"diagnosis":"descrição do problema coletivo observado na zona",'
        '"recommended_action":"ação específica para o operador ou técnico",'
        '"urgency_hours":4}'
    )

    lines += [
        "",
        "Estados que devem ser diferenciados quando aplicável: zona_sem_leitura_termica, zona_sem_sensor, zona_sem_aparelhos_vinculados, aparelhos_sem_comunicacao, aparelhos_bloqueados, aparelhos_nao_controlaveis, api_com_erro, leitura_stale, dados_insuficientes.",
        "Para zona quente, priorize ligar aparelhos desligados disponíveis antes de reduzir setpoint. Para zona fria, priorize aumentar setpoint dos aparelhos ligados antes de desligar excedentes.",
        "Se todos os aparelhos da zona estiverem ligados, não recomende power_on; para hotspot local, recomende ajuste de setpoint real dos aparelhos próximos se houver margem, senão verificação técnica.",
        "Com base no estado coletivo da zona, identifique o problema e retorne o JSON:",
        schema,
    ]

    return "\n".join(lines)


def _parse_zone_response(raw: str, twin: dict) -> ZoneAnalysis | None:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"```(?:json)?", "", cleaned).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        logger.debug("Sem JSON na resposta de zona %s: %r", twin.get("zone_label"), raw[:200])
        return None
    try:
        data = json.loads(match.group())
        data.setdefault("zone_key", twin["zone_key"])
        data.setdefault("zone_label", twin.get("zone_label", twin["zone_key"]))
        data.setdefault("store_id", twin["store_id"])
        analysis = ZoneAnalysis(**data)
        if not analysis.issue_detected or not analysis.severity:
            return None
        analysis.devices_analyzed = len(twin.get("contributing_devices", []))
        analysis.zone_status = twin.get("current_status", "")
        analysis.trend_c_per_hour = twin.get("trend_c_per_hour")
        return analysis
    except Exception as exc:
        logger.debug("Parse zona falhou %s: %s", twin.get("zone_label"), exc)
        return None


def _fallback_zone_analysis(twin: dict) -> ZoneAnalysis:
    status    = twin.get("current_status", "NO_READING")
    risk      = twin.get("risk_level", "LOW")
    avg       = twin.get("current_avg_temp")
    trend     = twin.get("trend_c_per_hour") or 0.0
    ideal_max = twin.get("ideal_max", 24)
    devices   = twin.get("contributing_devices", [])
    anomalous = [d for d in devices if d.get("status") not in ("NORMAL", "DESLIGADO", "SEM_LEITURA", "LEITURA_STALE")]

    if risk == "CRITICAL" or status == "CRITICAL":
        severity, urgency = "CRITICAL", 0
    elif risk == "HIGH" or status == "HOT":
        severity, urgency = "HIGH", 2
    elif risk == "MEDIUM" or status == "WARM":
        severity, urgency = "MEDIUM", 8
    else:
        severity, urgency = "LOW", 24

    temp_s = f"{avg:.1f}°C" if avg is not None else "desconhecida"

    return ZoneAnalysis(
        zone_key=twin["zone_key"],
        zone_label=twin.get("zone_label", twin["zone_key"]),
        store_id=twin["store_id"],
        issue_detected=True,
        severity=severity,
        root_cause=(
            f"LLM indisponível — {len(anomalous)} de {len(devices)} dispositivos com anomalia, "
            f"tendência {trend:+.1f}°C/h."
        ),
        diagnosis=f"Zona {status} com temperatura média {temp_s} (ideal ≤ {ideal_max}°C).",
        recommended_action=twin.get("recommended_action", "Verificar dispositivos da zona e ajustar setpoint."),
        urgency_hours=urgency,
        analysis_source="fallback",
        devices_analyzed=len(devices),
        zone_status=status,
        trend_c_per_hour=twin.get("trend_c_per_hour"),
    )
