"""Authorization and login security handlers."""

from __future__ import annotations

from io import BytesIO

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardButton, Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards import get_auth_keyboard, get_admin_keyboard, get_main_keyboard
from database import DatabaseRepository
from services import NotificationService
from services.password_recovery import PasswordRecoveryService
from services.two_factor import LoginSecurityService, TwoFactorService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


def _extract_command_payload(text: str, command: str) -> str:
    """Extract command payload text after command token."""
    return (text or "").replace(command, "", 1).strip()


def _normalize_2fa_code(raw: str) -> str:
    """Normalize 2FA code by removing spaces."""
    return (raw or "").strip().replace(" ", "")


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
            "\n<b>Безопасность:</b>\n"
            "• /login &lt;пароль&gt; — вход по паролю\n"
            "• /2fa_setup — начать настройку 2FA\n"
            "• /2fa_verify &lt;код&gt; — включить 2FA\n"
            "• /2fa_disable &lt;код&gt; — отключить 2FA\n"
            "• /2fa &lt;код/backup&gt; — подтвердить 2FA при входе\n"
            "• /recover — получить токен сброса пароля\n"
            "• /reset_password &lt;token&gt; &lt;new_password&gt; — сбросить пароль\n"
        )

    if user and user.is_admin:
        help_text += (
            "\n<b>Администратор:</b>\n"
            "• /auth &lt;user_id&gt; approve|reject — управление доступом\n"
            "• /admin — панель администратора\n"
            "• /users [page] — список пользователей\n"
            "• /logs [user_id] [page] — просмотр логов\n"
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
    if not provisioning_uri:
        await message.answer("❌ Failed to build 2FA provisioning URI. Try again later.")
        return

    # Try to send QR code image. Fallback to plain URI if qrcode is unavailable.
    qr_sent = False
    try:
        import qrcode

        qr_img = qrcode.make(provisioning_uri)
        buf = BytesIO()
        qr_img.save(buf, format="PNG")
        qr_bytes = buf.getvalue()
        qr_file = BufferedInputFile(qr_bytes, filename="2fa_qr.png")
        await message.answer_photo(
            photo=qr_file,
            caption=(
                "🔐 <b>2FA Setup</b>\n\n"
                "1. Scan this QR with your authenticator app.\n"
                "2. Then run: <code>/2fa_verify CODE</code>"
            ),
            parse_mode="HTML",
        )
        qr_sent = True
    except Exception as exc:
        logger.warning(f"Unable to render/send 2FA QR image for {message.from_user.id}: {exc}")

    if not qr_sent:
        await message.answer(
            "🔐 <b>2FA Setup</b>\n\n"
            "Install an authenticator app and add this URI:\n"
            f"<code>{provisioning_uri}</code>",
            parse_mode="HTML",
        )

    await message.answer(
        f"Manual secret (if QR scan unavailable):\n<code>{secret}</code>\n\n"
        "After setup, verify with: <code>/2fa_verify 123456</code>",
        parse_mode="HTML",
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
    
    code = _normalize_2fa_code(_extract_command_payload(message.text, "/2fa_verify"))
    valid_format, reason = TwoFactorService.validate_code_format(code)
    if not valid_format:
        await message.answer(f"❌ {reason}\nUsage: /2fa_verify 123456")
        return

    two_factor_service = TwoFactorService()
    success = await two_factor_service.enable_2fa(message.from_user.id, code)
    if not success:
        await message.answer(f"❌ {two_factor_service.last_error or 'Failed to enable 2FA.'}")
        await db.add_log_entry(
            action="2fa_enable_failed",
            user_id=user.id,
            details=f"reason={two_factor_service.last_error}",
        )
        return

    backup_codes = await two_factor_service.generate_backup_codes(message.from_user.id)
    if backup_codes:
        backup_codes_text = "\n".join(f"• <code>{code}</code>" for code in backup_codes)
        await message.answer(
            "✅ 2FA enabled successfully!\n\n"
            "Save these one-time backup codes in a safe place.\n"
            "Each code can be used once if you lose access to the authenticator app:\n\n"
            f"{backup_codes_text}",
            parse_mode="HTML",
        )
    else:
        await message.answer(
            "✅ 2FA enabled successfully, but backup code generation failed.\n"
            "You can proceed with authenticator codes only."
        )
    await db.add_log_entry(
        action="2fa_enabled",
        user_id=user.id,
        details="Two-factor authentication enabled",
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
    
    code = _normalize_2fa_code(_extract_command_payload(message.text, "/2fa_disable"))
    valid_format, reason = TwoFactorService.validate_code_format(code)
    if not valid_format:
        await message.answer(f"❌ {reason}\nUsage: /2fa_disable 123456")
        return

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
        await message.answer(f"❌ {two_factor_service.last_error or 'Failed to disable 2FA.'}")


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
    password = _extract_command_payload(message.text, "/login")
    
    if not password:
        await message.answer(
            "❌ Please provide your password.\n"
            "Usage: /login PASSWORD\n\n"
            "Example: /login MySecurePassword123"
        )
        return
    
    # Verify password
    if await db.check_user_password(message.from_user.id, password):
        # If 2FA is enabled, require second factor before login success.
        two_factor_service = TwoFactorService()
        if await two_factor_service.is_2fa_enabled(message.from_user.id):
            login_security.set_pending_2fa(message.from_user.id)
            await db.add_log_entry(
                action="login_password_verified",
                user_id=user.id,
                details="Password verified, waiting for 2FA confirmation",
            )
            await message.answer(
                "✅ Password verified.\n"
                "Enter your 2FA code now:\n"
                "<code>/2fa 123456</code>",
                parse_mode="HTML",
            )
            return

        await login_security.record_successful_login(message.from_user.id)
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

        remaining = await login_security.remaining_attempts(message.from_user.id)
        await db.add_log_entry(
            action="login_failed",
            user_id=user.id,
            details=f"remaining_attempts={remaining}",
        )
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
            f"Use this token within 1 hour to reset your password:\n"
            f"<code>/reset_password {token} NEW_PASSWORD</code>\n\n"
            f"Example:\n"
            f"<code>/reset_password {token} MyNewPassword123</code>"
        )
        await db.add_log_entry(
            action="recovery_token_generated",
            user_id=user.id,
            details="Password recovery token issued",
        )
    else:
        await message.answer(f"❌ {recovery_service.last_error or 'Failed to generate recovery token.'}")
        await db.add_log_entry(
            action="recovery_token_failed",
            user_id=user.id,
            details=str(recovery_service.last_error),
        )


@router.message(Command("reset_password"))
async def cmd_reset_password(message: Message):
    """Handle /reset_password command - reset password with token."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    # Parse command
    parts = _extract_command_payload(message.text, "/reset_password").split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Please provide token and new password.\n"
            "Usage: /reset_password TOKEN NEW_PASSWORD\n\n"
            "Example: /reset_password TOKEN MyNewPassword123"
        )
        return
    
    token, new_password = parts
    
    recovery_service = PasswordRecoveryService()

    if await recovery_service.reset_password(message.from_user.id, token, new_password):
        await message.answer(
            "✅ Password has been reset successfully!\n\n"
            "You can now login with your new password:\n"
            "/login YOUR_PASSWORD"
        )
        await db.add_log_entry(
            action="password_reset_success",
            user_id=user.id,
            details="Password reset via recovery token",
        )
    else:
        await message.answer(
            f"❌ {recovery_service.last_error or 'Invalid or expired token.'}\n"
            "Use /recover to generate a new recovery token."
        )
        await db.add_log_entry(
            action="password_reset_failed",
            user_id=user.id,
            details=str(recovery_service.last_error),
        )


@router.message(Command("2fa"))
async def cmd_2fa_verify_short(message: Message):
    """Handle /2fa command - verify 2FA code."""
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user:
        await message.answer("❌ User not found. Use /start first.")
        return
    
    if not user.is_2fa_enabled:
        await message.answer("ℹ️ 2FA is not enabled for your account.")
        return

    login_security = LoginSecurityService()
    # Allow /2fa if user is already authorized OR recently passed password check.
    if not user.is_authorized and not login_security.has_pending_2fa(message.from_user.id):
        await message.answer(
            "❌ 2FA verification is not pending.\n"
            "Please login with password first: /login YOUR_PASSWORD"
        )
        return

    code = _normalize_2fa_code(_extract_command_payload(message.text, "/2fa"))

    # Allow backup codes (alphanumeric) in addition to 6-digit TOTP.
    code_format_ok, reason = TwoFactorService.validate_code_format(code)
    looks_like_backup = code.isalnum() and len(code) >= 8
    if not code_format_ok and not looks_like_backup:
        await message.answer(f"❌ {reason}\nUsage: /2fa 123456")
        return

    two_factor_service = TwoFactorService()
    if await two_factor_service.verify_code(message.from_user.id, code):
        user.is_authorized = True
        await db.update_user(user)
        await login_security.record_successful_login(message.from_user.id)
        await db.add_log_entry(
            action="2fa_login_success",
            user_id=user.id,
            details="User logged in with 2FA",
        )
        await message.answer("✅ 2FA verified! Login successful!")
    else:
        await login_security.record_failed_attempt(message.from_user.id)
        await db.add_log_entry(
            action="2fa_login_failed",
            user_id=user.id,
            details=str(two_factor_service.last_error),
        )
        await message.answer(
            f"❌ {two_factor_service.last_error or 'Invalid 2FA code.'}\n"
            "Please check your authenticator app and try again."
        )
