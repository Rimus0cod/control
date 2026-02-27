"""Main bot entry point."""
import asyncio
import os
import signal
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.utils.token import TokenValidationError
from loguru import logger

from config import get_settings
from database import DatabaseRepository
from bot.bot_config import BotConfig
from handlers import (
    auth_router,
    pc_router,
    wol_router,
    dota_router,
    notification_router,
    voice_router,
)
from utils import setup_logging


# Global bot instance
_bot: Bot = None
_dp: Dispatcher = None


def create_bot() -> tuple[Bot, Dispatcher]:
    """Create and configure bot instance."""
    global _bot, _dp
    
    # Get settings
    settings = get_settings()
    
    # Setup logging
    setup_logging(
        log_file=settings.log_file,
        log_level=settings.log_level,
    )
    
    logger.info("Starting Telegram PC Controller Bot...")
    
    # Validate token
    if not settings.bot_token:
        logger.error("BOT_TOKEN is not set in environment!")
        sys.exit(1)
    
    try:
        # Create bot instance with DefaultBotProperties (aiogram 3.7+)
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        
        # Attach config to bot
        _bot.config = BotConfig.from_settings()
        
        # Create dispatcher
        _storage = MemoryStorage()
        _dp = Dispatcher(
            storage=_storage,
        )
        
        # Register routers
        _dp.include_router(auth_router)
        _dp.include_router(wol_router)
        _dp.include_router(pc_router)
        _dp.include_router(dota_router)
        _dp.include_router(notification_router)
        _dp.include_router(voice_router)  # voice commands via Whisper
        
        logger.info("Bot configured successfully")
        
        return _bot, _dp
        
    except TokenValidationError as e:
        logger.error(f"Invalid bot token: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to create bot: {e}")
        sys.exit(1)


def get_bot() -> Bot:
    """Get bot instance."""
    global _bot
    return _bot


async def setup_commands(bot: Bot):
    """Setup bot commands menu."""
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="wake", description="Включить ПК (WoL)"),
        BotCommand(command="status", description="Статус ПК (CPU/RAM/диск)"),
        BotCommand(command="screenshot", description="Скриншот рабочего стола"),
        BotCommand(command="reboot", description="Перезагрузить ПК"),
        BotCommand(command="shutdown", description="Выключить ПК"),
        BotCommand(command="cancel", description="Отменить выключение"),
        BotCommand(command="processes", description="Список процессов"),
        BotCommand(command="cmd", description="Выполнить команду"),
        BotCommand(command="dota", description="Статус Dota 2"),
        BotCommand(command="dotahistory", description="История матчей Dota 2"),
        BotCommand(command="dotalive", description="Live матч (реал-тайм)"),
        BotCommand(command="dotabuffs", description="Баффы игроков в матче"),
        BotCommand(command="notify", description="Уведомления вкл/выкл"),
    ]
    
    await bot.set_my_commands(commands)
    logger.info("Bot commands configured")


async def on_startup(bot: Bot):
    """Handle bot startup."""
    logger.info("Bot starting up...")
    
    # Initialize database
    db = DatabaseRepository()
    await db.init_db()
    logger.info("Database initialized")
    
    # Setup commands
    await setup_commands(bot)
    
    logger.info("Bot is ready!")


async def on_shutdown(bot: Bot):
    """Handle bot shutdown."""
    logger.info("Bot shutting down...")
    
    # Close database
    db = DatabaseRepository()
    await db.close()
    
    logger.info("Bot stopped")


@asynccontextmanager
async def lifespan(dp: Dispatcher, bot: Bot):
    """Manage bot lifecycle."""
    # Startup
    await on_startup(bot)
    
    yield
    
    # Shutdown
    await on_shutdown(bot)


async def main():
    """Main function to run the bot."""
    # Create bot
    bot, dp = create_bot()
    
    # Run startup
    await on_startup(bot)
    
    # Run polling
    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "edited_message",
                "channel_post",
                "voice",   # voice messages for Whisper recognition
            ],
        )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await on_shutdown(bot)


def run():
    """Run the bot."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")


if __name__ == "__main__":
    run()
