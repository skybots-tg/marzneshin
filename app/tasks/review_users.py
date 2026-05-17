import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError

from app import marznode
from app.db import (
    GetDB,
    get_users,
)
from app.models.notification import UserNotification
from app.models.user import (
    UserResponse,
    UserExpireStrategy,
)
from app.notification import notify
from app.utils.async_utils import fire_and_forget

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def _safe_commit(db, user, max_retry=3):
    """Commit with retry on MariaDB 1020 (record changed since last read)."""
    for attempt in range(max_retry):
        try:
            db.commit()
            db.refresh(user)
            return True
        except OperationalError as exc:
            if exc.orig and getattr(exc.orig, "args", (None,))[0] == 1020:
                db.rollback()
                if attempt < max_retry - 1:
                    time.sleep(0.15 * (attempt + 1))
                    db.refresh(user)
                    continue
            raise
    return False


async def review_users():
    now = datetime.utcnow()
    with GetDB() as db:
        for user in get_users(db, activated=True, is_active=False):
            if (
                user.data_limit_reached
                and not user.expired
                and user.enabled
                and not user.removed
            ):
                continue

            marznode.operations.update_user(user, remove=True, db=db)
            user.activated = False
            if not _safe_commit(db, user):
                continue

            fire_and_forget(
                notify(
                    action=UserNotification.Action.user_deactivated,
                    user=UserResponse.model_validate(user),
                )
            )

            logger.info(
                "User `%s` activation state changed to `%s`",
                user.username,
                str(user.activated),
            )

        for user in get_users(
            db,
            expire_strategy=UserExpireStrategy.START_ON_FIRST_USE,
            is_active=True,
        ):
            base_time = user.edit_at or user.created_at

            if not (
                (user.online_at and base_time <= user.online_at)
                or (
                    user.activation_deadline
                    and (user.activation_deadline <= now)
                )
            ):
                continue

            user.expire_date = datetime.utcnow() + timedelta(
                seconds=user.usage_duration
            )
            user.expire_strategy = UserExpireStrategy.FIXED_DATE
            _safe_commit(db, user)
            logger.info("on hold user `%s` has been activated", user.username)
