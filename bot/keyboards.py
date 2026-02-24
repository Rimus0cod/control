"""Keyboard layouts for the bot."""
from typing import List

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def get_main_keyboard(is_authorized: bool = False, is_admin: bool = False) -> InlineKeyboardMarkup:
    """
    Get main keyboard markup.
    
    Args:
        is_authorized: Whether user is authorized
        is_admin: Whether user is admin
        
    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    
    if is_authorized:
        # PC Control buttons - по одной кнопке в ряд для лучшей видимости
        builder.add(
            InlineKeyboardButton(
                text="🔌 Wake PC",
                callback_data="pc_wake"
            ),
        )
        builder.add(
            InlineKeyboardButton(
                text="📊 Status",
                callback_data="pc_status"
            ),
        )
        builder.add(
            InlineKeyboardButton(
                text="🖥 Commands",
                callback_data="pc_commands"
            ),
        )
        builder.add(
            InlineKeyboardButton(
                text="🎮 Dota 2",
                callback_data="dota_status"
            ),
        )
        builder.add(
            InlineKeyboardButton(
                text="🔔 Notifications",
                callback_data="toggle_notifications"
            ),
        )
        
        # Admin buttons
        if is_admin:
            builder.add(
                InlineKeyboardButton(
                    text="👥 Auth Requests",
                    callback_data="admin_auth"
                ),
            )
            builder.add(
                InlineKeyboardButton(
                    text="📝 Logs",
                    callback_data="admin_logs"
                ),
            )
    else:
        # Not authorized
        builder.add(
            InlineKeyboardButton(
                text="🔐 Request Access",
                callback_data="request_auth"
            ),
        )
    
    # Always show help
    builder.add(
        InlineKeyboardButton(
            text="❓ Help",
            callback_data="show_help"
        ),
    )
    
    # Явно указываем по 1 кнопке в ряду
    builder.adjust(1)
    return builder.as_markup()


def get_admin_keyboard() -> InlineKeyboardMarkup:
    """
    Get admin keyboard markup.
    
    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    
    builder.add(
        InlineKeyboardButton(
            text="👥 Auth Requests",
            callback_data="admin_auth"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="📝 Logs",
            callback_data="admin_logs"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="🔌 PC Control",
            callback_data="admin_pc"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="⚙️ Settings",
            callback_data="admin_settings"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="🔙 Back",
            callback_data="back_to_main"
        ),
    )
    
    builder.adjust(1)
    return builder.as_markup()


def get_auth_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """
    Get authorization decision keyboard.
    
    Args:
        user_id: User ID to authorize
        
    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    
    builder.add(
        InlineKeyboardButton(
            text="✅ Approve",
            callback_data=f"auth_approve_{user_id}"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="❌ Reject",
            callback_data=f"auth_reject_{user_id}"
        ),
    )
    
    builder.adjust(1)
    return builder.as_markup()


def get_pc_commands_keyboard() -> InlineKeyboardMarkup:
    """
    Get PC commands keyboard.
    
    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    
    builder.add(
        InlineKeyboardButton(
            text="🔄 Reboot",
            callback_data="pc_reboot"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="⏻ Shutdown",
            callback_data="pc_shutdown"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="📋 Processes",
            callback_data="pc_processes"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="❌ Cancel",
            callback_data="pc_cancel"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="🔙 Back",
            callback_data="back_to_main"
        ),
    )
    
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    """
    Get confirmation keyboard.
    
    Args:
        action: Action to confirm
        
    Returns:
        Inline keyboard markup
    """
    builder = InlineKeyboardBuilder()
    
    builder.add(
        InlineKeyboardButton(
            text="✅ Confirm",
            callback_data=f"confirm_{action}"
        ),
    )
    builder.add(
        InlineKeyboardButton(
            text="❌ Cancel",
            callback_data="cancel_action"
        ),
    )
    
    builder.adjust(1)
    return builder.as_markup()
