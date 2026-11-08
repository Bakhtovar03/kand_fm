from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from admin_utils import (
    ADD_JANOZA_ADMIN_CALLBACK, ADMIN_PANEL_CALLBACK, CONFIRM_INVITE_CALLBACK,
    NEW_INVITE_CALLBACK, REMOVE_JANOZA_ADMIN_CALLBACK, RESTART_INVITE_CALLBACK,
)
from lexicon.lexicon import BUTTON_LEXICON


def _keyboard(*actions: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=BUTTON_LEXICON.get(action, action), callback_data=action)]
        for action in actions
    ])


def user_menu_keyboard(is_subscriber: bool, is_admin: bool) -> InlineKeyboardMarkup:
    actions = ["exchange_rate", "Cancel_subscription" if is_subscriber else "janoza"]
    if is_admin:
        actions.append(ADMIN_PANEL_CALLBACK)
    return _keyboard(*actions)


def subscription_keyboard(is_subscriber: bool) -> InlineKeyboardMarkup:
    return _keyboard("Cancel_subscription" if is_subscriber else "janoza")


def exchange_rate_keyboard() -> InlineKeyboardMarkup:
    return _keyboard("exchange_rate")


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return _keyboard(NEW_INVITE_CALLBACK, ADD_JANOZA_ADMIN_CALLBACK, REMOVE_JANOZA_ADMIN_CALLBACK)


def invite_keyboard(confirm: bool = False) -> InlineKeyboardMarkup:
    actions = [CONFIRM_INVITE_CALLBACK, RESTART_INVITE_CALLBACK] if confirm else []
    rows = _keyboard(*actions).inline_keyboard
    rows.append([InlineKeyboardButton(text="Бекор кардан", callback_data=ADMIN_PANEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def remove_admin_keyboard(admins: dict[str, str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"{name} ({admin_id})", callback_data=f"{REMOVE_JANOZA_ADMIN_CALLBACK}:{admin_id}")]
        for admin_id, name in sorted(admins.items(), key=lambda item: item[1].casefold())
    ]
    rows.append([InlineKeyboardButton(text="Назад", callback_data=ADMIN_PANEL_CALLBACK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

