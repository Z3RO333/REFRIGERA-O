"""
Job de análise de IA: roda após cada ciclo de polling.
Consulta devices com anomalias, envia ao Ollama para diagnóstico
e dispara emails para severidades HIGH/CRITICAL.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.cache.redis_client import redis_client
from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.alert import Alert
from app.models.device import Device, DeviceParameters, DeviceStatusLatest
from app.models.reading import DeviceReading
from app.models.store import Store, StoreSector

logger = logging.getLogger(__name__)

# Cooldown entre emails do mesmo device (evita spam)
EMAIL_COOLDOWN_SECONDS = 3600  # 1 hora
AI_ANALYSIS_LOCK_SECONDS = 900  # evita análises duplicadas por trigger/polling concorrente

# Statuses que merecem análise
ANOMALOUS_STATUSES = {"ATENÇÃO", "CRÍTICO", "BAIXA_EFICIÊNCIA", "SEM_LEITURA", "DESLIGADO"}


async def run_ai_analysis() -> None:
    """Ponto de entrada do job — chamado após poll_all_devices."""
    if not settings.ai_analysis_enabled:
        return

    lock_key = "ai:analysis:lock"
    if not await redis_client.acquire_lock(lock_key, ttl=AI_ANALYSIS_LOCK_SECONDS):
        logger.debug("AI analysis: execução ignorada, lock ativo")
        return

    from app.ai.analyzer import analyze_anomalies
    from app.ai.email_manager import buffer_alert_for_email

    try:
        devices_data, device_info_map = await _fetch_anomalous_devices()
        if not devices_data:
            logger.debug("AI analysis: nenhuma anomalia para analisar")
            return

        logger.info("AI analysis: analisando %d dispositivos anômalos", len(devices_data))
        analyses = await analyze_anomalies(devices_data)

        alerts_buffered = 0
        for analysis in analyses:
            device_info = device_info_map.get(analysis.device_id, {})
            await _cache_analysis(analysis, device_info)

            if not analysis.email_worthy:
                continue

            cooldown_key = f"ai:email_cd:{analysis.device_id}"
            if await redis_client.exists(cooldown_key):
                logger.debug("Cooldown ativo para %s", analysis.device_name)
                continue

            await buffer_alert_for_email(analysis, device_info)
            await redis_client.set(cooldown_key, "1", ttl=EMAIL_COOLDOWN_SECONDS)
            alerts_buffered += 1

        await _log_ai_analyses_to_db(analyses, device_info_map)

        logger.info(
            "AI analysis concluída: %d analisados, %d alertas adicionados ao buffer de email",
            len(analyses), alerts_buffered
        )
    except Exception as exc:
        logger.error("Erro no job de análise de IA: %s", exc, exc_info=True)
    finally:
        await redis_client.release_lock(lock_key)


from sqlalchemy import select, func
from app.models.reading import DeviceReading

async def _fetch_anomalous_devices() -> tuple[list[dict], dict[str, dict]]:
    """Retorna lista de dicts enriquecidos para o LLM e um mapa device_id → info."""
    async with AsyncSessionLocal() as session:
        now   = datetime.utcnow()
        hour  = now.hour
        ago7d = now - timedelta(days=7)
        ago1h = now - timedelta(hours=1)
        ago30d = now - timedelta(days=30)

        # Média histórica na mesma hora (últimos 7 dias)
        baseline_res = await session.execute(
            select(DeviceReading.device_id, func.avg(DeviceReading.temperature).label("avg_temp"))
            .where(DeviceReading.time >= ago7d,
                   func.extract("hour", DeviceReading.time) == hour,
                   DeviceReading.temperature.is_not(None))
            .group_by(DeviceReading.device_id)
        )
        baseline_map = {str(r.device_id): r.avg_temp for r in baseline_res.all()}

        # Tendência: última leitura vs leitura de 1h atrás
        trend_res = await session.execute(
            select(
                DeviceReading.device_id,
                func.first_value(DeviceReading.temperature)
                    .over(partition_by=DeviceReading.device_id,
                          order_by=DeviceReading.time.desc()).label("temp_latest"),
                func.first_value(DeviceReading.temperature)
                    .over(partition_by=DeviceReading.device_id,
                          order_by=DeviceReading.time.asc()).label("temp_oldest"),
            )
            .where(DeviceReading.time >= ago1h,
                   DeviceReading.temperature.is_not(None))
            .distinct(DeviceReading.device_id)
        )
        trend_map: dict[str, tuple[float, float]] = {}
        for r in trend_res.all():
            if r.temp_latest is not None and r.temp_oldest is not None:
                trend_map[str(r.device_id)] = (r.temp_latest, r.temp_oldest)

        # Contagem de alertas nos últimos 30 dias
        alert_res = await session.execute(
            select(Alert.device_id, func.count(Alert.id).label("cnt"))
            .where(Alert.opened_at >= ago30d)
            .group_by(Alert.device_id)
        )
        alert_map = {str(r.device_id): r.cnt for r in alert_res.all()}

        # Query principal com campos enriquecidos
        result = await session.execute(
            select(
                Device.id,
                Device.name,
                Device.btu,
                Device.is_critical_environment,
                Device.last_maintenance,
                DeviceStatusLatest.status_classification,
                DeviceStatusLatest.temperature,
                DeviceStatusLatest.delta_temp,
                DeviceStatusLatest.humidity,
                DeviceStatusLatest.efficiency_score,
                DeviceStatusLatest.state,
                DeviceStatusLatest.updated_at,
                DeviceStatusLatest.accumulated_on_minutes,
                DeviceStatusLatest.accumulated_off_minutes,
                DeviceParameters.setpoint_cool,
                StoreSector.name.label("sector_name"),
                StoreSector.store_id.label("store_id"),
                Store.name.label("store_name"),
            )
            .join(DeviceStatusLatest, Device.id == DeviceStatusLatest.device_id)
            .join(StoreSector, Device.sector_id == StoreSector.id)
            .join(Store, StoreSector.store_id == Store.id)
            .outerjoin(DeviceParameters, Device.id == DeviceParameters.device_id)
            .where(Device.active == True,
                   DeviceStatusLatest.status_classification.in_(ANOMALOUS_STATUSES))
        )
        rows = result.all()

        # Usa apenas zonas customizadas — sem hardcoded
        from app.services.zone_controller import _load_all_custom_zones
        from app.models.zone import ZoneAutomation
        from sqlalchemy import or_

        custom_zones = await _load_all_custom_zones(session)
        sector_to_zone: dict = {}  # custom zones usam device_ids, não sector_names

        # Temperatura média por zona customizada (via device_ids)
        zone_avg_map: dict[str, float] = {}
        for zone_cfg in custom_zones.values():
            if not zone_cfg.device_ids:
                continue
            avg_res = await session.execute(
                select(func.avg(DeviceStatusLatest.temperature))
                .join(Device, DeviceStatusLatest.device_id == Device.id)
                .where(
                    Device.id.in_(zone_cfg.device_ids),
                    DeviceStatusLatest.temperature.is_not(None),
                )
            )
            avg_val = avg_res.scalar()
            if avg_val is not None:
                zone_avg_map[zone_cfg.key] = round(float(avg_val), 1)

        # Modo de automação atual por (store_id, zone_key)
        auto_res = await session.execute(select(ZoneAutomation))
        automation_map: dict[tuple, str] = {
            (str(a.store_id), a.zone_key): a.mode
            for a in auto_res.scalars().all()
        }

    devices_data: list[dict] = []
    device_info_map: dict[str, dict] = {}

    for row in rows:
        did = str(row.id)

        on_min  = row.accumulated_on_minutes
        off_min = row.accumulated_off_minutes
        hours_on = round(on_min / 60, 0) if on_min else None
        total_min = (on_min or 0) + (off_min or 0)
        uptime_pct = round(on_min / total_min * 100, 1) if total_min > 0 and on_min else None

        days_maint = None
        if row.last_maintenance:
            days_maint = (datetime.utcnow() - row.last_maintenance).days

        # Tendência de temperatura
        trend_label, trend_delta = None, None
        if did in trend_map:
            latest, oldest = trend_map[did]
            td = round(latest - oldest, 1)
            trend_delta = td
            if td > 0.5:
                trend_label = "subindo"
            elif td < -0.5:
                trend_label = "caindo"
            else:
                trend_label = "estável"

        info = {
            "device_id": did,
            "device_name": row.name,
            "store_name": row.store_name,
            "sector_name": row.sector_name,
            "status": row.status_classification,
            "temperature": row.temperature,
            "setpoint_cool": row.setpoint_cool or 24,
            "delta_temp": row.delta_temp,
            "humidity": row.humidity,
            "efficiency_score": row.efficiency_score,
            "state": row.state,
            "is_critical_environment": row.is_critical_environment,
            "btu": row.btu,
            "historical_avg": baseline_map.get(did),
            "temperature_trend": trend_label,
            "temperature_trend_delta": trend_delta,
            "hours_of_operation": hours_on,
            "uptime_pct": uptime_pct,
            "days_since_maintenance": days_maint,
            "alerts_30d": alert_map.get(did, 0),
            "last_reading_at": row.updated_at.isoformat() if row.updated_at else None,
        }

        # Contexto de zona
        zone_cfg = sector_to_zone.get(row.sector_name or "")
        if zone_cfg:
            auto_mode = automation_map.get((str(row.store_id), zone_cfg.key), "manual")
            info["zone"] = {
                "store_id": str(row.store_id),
                "zone_key": zone_cfg.key,
                "zone_label": zone_cfg.label,
                "ideal_min": zone_cfg.ideal_min,
                "ideal_max": zone_cfg.ideal_max,
                "avg_temperature": zone_avg_map.get(zone_cfg.key),
                "automation_mode": auto_mode,
                "zone_type": zone_cfg.zone_type,
            }
        else:
            info["zone"] = None

        devices_data.append(info)
        device_info_map[did] = info

    return devices_data, device_info_map


async def _log_ai_analyses_to_db(analyses, device_info_map: dict) -> None:
    """Persiste análises de IA no audit_log para rastreabilidade permanente."""
    from app.models.audit import AuditLog
    try:
        async with AsyncSessionLocal() as session:
            for analysis in analyses:
                if not analysis.issue_detected:
                    continue
                info = device_info_map.get(analysis.device_id, {})
                zone = info.get("zone") or {}
                entry = AuditLog(
                    action_type="ai_analysis",
                    origin="ai",
                    severity=analysis.severity,
                    device_name=analysis.device_name,
                    store_name=info.get("store_name"),
                    sector_name=info.get("sector_name"),
                    zone_key=zone.get("zone_key"),
                    description=analysis.diagnosis or analysis.root_cause,
                    extra_data={
                        "root_cause": analysis.root_cause,
                        "recommended_action": analysis.recommended_action,
                        "urgency_hours": analysis.urgency_hours,
                        "email_worthy": analysis.email_worthy,
                        "analysis_source": analysis.analysis_source,
                        "temperature": info.get("temperature"),
                        "setpoint_cool": info.get("setpoint_cool"),
                        "delta_temp": info.get("delta_temp"),
                        "efficiency_score": info.get("efficiency_score"),
                        "zone_label": zone.get("zone_label"),
                        "zone_ideal_min": zone.get("ideal_min"),
                        "zone_ideal_max": zone.get("ideal_max"),
                        "zone_avg_temp": zone.get("avg_temperature"),
                        "automation_mode": zone.get("automation_mode"),
                    },
                )
                session.add(entry)

                if analysis.severity in ("HIGH", "CRITICAL"):
                    await redis_client.publish("ai.analysis.created", {
                        "device_id": analysis.device_id,
                        "device_name": analysis.device_name,
                        "severity": analysis.severity,
                        "root_cause": analysis.root_cause,
                        "analysis_source": analysis.analysis_source,
                        "store_name": info.get("store_name"),
                        "sector_name": info.get("sector_name"),
                    })

            await session.commit()
    except Exception as exc:
        logger.warning("Falha ao persistir análises de IA no audit_log: %s", exc)


async def _cache_analysis(analysis, device_info: dict) -> None:
    """Salva última análise no Redis para o endpoint /ai/status."""
    import json
    key = f"ai:last_analysis:{analysis.device_id}"
    payload = {
        **analysis.model_dump(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "temperature": device_info.get("temperature"),
        "setpoint_cool": device_info.get("setpoint_cool"),
        "store_name": device_info.get("store_name"),
        "sector_name": device_info.get("sector_name"),
    }
    await redis_client.set(key, json.dumps(payload), ttl=86400)  # 24h


# ── Análise de zona ───────────────────────────────────────────────────────────

ZONE_COOLDOWN_SECONDS = 7200  # 2h por zona (evita re-análise desnecessária)


async def run_zone_analysis() -> None:
    """Analisa zonas com anomalias via LLM. Chamado pelo scheduler a cada 30 min."""
    if not settings.ai_analysis_enabled:
        return

    from app.ai.analyzer import analyze_zone
    from app.services.digital_twin import compute_store_twin

    try:
        async with AsyncSessionLocal() as session:
            stores_res = await session.execute(select(Store).where(Store.active == True))
            store_list = [(s.id, s.name) for s in stores_res.scalars().all()]

        zones_analyzed = 0
        for store_uuid, store_name in store_list:
            async with AsyncSessionLocal() as session:
                twins = await compute_store_twin(store_uuid, session)

            for twin in twins:
                status = twin.get("current_status", "NO_READING")
                early  = twin.get("early_warning", False)
                risk   = twin.get("risk_level", "LOW")

                needs_analysis = (
                    status in ("WARM", "HOT", "CRITICAL")
                    or early
                    or risk in ("HIGH", "CRITICAL")
                )
                if not needs_analysis:
                    continue

                cooldown_key = f"ai:zone_cd:{store_uuid}:{twin['zone_key']}"
                if await redis_client.exists(cooldown_key):
                    logger.debug("Zone cooldown ativo: %s/%s", store_uuid, twin["zone_key"])
                    continue

                analysis = await analyze_zone(twin)
                await _cache_zone_analysis(analysis)
                await _log_zone_analysis_to_db(analysis, twin, store_name)
                await redis_client.set(cooldown_key, "1", ttl=ZONE_COOLDOWN_SECONDS)
                zones_analyzed += 1

        logger.info("Zone AI analysis: %d zona(s) analisada(s)", zones_analyzed)
    except Exception as exc:
        logger.error("Erro no job de análise de zonas: %s", exc, exc_info=True)


async def trigger_zone_analysis(store_id_str: str, zone_key: str) -> None:
    """Análise on-demand de zona específica (modelo pesado). Chamado pelo endpoint."""
    if not settings.ai_analysis_enabled:
        return

    from app.ai.analyzer import analyze_zone_deep
    from app.services.digital_twin import compute_zone_twin
    from app.services.zone_controller import _load_all_custom_zones

    try:
        async with AsyncSessionLocal() as _s:
            all_zones = await _load_all_custom_zones(_s)
        zone_cfg = all_zones.get(zone_key)
        if not zone_cfg:
            logger.warning("Zona customizada '%s' não encontrada — crie a zona no editor do mapa", zone_key)
            return

        store_uuid = uuid.UUID(store_id_str)
        async with AsyncSessionLocal() as session:
            twin = await compute_zone_twin(store_uuid, zone_cfg, session)

        analysis = await analyze_zone_deep(twin)

        # Remove cooldown para permitir re-análise imediata
        await redis_client.delete(f"ai:zone_cd:{store_id_str}:{zone_key}")

        await _cache_zone_analysis(analysis)

        async with AsyncSessionLocal() as session:
            store_res = await session.execute(select(Store).where(Store.id == store_uuid))
            store = store_res.scalar_one_or_none()

        await _log_zone_analysis_to_db(analysis, twin, store.name if store else None)
        logger.info("On-demand zone analysis: %s/%s → %s", store_id_str, zone_key, analysis.severity)
    except Exception as exc:
        logger.error("Erro na análise on-demand da zona %s/%s: %s", store_id_str, zone_key, exc, exc_info=True)


async def _cache_zone_analysis(analysis) -> None:
    import json
    key = f"ai:last_zone_analysis:{analysis.store_id}:{analysis.zone_key}"
    payload = {
        **analysis.model_dump(),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis_client.set(key, json.dumps(payload), ttl=86400)


async def _log_zone_analysis_to_db(analysis, twin: dict, store_name: str | None) -> None:
    from app.models.audit import AuditLog
    try:
        async with AsyncSessionLocal() as session:
            entry = AuditLog(
                action_type="ai_analysis",
                origin="ai",
                severity=analysis.severity,
                store_name=store_name,
                zone_key=analysis.zone_key,
                description=f"[ZONA {analysis.zone_label}] {analysis.diagnosis or analysis.root_cause}",
                extra_data={
                    "zone_label": analysis.zone_label,
                    "zone_status": analysis.zone_status,
                    "trend_c_per_hour": analysis.trend_c_per_hour,
                    "root_cause": analysis.root_cause,
                    "recommended_action": analysis.recommended_action,
                    "urgency_hours": analysis.urgency_hours,
                    "analysis_source": analysis.analysis_source,
                    "devices_analyzed": analysis.devices_analyzed,
                    "current_avg_temp": twin.get("current_avg_temp"),
                    "risk_level": twin.get("risk_level"),
                    "confidence": twin.get("confidence"),
                },
            )
            session.add(entry)

            if analysis.severity in ("HIGH", "CRITICAL"):
                await redis_client.publish("zone.ai_analysis.created", {
                    "zone_key": analysis.zone_key,
                    "zone_label": analysis.zone_label,
                    "store_id": analysis.store_id,
                    "severity": analysis.severity,
                    "root_cause": analysis.root_cause,
                    "zone_status": analysis.zone_status,
                    "trend_c_per_hour": analysis.trend_c_per_hour,
                    "analysis_source": analysis.analysis_source,
                })

            await session.commit()
    except Exception as exc:
        logger.warning("Falha ao persistir análise de zona: %s", exc)
