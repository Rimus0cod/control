"""Wake-on-LAN handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard
from database import DatabaseRepository
from services import WakeOnLanService, NotificationService
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("wake"))
async def cmd_wake(message: Message, bot: Bot):
    """Handle /wake command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    await message.answer("🔌 Sending Wake-on-LAN packet...")
    
    try:
        wol_service = WakeOnLanService()
        
        # Send magic packet
        success = await wol_service.wake(retries=3)
        
        if success:
            await message.answer(
                "✅ Magic packet sent!\n"
                "Verifying PC is online..."
            )
            
            # Update last wake attempt
            await db.update_last_wake_attempt()
            
            # Log action
            await db.add_log_entry(
                action="wake_sent",
                user_id=user.id,
                details="Wake-on-LAN packet sent",
            )
            
            # Verify wake
            is_online = await wol_service.verify_wake(timeout=30)
            
            # Update PC status
            await db.update_pc_status(
                is_online=is_online,
                ip_address=bot.config.pc_ip_address,
            )
            
            if is_online:
                await message.answer(
                    "✅ <b>PC is ONLINE!</b>",
                    reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
                )
                
                # Notify all users
                notification_service = NotificationService(bot)
                await notification_service.notify_pc_status_change(
                    is_online=True,
                    ip_address=bot.config.pc_ip_address,
                )
            else:
                await message.answer(
                    "⚠️ Packet sent but PC not responding.\n"
                    "It may need more time or WoL may not be enabled in BIOS.",
                    reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
                )
        else:
            await message.answer(
                "❌ Failed to send Wake-on-LAN packet.",
                reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
            )
            
    except Exception as e:
        logger.error(f"Wake-on-LAN error: {e}")
        await message.answer(f"❌ Error: {str(e)}")


@router.callback_query(F.data == "pc_wake", IsAuthorized())
async def callback_pc_wake(callback: CallbackQuery, bot: Bot):
    """Handle PC wake button."""
    await callback.message.answer(
        "🔌 Use /wake command to power on the PC.",
    )
    await callback.answer()

@router.callback_query(F.data == "pc_status", IsAuthorized())
async def callback_pc_status(callback: CallbackQuery, bot: Bot):
    """Handle PC status button."""
    await callback.message.answer(
        "📊 Use /status command to check PC status."
    )
    await callback.answer()
