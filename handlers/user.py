from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from keyboards.inlinekeyboards import create_inline_keyboards
from lexicon.lexicon import BUTTON_LEXICON, COMMAND_LEXICON
from utils import split_text_for_telegram


user_router = Router()


@user_router.message(CommandStart() or Command("/start"))
async def start(message: Message):
    # Показываем приветствие и кнопку для запроса курсов валют.
    await message.answer(
        text=COMMAND_LEXICON["russian"]["/start"],
        parse_mode=ParseMode.HTML,
        reply_markup=create_inline_keyboards(BUTTON_LEXICON["exchange_rate"]),
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




