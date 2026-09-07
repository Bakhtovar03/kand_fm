from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from lexicon.lexicon import BUTTON_LEXICON


def create_inline_keyboards(*buttons: str):
    kb_builder = InlineKeyboardBuilder()
    kb_builder.row(*[
        InlineKeyboardButton(
            text=BUTTON_LEXICON.get(button,button) ,
            callback_data=str(button)
        ) for button in buttons
    ],width=1)
    return kb_builder.as_markup()


def create_inline_keyboards_callback(buttons:dict[int,str]):
    kb_builder = InlineKeyboardBuilder()
    kb_builder.row(*[
        InlineKeyboardButton(
            text=BUTTON_LEXICON.get(name,name) ,
            callback_data=str(admin_id)
        ) for admin_id,name in buttons.items()
    ],width=1)
    return kb_builder.as_markup()

