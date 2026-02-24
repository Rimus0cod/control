"""Authorization handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAdmin, IsOwner
from bot.keyboards import get_auth_keyboard, get_admin_keyboard, get_main_keyboard
from database import DatabaseRepository
from services import NotificationService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    """Handle /start command."""
    db = DatabaseRepository()
    
    # Get or create user
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        user = await db.create_user(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
        
        # Log user creation
        await db.add_log_entry(
            action="user_created",
            user_id=user.id,
            details=f"New user: {message.from_user.username or message.from_user.first_name}",
        )
    
    if user.is_authorized:
        welcome_text = (
            f"👋 <b>Welcome back!</b>\n\n"
            f"You are authorized and can use all bot commands.\n"
            f"Use /help to see available commands."
        )
        keyboard = get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
    else:
        welcome_text = (
            f"👋 <b>Welcome!</b>\n\n"
            f"This bot controls a remote PC.\n"
            f"You need authorization to use it.\n\n"
            f"Click below to request access."
        )
        keyboard = get_main_keyboard(is_authorized=False)
    
    await message.answer(welcome_text, reply_markup=keyboard)
    
    logger.info(f"User {message.from_user.id} started the bot")


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    help_text = (
        "<b>📖 Available Commands</b>\n\n"
        "<b>General:</b>\n"
        "• /start - Start the bot\n"
        "• /help - Show this help\n\n"
    )
    
    if user and user.is_authorized:
        help_text += (
            "<b>PC Control:</b>\n"
            "• /wake - Wake up PC (WoL)\n"
            "• /status - Check PC status\n"
            "• /reboot - Reboot PC\n"
            "• /shutdown - Shutdown PC\n"
            "• /cmd <command> - Execute command\n\n"
            "<b>Dota 2:</b>\n"
            "• /dota - Get player status\n\n"
            "<b>Settings:</b>\n"
            "• /notify - Toggle notifications\n"
        )
    
    if user and user.is_admin:
        help_text += (
            "\n<b>Admin:</b>\n"
            "• /auth <user_id> approve/reject - Manage auth\n"
            "• /logs - View logs\n"
        )
    
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("auth"))
async def cmd_auth(message: Message, bot: Bot):
    """Handle /auth command."""
    # Check if admin
    if not message.from_user.id in bot.config.admin_ids:
        await message.answer("❌ You are not authorized to use this command.")
        return
    
    # Parse command arguments
    args = message.text.split()
    
    if len(args) < 3:
        await message.answer(
            "Usage: /auth USER_ID approve|reject"
        )
        return
    
    try:
        user_id = int(args[1])
        action = args[2].lower()
        
        if action not in ["approve", "reject"]:
            await message.answer("Invalid action. Use 'approve' or 'reject'.")
            return
        
        db = DatabaseRepository()
        user = await db.get_user_by_telegram_id(user_id)
        
        if not user:
            await message.answer(f"User with ID {user_id} not found.")
            return
        
        # Update user authorization
        user.is_authorized = (action == "approve")
        user.is_admin = (action == "approve" and user_id in bot.config.admin_ids)
        
        await db.update_user(user)
        
        # Log action
        await db.add_log_entry(
            action=f"auth_{action}",
            user_id=message.from_user.id,
            details=f"User {user_id} was {action}d",
        )
        
        # Send notification to user
        notification_service = NotificationService(bot)
        
        if action == "approve":
            await notification_service.notify_auth_approved(user_id)
            await message.answer(f"✅ User {user_id} has been approved.")
        else:
            await notification_service.notify_auth_rejected(user_id)
            await message.answer(f"❌ User {user_id} has been rejected.")
            
    except ValueError:
        await message.answer("Invalid user ID.")


@router.callback_query(F.data == "request_auth")
async def callback_request_auth(callback: CallbackQuery, bot: Bot):
    """Handle auth request button."""
    db = DatabaseRepository()
    
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    
    if user and user.is_authorized:
        await callback.answer("You are already authorized!", show_alert=True)
        return
    
    # Create auth request
    if user:
        await db.create_auth_request(user.id)
        
        # Log request
        await db.add_log_entry(
            action="auth_request",
            user_id=user.id,
            details=f"Auth request from {callback.from_user.username}",
        )
        
        # Notify admins
        notification_service = NotificationService(bot)
        await notification_service.notify_auth_request(
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            user_id=callback.from_user.id,
        )
        
        await callback.message.answer(
            "✅ Your authorization request has been sent to admins.\n"
            "You will be notified when it's processed."
        )
    else:
        await callback.message.answer(
            "Please use /start first to create your profile."
        )
    
    await callback.answer()


@router.callback_query(F.data.startswith("auth_approve_"))
async def callback_auth_approve(callback: CallbackQuery, bot: Bot):
    """Handle auth approval button."""
    # Check admin
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.split("_")[-1])
        
        db = DatabaseRepository()
        user = await db.get_user_by_telegram_id(user_id)
        
        if not user:
            await callback.answer("User not found!", show_alert=True)
            return
        
        # Update user
        user.is_authorized = True
        user.is_admin = (user_id in bot.config.admin_ids)
        
        await db.update_user(user)
        
        # Log
        await db.add_log_entry(
            action="auth_approved",
            user_id=callback.from_user.id,
            details=f"Approved user {user_id}",
        )
        
        # Notify user
        notification_service = NotificationService(bot)
        await notification_service.notify_auth_approved(user_id)
        
        await callback.message.edit_text(
            f"✅ User {user.username or user_id} has been approved."
        )
        await callback.answer()
        
    except ValueError:
        await callback.answer("Invalid user ID!", show_alert=True)


@router.callback_query(F.data.startswith("auth_reject_"))
async def callback_auth_reject(callback: CallbackQuery, bot: Bot):
    """Handle auth rejection button."""
    # Check admin
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    try:
        user_id = int(callback.data.split("_")[-1])
        
        db = DatabaseRepository()
        user = await db.get_user_by_telegram_id(user_id)
        
        if not user:
            await callback.answer("User not found!", show_alert=True)
            return
        
        # Update user
        user.is_authorized = False
        await db.update_user(user)
        
        # Log
        await db.add_log_entry(
            action="auth_rejected",
            user_id=callback.from_user.id,
            details=f"Rejected user {user_id}",
        )
        
        # Notify user
        notification_service = NotificationService(bot)
        await notification_service.notify_auth_rejected(user_id)
        
        await callback.message.edit_text(
            f"❌ User {user.username or user_id} has been rejected."
        )
        await callback.answer()
        
    except ValueError:
        await callback.answer("Invalid user ID!", show_alert=True)


@router.callback_query(F.data == "admin_auth")
async def callback_admin_auth(callback: CallbackQuery, bot: Bot):
    """Handle admin auth requests view."""
    if not callback.from_user.id in bot.config.admin_ids:
        await callback.answer("Unauthorized!", show_alert=True)
        return
    
    db = DatabaseRepository()
    requests = await db.get_pending_auth_requests()
    
    if not requests:
        await callback.message.answer(
            "No pending authorization requests.",
            reply_markup=get_admin_keyboard()
        )
    else:
        for req in requests:
            user = req.user
            text = (
                f"<b>Authorization Request</b>\n\n"
                f"User: {user.username or user.first_name}\n"
                f"ID: <code>{user.telegram_id}</code>\n"
                f"Requested: {req.requested_at}"
            )
            
            await callback.message.answer(
                text,
                reply_markup=get_auth_keyboard(user.telegram_id)
            )
    
    await callback.answer()
