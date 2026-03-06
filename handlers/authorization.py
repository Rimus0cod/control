"""Authorization handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.filters import IsAdmin, IsOwner
from bot.keyboards import get_auth_keyboard, get_admin_keyboard, get_main_keyboard
from database import DatabaseRepository
from services import NotificationService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


async def _send_profile_invite(bot: Bot, telegram_id: int) -> None:
    """
    Send a one-time message to a newly approved user inviting them
    to fill in their personal PC / Steam settings via /setprofile.
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Заполнить профиль", callback_data="profile_edit"))
    builder.add(InlineKeyboardButton(text="Пропустить", callback_data="back_to_main"))
    builder.adjust(2)

    try:
        await bot.send_message(
            telegram_id,
            "<b>Добро пожаловать!</b>\n\n"
            "Вы можете настроить персональные параметры своего ПК и Steam-аккаунта.\n"
            "Это опционально — незаполненные поля берутся из глобальных настроек бота.\n\n"
            "Хотите заполнить профиль сейчас?",
            parse_mode="HTML",
            reply_markup=builder.as_markup(),
        )
    except Exception as exc:
        logger.warning(f"Could not send profile invite to {telegram_id}: {exc}")


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
            "<b>Управление ПК:</b>\n"
            "• /wake — включить ПК (WoL)\n"
            "• /status — статус ПК (CPU/RAM/диск)\n"
            "• /screenshot — скриншот рабочего стола\n"
            "• /reboot — перезагрузить ПК\n"
            "• /shutdown — выключить ПК\n"
            "• /cancel — отменить выключение\n"
            "• /processes — список процессов\n"
            "• /cmd &lt;команда&gt; — выполнить команду\n\n"
            "<b>Dota 2:</b>\n"
            "• /dota — статус игрока\n"
            "• /dotahistory — история матчей\n"
            "• /dotalive — реал-тайм матч\n"
            "• /dotabuffs [match_id] — баффы игроков\n\n"
            "<b>Профиль:</b>\n"
            "• /profile — просмотр личных настроек\n"
            "• /setprofile — заполнить / изменить профиль\n\n"
            "<b>Настройки:</b>\n"
            "• /notify — уведомления вкл/выкл\n"
        )

    if user and user.is_admin:
        help_text += (
            "\n<b>Администратор:</b>\n"
            "• /auth &lt;user_id&gt; approve|reject — управление доступом\n"
            "• /logs — просмотр логов\n"
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
        # Invite user to fill their profile
        await _send_profile_invite(bot, user_id)
        
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


# ──────────────────────────────────────────────
# Two-Factor Authentication Commands
# ──────────────────────────────────────────────

@router.message(Command("2fa_setup"))
async def cmd_2fa_setup(message: Message):
    """Handle /2fa_setup command - start 2FA setup."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if not user.is_authorized:
        await message.answer("❌ You need to be authorized first.")
        return
    
    if user.is_2fa_enabled:
        await message.answer(
            "ℹ️ 2FA is already enabled for your account.\n"
            "Use /2fa_disable to disable it."
        )
        return
    
    # Generate secret
    two_factor_service = TwoFactorService()
    secret = await two_factor_service.generate_secret(message.from_user.id)
    
    if not secret:
        await message.answer("❌ Failed to generate 2FA secret.")
        return
    
    # Get provisioning URI
    provisioning_uri = await two_factor_service.get_provisioning_uri(message.from_user.id)
    
    await message.answer(
        f"🔐 <b>2FA Setup</b>\n\n"
        f"To enable Two-Factor Authentication:\n\n"
        f"1. Install an authenticator app (Google Authenticator, Authy, etc.)\n"
        f"2. Scan this QR code:\n\n"
        f"<code>{provisioning_uri}</code>\n\n"
        f"Or enter this secret manually:\n<code>{secret}</code>\n\n"
        f"After setting up, send /2fa_verify CODE to verify and enable 2FA."
    )


@router.message(Command("2fa_verify"))
async def cmd_2fa_verify(message: Message):
    """Handle /2fa_verify command - verify and enable 2FA."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if not user.is_authorized:
        await message.answer("❌ You need to be authorized first.")
        return
    
    if user.is_2fa_enabled:
        await message.answer("ℹ️ 2FA is already enabled.")
        return
    
    # Get verification code from message
    code = message.text.replace("/2fa_verify", "").strip()
    
    if not code or len(code) < 6:
        await message.answer(
            "❌ Please provide the verification code.\n"
            "Usage: /2fa_verify CODE\n\n"
            "Example: /2fa_verify 123456"
        )
        return
    
    # Verify and enable
    two_factor_service = TwoFactorService()
    success = await two_factor_service.enable_2fa(message.from_user.id, code)
    
    if success:
        await message.answer("✅ 2FA enabled successfully!")
        await db.add_log_entry(
            action="2fa_enabled",
            user_id=user.id,
            details="Two-factor authentication enabled",
        )
    else:
        await message.answer(
            "❌ Invalid verification code.\n"
            "Please check your authenticator app and try again."
        )


@router.message(Command("2fa_disable"))
async def cmd_2fa_disable(message: Message):
    """Handle /2fa_disable command - disable 2FA."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if not user.is_authorized:
        await message.answer("❌ You need to be authorized first.")
        return
    
    if not user.is_2fa_enabled:
        await message.answer("ℹ️ 2FA is not enabled for your account.")
        return
    
    # Get verification code from message
    code = message.text.replace("/2fa_disable", "").strip()
    
    if not code or len(code) < 6:
        await message.answer(
            "❌ Please provide the verification code to disable 2FA.\n"
            "Usage: /2fa_disable CODE\n\n"
            "Example: /2fa_disable 123456"
        )
        return
    
    # Verify and disable
    two_factor_service = TwoFactorService()
    success = await two_factor_service.disable_2fa(message.from_user.id, code)
    
    if success:
        await message.answer("✅ 2FA disabled successfully!")
        await db.add_log_entry(
            action="2fa_disabled",
            user_id=user.id,
            details="Two-factor authentication disabled",
        )
    else:
        await message.answer(
            "❌ Invalid verification code.\n"
            "Please check your authenticator app and try again."
        )


# ──────────────────────────────────────────────
# Login with Password
# ──────────────────────────────────────────────

@router.message(Command("login"))
async def cmd_login(message: Message):
    """Handle /login command - login with password."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if user.is_authorized and not user.password_hash:
        await message.answer("ℹ️ You are already authorized and don't have a password set.")
        return
    
    # Check if account is locked
    login_security = LoginSecurityService()
    can_login, error_msg = await login_security.check_login_attempts(message.from_user.id)
    
    if not can_login:
        await message.answer(f"❌ {error_msg}")
        return
    
    # Get password from message
    password = message.text.replace("/login", "").strip()
    
    if not password:
        await message.answer(
            "❌ Please provide your password.\n"
            "Usage: /login PASSWORD\n\n"
            "Example: /login MySecurePassword123"
        )
        return
    
    # Verify password
    if await db.check_user_password(message.from_user.id, password):
        # Reset failed attempts
        await login_security.record_successful_login(message.from_user.id)
        
        # If 2FA is enabled, ask for 2FA code
        two_factor_service = TwoFactorService()
        if await two_factor_service.is_2fa_enabled(message.from_user.id):
            await message.answer(
                "✅ Password verified!\n"
                "Now please enter your 2FA code:\n"
                "/2fa CODE"
            )
        else:
            # Authorize user
            user.is_authorized = True
            await db.update_user(user)
            await db.add_log_entry(
                action="login_success",
                user_id=user.id,
                details="User logged in with password",
            )
            await message.answer("✅ Login successful! You now have access to all commands.")
    else:
        # Record failed attempt
        await login_security.record_failed_attempt(message.from_user.id)
        
        # Check remaining attempts
        user = await db.get_user_by_telegram_id(message.from_user.id)
        remaining = 5 - user.failed_login_attempts
        
        await message.answer(
            f"❌ Invalid password.\n"
            f"Attempts remaining: {remaining}"
        )


# ──────────────────────────────────────────────
# Password Recovery
# ──────────────────────────────────────────────

@router.message(Command("recover"))
async def cmd_recover(message: Message):
    """Handle /recover command - start password recovery."""
    from services.password_recovery import PasswordRecoveryService
    
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    recovery_service = PasswordRecoveryService()
    
    # Check if already has valid token
    if await recovery_service.is_token_valid(message.from_user.id):
        await message.answer(
            "ℹ️ You already have a valid recovery token.\n"
            "Use /reset_password TOKEN NEW_PASSWORD to set new password.\n\n"
            "Or wait for the current token to expire."
        )
        return
    
    # Generate new token
    token = await recovery_service.generate_recovery_token(message.from_user.id)
    
    if token:
        await message.answer(
            f"🔑 <b>Password Recovery</b>\n\n"
            f"Your recovery token has been generated.\n\n"
            f"<code>{token}</code>\n\n"
            f"Use this token within 24 hours to reset your password:\n"
            f"<code>/reset_password {token} NEW_PASSWORD</code>\n\n"
            f"Example:\n"
            f"<code>/reset_password {token} MyNewPassword123</code>"
        )
    else:
        await message.answer("❌ Failed to generate recovery token.")


@router.message(Command("reset_password"))
async def cmd_reset_password(message: Message):
    """Handle /reset_password command - reset password with token."""
    from services.password_recovery import PasswordRecoveryService
    
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    # Parse command
    parts = message.text.replace("/reset_password", "").strip().split()
    
    if len(parts) < 2:
        await message.answer(
            "❌ Please provide token and new password.\n"
            "Usage: /reset_password TOKEN NEW_PASSWORD\n\n"
            "Example: /reset_password TOKEN MyNewPassword123"
        )
        return
    
    token = parts[0]
    new_password = parts[1]
    
    if len(new_password) < 8:
        await message.answer(
            "❌ Password must be at least 8 characters."
        )
        return
    
    recovery_service = PasswordRecoveryService()
    
    if await recovery_service.reset_password(message.from_user.id, token, new_password):
        await message.answer(
            "✅ Password has been reset successfully!\n\n"
            "You can now login with your new password:\n"
            "/login YOUR_PASSWORD"
        )
    else:
        await message.answer(
            "❌ Invalid or expired token.\n"
            "Use /recover to generate a new recovery token."
        )


@router.message(Command("2fa"))
async def cmd_2fa_verify_short(message: Message):
    """Handle /2fa command - verify 2FA code."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if not user.is_authorized:
        await message.answer("❌ You need to be authorized first.")
        return
    
    if not user.is_2fa_enabled:
        await message.answer("ℹ️ 2FA is not enabled for your account.")
        return
    
    # Get code from message
    code = message.text.replace("/2fa", "").strip()
    
    if not code or len(code) < 6:
        await message.answer(
            "❌ Please provide the 2FA code.\n"
            "Usage: /2fa CODE\n\n"
            "Example: /2fa 123456"
        )
        return
    
    # Verify code
    two_factor_service = TwoFactorService()
    if await two_factor_service.verify_code(message.from_user.id, code):
        # Authorize user
        user.is_authorized = True
        await db.update_user(user)
        
        await db.add_log_entry(
            action="2fa_login_success",
            user_id=user.id,
            details="User logged in with 2FA",
        )
        await message.answer("✅ 2FA verified! Login successful!")
    else:
        await message.answer(
            "❌ Invalid 2FA code.\n"
            "Please check your authenticator app and try again."
        )
