"""Admin handlers for user management and audit operations."""

from __future__ import annotations

from html import escape
from math import ceil
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards import get_admin_keyboard
from database import DatabaseRepository
from database.models import User
from services.two_factor import TwoFactorService

router = Router()

PAGE_SIZE = 20


def _extract_payload(text: str, command: str) -> str:
    """Extract command payload from message text."""
    return (text or "").replace(command, "", 1).strip()


def _is_admin(bot: Bot, telegram_id: int) -> bool:
    return telegram_id in bot.config.admin_ids


async def _require_admin(message: Message, bot: Bot) -> bool:
    """Send error and return False when actor is not an admin."""
    if not _is_admin(bot, message.from_user.id):
        await message.answer("❌ You are not an admin.")
        return False
    return True


def _parse_user_id(raw: str) -> Optional[int]:
    raw = (raw or "").strip()
    if not raw or not raw.lstrip("-").isdigit():
        return None
    value = int(raw)
    return value if value > 0 else None


def _build_confirm_keyboard(action: str, user_id: int) -> InlineKeyboardMarkup:
    """Create inline keyboard for destructive admin actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm",
                    callback_data=f"admin_confirm:{action}:{user_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data="admin_confirm:cancel:0",
                ),
            ]
        ]
    )


def _render_users_page(users: list[User], page: int) -> str:
    """Render paginated user list."""
    total_pages = max(1, ceil(len(users) / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE

    lines = [f"<b>👥 All Users</b> (page {page}/{total_pages})", ""]

    for user in users[start:end]:
        status = "✅" if user.is_authorized else "❌"
        admin = " 👑" if user.is_admin else ""
        two_factor = " 🔐" if user.is_2fa_enabled else ""
        display_name = escape(user.username or user.first_name or "Unknown")
        lines.append(
            f"{status} <code>{user.id}</code> | tg:<code>{user.telegram_id}</code> | {display_name}{admin}{two_factor}"
        )

    if len(users) > PAGE_SIZE:
        lines.append("")
        lines.append("Use /users <page> to browse.")

    return "\n".join(lines)


@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    """Show admin command panel."""
    if not await _require_admin(message, bot):
        return

    await message.answer(
        "🔧 <b>Admin Panel</b>\n\n"
        "Commands:\n"
        "/users [page] - list users\n"
        "/user USER_ID - user details\n"
        "/approve USER_ID - approve user\n"
        "/reject USER_ID - reject user (confirm)\n"
        "/ban USER_ID - ban user (confirm)\n"
        "/unban USER_ID - unban user\n"
        "/reset_2fa USER_ID - reset user 2FA (confirm)\n"
        "/set_password USER_ID PASSWORD - set user password\n"
        "/logs [USER_ID] [page] - view logs",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )


@router.message(Command("users"))
async def cmd_users(message: Message, bot: Bot):
    """List all users with pagination."""
    if not await _require_admin(message, bot):
        return

    payload = _extract_payload(message.text, "/users")
    page = int(payload) if payload.isdigit() else 1

    db = DatabaseRepository()
    users = await db.get_all_users()

    if not users:
        await message.answer("No users found.")
        return

    await message.answer(_render_users_page(users, page), parse_mode="HTML")


@router.message(Command("user"))
async def cmd_user(message: Message, bot: Bot):
    """Show details for a specific internal user ID."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/user"))
    if not user_id:
        await message.answer("❌ Invalid user ID. Usage: /user USER_ID")
        return

    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)

    if not user:
        await message.answer(f"User with ID {user_id} not found.")
        return

    text = (
        "<b>👤 User Details</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: {escape(user.username or 'N/A')}\n"
        f"Name: {escape((user.first_name or 'N/A') + (' ' + user.last_name if user.last_name else ''))}\n"
        f"Authorized: {'Yes' if user.is_authorized else 'No'}\n"
        f"Admin: {'Yes' if user.is_admin else 'No'}\n"
        f"2FA Enabled: {'Yes' if user.is_2fa_enabled else 'No'}\n"
        f"Password Set: {'Yes' if user.password_hash else 'No'}\n"
        f"Failed Login Attempts: {user.failed_login_attempts}\n"
        f"Locked Until: {user.locked_until or 'Never'}\n"
        f"Created: {user.created_at}\n"
        f"Updated: {user.updated_at}"
    )

    await message.answer(text, parse_mode="HTML")


@router.message(Command("approve"))
async def cmd_approve(message: Message, bot: Bot):
    """Approve user immediately."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/approve"))
    if not user_id:
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
    """Reject user with explicit confirmation."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/reject"))
    if not user_id:
        await message.answer("❌ Invalid user ID. Usage: /reject USER_ID")
        return

    await message.answer(
        f"Reject user {user_id}?",
        reply_markup=_build_confirm_keyboard("reject", user_id),
    )


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot):
    """Ban user with explicit confirmation."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/ban"))
    if not user_id:
        await message.answer("❌ Invalid user ID. Usage: /ban USER_ID")
        return

    await message.answer(
        f"Ban user {user_id}? This removes access and admin role.",
        reply_markup=_build_confirm_keyboard("ban", user_id),
    )


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot):
    """Unban user and reset lockout counters."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/unban"))
    if not user_id:
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
    """Reset 2FA for user with explicit confirmation."""
    if not await _require_admin(message, bot):
        return

    user_id = _parse_user_id(_extract_payload(message.text, "/reset_2fa"))
    if not user_id:
        await message.answer("❌ Invalid user ID. Usage: /reset_2fa USER_ID")
        return

    await message.answer(
        f"Reset 2FA for user {user_id}?",
        reply_markup=_build_confirm_keyboard("reset_2fa", user_id),
    )


@router.message(Command("set_password"))
async def cmd_set_password(message: Message, bot: Bot):
    """Set user password with policy validation."""
    if not await _require_admin(message, bot):
        return

    payload = _extract_payload(message.text, "/set_password")
    parts = payload.split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            "❌ Usage: /set_password USER_ID PASSWORD\n"
            "Example: /set_password 123 Str0ngP@ssw0rd"
        )
        return

    user_id = _parse_user_id(parts[0])
    if not user_id:
        await message.answer("❌ Invalid user ID.")
        return

    password = parts[1]
    is_valid, reason = User.validate_password_strength(password)
    if not is_valid:
        await message.answer(f"❌ {reason}")
        return

    db = DatabaseRepository()
    try:
        success = await db.update_user_password(user_id, password)
    except ValueError as exc:
        await message.answer(f"❌ {exc}")
        return

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
    """View logs, optionally filtered by user ID, with pagination."""
    if not await _require_admin(message, bot):
        return

    payload = _extract_payload(message.text, "/logs")
    raw_parts = payload.split()

    target_user_id: Optional[int] = None
    page = 1

    if raw_parts:
        first = _parse_user_id(raw_parts[0])
        if first is not None:
            target_user_id = first
            if len(raw_parts) > 1 and raw_parts[1].isdigit():
                page = int(raw_parts[1])
        elif raw_parts[0].isdigit():
            page = int(raw_parts[0])

    db = DatabaseRepository()

    if target_user_id:
        logs = await db.get_user_logs(target_user_id)
        title = f"Logs for user {target_user_id}"
    else:
        logs = await db.get_recent_logs(200)
        title = "Recent Logs"

    if not logs:
        await message.answer("No logs found.")
        return

    total_pages = max(1, ceil(len(logs) / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE

    lines = [f"<b>{escape(title)}</b> (page {page}/{total_pages})", ""]
    for log in logs[start:end]:
        details = escape(log.details or "")
        lines.append(f"{log.created_at} - <b>{escape(log.action)}</b>")
        if details:
            lines.append(f"└ {details}")

    if len(logs) > PAGE_SIZE:
        lines.append("")
        lines.append("Use /logs [USER_ID] <page> to browse.")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_confirm:"))
async def callback_admin_confirm(callback: CallbackQuery, bot: Bot):
    """Handle confirm/cancel callbacks for destructive admin actions."""
    if not _is_admin(bot, callback.from_user.id):
        await callback.answer("Unauthorized!", show_alert=True)
        return

    try:
        _, action, raw_user_id = callback.data.split(":", 2)
    except ValueError:
        await callback.answer("Invalid confirmation payload.", show_alert=True)
        return
    if action == "cancel":
        await callback.message.edit_text("Action cancelled.")
        await callback.answer()
        return

    user_id = _parse_user_id(raw_user_id)
    if not user_id:
        await callback.answer("Invalid user ID.", show_alert=True)
        return

    db = DatabaseRepository()
    user = await db.get_user_by_id(user_id)
    if not user:
        await callback.message.edit_text(f"User with ID {user_id} not found.")
        await callback.answer()
        return

    if action == "reject":
        if user.telegram_id == callback.from_user.id:
            await callback.message.edit_text("❌ You cannot reject your own account.")
            await callback.answer()
            return
        user.is_authorized = False
        await db.update_user(user)
        await db.add_log_entry(
            action="user_rejected",
            user_id=user.id,
            details=f"Rejected by admin {callback.from_user.id}",
        )
        await callback.message.edit_text(f"❌ User {user_id} has been rejected.")

    elif action == "ban":
        if user.telegram_id == callback.from_user.id:
            await callback.message.edit_text("❌ You cannot ban your own account.")
            await callback.answer()
            return
        user.is_authorized = False
        user.is_admin = False
        await db.update_user(user)
        await db.add_log_entry(
            action="user_banned",
            user_id=user.id,
            details=f"Banned by admin {callback.from_user.id}",
        )
        await callback.message.edit_text(f"🚫 User {user_id} has been banned.")

    elif action == "reset_2fa":
        two_factor_service = TwoFactorService()
        success = await two_factor_service.reset_2fa(user_id)
        if success:
            await db.add_log_entry(
                action="2fa_reset_admin",
                user_id=user_id,
                details=f"2FA reset by admin {callback.from_user.id}",
            )
            await callback.message.edit_text(f"✅ 2FA has been reset for user {user_id}.")
        else:
            await callback.message.edit_text(f"❌ Failed to reset 2FA for user {user_id}.")
    else:
        await callback.answer("Unknown action.", show_alert=True)
        return

    await callback.answer()


@router.callback_query(F.data == "admin_panel")
async def callback_admin_panel(callback: CallbackQuery, bot: Bot):
    """Handle admin panel button."""
    if not _is_admin(bot, callback.from_user.id):
        await callback.answer("Unauthorized!", show_alert=True)
        return

    await callback.message.answer(
        "🔧 <b>Admin Panel</b>\n\nSelect an action:",
        reply_markup=get_admin_keyboard(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_users")
async def callback_admin_users(callback: CallbackQuery, bot: Bot):
    """Handle admin users button."""
    if not _is_admin(bot, callback.from_user.id):
        await callback.answer("Unauthorized!", show_alert=True)
        return

    db = DatabaseRepository()
    users = await db.get_all_users()

    if not users:
        await callback.message.answer("No users found.")
    else:
        await callback.message.answer(_render_users_page(users, page=1), parse_mode="HTML")

    await callback.answer()


@router.callback_query(F.data == "admin_logs")
async def callback_admin_logs(callback: CallbackQuery, bot: Bot):
    """Quick access to recent logs from admin keyboard."""
    if not _is_admin(bot, callback.from_user.id):
        await callback.answer("Unauthorized!", show_alert=True)
        return

    db = DatabaseRepository()
    logs = await db.get_recent_logs(PAGE_SIZE)
    if not logs:
        await callback.message.answer("No logs found.")
        await callback.answer()
        return

    lines = ["<b>Recent Logs</b>", ""]
    for log in logs:
        details = escape(log.details or "")
        lines.append(f"{log.created_at} - <b>{escape(log.action)}</b>")
        if details:
            lines.append(f"└ {details}")

    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_settings")
async def callback_admin_settings(callback: CallbackQuery, bot: Bot):
    """Placeholder callback for future admin settings actions."""
    if not _is_admin(bot, callback.from_user.id):
        await callback.answer("Unauthorized!", show_alert=True)
        return

    await callback.message.answer(
        "Admin settings:\n"
        "- Manage users: /users\n"
        "- Manage logs: /logs\n"
        "- Security: /reset_2fa, /set_password",
    )
    await callback.answer()
