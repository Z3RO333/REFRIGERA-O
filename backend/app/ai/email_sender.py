"""
Envio de emails de alerta de refrigeração via SMTP.
Usa smtplib padrão executado em thread para não bloquear o event loop.
"""
import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import partial
from html import escape

from app.config import settings
from app.ai.analyzer import DeviceAnalysis

logger = logging.getLogger(__name__)

_SEVERITY_COLORS = {
    "CRITICAL": {"header": "#b71c1c", "badge": "#e53935"},
    "HIGH":     {"header": "#bf360c", "badge": "#f4511e"},
    "MEDIUM":   {"header": "#e65100", "badge": "#fb8c00"},
    "LOW":      {"header": "#1565c0", "badge": "#1e88e5"},
}

_SEVERITY_LABELS = {
    "CRITICAL": "🔴 CRÍTICO",
    "HIGH":     "🟠 ALTO",
    "MEDIUM":   "🟡 MÉDIO",
    "LOW":      "🔵 BAIXO",
}


def _get_recipients() -> list[str]:
    recipients = [r.strip() for r in settings.email_alert_recipients.split(",") if r.strip()]
    if settings.allowed_email_domain:
        domain = settings.allowed_email_domain.lstrip("@").lower()
        recipients = [r for r in recipients if r.lower().endswith(f"@{domain}")]
    return recipients


def _html(analysis: DeviceAnalysis, device_info: dict) -> str:
    sev = analysis.severity
    colors = _SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["MEDIUM"])
    label = _SEVERITY_LABELS.get(sev, sev)

    temp = device_info.get("temperature")
    setpoint = device_info.get("setpoint_cool") or 24
    delta = round((temp - setpoint), 1) if temp is not None else None
    delta_str = f"+{delta}°C" if delta and delta > 0 else (f"{delta}°C" if delta is not None else "—")
    temp_str = f"{temp:.1f}°C" if temp is not None else "—"
    temp_color = colors["badge"]

    store = device_info.get("store_name", "—")
    sector = device_info.get("sector_name", "—")
    status = device_info.get("status", "—")
    efficiency = device_info.get("efficiency_score")
    eff_str = f"{round(efficiency * 100)}%" if efficiency is not None else "—"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:Arial,Helvetica,sans-serif;background:#f0f2f5;margin:0;padding:24px}}
  .wrap{{background:#fff;border-radius:10px;max-width:580px;margin:0 auto;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
  .hdr{{background:{colors["header"]};color:#fff;padding:20px 28px}}
  .hdr h1{{margin:0;font-size:18px;font-weight:700}}
  .hdr p{{margin:4px 0 0;font-size:13px;opacity:.85}}
  .body{{padding:24px 28px}}
  .badge{{display:inline-block;padding:5px 14px;border-radius:20px;background:{colors["badge"]};color:#fff;font-weight:700;font-size:13px;margin-bottom:16px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}
  .cell .lbl{{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:.5px;margin-bottom:2px}}
  .cell .val{{font-size:18px;font-weight:700;color:#222}}
  .cell .val.accent{{color:{temp_color}}}
  .box{{border-radius:8px;padding:14px 18px;margin:12px 0}}
  .diag{{background:#fff8e1;border-left:4px solid #ffc107}}
  .act{{background:#e8f5e9;border-left:4px solid #43a047}}
  .box strong{{display:block;font-size:12px;color:#555;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
  .box p{{margin:0;font-size:14px;color:#333;line-height:1.5}}
  .footer{{padding:16px 28px;background:#f8f9fa;border-top:1px solid #e9ecef;font-size:11px;color:#aaa}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>⚠️ Alerta de Refrigeração</h1>
    <p>Sistema de Monitoramento — Bemol Varejo</p>
  </div>
  <div class="body">
    <div class="badge">{label}</div>
    <div class="grid">
      <div class="cell">
        <div class="lbl">Equipamento</div>
        <div class="val" style="font-size:15px">{analysis.device_name}</div>
      </div>
      <div class="cell">
        <div class="lbl">Localização</div>
        <div class="val" style="font-size:14px;color:#555">{store} › {sector}</div>
      </div>
      <div class="cell">
        <div class="lbl">Temperatura</div>
        <div class="val accent">{temp_str}</div>
      </div>
      <div class="cell">
        <div class="lbl">Setpoint / Delta</div>
        <div class="val">{setpoint}°C &nbsp;<span style="color:{temp_color}">{delta_str}</span></div>
      </div>
      <div class="cell">
        <div class="lbl">Status</div>
        <div class="val" style="font-size:14px">{status}</div>
      </div>
      <div class="cell">
        <div class="lbl">Eficiência</div>
        <div class="val" style="font-size:14px">{eff_str}</div>
      </div>
    </div>

    <div class="box diag">
      <strong>🔍 Diagnóstico da IA</strong>
      <p>{analysis.diagnosis}</p>
    </div>
    <div class="box act">
      <strong>✅ Ação Recomendada</strong>
      <p>{analysis.recommended_action}</p>
    </div>
  </div>
  <div class="footer">
    Gerado automaticamente · Sistema de Refrigeração Bemol · Análise por IA local (Nemotron)
  </div>
</div>
</body>
</html>"""


def _device_row_html(analysis: DeviceAnalysis, device_info: dict) -> str:
    sev = analysis.severity
    colors = _SEVERITY_COLORS.get(sev, _SEVERITY_COLORS["MEDIUM"])
    label = _SEVERITY_LABELS.get(sev, sev)

    temp = device_info.get("temperature")
    setpoint = device_info.get("setpoint_cool") or 24
    delta = round((temp - setpoint), 1) if temp is not None else None
    delta_str = f"+{delta}°C" if delta and delta > 0 else (f"{delta}°C" if delta is not None else "—")
    temp_str = f"{temp:.1f}°C" if temp is not None else "—"
    humidity = device_info.get("humidity")
    humidity_str = f"{humidity:.0f}%" if humidity is not None else "—"
    efficiency = device_info.get("efficiency_score")
    eff_str = f"{round(efficiency * 100)}%" if efficiency is not None else "—"

    store = escape(str(device_info.get("store_name") or "—"))
    sector = escape(str(device_info.get("sector_name") or "—"))
    status = escape(str(device_info.get("status") or "—"))
    device_name = escape(analysis.device_name)
    diagnosis = escape(analysis.diagnosis)
    action = escape(analysis.recommended_action)

    return f"""
    <div class="item">
      <div class="item-top">
        <div>
          <div class="device">{device_name}</div>
          <div class="where">{store} › {sector}</div>
        </div>
        <span class="badge" style="background:{colors["badge"]}">{label}</span>
      </div>
      <table class="metrics" role="presentation" cellspacing="0" cellpadding="0">
        <tr>
          <td><span>Temperatura</span><strong style="color:{colors["badge"]}">{temp_str}</strong></td>
          <td><span>Setpoint / Delta</span><strong>{setpoint}°C / <em style="color:{colors["badge"]}">{delta_str}</em></strong></td>
          <td><span>Status</span><strong>{status}</strong></td>
          <td><span>Umidade</span><strong>{humidity_str}</strong></td>
          <td><span>Eficiência</span><strong>{eff_str}</strong></td>
        </tr>
      </table>
      <div class="note diag"><strong>Diagnóstico</strong><p>{diagnosis}</p></div>
      <div class="note action"><strong>Ação recomendada</strong><p>{action}</p></div>
    </div>"""


def _html_digest(items: list[tuple[DeviceAnalysis, dict]]) -> str:
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sorted_items = sorted(items, key=lambda item: severity_order.get(item[0].severity, 9))
    rows = "\n".join(_device_row_html(analysis, device_info) for analysis, device_info in sorted_items)

    counts: dict[str, int] = {}
    for analysis, _device_info in sorted_items:
        counts[analysis.severity] = counts.get(analysis.severity, 0) + 1

    summary = " · ".join(
        f"{_SEVERITY_LABELS.get(sev, sev)}: {count}"
        for sev, count in sorted(counts.items(), key=lambda item: severity_order.get(item[0], 9))
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:Arial,Helvetica,sans-serif;background:#f0f2f5;margin:0;padding:24px;color:#222}}
  .wrap{{background:#fff;border-radius:10px;max-width:860px;margin:0 auto;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1)}}
  .hdr{{background:#263238;color:#fff;padding:22px 28px}}
  .hdr h1{{margin:0;font-size:20px;font-weight:700}}
  .hdr p{{margin:6px 0 0;font-size:13px;opacity:.9}}
  .body{{padding:22px 28px}}
  .summary{{background:#eef3f7;border-left:4px solid #607d8b;border-radius:8px;padding:12px 16px;margin-bottom:18px;font-size:14px}}
  .item{{border:1px solid #e0e0e0;border-radius:8px;padding:16px 18px;margin:14px 0;background:#fff}}
  .item-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}}
  .device{{font-size:16px;font-weight:700;color:#111}}
  .where{{font-size:12px;color:#666;margin-top:3px}}
  .badge{{display:inline-block;white-space:nowrap;padding:5px 12px;border-radius:20px;color:#fff;font-weight:700;font-size:12px}}
  .metrics{{width:100%;border-collapse:collapse;margin:10px 0 12px}}
  .metrics td{{border-top:1px solid #eee;border-bottom:1px solid #eee;padding:10px 8px;vertical-align:top}}
  .metrics span{{display:block;font-size:10px;color:#888;text-transform:uppercase;letter-spacing:.4px;margin-bottom:4px}}
  .metrics strong{{font-size:13px;color:#222;font-style:normal}}
  .metrics em{{font-style:normal}}
  .note{{border-radius:7px;padding:10px 12px;margin-top:8px}}
  .note strong{{display:block;font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.4px;margin-bottom:5px}}
  .note p{{margin:0;font-size:13px;line-height:1.45;color:#333}}
  .diag{{background:#fff8e1;border-left:4px solid #ffc107}}
  .action{{background:#e8f5e9;border-left:4px solid #43a047}}
  .footer{{padding:16px 28px;background:#f8f9fa;border-top:1px solid #e9ecef;font-size:11px;color:#888}}
  @media(max-width:720px){{
    body{{padding:12px}}
    .body,.hdr,.footer{{padding-left:16px;padding-right:16px}}
    .item-top{{display:block}}
    .badge{{margin-top:10px}}
    .metrics td{{display:block;width:100%;box-sizing:border-box}}
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>Alertas de Refrigeração</h1>
    <p>Sistema de Monitoramento — Bemol Varejo</p>
  </div>
  <div class="body">
    <div class="summary">
      <strong>{len(sorted_items)} equipamento(s) precisam de atenção.</strong><br>
      {summary}
    </div>
    {rows}
  </div>
  <div class="footer">
    Gerado automaticamente · Sistema de Refrigeração Bemol · Análise por IA local
  </div>
</div>
</body>
</html>"""


def _build_msg(analysis: DeviceAnalysis, device_info: dict, recipients: list[str]) -> MIMEMultipart:
    temp = device_info.get("temperature")
    setpoint = device_info.get("setpoint_cool") or 24
    delta = round(temp - setpoint, 1) if temp is not None else None
    delta_str = f"+{delta}" if delta and delta > 0 else str(delta) if delta is not None else "?"
    label = _SEVERITY_LABELS.get(analysis.severity, analysis.severity)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{label}] {analysis.device_name} — {delta_str}°C vs setpoint"
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(_html(analysis, device_info), "html", "utf-8"))
    return msg


def _build_digest_msg(items: list[tuple[DeviceAnalysis, dict]], recipients: list[str]) -> MIMEMultipart:
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sorted_items = sorted(items, key=lambda item: severity_order.get(item[0].severity, 9))
    top_severity = sorted_items[0][0].severity
    label = _SEVERITY_LABELS.get(top_severity, top_severity)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[{label}] {len(sorted_items)} alerta(s) de refrigeração"
    msg["From"] = settings.email_from
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(_html_digest(sorted_items), "html", "utf-8"))
    return msg


def _send_sync(msg: MIMEMultipart, recipients: list[str]) -> bool:
    try:
        if settings.email_use_ssl:
            srv = smtplib.SMTP_SSL(settings.email_host, settings.email_port, timeout=15)
        else:
            srv = smtplib.SMTP(settings.email_host, settings.email_port, timeout=15)
            if settings.email_use_tls:
                srv.starttls()

        if settings.email_username:
            srv.login(settings.email_username, settings.email_password)

        srv.sendmail(settings.email_from, recipients, msg.as_bytes())
        srv.quit()
        logger.info("Email enviado para %s: %s", recipients, msg["Subject"])
        return True
    except Exception as exc:
        logger.error("Falha ao enviar email de alerta: %s", exc)
        return False


async def send_alert_email(analysis: DeviceAnalysis, device_info: dict) -> bool:
    if not settings.email_enabled:
        logger.info("Email desabilitado (EMAIL_ENABLED=false) — análise: %s %s",
                    analysis.severity, analysis.device_name)
        return False

    recipients = _get_recipients()
    if not recipients:
        logger.warning("Nenhum destinatário configurado ou nenhum com domínio @%s",
                       settings.allowed_email_domain or "?")
        return False

    msg = _build_msg(analysis, device_info, recipients)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_send_sync, msg, recipients))


async def send_alert_digest(items: list[tuple[DeviceAnalysis, dict]]) -> bool:
    if not items:
        return False

    if not settings.email_enabled:
        logger.info("Email desabilitado (EMAIL_ENABLED=false) — %d alertas pendentes", len(items))
        return False

    recipients = _get_recipients()
    if not recipients:
        logger.warning("Nenhum destinatário configurado ou nenhum com domínio @%s",
                       settings.allowed_email_domain or "?")
        return False

    msg = _build_digest_msg(items, recipients)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_send_sync, msg, recipients))
