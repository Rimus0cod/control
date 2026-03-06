"""Admin handlers for user management."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAdmin
from bot.keyboards import get_admin_keyboard
from database import DatabaseRepository
from services.two_factor import TwoFactorService
from services.password_recovery import PasswordRecoveryService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    """Handle /admin command - show admin panel."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    await message.answer(
        "🔧 <b>Admin Panel</b>\n\n"
        "Available commands:\n"
        "/users - List all users\n"
        "/user USER_ID - Get user details\n"
        "/approve USER_ID - Approve user\n"
        "/reject USER_ID - Reject user\n"
        "/ban USER_ID - Ban user\n"
        "/unban USER_ID - Unban user\n"
        "/reset_2fa USER_ID - Reset 2FA for user\n"
        "/set_password USER_ID PASSWORD - Set user password\n"
        "/logs [USER_ID] - View logs",
        reply_markup=get_admin_keyboard()
    )


@router.message(Command("users"))
async def cmd_users(message: Message, bot: Bot):
    """Handle /users command - list all users."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    db = DatabaseRepository()
    users = await db.get_all_users()
    
    if not users:
        await message.answer("No users found.")
        return
    
    text = "<b>👥 All Users</b>\n\n"
    
    for user in users[:20]:  # Show first 20
        status = "✅" if user.is_authorized else "❌"
        admin = " 👑" if user.is_admin else ""
        two_factor = " 🔐" if user.is_2fa_enabled else ""
        
        text += (
            f"{status} {user.telegram_id} - {user.username or user.first_name or 'Unknown'}"
            f"{admin}{two_factor}\n"
        )
    
    if len(users) > 20:
        text += f"\n... and {len(users) - 20} more users"
    
    await message.answer(text)


@router.message(Command("user"))
async def cmd_user(message: Message, bot: Bot):
    """Handle /user command - get user details."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    # Parse user ID
    try:
        user_id = int(message.text.replace("/user", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /user USER_ID")
        return
    
    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    
    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return
    
    # Build user info
    text = (
        f"<b>👤 User Details</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {user.username or 'N/A'}\n"
        f"Name: {user.first_name or 'N/A'} {user.last_name or ''}\n"
        f"Authorized: {'Yes' if user.is_authorized else 'No'}\n"
        f"Admin: {'Yes' if user.is_admin else 'No'}\n"
        f"2FA Enabled: {'Yes' if user.is_2fa_enabled else 'No'}\n"
        f"Password Set: {'Yes' if user.password_hash else 'No'}\n"
        f"Failed Login Attempts: {user.failed_login_attempts}\n"
        f"Locked Until: {user.locked_until or 'Never'}\n"
        f"Created: {user.created_at}\n"
        f"Updated: {user.updated_at}"
    )
    
    await message.answer(text)


@router.message(Command("approve"))
async def cmd_approve(message: Message, bot: Bot):
    """Handle /approve command - approve user."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    try:
        user_id = int(message.text.replace("/approve", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /approve USER_ID")
        return
    
    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    
    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return
    
    user.is_authorized = True
    await db.update_user(user)
    
    await db.add_log_entry(
        action="user_approved",
        user_id=user.id,
        details=f"Approved by admin {message.from_user.id}",
    )
    
    await message.answer(f"✅ User {user_id} has been approved.")


@router.message(Command("reject"))
async def cmd_reject(message: Message, bot: Bot):
    """Handle /reject command - reject user."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    try:
        user_id = int(message.text.replace("/reject", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /reject USER_ID")
        return
    
    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    
    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return
    
    user.is_authorized = False
    await db.update_user(user)
    
    await db.add_log_entry(
        action="user_rejected",
        user_id=user.id,
        details=f"Rejected by admin {message.from_user.id}",
    )
    
    await message.answer(f"❌ User {user_id} has been rejected.")


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    """Handle /ban command - ban user."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    try:
        user_id = int(message.text.replace("/ban", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /ban USER_ID")
        return
    
    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    
    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return
    
    user.is_authorized = False
    user.is_admin = False
    await db.update_user(user)
    
    await db.add_log_entry(
        action="user_banned",
        user_id=user.id,
        details=f"Banned by admin {message.from_user.id}",
    )
    
    await message.answer(f"🚫 User {user_id} has been banned.")


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    """Handle /unban command - unban user."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    try:
        user_id = int(message.text.replace("/unban", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /unban USER_ID")
        return
    
    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    
    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return
    
    user.is_authorized = True
    user.failed_login_attempts = 0
    user.locked_until = None
    await db.update_user(user)
    
    await db.add_log_entry(
        action="user_unbanned",
        user_id=user.id,
        details=f"Unbanned by admin {message.from_user.id}",
    )
    
    await message.answer(f"✅ User {user_id} has been unbanned.")


@router.message(Command("reset_2fa"))
async def cmd_reset_2fa(message: Message, bot: Bot):
    """Handle /reset_2fa command - reset 2FA for user."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    try:
        user_id = int(message.text.replace("/reset_2fa", "").strip())
    except ValueError:
        await message.answer("❌ Invalid user ID. Usage: /reset_2fa USER_ID")
        return
    
    two_factor_service = TwoFactorService()
    success = await two_factor_service.reset_2fa(user_id)
    
    if success:
        await message.answer(f"✅ 2FA has been reset for user {user_id}.")
        
        db = DatabaseRepository()
        await db.add_log_entry(
            action="2fa_reset_admin",
            user_id=user_id,
            details=f"2FA reset by admin {message.from_user.id}",
        )
    else:
        await message.answer(f"❌ User {user_id} not found.")


@router.message(Command("set_password"))
async def cmd_set_password(message: Message, bot: Bot):
    """Handle /set_password command - set user password."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    # Parse command
    parts = message.text.replace("/set_password", "").strip().split()
    
    if len(parts) < 2:
        await message.answer(
            "❌ Usage: /set_password USER_ID PASSWORD\n\n"
            "Example: /set_password 123 MyPassword123"
        )
        return
    
    try:
        user_id = int(parts[0])
    except ValueError:
        await message.answer("❌ Invalid user ID.")
        return
    
    password = parts[1]
    
    if len(password) < 8:
        await message.answer("❌ Password must be at least 8 characters.")
        return
    
    db = DatabaseRepository()
    success = await db.update_user_password(user_id, password)
    
    if success:
        await message.answer(f"✅ Password has been set for user {user_id}.")
        
        await db.add_log_entry(
            action="password_set_admin",
            user_id=user_id,
            details=f"Password set by admin {message.from_user.id}",
        )
    else:
        await message.answer(f"❌ User {user_id} not found.")


@router.message(Command("logs"))
async def cmd_logs(message: Message, bot: Bot):
    """Handle /logs command - view logs."""
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not an admin.")
        return
    
    # Parse optional user ID
    user_id = None
    try:
        parts = message.text.replace("/logs", "").strip()
        if parts:
            user_id = int(parts)
    except ValueError:
        pass
    
    db = DatabaseRepository()
    
    if user_id:
        logs = await db.get_user_logs(user_id)
        title = f"Logs for user {user_id}"
    else:
        logs = await db.get_recent_logs(50)
        title = "Recent Logs"
    
    if not logs:
        await message.answer("No logs found.")
        return
    
    text = f"<b>{title}</b>\n\n"
    
    for log in logs[:20]:
        text += f"{log.created_at} - {log.action}\n"
        if log.details:
            text += f"  └ {log.details}\n"
    
    await message.answer(text)


# ──────────────────────────────────────────────
# Callback Queries
# ──────────────────────────────────────────────

@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, bot: Bot):
    """Handle admin panel button."""
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    await callback.message.answer(
        "🔧 <b>Admin Panel</b>\n\n"
        "Select an action:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def callback_admin_users(callback: CallbackQuery, bot: Bot):
    """Handle admin users button."""
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    db = DatabaseRepository()
    users = await db.get_all_users()
    
    if not users:
        await callback.message.answer("No users found.")
    else:
        text = "<b>👥 All Users</b>\n\n"
        for user in users[:20]:
            status = "✅" if user.is_authorized else "❌"
            text += f"{status} {user.telegram_id} - {user.username or user.first_name or 'Unknown'}\n"
        
        await callback.message.answer(text, reply_markup=get_admin_keyboard())
    
    await callback.answer()
