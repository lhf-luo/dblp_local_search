"""Dedicated updater scheduler. Cron uses standard Sunday=0 semantics."""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from dblp_local_search.config import Settings
from dblp_local_search.ingestion.update import update


def cron_trigger(expression: str, timezone: str) -> CronTrigger:
    parts = expression.split()
    if len(parts) != 5:
        raise ValueError("DBLP_UPDATE_CRON requires 5 fields")
    minute, hour, day, month, weekday = parts
    # APScheduler numbers Monday=0, unlike conventional crontab Sunday=0.
    if weekday == "0" or weekday == "7":
        weekday = "sun"
    elif weekday in ("1", "2", "3", "4", "5", "6"):
        weekday = ("mon", "tue", "wed", "thu", "fri", "sat")[int(weekday) - 1]
    elif weekday != "*" and weekday.lower() not in (
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ):
        raise ValueError(
            "Use a single weekday 0-7/name or *; weekday ranges unsupported"
        )
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=weekday,
        timezone=timezone,
    )

#设置定时的任务，常驻内存
def run(settings: Settings) -> None:
    scheduler = BlockingScheduler(timezone=settings.timezone)

    def job() -> None:
        try:
            update(settings)
        except Exception:
            logging.exception("DBLP update failed; previous database remains active")

    scheduler.add_job(
        job,
        cron_trigger(settings.update_cron, settings.timezone),
        id="weekly-update",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    print(
        f"Updater waiting: {settings.update_cron} ({settings.timezone}); no startup update",
        flush=True,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=True)
