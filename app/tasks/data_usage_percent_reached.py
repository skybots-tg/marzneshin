from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import NOTIFY_REACHED_USAGE_PERCENT
from app.db.models import User
from app.models.notification import UserNotification
from app.models.user import UserResponse
from app.notification.notifiers import notify
from app.utils.async_utils import fire_and_forget


async def data_usage_percent_reached(db: Session, users_usage: list) -> None:
    """
    Monitors data usage of active users and sends a notification if usage
    crosses NOTIFY_REACHED_USAGE_PERCENT of their data limit on this tick.

    Hot path: this runs every ``record_user_usages_interval`` seconds for
    every user that produced traffic. To keep it cheap we first read only
    the three columns needed to decide who crosses the threshold
    (``id``, ``used_traffic``, ``data_limit``) instead of materialising full
    ORM ``User`` rows (which would eager-join services). Only the few users
    that actually cross the threshold are loaded as ORM objects so we can
    build a ``UserResponse`` for the notification.
    """

    users_usage_dict = {user["id"]: user["value"] for user in users_usage}
    if not users_usage_dict:
        return

    rows = db.execute(
        select(User.id, User.used_traffic, User.data_limit).where(
            User.id.in_(users_usage_dict.keys()),
            User.data_limit.isnot(None),
            User.data_limit > 0,
        )
    ).all()

    crossed_ids: list[int] = []
    for uid, used_traffic, data_limit in rows:
        added = users_usage_dict.get(uid, 0)
        before_pct = (used_traffic / data_limit) * 100
        after_pct = ((used_traffic + added) / data_limit) * 100
        if before_pct < NOTIFY_REACHED_USAGE_PERCENT < after_pct:
            crossed_ids.append(uid)

    if not crossed_ids:
        return

    for user in db.query(User).filter(User.id.in_(crossed_ids)):
        # Reflect the post-update total in the notification payload without
        # persisting it here (phase 3 of record_user_usages owns the write).
        user.used_traffic += users_usage_dict[user.id]
        fire_and_forget(
            notify(
                action=UserNotification.Action.reached_usage_percent,
                user=UserResponse.model_validate(user),
            )
        )

    db.expunge_all()
