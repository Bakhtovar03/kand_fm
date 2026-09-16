import asyncio
from html import escape

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message, User
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_utils import (
    ADD_JANOZA_ADMIN_CALLBACK,
    ADMIN_PANEL_CALLBACK,
    CONFIRM_INVITE_CALLBACK,
    GLOBAL_ADMIN_LIST,
    IsAdmin,
    JANOZA_ADMINS_KEY,
    JANOZA_FORM_KEY,
    NEW_INVITE_CALLBACK,
    REMOVE_JANOZA_ADMIN_CALLBACK,
    RESTART_INVITE_CALLBACK,
    build_janoza_form_summary,
    build_janoza_redis_mapping,
    build_janoza_saved_summary,
    get_janoza_photo_file_id,
    is_janoza_form_complete,
    send_janoza_form_to_subscribers,
)
from keyboards.inlinekeyboards import create_inline_keyboards


admin_router = Router()

# Все хендлеры этого роутера доступны только администраторам.
admin_router.message.filter(IsAdmin(admin_list=GLOBAL_ADMIN_LIST, redis_hash=JANOZA_ADMINS_KEY))
admin_router.callback_query.filter(IsAdmin(admin_list=GLOBAL_ADMIN_LIST, redis_hash=JANOZA_ADMINS_KEY))


# FSM для админ-панели
class FSMAdmin(StatesGroup):
    # Пользователь находится в панели администратора.
    admin_panel = State()
    # Шаг добавления имени, фамилии и отчества.
    add_name = State()
    # Шаг добавления фото.
    add_photo = State()
    # Шаг добавления места проведения.
    add_location = State()
    # Шаг добавления время проведения.
    add_datetime = State()
    # Шаг добавления даты рождения.
    add_birthday = State()

    # Шаг проверки заполненной формы.
    confirm_invite = State()
    # Шаг добавления администратора через forwarded-сообщение.
    add_admin = State()
    # Состояние просмотра списка удаляемых Redis-администраторов.
    remove_admin = State()


# -------------------- ХЭНДЛЕРЫ --------------------


def build_admin_panel_keyboard():
    return create_inline_keyboards(
        NEW_INVITE_CALLBACK,
        ADD_JANOZA_ADMIN_CALLBACK,
        REMOVE_JANOZA_ADMIN_CALLBACK,
    )


def build_remove_admin_keyboard(admins: dict[str, str]):
    kb_builder = InlineKeyboardBuilder()
    for admin_id, name in sorted(admins.items(), key=lambda item: item[1].casefold()):
        kb_builder.row(
            InlineKeyboardButton(
                text=f"{name} ({admin_id})",
                callback_data=f"{REMOVE_JANOZA_ADMIN_CALLBACK}:{admin_id}",
            )
        )
    kb_builder.row(
        InlineKeyboardButton(
            text="Назад",
            callback_data=ADMIN_PANEL_CALLBACK,
        )
    )
    return kb_builder.as_markup()


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
        reply_markup=build_admin_panel_keyboard(),
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
    await message.answer(
        text="Амал бекор карда шуд.",
        reply_markup=build_admin_panel_keyboard(),
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
            reply_markup=build_admin_panel_keyboard(),
        )
        return

    existing_admin = await redis_client.hget(JANOZA_ADMINS_KEY, admin_id)
    if existing_admin:
        await state.clear()
        await state.set_state(FSMAdmin.admin_panel)
        await message.answer(
            f"{escape(admin_name)} уже есть в списке администраторов.",
            reply_markup=build_admin_panel_keyboard(),
        )
        return

    await redis_client.hset(JANOZA_ADMINS_KEY, admin_id, admin_name)
    await state.clear()
    await state.set_state(FSMAdmin.admin_panel)
    await message.answer(
        f"Администратор добавлен:\n{escape(admin_name)}\nID: <code>{admin_id}</code>",
        reply_markup=build_admin_panel_keyboard(),
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
            reply_markup=build_admin_panel_keyboard(),
        )
        return

    await state.clear()
    await state.set_state(FSMAdmin.remove_admin)
    await callback_query.message.answer(
        "Выберите администратора для удаления:",
        reply_markup=build_remove_admin_keyboard(admins),
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
            reply_markup=build_admin_panel_keyboard(),
        )
    else:
        await callback_query.message.answer(
            "Администратор уже был удален или не найден.",
            reply_markup=build_admin_panel_keyboard(),
        )


@admin_router.callback_query(F.data == NEW_INVITE_CALLBACK)
async def start_new_invite(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message:
        return

    # Новая форма начинается с чистого FSM-контекста.
    await state.clear()
    await state.set_state(FSMAdmin.add_name)
    await callback_query.message.answer("Номи марҳум:")


@admin_router.message(FSMAdmin.add_name)
async def add_invite_name(message: Message, state: FSMContext):
    # На каждом текстовом шаге пустое сообщение не двигает FSM дальше.
    name = (message.text or "").strip()
    if not name:
        await message.answer("номи марҳумро нависед.")
        return

    await state.update_data(name=name)
    await state.set_state(FSMAdmin.add_photo)
    await message.answer("Расми марҳум:")


@admin_router.message(FSMAdmin.add_photo)
async def add_invite_photo(message: Message, state: FSMContext):
    # Фото может прийти как обычное Telegram-фото или как document-изображение.
    photo_file_id = get_janoza_photo_file_id(message)
    if not photo_file_id:
        await message.answer(
            "Расм бояд навъи(формат) расми бошад - jpg,png ..."
        )
        return

    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(FSMAdmin.add_birthday)
    await message.answer("Санаи таваллуди марҳум:")


@admin_router.message(FSMAdmin.add_birthday)
async def add_invite_birthday(message: Message, state: FSMContext):
    # Формат даты пока оставлен свободным, чтобы не ломать текущую логику проекта.
    birthday = (message.text or "").strip()
    if not birthday:
        await message.answer("Санаи таваллудро дуруст нависед.")
        return

    await state.update_data(birthday=birthday)
    await state.set_state(FSMAdmin.add_datetime)
    await message.answer("Санаю вакти ҷаноза:")


@admin_router.message(FSMAdmin.add_datetime)
async def add_invite_datetime(message: Message, state: FSMContext):
    # Дата/время сохраняется текстом для дальнейшей рассылки.
    event_datetime = (message.text or "").strip()
    if not event_datetime:
        await message.answer("Санаю вактро дуруст нависед.")
        return

    await state.update_data(event_datetime=event_datetime)
    await state.set_state(FSMAdmin.add_location)
    await message.answer("Макони ҷаноза:")


@admin_router.message(FSMAdmin.add_location)
async def add_invite_location(message: Message, state: FSMContext):
    # add_location уже есть в FSM, поэтому место включено в итоговую форму.
    location = (message.text or "").strip()
    if not location:
        await message.answer("Маконро дуруст нависед.")
        return

    await state.update_data(location=location)
    data = await state.get_data()

    # Перед Redis-записью админ видит полную форму и явно подтверждает ее.
    await message.answer_photo(
        photo=data["photo_file_id"],
        caption=build_janoza_form_summary(data),
        parse_mode=ParseMode.HTML,
        reply_markup=create_inline_keyboards(
            CONFIRM_INVITE_CALLBACK,
            RESTART_INVITE_CALLBACK,
        ),
    )
    await state.set_state(FSMAdmin.confirm_invite)


@admin_router.callback_query(F.data == CONFIRM_INVITE_CALLBACK, FSMAdmin.confirm_invite)
async def confirm_invite_form(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    data = await state.get_data()

    # Защита от подтверждения устаревшего callback или неполной FSM-сессии.
    if not is_janoza_form_complete(data):
        await state.clear()
        if callback_query.message:
            await callback_query.message.answer(
                "итиллот нопура, Варақаро аз нав пур кунед.",
                reply_markup=build_admin_panel_keyboard(),
            )
        return

    redis_client = getattr(callback_query.bot, "redis_client")
    redis_mapping = build_janoza_redis_mapping(data)
    await redis_client.hset(
        JANOZA_FORM_KEY,
        mapping=redis_mapping,
    )

    # Рассылка запускается в фоне: callback подтверждения не ждет отправку всем подписчикам.
    asyncio.create_task(
        send_janoza_form_to_subscribers(
            bot=callback_query.bot,
            redis_client=redis_client,
            data=redis_mapping,
            admin_chat_id=callback_query.message.chat.id if callback_query.message else None,
        )
    )
    await state.clear()

    if not callback_query.message:
        return

    await callback_query.message.answer(
        text=f"{build_janoza_saved_summary(data)}\n\nНомаҳои хабарӣ фирсонда шуда истодааст.",
        reply_markup=build_admin_panel_keyboard(),
    )


@admin_router.callback_query(F.data == RESTART_INVITE_CALLBACK, FSMAdmin.confirm_invite)
async def restart_invite_form(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    if not callback_query.message:
        await state.clear()
        return

    # Старые временные данные не сохраняются и не используются повторно.
    await state.clear()
    await state.set_state(FSMAdmin.add_name)
    await callback_query.message.answer("номи марҳумро нависед:")
