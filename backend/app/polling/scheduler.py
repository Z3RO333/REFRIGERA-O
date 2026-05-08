from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.config import settings
from app.polling.device_poller import poll_all_devices
from app.polling.configs_poller import poll_configs_for_all
from app.polling.external_sensors_poller import poll_external_sensors
from app.ai.email_manager import send_consolidated_email_job

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

    scheduler.start()

async def stop_scheduler():
    scheduler.shutdown(wait=False)
