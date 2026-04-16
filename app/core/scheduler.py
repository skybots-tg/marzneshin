import logging
import os
import tempfile
from functools import wraps

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.settings import settings
from app.tasks import (
    aggregate_old_usages,
    check_pool_health,
    cleanup_ai_backups,
    record_user_usages,
    reset_user_data_usage,
    review_users,
    expire_days_reached,
)

logger = logging.getLogger(__name__)

_LOCK_DIR = os.path.join(tempfile.gettempdir(), "marzneshin_locks")
os.makedirs(_LOCK_DIR, exist_ok=True)


def single_instance(func):
    """Prevent concurrent execution across workers using an exclusive file lock.

    When multiple Uvicorn workers run the same scheduled task, only one
    acquires the lock; the others skip that tick silently.
    """
    lock_path = os.path.join(_LOCK_DIR, f"{func.__name__}.lock")

    @wraps(func)
    async def wrapper(*args, **kwargs):
        fd = None
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return
        except OSError as exc:
            logger.debug("Lock acquire failed for %s: %s", func.__name__, exc)
            return
        try:
            return await func(*args, **kwargs)
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(lock_path)
            except OSError:
                pass

    return wrapper


_record_user_usages = single_instance(record_user_usages)
_review_users = single_instance(review_users)
_expire_days_reached = single_instance(expire_days_reached)
_reset_user_data_usage = single_instance(reset_user_data_usage)
_aggregate_old_usages = single_instance(aggregate_old_usages)
_cleanup_ai_backups = single_instance(cleanup_ai_backups)


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    scheduler.add_job(
        _record_user_usages,
        "interval",
        coalesce=True,
        seconds=settings.tasks.record_user_usages_interval,
        max_instances=1,
    )
    scheduler.add_job(
        _review_users,
        "interval",
        seconds=settings.tasks.review_users_interval,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _expire_days_reached,
        "interval",
        seconds=settings.tasks.expire_days_reached_interval,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _reset_user_data_usage,
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
        _aggregate_old_usages,
        "cron",
        hour=3,
        minute=0,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _cleanup_ai_backups,
        "cron",
        hour=4,
        minute=0,
        coalesce=True,
        max_instances=1,
    )

    return scheduler
