from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.settings import settings
from app.tasks import (
    aggregate_old_usages,
    check_pool_health,
    record_user_usages,
    reset_user_data_usage,
    review_users,
    expire_days_reached,
)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        record_user_usages,
        "interval",
        coalesce=True,
        seconds=settings.tasks.record_user_usages_interval,
        max_instances=1,
    )
    scheduler.add_job(
        review_users,
        "interval",
        seconds=settings.tasks.review_users_interval,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        expire_days_reached,
        "interval",
        seconds=settings.tasks.expire_days_reached_interval,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        reset_user_data_usage,
        "interval",
        seconds=settings.tasks.reset_user_data_usage,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        check_pool_health,
        "interval",
        seconds=15,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        aggregate_old_usages,
        "cron",
        hour=3,
        minute=0,
        coalesce=True,
        max_instances=1,
    )

    return scheduler
