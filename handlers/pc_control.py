"""PC control handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard, get_pc_commands_keyboard, get_confirm_keyboard
from database import DatabaseRepository
from services import PCManager, NotificationService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("reboot"))
async def cmd_reboot(message: Message, bot: Bot):
    """Handle /reboot command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    # Confirm action
    await message.answer(
        "⚠️ <b>Confirm Reboot</b>\n\n"
        "This will restart the PC in 60 seconds.\n"
        "Use /cancel to abort.",
        reply_markup=get_confirm_keyboard("reboot"),
        parse_mode="HTML"
    )


@router.message(Command("shutdown"))
async def cmd_shutdown(message: Message, bot: Bot):
    """Handle /shutdown command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    # Confirm action
    await message.answer(
        "⚠️ <b>Confirm Shutdown</b>\n\n"
        "This will shut down the PC in 60 seconds.\n"
        "Use /cancel to abort.",
        reply_markup=get_confirm_keyboard("shutdown"),
        parse_mode="HTML"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, bot: Bot):
    """Handle /cancel command to abort shutdown/reboot."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    try:
        pc_manager = PCManager()
        success = await pc_manager.cancel_shutdown()
        
        if success:
            await message.answer(
                "✅ Shutdown cancelled!",
                reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
            )
            
            # Log action
            await db.add_log_entry(
                action="shutdown_cancelled",
                user_id=user.id,
            )
        else:
            await message.answer(
                "❌ Failed to cancel shutdown.",
                reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
            )
            
    except Exception as e:
        logger.error(f"Cancel shutdown error: {e}")
        await message.answer(f"❌ Error: {str(e)}")


@router.message(Command("cmd"))
async def cmd_command(message: Message, bot: Bot):
    """Handle /cmd command to execute arbitrary commands."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    # Get command from message
    command = message.text.replace("/cmd", "").strip()
    
    if not command:
        await message.answer(
            "Usage: /cmd <command>\n\n"
            "Example: /cmd dir"
        )
        return
    
    # Only allow safe commands for non-admin
    safe_commands = ["dir", "ipconfig", "hostname", "tasklist", "systeminfo"]
    
    if not user.is_admin and not any(command.lower().startswith(safe) for safe in safe_commands):
        await message.answer(
            "❌ This command is not allowed.\n"
            "Available commands: " + ", ".join(safe_commands)
        )
        return
    
    await message.answer(f"🔄 Executing: <code>{command}</code>", parse_mode="HTML")
    
    try:
        pc_manager = PCManager()
        result = await pc_manager.execute_command(command)
        
        output = result.get("stdout", "") or result.get("stderr", "") or "No output"
        
        if result.get("success"):
            await message.answer(
                f"✅ <b>Command executed successfully</b>\n\n"
                f"<pre>{output[:4000]}</pre>",
                parse_mode="HTML"
            )
            
            # Log action
            await db.add_log_entry(
                action="command_executed",
                user_id=user.id,
                details=f"Command: {command}",
            )
        else:
            await message.answer(
                f"❌ <b>Command failed</b>\n\n"
                f"<pre>{output[:4000]}</pre>",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Command execution error: {e}")
        await message.answer(f"❌ Error: {str(e)}")


@router.message(Command("processes"))
async def cmd_processes(message: Message, bot: Bot):
    """Handle /processes command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    await message.answer("📋 Loading processes...")
    
    try:
        pc_manager = PCManager()
        processes = await pc_manager.get_running_processes(limit=15)
        
        if processes:
            text = "<b>Top Processes</b>\n\n"
            
            for proc in processes:
                name = proc.get("name", "Unknown")
                cpu = proc.get("cpu_percent", 0)
                mem = proc.get("memory_percent", 0)
                text += f"• {name} | CPU: {cpu}% | MEM: {mem}%\n"
            
            await message.answer(text, parse_mode="HTML")
        else:
            await message.answer("No processes found.")
            
    except Exception as e:
        logger.error(f"Process list error: {e}")
        await message.answer(f"❌ Error: {str(e)}")


# Callback handlers
@router.callback_query(F.data == "pc_commands", IsAuthorized())
async def callback_pc_commands(callback: CallbackQuery, bot: Bot):
    """Handle PC commands menu."""
    await callback.message.answer(
        "🖥 <b>PC Commands</b>",
        reply_markup=get_pc_commands_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "pc_reboot", IsAuthorized())
async def callback_pc_reboot(callback: CallbackQuery, bot: Bot):
    """Handle reboot button."""
    await callback.message.answer(
        "Use /reboot command to reboot the PC.",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_shutdown", IsAuthorized())
async def callback_pc_shutdown(callback: CallbackQuery, bot: Bot):
    """Handle shutdown button."""
    await callback.message.answer(
        "Use /shutdown command to shut down the PC.",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_cancel", IsAuthorized())
async def callback_pc_cancel(callback: CallbackQuery, bot: Bot):
    """Handle cancel button."""
    await callback.message.answer(
        "Use /cancel command to abort shutdown/reboot.",
    )
    await callback.answer()


@router.callback_query(F.data == "pc_processes", IsAuthorized())
async def callback_pc_processes(callback: CallbackQuery, bot: Bot):
    """Handle processes button."""
    await callback.message.answer(
        "Use /processes command to see running processes.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_"), IsAuthorized())
async def callback_confirm_action(callback: CallbackQuery, bot: Bot):
    """Handle confirmation buttons."""
    action = callback.data.replace("confirm_", "")
    
    db = DatabaseRepository()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    
    try:
        pc_manager = PCManager()
        
        if action == "reboot":
            success = await pc_manager.reboot()
            action_text = "reboot"
        elif action == "shutdown":
            success = await pc_manager.shutdown()
            action_text = "shutdown"
        else:
            await callback.answer("Unknown action", show_alert=True)
            return
        
        if success:
            await callback.message.answer(
                f"✅ PC will {action_text} in 60 seconds.",
                reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
            )
            
            # Log action
            await db.add_log_entry(
                action=f"{action_text}_initiated",
                user_id=user.id,
            )
        else:
            await callback.message.answer(
                f"❌ Failed to initiate {action_text}.",
                reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
            )
            
    except Exception as e:
        logger.error(f"Confirm action error: {e}")
        await callback.message.answer(f"❌ Error: {str(e)}")
    
    await callback.answer()


@router.callback_query(F.data == "cancel_action")
async def callback_cancel_action(callback: CallbackQuery, bot: Bot):
    """Handle cancel action button."""
    await callback.message.answer(
        "❌ Action cancelled.",
        reply_markup=get_main_keyboard(is_authorized=True)
    )
    await callback.answer()
