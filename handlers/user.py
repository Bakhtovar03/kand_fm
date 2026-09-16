from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from admin_utils import ADMIN_PANEL_CALLBACK, JANOZA_SUBSCRIBERS_KEY, is_janoza_admin
from keyboards.inlinekeyboards import create_inline_keyboards
from lexicon.lexicon import BUTTON_LEXICON, COMMAND_LEXICON
from utils import split_text_for_telegram


user_router = Router()


@user_router.message(CommandStart())
async def start(message: Message):
    # Проверяем, есть ли пользователь в множестве подписчиков janoza_subscribers.
    redis_client = getattr(message.bot, "redis_client")
    is_subscriber = await redis_client.sismember(
        JANOZA_SUBSCRIBERS_KEY,
        message.from_user.id,
    )
    is_admin = await is_janoza_admin(redis_client, message.from_user.id)

    # На старте показываем актуальное действие: подписаться или отменить подписку.
    janoza_button = (
        BUTTON_LEXICON["Cancel_subscription"]
        if is_subscriber
        else BUTTON_LEXICON["janoza"]
    )

    buttons = [
        BUTTON_LEXICON["exchange_rate"],
        janoza_button,
    ]
    if is_admin:
        buttons.append(ADMIN_PANEL_CALLBACK)

    await message.answer(
        text=COMMAND_LEXICON["russian"]["/start"],
        parse_mode=ParseMode.HTML,
        reply_markup=create_inline_keyboards(*buttons),
    )


@user_router.callback_query(F.data == BUTTON_LEXICON["janoza"])
async def subscribe_to_janoza(callback_query: CallbackQuery):
    # ID пользователя сохраняется в Redis-множестве, откуда админская рассылка берет получателей.
    redis_client = getattr(callback_query.bot, "redis_client")
    is_subscriber = await redis_client.sismember(
        JANOZA_SUBSCRIBERS_KEY,
        callback_query.from_user.id,
    )
    if is_subscriber:
        await callback_query.message.answer('Шумо алакай обуна ҳастед✅')
        return

    await redis_client.sadd(JANOZA_SUBSCRIBERS_KEY, callback_query.from_user.id)

    if not callback_query.message:
        return

    # После подписки показываем кнопку отмены, чтобы пользователь мог сам выйти из рассылки.
    await callback_query.message.answer(
        text="шумо обунаро бо бомуваффақият пайваст намудет✅",
        reply_markup=create_inline_keyboards(BUTTON_LEXICON["Cancel_subscription"]),
    )


@user_router.callback_query(F.data == BUTTON_LEXICON["Cancel_subscription"])
async def cancel_janoza_subscription(callback_query: CallbackQuery):
    # Удаление из множества отключает пользователя от будущих фоновых рассылок.
    redis_client = getattr(callback_query.bot, "redis_client")
    removed_count = await redis_client.srem(
        JANOZA_SUBSCRIBERS_KEY,
        callback_query.from_user.id,
    )



    if not callback_query.message:
        return

    await callback_query.message.answer(
        text=(
            "Обуна катъ гардид❌"
            if removed_count
            else "шумо ба обуна пайваст нестед."
        ),
        reply_markup=create_inline_keyboards(BUTTON_LEXICON["janoza"]),
    )


@user_router.callback_query(F.data == BUTTON_LEXICON["exchange_rate"])
async def exchange_rate(callback_query: CallbackQuery):
    # Достаем из Redis заранее подготовленный текст с курсами.
    redis_client = getattr(callback_query.bot, "redis_client")
    rate = await redis_client.hget("exchange_rate", "rate")

    await callback_query.answer()

    if not callback_query.message:
        return

    if not rate:
        await callback_query.message.answer(
            text="Курсы валют пока не загружены.",
            reply_markup=create_inline_keyboards(BUTTON_LEXICON["exchange_rate"])
        )
        return

    # Telegram не принимает сообщения длиннее 4096 символов, поэтому отправляем частями.
    for message_part in split_text_for_telegram(rate):
        await callback_query.message.answer(
            text=message_part,
            parse_mode=ParseMode.HTML,
            reply_markup=create_inline_keyboards(BUTTON_LEXICON["exchange_rate"])
        )
