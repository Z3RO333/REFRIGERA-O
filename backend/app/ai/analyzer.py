"""
Análise de anomalias de refrigeração via Ollama.

Estratégia de modelos:
- SEM_LEITURA / DESLIGADO  → regra determinística (instantâneo)
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

_SEM = asyncio.Semaphore(1)

SYSTEM_PROMPT = """Você é um especialista em diagnóstico de sistemas de ar condicionado para ambientes comerciais (varejo).

Seu papel é analisar dados de monitoramento em tempo real e identificar problemas, causas raiz e ações corretivas precisas.

Conhecimentos aplicáveis:
- Delta acima do setpoint > 2°C por mais de 15 min indica perda de capacidade de refrigeração
- Delta > 4°C em ambiente crítico (farmácia, servidor) exige ação imediata
- Eficiência < 60% combinada com alta temperatura sugere filtro entupido ou baixo nível de gás
- Se a temperatura atual supera a média histórica no mesmo horário em > 3°C, há degradação recente
- Equipamentos com > 5.000h de operação sem manutenção têm alta probabilidade de filtro sujo
- Umidade > 70% combinada com temperatura alta pode indicar condensador com problema
- Temperatura subindo (tendência positiva) é mais urgente que temperatura estável acima do setpoint

Responda SOMENTE com JSON puro, sem markdown, sem texto fora do JSON."""

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


# ── Análise determinística para SEM_LEITURA / DESLIGADO ──────────────────────

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
        async with httpx.AsyncClient(timeout=360) as client:
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
        f"Local: {device.get('store_name','?')} › {zone_label}",
        f"Ambiente crítico: {'SIM' if is_crit else 'NÃO'}",
        f"Status atual: {device['status']}",
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
