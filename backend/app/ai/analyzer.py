"""
Análise de anomalias de refrigeração via Ollama (llama3.2:3b local).

Estratégia:
- SEM_LEITURA → regra determinística, sem LLM (rápido)
- ATENÇÃO / CRÍTICO / BAIXA_EFICIÊNCIA → LLM por device (1 de cada vez, semáforo)
"""
import asyncio
import json
import logging
import re

import httpx
from pydantic import BaseModel, field_validator

from app.config import settings

logger = logging.getLogger(__name__)

# Semáforo para não saturar o Ollama com requisições paralelas
_SEM = asyncio.Semaphore(1)

SYSTEM_PROMPT = (
    "Você diagnostica equipamentos de ar condicionado em lojas de varejo. "
    "Responda SOMENTE com JSON puro, sem markdown."
)


class DeviceAnalysis(BaseModel):
    device_id: str
    device_name: str
    issue_detected: bool = False
    severity: str | None = None   # LOW | MEDIUM | HIGH | CRITICAL
    diagnosis: str = ""
    recommended_action: str = ""
    email_worthy: bool = False

    @field_validator("severity", mode="before")
    @classmethod
    def validate_severity(cls, v) -> str | None:
        if not v:
            return None
        v = str(v).upper().strip()
        return v if v in {"LOW", "MEDIUM", "HIGH", "CRITICAL"} else "MEDIUM"


# ── Análise determinística para SEM_LEITURA ──────────────────────────────────

def analyze_no_reading(device: dict) -> DeviceAnalysis:
    """Não precisa de LLM — regra simples para SEM_LEITURA e DESLIGADO."""
    status = device.get("status", "SEM_LEITURA")
    is_crit = device.get("is_critical_environment", False)

    if status == "DESLIGADO":
        return DeviceAnalysis(
            device_id=device["device_id"],
            device_name=device["device_name"],
            issue_detected=True,
            severity="HIGH" if is_crit else "LOW",
            diagnosis="Equipamento detectado como desligado durante o período de monitoramento.",
            recommended_action="Confirmar se o desligamento foi intencional. Se não, religar e verificar causa.",
            email_worthy=is_crit,
        )

    # SEM_LEITURA
    return DeviceAnalysis(
        device_id=device["device_id"],
        device_name=device["device_name"],
        issue_detected=True,
        severity="HIGH" if is_crit else "MEDIUM",
        diagnosis="Sem leitura há mais de 15 minutos. Possível falha de comunicação, sensor ou equipamento offline.",
        recommended_action="Verificar alimentação elétrica, conectividade de rede e status físico do equipamento.",
        email_worthy=is_crit,
    )


# ── Análise via LLM para anomalias reais de temperatura ──────────────────────

async def analyze_anomalies(devices_data: list[dict]) -> list[DeviceAnalysis]:
    """
    Processa devices:
    - SEM_LEITURA / DESLIGADO → regra determinística (sem LLM)
    - ATENÇÃO / CRÍTICO / BAIXA_EFICIÊNCIA → LLM (com fallback em regras)
    """
    results: list[DeviceAnalysis] = []

    rule_based = [d for d in devices_data if d["status"] in ("SEM_LEITURA", "DESLIGADO")]
    needs_llm  = [d for d in devices_data if d["status"] not in ("SEM_LEITURA", "DESLIGADO")]

    # Regra determinística
    for d in rule_based:
        results.append(analyze_no_reading(d))

    # LLM sequencial (semáforo=1 para não sobrecarregar Ollama)
    for device in needs_llm:
        analysis = await _analyze_one(device)
        if analysis:
            results.append(analysis)

    return results


async def _analyze_one(device: dict) -> DeviceAnalysis | None:
    """Chama o LLM para um único device com prompt compacto."""
    temp = device.get("temperature")
    setpoint = device.get("setpoint_cool") or 24
    delta = round(temp - setpoint, 1) if temp is not None else None
    eff = device.get("efficiency_score")
    eff_pct = f"{round(eff * 100)}%" if eff is not None else "—"
    crit = "SIM" if device.get("is_critical_environment") else "NÃO"
    h_avg = device.get("historical_avg")
    h_avg_str = f"{h_avg:.1f}°C" if h_avg is not None else "N/A"

    user_msg = f"""Equipamento: {device['device_name']}
Local: {device.get('store_name','?')} › {device.get('sector_name','?')}
Status: {device['status']}
Temperatura Atual: {f"{temp:.1f}°C" if temp is not None else "—"}
Média Histórica (nesta hora): {h_avg_str}
Setpoint: {setpoint}°C | Delta Setpoint: {f"+{delta}°C" if delta and delta > 0 else (f"{delta}°C" if delta is not None else "—")}
Eficiência: {eff_pct} | Ambiente crítico: {crit}

Considere a Média Histórica como baseline dinâmico. Se a temp atual for muito maior que a média histórica mesmo com delta setpoint baixo, pode haver um problema de vedação ou carga térmica alta.

Retorne JSON:
{{"device_id":"{device['device_id']}","device_name":"{device['device_name']}","issue_detected":true,"severity":"HIGH","diagnosis":"...","recommended_action":"...","email_worthy":true}}"""

    async with _SEM:
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/v1/chat/completions",
                    json={
                        "model": settings.ollama_model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.1,
                        "max_tokens": 300,
                        "stream": False,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("LLM falhou para %s [%s]: %r",
                           device["device_name"], type(exc).__name__, exc)
            return _fallback_analysis(device)

    return _parse_single(content, device)


def _parse_single(raw: str, device: dict) -> DeviceAnalysis | None:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()
    match = re.search(r"\{[\s\S]*?\}", cleaned)
    if not match:
        return _fallback_analysis(device)
    try:
        data = json.loads(match.group())
        analysis = DeviceAnalysis(**data)
        return analysis if analysis.issue_detected and analysis.severity else None
    except Exception as exc:
        logger.debug("Parse falhou para %s: %s", device["device_name"], exc)
        return _fallback_analysis(device)


def _fallback_analysis(device: dict) -> DeviceAnalysis:
    """Análise baseada em regras quando o LLM falha."""
    delta = device.get("delta_temp") or 0
    status = device.get("status", "ATENÇÃO")
    is_crit = device.get("is_critical_environment", False)

    if status == "CRÍTICO" or delta > 6:
        severity, email = "CRITICAL", True
    elif delta > 3 or is_crit:
        severity, email = "HIGH", True
    elif delta > 1.5:
        severity, email = "MEDIUM", False
    else:
        severity, email = "LOW", False

    return DeviceAnalysis(
        device_id=device["device_id"],
        device_name=device["device_name"],
        issue_detected=True,
        severity=severity,
        diagnosis=f"Status {status} com delta de +{delta:.1f}°C acima do setpoint de {device.get('setpoint_cool',24)}°C.",
        recommended_action="Verificar filtros, nível de gás refrigerante e condições do ambiente.",
        email_worthy=email,
    )
