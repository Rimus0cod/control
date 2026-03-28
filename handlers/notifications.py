"""Notifications handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard, get_admin_keyboard
from database import DatabaseRepository
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("notify"))
async def cmd_notify(message: Message, bot: Bot):
    """Handle /notify command to toggle notifications."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    # Toggle notifications
    user.notifications_enabled = not user.notifications_enabled
    await db.update_user(user)
    
    status = "enabled" if user.notifications_enabled else "disabled"
    
    await message.answer(
        f"🔔 Notifications {status}!",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
    )
    
    # Log action
    await db.add_log_entry(
        action=f"notifications_{status}",
        user_id=user.id,
    )


@router.callback_query(F.data == "toggle_notifications", IsAuthorized())
async def callback_toggle_notifications(callback: CallbackQuery, bot: Bot):
    """Handle notifications toggle button."""
    db = DatabaseRepository()
    
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    
    if not user:
        await callback.answer("User not found!", show_alert=True)
        return
    
    # Toggle notifications
    user.notifications_enabled = not user.notifications_enabled
    await db.update_user(user)
    
    status = "enabled" if user.notifications_enabled else "disabled"
    
    await callback.message.answer(
        f"🔔 Notifications {status}!",
        reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
    )
    
    await callback.answer()


@router.message(Command("logs"))
async def cmd_logs(message: Message, bot: Bot):
    """Handle /logs command."""
    # Check if admin
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not authorized to use this command.")
        return
    
    db = DatabaseRepository()
    logs = await db.get_log_entries(limit=20)
    
    if not logs:
        await message.answer("No logs found.")
        return
    
    text = "<b>📝 Recent Logs</b>\n\n"
    
    for log in logs:
        timestamp = log.created_at.strftime("%H:%M:%S")
        action = log.action
        details = log.details or ""
        
        text += f"<code>{timestamp}</code> {action}"
        if details:
            text += f" - {details}"
        text += "\n"
    
    await message.answer(
        text[:4000],
        parse_mode="HTML",
        reply_markup=get_admin_keyboard()
    )


@router.callback_query(F.data == "admin_logs")
async def callback_admin_logs(callback: CallbackQuery, bot: Bot):
    """Handle admin logs view."""
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    db = DatabaseRepository()
    logs = await db.get_log_entries(limit=20)
    
    if not logs:
        await callback.message.answer(
            "No logs found.",
            reply_markup=get_admin_keyboard()
        )
    else:
        text = "<b>📝 Recent Logs</b>\n\n"
        
        for log in logs:
            timestamp = log.created_at.strftime("%H:%M:%S")
            action = log.action
            details = log.details or ""
            
            text += f"<code>{timestamp}</code> {action}"
            if details:
                text += f" - {details}"
            text += "\n"
        
        await callback.message.answer(
            text[:4000],
            parse_mode="HTML",
            reply_markup=get_admin_keyboard()
        )
    
    await callback.answer()


@router.callback_query(F.data == "back_to_main")
async def callback_back_to_main(callback: CallbackQuery, bot: Bot):
    """Handle back to main menu."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    
    is_auth = user and user.is_authorized
    is_admin = user and user.is_admin
    
    await callback.message.answer(
        "🏠 Main Menu",
        reply_markup=get_main_keyboard(is_authorized=is_auth, is_admin=is_admin)
    )
    await callback.answer()


@router.callback_query(F.data == "show_help")
async def callback_show_help(callback: CallbackQuery):
    """Handle help button."""
    help_text = (
        "<b>📖 Help</b>\n\n"
        "This bot provides remote control for a Windows PC.\n\n"
        "<b>Features:</b>\n"
        "• Wake-on-LAN - Power on PC remotely\n"
        "• PC Control - Reboot, shutdown, execute commands\n"
        "• Dota 2 - Track player status and matches\n"
        "• Notifications - Get alerts about PC and game status\n\n"
        "<b>Commands:</b>\n"
        "• /start - Start the bot\n"
        "• /help - Show this help\n"
        "• /wake - Power on PC\n"
        "• /status - Check PC status\n"
        "• /dota - Check Dota 2 status\n"
        "• /notify - Toggle notifications"
    )
    
    await callback.message.answer(
        help_text,
        parse_mode="HTML"
    )
    await callback.answer()
