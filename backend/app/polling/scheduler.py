import logging
from functools import wraps
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from app.cache.redis_client import redis_client
from app.config import settings
from app.polling.device_poller import poll_all_devices
from app.polling.configs_poller import poll_configs_for_all
from app.polling.external_sensors_poller import poll_external_sensors
from app.ai.email_manager import send_consolidated_email_job
from app.ai.job import run_zone_analysis
from app.services.zone_controller import run_zone_controller, run_zone_verification
from app.db.retention import purge_old_readings
from app.services.zone_controller import release_expired_maintenance_zones

logger = logging.getLogger(__name__)

# Redis lock TTL per job — slightly under each job's interval so the lock
# expires before the next scheduled run even if the job hangs.
_JOB_LOCK_TTL = {
    "poll_variables":        240,   # interval 5 min  → lock 4 min
    "poll_configs":          290,   # interval 5 min  → lock ~5 min
    "poll_external_sensors": 240,   # interval 5 min  → lock 4 min
    "consolidated_email":    300,   # interval varies → lock 5 min
    "zone_controller":       280,   # interval 5 min  → lock ~4.5 min
    "zone_verification":     150,   # interval 3 min  → lock 2.5 min
    "zone_ai_analysis":     1700,   # interval 30 min → lock 28 min
    "purge_old_readings":   3600,   # interval 24 h   → lock 1 h
    "release_maintenance":   55,    # interval 1 min  → lock 55s
}


def _with_lock(job_id: str):
    """Wraps an async job so only one worker runs it at a time via Redis lock."""
    ttl = _JOB_LOCK_TTL.get(job_id, 300)

    def decorator(fn):
        @wraps(fn)
        async def wrapped():
            lock_key = f"sched:lock:{job_id}"
            if not await redis_client.acquire_lock(lock_key, ttl=ttl):
                logger.debug("Skipping job %s — locked by another worker", job_id)
                return
            try:
                await fn()
            finally:
                await redis_client.release_lock(lock_key)
        return wrapped
    return decorator


@_with_lock("poll_variables")
async def _job_poll_variables():
    await poll_all_devices()


@_with_lock("poll_configs")
async def _job_poll_configs():
    await poll_configs_for_all()


@_with_lock("poll_external_sensors")
async def _job_poll_external_sensors():
    await poll_external_sensors()


@_with_lock("consolidated_email")
async def _job_consolidated_email():
    await send_consolidated_email_job()


@_with_lock("zone_controller")
async def _job_zone_controller():
    await run_zone_controller()


@_with_lock("zone_verification")
async def _job_zone_verification():
    await run_zone_verification()


@_with_lock("zone_ai_analysis")
async def _job_zone_ai_analysis():
    await run_zone_analysis()


@_with_lock("purge_old_readings")
async def _job_purge_old_readings():
    await purge_old_readings()


@_with_lock("release_maintenance")
async def _job_release_maintenance():
    await release_expired_maintenance_zones()


def _on_job_error(event):
    logger.error("Job %s falhou: %s", event.job_id, event.exception, exc_info=event.traceback)


def _on_job_missed(event):
    logger.warning("Job %s atrasado/pulado (executor lotado ou loop travado)", event.job_id)


scheduler = AsyncIOScheduler()


async def start_scheduler():
    scheduler.add_job(
        _job_poll_variables,
        trigger=IntervalTrigger(seconds=settings.poll_variables_interval),
        id="poll_variables", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_poll_configs,
        trigger=IntervalTrigger(seconds=settings.poll_configs_interval),
        id="poll_configs", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_poll_external_sensors,
        trigger=IntervalTrigger(seconds=settings.poll_variables_interval),
        id="poll_external_sensors", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_consolidated_email,
        trigger=IntervalTrigger(minutes=settings.email_consolidated_interval_minutes),
        id="consolidated_email", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_zone_controller,
        trigger=IntervalTrigger(minutes=5),
        id="zone_controller", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_zone_verification,
        trigger=IntervalTrigger(minutes=3),
        id="zone_verification", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_zone_ai_analysis,
        trigger=IntervalTrigger(minutes=30),
        id="zone_ai_analysis", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_purge_old_readings,
        trigger=IntervalTrigger(hours=24),
        id="purge_old_readings", replace_existing=True, max_instances=1,
    )
    scheduler.add_job(
        _job_release_maintenance,
        trigger=IntervalTrigger(minutes=1),
        id="release_maintenance", replace_existing=True, max_instances=1,
    )

    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
    scheduler.start()


async def stop_scheduler():
    scheduler.shutdown(wait=False)
