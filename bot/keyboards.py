"""Keyboard layouts for the bot."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_keyboard(
    is_authorized: bool = False,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    """Main keyboard: shown after /start."""
    builder = InlineKeyboardBuilder()

    if is_authorized:
        builder.add(InlineKeyboardButton(text="Wake PC", callback_data="pc_wake"))
        builder.add(InlineKeyboardButton(text="Статус ПК", callback_data="pc_status"))
        builder.add(InlineKeyboardButton(text="Управление ПК", callback_data="pc_commands"))
        builder.add(InlineKeyboardButton(text="Dota 2", callback_data="dota_status"))
        builder.add(InlineKeyboardButton(text="Уведомления", callback_data="toggle_notifications"))

        if is_admin:
            builder.add(InlineKeyboardButton(text="Запросы доступа", callback_data="admin_auth"))
            builder.add(InlineKeyboardButton(text="Логи", callback_data="admin_logs"))
    else:
        builder.add(InlineKeyboardButton(text="Запросить доступ", callback_data="request_auth"))

    builder.add(InlineKeyboardButton(text="Помощь", callback_data="show_help"))
    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Admin panel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Запросы доступа", callback_data="admin_auth"))
    builder.add(InlineKeyboardButton(text="Логи", callback_data="admin_logs"))
    builder.add(InlineKeyboardButton(text="Управление ПК", callback_data="pc_commands"))
    builder.add(InlineKeyboardButton(text="Настройки", callback_data="admin_settings"))
    builder.add(InlineKeyboardButton(text="Назад", callback_data="back_to_main"))
    builder.adjust(1)
    return builder.as_markup()


def get_auth_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Approve / reject a specific user."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Одобрить", callback_data=f"auth_approve_{user_id}"))
    builder.add(InlineKeyboardButton(text="Отклонить", callback_data=f"auth_reject_{user_id}"))
    builder.adjust(2)
    return builder.as_markup()


def get_pc_commands_keyboard() -> InlineKeyboardMarkup:
    """PC control submenu."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Перезагрузка", callback_data="pc_reboot"))
    builder.add(InlineKeyboardButton(text="Выключение", callback_data="pc_shutdown"))
    builder.add(InlineKeyboardButton(text="Отменить", callback_data="pc_cancel"))
    builder.add(InlineKeyboardButton(text="Процессы", callback_data="pc_processes"))
    builder.add(InlineKeyboardButton(text="Скриншот", callback_data="pc_screenshot"))
    builder.add(InlineKeyboardButton(text="Статус", callback_data="pc_status"))
    builder.add(InlineKeyboardButton(text="Назад", callback_data="back_to_main"))
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def get_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """Confirmation dialog for destructive actions."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Подтвердить", callback_data=f"confirm_{action}"))
    builder.add(InlineKeyboardButton(text="Отмена", callback_data="cancel_action"))
    builder.adjust(2)
    return builder.as_markup()


def get_dota_keyboard() -> InlineKeyboardMarkup:
    """Dota 2 submenu."""
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Статус игрока", callback_data="dota_status"))
    builder.add(InlineKeyboardButton(text="Live матч", callback_data="dota_live"))
    builder.add(InlineKeyboardButton(text="История матчей", callback_data="dota_history"))
    builder.add(InlineKeyboardButton(text="Назад", callback_data="back_to_main"))
    builder.adjust(2, 1, 1)
    return builder.as_markup()