"""
User profile / registration handler.

Allows each authorised user to store their own PC and Steam settings.
All fields are optional — the bot falls back to global .env values if
a user hasn't set a field.

Commands:
  /profile        — show current profile + edit button
  /setprofile     — start the step-by-step registration wizard

FSM states (ProfileSetup):
  mac → ip → broadcast → username → password → domain →
  steam_api_key → steam_account_id → [done]

Each step shows a "Пропустить" (skip) button so the user doesn't
have to fill every field.
"""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard
from database import DatabaseRepository
from utils import get_logger
from utils.validators import validate_mac_address, validate_ip_address

router = Router()
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# FSM States
# ---------------------------------------------------------------------------

class ProfileSetup(StatesGroup):
    mac         = State()
    ip          = State()
    broadcast   = State()
    username    = State()
    password    = State()
    domain      = State()
    steam_key   = State()
    steam_id    = State()


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _skip_kb(cancel: bool = True) -> InlineKeyboardMarkup:
    """Inline keyboard with Skip (and optionally Cancel) buttons."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Пропустить", callback_data="profile_skip"))
    if cancel:
        builder.add(InlineKeyboardButton(text="Отмена", callback_data="profile_cancel"))
    builder.adjust(2)
    return builder.as_markup()


def _profile_view_kb() -> InlineKeyboardMarkup:
    """Keyboard shown when viewing the profile."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Редактировать", callback_data="profile_edit"))
    builder.add(InlineKeyboardButton(text="Сбросить профиль", callback_data="profile_reset"))
    builder.add(InlineKeyboardButton(text="Назад", callback_data="back_to_main"))
    builder.adjust(2, 1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value: str | None, masked: bool = False) -> str:
    """Format a profile field for display. Masks passwords."""
    if value is None:
        return "<i>не задано</i>"
    if masked:
        return "••••••"
    return f"<code>{value}</code>"


def _build_profile_text(profile) -> str:
    """Build HTML profile summary from a UserProfile ORM object (or None)."""
    if profile is None:
        return (
            "<b>Ваш профиль пуст.</b>\n\n"
            "Используйте /setprofile чтобы заполнить настройки.\n"
            "Все поля опциональны — незаполненные будут взяты из глобальных настроек бота."
        )

    return (
        "<b>Ваш профиль</b>\n\n"
        "<b>Wake-on-LAN / Сеть</b>\n"
        f"MAC-адрес:    {_fmt(profile.pc_mac_address)}\n"
        f"IP-адрес:     {_fmt(profile.pc_ip_address)}\n"
        f"Broadcast:    {_fmt(profile.pc_broadcast_address)}\n\n"
        "<b>Учётные данные ПК</b>\n"
        f"Пользователь: {_fmt(profile.pc_username)}\n"
        f"Пароль:       {_fmt(profile.pc_password, masked=True)}\n"
        f"Домен:        {_fmt(profile.pc_domain)}\n\n"
        "<b>Dota 2 / Steam</b>\n"
        f"Steam API Key: {_fmt(profile.dota2_steam_api_key, masked=True)}\n"
        f"Account ID:    {_fmt(profile.dota2_account_id)}"
    )


# ---------------------------------------------------------------------------
# /profile — view
# ---------------------------------------------------------------------------

@router.message(Command("profile"), IsAuthorized())
async def cmd_profile(message: Message) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Профиль недоступен.")
        return

    profile = await db.get_user_profile(user.id)
    await message.answer(
        _build_profile_text(profile),
        parse_mode="HTML",
        reply_markup=_profile_view_kb(),
    )


@router.callback_query(F.data == "show_profile", IsAuthorized())
async def callback_show_profile(callback: CallbackQuery) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Профиль недоступен.", show_alert=True)
        return

    profile = await db.get_user_profile(user.id)
    await callback.message.answer(
        _build_profile_text(profile),
        parse_mode="HTML",
        reply_markup=_profile_view_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Profile reset
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "profile_reset", IsAuthorized())
async def callback_profile_reset(callback: CallbackQuery) -> None:
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Ошибка.", show_alert=True)
        return

    deleted = await db.delete_user_profile(user.id)
    if deleted:
        await callback.message.answer(
            "Профиль сброшен. Теперь используются глобальные настройки бота.",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
        )
        await db.add_log_entry(action="profile_reset", user_id=user.id)
    else:
        await callback.message.answer("Профиль уже пуст.")
    await callback.answer()


# ---------------------------------------------------------------------------
# /setprofile — start wizard
# ---------------------------------------------------------------------------

@router.message(Command("setprofile"), IsAuthorized())
@router.callback_query(F.data == "profile_edit", IsAuthorized())
async def start_profile_setup(event: Message | CallbackQuery, state: FSMContext) -> None:
    """Entry point: start the profile setup wizard."""
    msg = event if isinstance(event, Message) else event.message
    await state.clear()
    await state.set_state(ProfileSetup.mac)
    await msg.answer(
        "<b>Настройка профиля</b> — шаг 1 из 8\n\n"
        "Введите <b>MAC-адрес</b> вашего ПК для Wake-on-LAN.\n"
        "Формат: <code>28:EE:52:00:0C:CA</code>\n\n"
        "Нажмите <b>Пропустить</b> если не нужно.",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    if isinstance(event, CallbackQuery):
        await event.answer()


# ---------------------------------------------------------------------------
# Step 1: MAC address
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.mac)
async def step_mac(message: Message, state: FSMContext) -> None:
    value = message.text.strip() if message.text else ""
    if value and not validate_mac_address(value):
        await message.answer(
            "Некорректный MAC-адрес. Попробуйте снова или нажмите Пропустить.\n"
            "Формат: <code>28:EE:52:00:0C:CA</code>",
            parse_mode="HTML",
            reply_markup=_skip_kb(),
        )
        return
    if value:
        await state.update_data(pc_mac_address=value.upper())
    await state.set_state(ProfileSetup.ip)
    await message.answer(
        "<b>Шаг 2 из 8</b>\n\nВведите <b>IP-адрес</b> вашего ПК.\n"
        "Пример: <code>192.168.0.104</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.mac)
async def skip_mac(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.ip)
    await callback.message.answer(
        "<b>Шаг 2 из 8</b>\n\nВведите <b>IP-адрес</b> вашего ПК.\n"
        "Пример: <code>192.168.0.104</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 2: IP address
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.ip)
async def step_ip(message: Message, state: FSMContext) -> None:
    value = message.text.strip() if message.text else ""
    if value and not validate_ip_address(value):
        await message.answer(
            "Некорректный IP-адрес. Попробуйте снова.",
            reply_markup=_skip_kb(),
        )
        return
    if value:
        await state.update_data(pc_ip_address=value)
    await state.set_state(ProfileSetup.broadcast)
    await message.answer(
        "<b>Шаг 3 из 8</b>\n\nВведите <b>Broadcast-адрес</b> сети.\n"
        "Пример: <code>192.168.0.255</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.ip)
async def skip_ip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.broadcast)
    await callback.message.answer(
        "<b>Шаг 3 из 8</b>\n\nВведите <b>Broadcast-адрес</b> сети.\n"
        "Пример: <code>192.168.0.255</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 3: Broadcast address
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.broadcast)
async def step_broadcast(message: Message, state: FSMContext) -> None:
    value = message.text.strip() if message.text else ""
    if value and not validate_ip_address(value):
        await message.answer(
            "Некорректный broadcast-адрес. Попробуйте снова.",
            reply_markup=_skip_kb(),
        )
        return
    if value:
        await state.update_data(pc_broadcast_address=value)
    await state.set_state(ProfileSetup.username)
    await message.answer(
        "<b>Шаг 4 из 8</b>\n\nВведите <b>имя пользователя</b> на ПК.\n"
        "Пример: <code>diff</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.broadcast)
async def skip_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.username)
    await callback.message.answer(
        "<b>Шаг 4 из 8</b>\n\nВведите <b>имя пользователя</b> на ПК.\n"
        "Пример: <code>diff</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 4: PC username
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.username)
async def step_username(message: Message, state: FSMContext) -> None:
    if message.text:
        await state.update_data(pc_username=message.text.strip())
    await state.set_state(ProfileSetup.password)
    await message.answer(
        "<b>Шаг 5 из 8</b>\n\nВведите <b>пароль</b> пользователя на ПК.\n"
        "Пароль скрывается в интерфейсе бота и хранится локально в БД бота.\n"
        "Вводите его только если это действительно нужно.",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.username)
async def skip_username(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.password)
    await callback.message.answer(
        "<b>Шаг 5 из 8</b>\n\nВведите <b>пароль</b> пользователя на ПК.",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 5: PC password
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.password)
async def step_password(message: Message, state: FSMContext) -> None:
    if message.text:
        await state.update_data(pc_password=message.text.strip())
        # Delete the message to avoid password being visible in chat
        try:
            await message.delete()
        except Exception:
            pass
    await state.set_state(ProfileSetup.domain)
    await message.answer(
        "<b>Шаг 6 из 8</b>\n\nВведите <b>домен</b> (для Windows) или оставьте пустым.\n"
        "Пример: <code>WORKGROUP</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.password)
async def skip_password(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.domain)
    await callback.message.answer(
        "<b>Шаг 6 из 8</b>\n\nВведите <b>домен</b> (WORKGROUP или имя домена).",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 6: Domain
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.domain)
async def step_domain(message: Message, state: FSMContext) -> None:
    if message.text:
        await state.update_data(pc_domain=message.text.strip())
    await state.set_state(ProfileSetup.steam_key)
    await message.answer(
        "<b>Шаг 7 из 8</b>\n\nВведите ваш <b>Steam Web API Key</b>.\n"
        "Получить: <a href='https://steamcommunity.com/dev/apikey'>steamcommunity.com/dev/apikey</a>",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.domain)
async def skip_domain(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.steam_key)
    await callback.message.answer(
        "<b>Шаг 7 из 8</b>\n\nВведите ваш <b>Steam Web API Key</b>.",
        parse_mode="HTML",
        reply_markup=_skip_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 7: Steam API key
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.steam_key)
async def step_steam_key(message: Message, state: FSMContext) -> None:
    if message.text:
        await state.update_data(dota2_steam_api_key=message.text.strip())
        try:
            await message.delete()
        except Exception:
            pass
    await state.set_state(ProfileSetup.steam_id)
    await message.answer(
        "<b>Шаг 8 из 8</b>\n\nВведите ваш <b>Steam Account ID</b> (32-bit).\n"
        "Пример: <code>1187895410</code>\n\n"
        "Найти можно на <a href='https://steamid.io'>steamid.io</a> — строка <b>steamID3</b> без скобок.",
        parse_mode="HTML",
        reply_markup=_skip_kb(cancel=False),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "profile_skip", ProfileSetup.steam_key)
async def skip_steam_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileSetup.steam_id)
    await callback.message.answer(
        "<b>Шаг 8 из 8</b>\n\nВведите ваш <b>Steam Account ID</b>.\n"
        "Пример: <code>1187895410</code>",
        parse_mode="HTML",
        reply_markup=_skip_kb(cancel=False),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 8: Steam Account ID — final step → save
# ---------------------------------------------------------------------------

@router.message(ProfileSetup.steam_id)
async def step_steam_id(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text:
        await state.update_data(dota2_account_id=message.text.strip())
    await _save_profile(message, state, bot)


@router.callback_query(F.data == "profile_skip", ProfileSetup.steam_id)
async def skip_steam_id(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await _save_profile(callback.message, state, bot, telegram_id=callback.from_user.id)
    await callback.answer()


async def _save_profile(
    message: Message,
    state: FSMContext,
    bot: Bot,
    telegram_id: int | None = None,
) -> None:
    """Persist collected data and finish the wizard."""
    data = await state.get_data()
    await state.clear()

    if not data:
        await message.answer(
            "Вы не заполнили ни одного поля. Профиль не сохранён.",
            reply_markup=get_main_keyboard(is_authorized=True),
        )
        return

    tid = telegram_id or message.chat.id
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(tid)
    if not user:
        await message.answer("Ошибка: пользователь не найден.")
        return

    profile = await db.upsert_user_profile(user.id, **data)

    await db.add_log_entry(
        action="profile_updated",
        user_id=user.id,
        details=f"fields: {list(data.keys())}",
    )

    await message.answer(
        "<b>Профиль сохранён!</b>\n\n"
        + _build_profile_text(profile),
        parse_mode="HTML",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin),
    )


# ---------------------------------------------------------------------------
# Cancel wizard at any step
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "profile_cancel")
async def cancel_profile_setup(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    await callback.message.answer(
        "Настройка профиля отменена.",
        reply_markup=get_main_keyboard(
            is_authorized=True,
            is_admin=user.is_admin if user else False,
        ),
    )
    await callback.answer()
