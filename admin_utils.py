import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

GLOBAL_ADMIN_LIST = [5393901453]


# Redis-hash с динамическими администраторами: user_id -> имя.
JANOZA_ADMINS_KEY = "janoza_admins"

# Redis-множество с пользователями, которым нужно отправить приглашение.
JANOZA_SUBSCRIBERS_KEY = "janoza_subscribers"

# Пауза между отправками держит рассылку ниже общего лимита Telegram.
JANOZA_MAILING_DELAY_SECONDS = 0.1

# Значения callback_data для административных кнопок.
ADMIN_PANEL_CALLBACK = "admin_panel"
NEW_INVITE_CALLBACK = "новое приглашение"
CONFIRM_INVITE_CALLBACK = "Подтвердить"
RESTART_INVITE_CALLBACK = "Заполнить заново"
ADD_JANOZA_ADMIN_CALLBACK = "add_janoza_admin"
REMOVE_JANOZA_ADMIN_CALLBACK = "remove_janoza_admin"


class IsAdmin(BaseFilter):
    def __init__(self, admin_list: list[int], redis_hash: str = JANOZA_ADMINS_KEY):
        self.admin_list = admin_list
        self.redis_hash = redis_hash

    async def __call__(self, event: Message | CallbackQuery) -> bool:
        # Фильтр используется и для сообщений, и для callback_query.
        redis_client = getattr(event.bot, "redis_client")
        return await is_janoza_admin(
            redis_client=redis_client,
            user_id=event.from_user.id,
            admin_list=self.admin_list,
            redis_hash=self.redis_hash,
        )


async def is_janoza_admin(
    redis_client,
    user_id: int,
    admin_list: list[int] | set[int] | tuple[int, ...] = GLOBAL_ADMIN_LIST,
    redis_hash: str = JANOZA_ADMINS_KEY,
) -> bool:
    """Проверяет администратора через GLOBAL_ADMIN_LIST или Redis hash janoza_admins."""
    if user_id in set(admin_list):
        return True

    try:
        return bool(await redis_client.hexists(redis_hash, str(user_id)))
    except Exception as exc:
        logging.error(f"Redis admin check failed: {exc}")
        return False


def get_janoza_photo_file_id(message: Message) -> str | None:
    return message.photo[-1].file_id if message.photo else None


def is_janoza_form_complete(data: dict) -> bool:
    return bool(data.get("text", "").strip())


def _normalize_subscriber_ids(subscribers: set | list | tuple) -> list[int]:
    """Redis возвращает строки, поэтому приводим ID к int и пропускаем мусор."""
    subscriber_ids = []
    for subscriber in subscribers:
        try:
            subscriber_ids.append(int(subscriber))
        except (TypeError, ValueError):
            logging.warning(f"Invalid janoza subscriber id was skipped: {subscriber}")

    return subscriber_ids


async def _send_janoza_invitation(bot: Bot, chat_id: int, data: dict) -> bool:
    """Отправляет приглашение в чат или канал с учетом Telegram flood control."""
    while True:
        try:
            if data.get("photo_file_id"):
                await bot.send_photo(
                    chat_id=chat_id, photo=data["photo_file_id"],
                    caption=data["text"], parse_mode="HTML",
                )
            else:
                await bot.send_message(chat_id=chat_id, text=data["text"], parse_mode="HTML")
            return True
        except TelegramRetryAfter as exc:
            # Telegram сам сообщает, сколько ждать перед повтором отправки.
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError:
            logging.warning(f"Janoza invitation was not sent to {chat_id}: access forbidden")
            return False
        except TelegramAPIError as exc:
            logging.error(f"Janoza invitation was not sent to {chat_id}: {exc}")
            return False


async def send_janoza_form_to_subscribers(
    bot: Bot,
    redis_client,
    data: dict,
    admin_chat_id: int | None = None,
    channel_id: int | None = None,
) -> None:
    """Публикует форму в канале и рассылает подписчикам из Redis."""
    try:
        channel_status = "Канал: не настроен (CHANNEL_ID не задан)."
        if channel_id is not None:
            channel_sent = await _send_janoza_invitation(bot, channel_id, data)
            channel_status = (
                "Канал: публикация отправлена."
                if channel_sent
                else "Канал: ошибка публикации. Проверьте права бота и CHANNEL_ID."
            )
            await asyncio.sleep(JANOZA_MAILING_DELAY_SECONDS)
        logging.info(channel_status)

        subscribers = await redis_client.smembers(JANOZA_SUBSCRIBERS_KEY)
        subscriber_ids = _normalize_subscriber_ids(subscribers)

        sent_count = 0
        failed_count = 0

        for chat_id in subscriber_ids:
            is_sent = await _send_janoza_invitation(bot, chat_id, data)
            if is_sent:
                sent_count += 1
            else:
                failed_count += 1

            # Даже успешные отправки разводим по времени, чтобы не попасть в общий лимит.
            await asyncio.sleep(JANOZA_MAILING_DELAY_SECONDS)

        logging.info(
            "Janoza mailing finished: sent=%s, failed=%s, total=%s",
            sent_count,
            failed_count,
            len(subscriber_ids),
        )

        if admin_chat_id is not None:
            await bot.send_message(
                chat_id=admin_chat_id,
                text=(
                    f"Рассылка завершена.\n"
                    f"Отправлено: {sent_count}\n"
                    f"Ошибок: {failed_count}\n"
                    f"Всего подписчиков: {len(subscriber_ids)}\n"
                    f"{channel_status}"
                ),
            )
    except Exception as exc:
        logging.error(f"Janoza mailing failed: {exc}")
        if admin_chat_id is not None:
            try:
                await bot.send_message(
                    chat_id=admin_chat_id,
                    text="Рассылка не завершилась из-за ошибки. Подробности записаны в лог.",
                )
            except TelegramAPIError as send_error:
                logging.error(f"Failed to notify admin about janoza mailing error: {send_error}")
