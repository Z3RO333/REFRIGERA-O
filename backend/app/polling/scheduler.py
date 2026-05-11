import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from app.config import settings
from app.polling.device_poller import poll_all_devices
from app.polling.configs_poller import poll_configs_for_all
from app.polling.external_sensors_poller import poll_external_sensors
from app.ai.email_manager import send_consolidated_email_job
from app.services.zone_controller import run_zone_controller, run_zone_verification
from app.db.retention import purge_old_readings

logger = logging.getLogger(__name__)


def _on_job_error(event):
    logger.error("Job %s falhou: %s", event.job_id, event.exception, exc_info=event.traceback)


def _on_job_missed(event):
    logger.warning("Job %s atrasado/pulado (executor lotado ou loop travado)", event.job_id)


scheduler = AsyncIOScheduler()

async def start_scheduler():
    scheduler.add_job(
        poll_all_devices,
        trigger=IntervalTrigger(seconds=settings.poll_variables_interval),
        id="poll_variables",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        poll_configs_for_all,
        trigger=IntervalTrigger(seconds=settings.poll_configs_interval),
        id="poll_configs",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        poll_external_sensors,
        trigger=IntervalTrigger(seconds=settings.poll_variables_interval),
        id="poll_external_sensors",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        send_consolidated_email_job,
        trigger=IntervalTrigger(minutes=settings.email_consolidated_interval_minutes),
        id="consolidated_email",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        run_zone_controller,
        trigger=IntervalTrigger(minutes=15),
        id="zone_controller",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        run_zone_verification,
        trigger=IntervalTrigger(minutes=3),
        id="zone_verification",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        purge_old_readings,
        trigger=IntervalTrigger(hours=24),
        id="purge_old_readings",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)

    scheduler.start()

async def stop_scheduler():
    scheduler.shutdown(wait=False)
