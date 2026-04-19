import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from app.config import TELEGRAM_PROXY_URL
from app.config.env import (
    TELEGRAM_API_TOKEN,
    TELEGRAM_ADMIN_ID,
    TELEGRAM_LOGGER_CHANNEL_ID,
)
from app.db import GetSettingsDB
from app.db.crud import get_notification_events_cached
from app.models.notification import Notification, UserNotification
from app.notification.helper import create_text

logger = logging.getLogger(__name__)


class BotManager:
    _instance = None

    @classmethod
    async def get_instance(cls):
        if cls._instance is None and TELEGRAM_API_TOKEN:
            if TELEGRAM_PROXY_URL:
                session = AiohttpSession(proxy=TELEGRAM_PROXY_URL)
            else:
                session = None

            cls._instance = Bot(
                token=TELEGRAM_API_TOKEN,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
                session=session,
            )
            try:
                await cls._instance.get_me()
            except:
                logger.error("Telegram API token is not valid.")
        return cls._instance


async def send_message(
    message: str,
    parse_mode=ParseMode.HTML,
):
    if not (bot := await BotManager.get_instance()):
        return

    for recipient_id in (TELEGRAM_ADMIN_ID or []) + [
        TELEGRAM_LOGGER_CHANNEL_ID
    ]:
        if not recipient_id:
            continue
        try:
            await bot.send_message(
                recipient_id,
                message,
                parse_mode=parse_mode,
            )
        except TelegramAPIError as e:
            logger.error(e)


def _is_event_enabled(notif: Notification) -> bool:
    """Check user-configured per-event toggles for Telegram delivery.

    NULL settings (column never written) means "send everything",
    matching the behaviour shipped before this feature existed.
    Non-user notifications (admin alerts, etc.) are not filterable here.
    """
    action = getattr(notif, "action", None)
    if not isinstance(action, UserNotification.Action):
        return True

    try:
        with GetSettingsDB() as db:
            toggles = get_notification_events_cached(db)
    except Exception:
        logger.exception(
            "Failed to load notification-events settings; sending event %s",
            action.value,
        )
        return True

    if not toggles:
        return True

    return bool(toggles.get(action.value, True))


async def send_notification(notif: Notification):
    if not _is_event_enabled(notif):
        return
    text = create_text(notif)
    await send_message(text)
