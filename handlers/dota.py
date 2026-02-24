"""Dota 2 handlers."""
from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from bot.filters import IsAuthorized
from bot.keyboards import get_main_keyboard
from database import DatabaseRepository
from services import DotaMonitor
from utils import get_logger

router = Router()
logger = get_logger(__name__)


@router.message(Command("dota"))
async def cmd_dota(message: Message, bot: Bot):
    """Handle /dota command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    await message.answer("🎮 Loading Dota 2 data...")
    
    try:
        dota_monitor = DotaMonitor()
        status = await dota_monitor.get_player_status()
        
        # Build response
        online_status = "🟢 Online" if status.get("online") else "⚪ Offline"
        in_game_status = "🎮 In Game" if status.get("in_game") else "🏠 Not in game"
        
        text = (
            f"<b>🎮 Dota 2 Status</b>\n\n"
            f"Player: {status.get('player_name', 'Unknown')}\n"
            f"Status: {online_status}\n"
            f"Game: {in_game_status}\n"
        )
        
        if status.get("in_game") and status.get("game_extra"):
            text += f"Hero: {status.get('game_extra')}"
        
        if status.get("last_match"):
            match = status["last_match"]
            text += (
                f"\n\n<b>Last Match</b>\n"
                f"Hero: {match.get('hero_name', 'Unknown')}\n"
            )
            
            kills = match.get("kills", 0)
            deaths = match.get("deaths", 0)
            assists = match.get("assists", 0)
            
            text += f"KDA: <code>{kills}/{deaths}/{assists}</code>\n"
            
            if match.get("started_at"):
                text += f"Played: {match.get('started_at')}"
        
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
        )
        
        # Log action
        await db.add_log_entry(
            action="dota_status_check",
            user_id=user.id,
        )
        
    except Exception as e:
        logger.error(f"Dota status error: {e}")
        await message.answer(f"❌ Error: {str(e)}")


@router.callback_query(F.data == "dota_status", IsAuthorized())
async def callback_dota_status(callback: CallbackQuery, bot: Bot):
    """Handle Dota status button."""
    await callback.message.answer(
        "Use /dota command to check your Dota 2 status."
    )
    await callback.answer()


@router.message(Command("dotahistory"))
async def cmd_dota_history(message: Message, bot: Bot):
    """Handle /dotahistory command."""
    db = DatabaseRepository()
    
    # Check authorization
    user = await db.get_user_by_telegram_id(message.from_user.id)
    
    if not user or not user.is_authorized:
        await message.answer(
            "❌ You are not authorized to use this command.",
            reply_markup=get_main_keyboard(is_authorized=False)
        )
        return
    
    await message.answer("🎮 Loading match history...")
    
    try:
        dota_monitor = DotaMonitor()
        matches = await dota_monitor.get_match_history(5)
        
        if not matches:
            await message.answer("No recent matches found.")
            return
        
        text = "<b>🎮 Recent Matches</b>\n\n"
        
        for match in matches:
            hero_id = match.get("hero_id", 0)
            hero_name = dota_monitor.get_hero_name(hero_id)
            
            kills = match.get("kills", 0)
            deaths = match.get("deaths", 0)
            assists = match.get("assists", 0)
            
            text += (
                f"• {hero_name}: <code>{kills}/{deaths}/{assists}</code>\n"
            )
        
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=get_main_keyboard(is_authorized=True, is_admin=user.is_admin)
        )
        
    except Exception as e:
        logger.error(f"Dota history error: {e}")
        await message.answer(f"❌ Error: {str(e)}")
