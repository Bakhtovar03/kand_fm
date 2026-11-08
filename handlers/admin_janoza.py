import asyncio
from html import escape

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User

from admin_utils import (
    ADD_JANOZA_ADMIN_CALLBACK,
    ADMIN_PANEL_CALLBACK,
    CONFIRM_INVITE_CALLBACK,
    GLOBAL_ADMIN_LIST,
    IsAdmin,
    JANOZA_ADMINS_KEY,
    NEW_INVITE_CALLBACK,
    REMOVE_JANOZA_ADMIN_CALLBACK,
    RESTART_INVITE_CALLBACK,
    get_janoza_photo_file_id,
    is_janoza_form_complete,
    send_janoza_form_to_subscribers,
)
from keyboards.inlinekeyboards import admin_panel_keyboard, invite_keyboard, remove_admin_keyboard


admin_router = Router()

# Все хендлеры этого роутера доступны только администраторам.
admin_router.message.filter(IsAdmin(admin_list=GLOBAL_ADMIN_LIST, redis_hash=JANOZA_ADMINS_KEY))
admin_router.callback_query.filter(IsAdmin(admin_list=GLOBAL_ADMIN_LIST, redis_hash=JANOZA_ADMINS_KEY))


# FSM для админ-панели
class FSMAdmin(StatesGroup):
    # Пользователь находится в панели администратора.
    admin_panel = State()
    add_content = State()

    # Шаг проверки заполненной формы.
    confirm_invite = State()
    # Шаг добавления администратора через forwarded-сообщение.
    add_admin = State()
    # Состояние просмотра списка удаляемых Redis-администраторов.
    remove_admin = State()


# -------------------- ХЭНДЛЕРЫ --------------------


def get_forwarded_user(message: Message) -> User | None:
    user = getattr(message, "forward_from", None)
    if user:
        return user

    forward_origin = getattr(message, "forward_origin", None)
    if getattr(forward_origin, "type", None) == "user":
        return getattr(forward_origin, "sender_user", None)

    return None


def build_admin_name(user: User) -> str:
    name = user.full_name or user.username or str(user.id)
    if user.username:
        return f"{name} (@{user.username})"
    return name


async def show_admin_panel(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)
    await message.answer(
        text="Панели маъмури",
        reply_markup=admin_panel_keyboard(),
    )


# /admin - показать панель администратора
@admin_router.message(Command(commands="admin"))
async def admin_buttons(message: Message, state: FSMContext):
    # /admin всегда возвращает администратора в главное меню панели.
    await show_admin_panel(message, state)


@admin_router.callback_query(F.data == ADMIN_PANEL_CALLBACK)
async def open_admin_panel(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    if callback_query.message:
        await show_admin_panel(callback_query.message, state)


@admin_router.message(Command(commands="cancel"))
async def cancel_admin_action(message: Message, state: FSMContext):
    # Команда отмены сбрасывает незавершенное заполнение формы.
    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)
    await message.answer(
        text="Амал бекор карда шуд.",
        reply_markup=admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == ADD_JANOZA_ADMIN_CALLBACK)
async def start_add_admin(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message:
        return

    await state.clear()
    await state.set_state(FSMAdmin.add_admin)
    await callback_query.message.answer(
        "Перешлите любое сообщение от пользователя, которого нужно назначить администратором."
    )


@admin_router.message(FSMAdmin.add_admin)
async def add_admin_from_forwarded_message(message: Message, state: FSMContext):
    forwarded_user = get_forwarded_user(message)
    if not forwarded_user:
        await message.answer(
            "Не удалось получить ID автора. Перешлите обычное сообщение пользователя без скрытого профиля."
        )
        return

    redis_client = getattr(message.bot, "redis_client")
    admin_id = str(forwarded_user.id)
    admin_name = build_admin_name(forwarded_user)

    if forwarded_user.id in GLOBAL_ADMIN_LIST:
        await state.clear()
        await state.set_state(FSMAdmin.admin_panel)
        await message.answer(
            f"{escape(admin_name)} уже является глобальным администратором.",
            reply_markup=admin_panel_keyboard(),
        )
        return

    existing_admin = await redis_client.hget(JANOZA_ADMINS_KEY, admin_id)
    if existing_admin:
        await state.clear()
        await state.set_state(FSMAdmin.admin_panel)
        await message.answer(
            f"{escape(admin_name)} уже есть в списке администраторов.",
            reply_markup=admin_panel_keyboard(),
        )
        return

    await redis_client.hset(JANOZA_ADMINS_KEY, admin_id, admin_name)
    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)
    await message.answer(
        f"Администратор добавлен:\n{escape(admin_name)}\nID: <code>{admin_id}</code>",
        reply_markup=admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == REMOVE_JANOZA_ADMIN_CALLBACK)
async def start_remove_admin(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message:
        return

    redis_client = getattr(callback_query.bot, "redis_client")
    admins = await redis_client.hgetall(JANOZA_ADMINS_KEY)
    if not admins:
        await callback_query.message.answer(
            "В списке администраторов пока никого нет.",
            reply_markup=admin_panel_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(FSMAdmin.remove_admin)
    await callback_query.message.answer(
        "Выберите администратора для удаления:",
        reply_markup=remove_admin_keyboard(admins),
    )


@admin_router.callback_query(F.data.startswith(f"{REMOVE_JANOZA_ADMIN_CALLBACK}:"))
async def remove_admin(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message or not callback_query.data:
        return

    admin_id = callback_query.data.split(":", 1)[1]
    redis_client = getattr(callback_query.bot, "redis_client")
    admin_name = await redis_client.hget(JANOZA_ADMINS_KEY, admin_id)
    removed_count = await redis_client.hdel(JANOZA_ADMINS_KEY, admin_id)

    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)
    if removed_count:
        name_text = f"\n{escape(admin_name)}" if admin_name else ""
        await callback_query.message.answer(
            f"Администратор удален:{name_text}\nID: <code>{escape(admin_id)}</code>",
            reply_markup=admin_panel_keyboard(),
        )
    else:
        await callback_query.message.answer(
            "Администратор уже был удален или не найден.",
            reply_markup=admin_panel_keyboard(),
        )


@admin_router.callback_query(F.data == NEW_INVITE_CALLBACK)
async def start_new_invite(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message:
        return

    await state.clear()
    await state.set_state(FSMAdmin.add_content)
    await callback_query.message.answer(
        "Матни хабарро фиристед ё расмро бо матн дар шарҳ фиристед. Расм ҳатмӣ нест.",
        reply_markup=invite_keyboard(),
    )


@admin_router.message(FSMAdmin.add_content)
async def add_invite_content(message: Message, state: FSMContext):
    if message.media_group_id:
        await message.answer("Як расм фиристед, на албом.", reply_markup=invite_keyboard())
        return
    data = await state.get_data()
    photo = get_janoza_photo_file_id(message)
    if not message.text and not photo:
        await message.answer("Матн ё расмро ҳамчун акс фиристед.", reply_markup=invite_keyboard())
        return
    photo = photo or data.get("photo_file_id", "")
    text = message.text or message.caption or ""
    if not text.strip():
        await state.update_data(photo_file_id=photo)
        await message.answer("Акнун матни хабарро фиристед.", reply_markup=invite_keyboard())
        return
    limit = 1024 if photo else 4096
    if len(text.encode("utf-16-le")) // 2 > limit:
        await state.update_data(photo_file_id=photo)
        await message.answer(f"Матн хеле дароз аст. То {limit} аломат фиристед.", reply_markup=invite_keyboard())
        return
    content = message.html_text if message.text else message.html_caption
    keyboard = invite_keyboard(confirm=True)
    if photo:
        await message.answer_photo(photo=photo, caption=content, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    else:
        await message.answer(content, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    await state.update_data(text=content, photo_file_id=photo)
    await state.set_state(FSMAdmin.confirm_invite)


@admin_router.callback_query(F.data == CONFIRM_INVITE_CALLBACK, FSMAdmin.confirm_invite)
async def confirm_invite_form(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()

    # Защита от подтверждения устаревшего callback или неполной FSM-сессии.
    if not is_janoza_form_complete(data):
        await state.clear()
        await state.set_state(FSMAdmin.admin_panel)
        if callback_query.message:
            await callback_query.message.answer(
                "итиллот нопура, Варақаро аз нав пур кунед.",
                reply_markup=admin_panel_keyboard(),
            )
        return

    redis_client = getattr(callback_query.bot, "redis_client")
    mailing_data = {"text": data["text"], "photo_file_id": data.get("photo_file_id", "")}

    # Рассылка запускается в фоне: callback подтверждения не ждет отправку всем подписчикам.
    asyncio.create_task(
        send_janoza_form_to_subscribers(
            bot=callback_query.bot,
            redis_client=redis_client,
            data=mailing_data,
            admin_chat_id=callback_query.message.chat.id if callback_query.message else None,
            channel_id=getattr(callback_query.bot, "channel_id", None),
        )
    )
    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)

    if not callback_query.message:
        return

    await callback_query.message.answer(
        text="Номаҳои хабарӣ фирсонда шуда истодааст.",
        reply_markup=admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == RESTART_INVITE_CALLBACK, FSMAdmin.confirm_invite)
async def restart_invite_form(callback_query: CallbackQuery, state: FSMContext):
    await start_new_invite(callback_query, state)
