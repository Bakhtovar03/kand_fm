from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from admin_utils import JANOZA_SUBSCRIBERS_KEY, is_janoza_admin
from keyboards.inlinekeyboards import exchange_rate_keyboard, subscription_keyboard, user_menu_keyboard
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

    await message.answer(
        text=COMMAND_LEXICON["/start"],
        parse_mode=ParseMode.HTML,
        reply_markup=user_menu_keyboard(is_subscriber, is_admin),
    )


@user_router.callback_query(F.data.in_({"janoza", BUTTON_LEXICON["janoza"], "Обуна шудан ба чанозахои Конибодом"}))
async def subscribe_to_janoza(callback_query: CallbackQuery):
    await callback_query.answer()

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
        reply_markup=subscription_keyboard(True),
    )


@user_router.callback_query(F.data.in_({"Cancel_subscription", BUTTON_LEXICON["Cancel_subscription"], "қатъ кардани обуна ба ҷаноза"}))
async def cancel_janoza_subscription(callback_query: CallbackQuery):
    await callback_query.answer()

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
        reply_markup=subscription_keyboard(False),
    )


@user_router.callback_query(F.data.in_({"exchange_rate", BUTTON_LEXICON["exchange_rate"]}))
async def exchange_rate(callback_query: CallbackQuery):
    # Достаем из Redis заранее подготовленный текст с курсами.
    redis_client = getattr(callback_query.bot, "redis_client")
    rate = await redis_client.hget("exchange_rate", "rate")

    await callback_query.answer()

    if not callback_query.message:
        return

    if not rate:
        await callback_query.message.answer(
            text="Қурбҳои асъор ҳанӯз боргузорӣ нашудаанд.",
            reply_markup=exchange_rate_keyboard()
        )
        return

    # Telegram не принимает сообщения длиннее 4096 символов, поэтому отправляем частями.
    for message_part in split_text_for_telegram(rate):
        await callback_query.message.answer(
            text=message_part,
            parse_mode=ParseMode.HTML,
            reply_markup=exchange_rate_keyboard()
        )
