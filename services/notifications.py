"""Notification service for sending messages to users."""
import asyncio
from typing import List, Optional

from aiogram import Bot
from loguru import logger

from config import get_settings
from database import DatabaseRepository


class NotificationService:
    """Service for sending notifications to users."""
    
    def __init__(self, bot: Bot):
        """Initialize notification service."""
        self.bot = bot
        self.db = DatabaseRepository()
        self.settings = get_settings()
    
    async def notify_admins(
        self,
        message: str,
        parse_mode: Optional[str] = "HTML",
    ) -> int:
        """
        Send message to all admins.
        
        Args:
            message: Message text
            parse_mode: Parse mode (HTML, Markdown)
            
        Returns:
            Number of messages sent
        """
        sent_count = 0
        
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(
                    admin_id,
                    message,
                    parse_mode=parse_mode,
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send admin notification to {admin_id}: {e}")
        
        return sent_count
    
    async def notify_all_users(
        self,
        message: str,
        parse_mode: Optional[str] = "HTML",
    ) -> int:
        """
        Send message to all authorized users.
        
        Args:
            message: Message text
            parse_mode: Parse mode
            
        Returns:
            Number of messages sent
        """
        users = await self.db.get_all_authorized_users()
        sent_count = 0
        
        for user in users:
            if not user.notifications_enabled:
                continue
            
            try:
                await self.bot.send_message(
                    user.telegram_id,
                    message,
                    parse_mode=parse_mode,
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send notification to {user.telegram_id}: {e}")
        
        return sent_count
    
    async def notify_user(
        self,
        telegram_id: int,
        message: str,
        parse_mode: Optional[str] = "HTML",
    ) -> bool:
        """
        Send message to specific user.
        
        Args:
            telegram_id: User's Telegram ID
            message: Message text
            parse_mode: Parse mode
            
        Returns:
            True if sent successfully
        """
        try:
            await self.bot.send_message(
                telegram_id,
                message,
                parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send notification to {telegram_id}: {e}")
            return False
    
    async def notify_pc_status_change(
        self,
        is_online: bool,
        ip_address: Optional[str] = None,
    ) -> None:
        """
        Notify about PC status change.
        
        Args:
            is_online: Whether PC is now online
            ip_address: PC IP address
        """
        if not self.settings.notify_on_pc_status:
            return
        
        status_text = "🟢 <b>ONLINE</b>" if is_online else "🔴 <b>OFFLINE</b>"
        
        message = (
            f"<b>PC Status Change</b>\n\n"
            f"Status: {status_text}\n"
            f"IP: {ip_address or 'N/A'}"
        )
        
        await self.notify_all_users(message)
    
    async def notify_dota_match(
        self,
        match_info: dict,
    ) -> None:
        """
        Notify about new Dota 2 match.
        
        Args:
            match_info: Match information
        """
        if not self.settings.notify_on_dota_game:
            return
        
        k = match_info.get("kills", 0)
        d = match_info.get("deaths", 0)
        a = match_info.get("assists", 0)
        
        duration = match_info.get("duration", 0)
        minutes = duration // 60
        seconds = duration % 60
        
        message = (
            f"<b>🎮 New Dota 2 Match</b>\n\n"
            f"Hero: {match_info.get('player_name', 'Unknown')}\n"
            f"Result: <code>{k}/{d}/{a}</code>\n"
            f"Duration: {minutes}:{seconds:02d}\n"
            f"Mode: {match_info.get('game_mode', 'Unknown')}"
        )
        
        await self.notify_all_users(message)
    
    async def notify_dota_game_start(
        self,
        player_name: str,
        hero: Optional[str] = None,
    ) -> None:
        """
        Notify about player starting a game.
        
        Args:
            player_name: Player name
            hero: Hero being played
        """
        if not self.settings.notify_on_dota_game:
            return
        
        hero_text = f"\nHero: {hero}" if hero else ""
        
        message = (
            f"<b>🎮 Game Started</b>\n\n"
            f"Player: {player_name}{hero_text}"
        )
        
        await self.notify_all_users(message)
    
    async def notify_auth_request(
        self,
        username: str,
        first_name: str,
        user_id: int,
    ) -> None:
        """
        Notify admins about new authorization request.
        
        Args:
            username: Telegram username
            first_name: User's first name
            user_id: User's Telegram ID
        """
        message = (
            f"<b>🔐 New Authorization Request</b>\n\n"
            f"User: {username or first_name}\n"
            f"ID: <code>{user_id}</code>\n\n"
            f"Use /auth {user_id} approve or /auth {user_id} reject"
        )
        
        await self.notify_admins(message)
    
    async def notify_auth_approved(
        self,
        telegram_id: int,
    ) -> None:
        """
        Notify user about authorization approval.
        
        Args:
            telegram_id: User's Telegram ID
        """
        message = (
            f"✅ <b>Authorization Approved</b>\n\n"
            f"You now have access to all bot commands!"
        )
        
        await self.notify_user(telegram_id, message)
    
    async def notify_auth_rejected(
        self,
        telegram_id: int,
    ) -> None:
        """
        Notify user about authorization rejection.
        
        Args:
            telegram_id: User's Telegram ID
        """
        message = (
            f"❌ <b>Authorization Rejected</b>\n\n"
            f"Your access request was denied."
        )
        
        await self.notify_user(telegram_id, message)
