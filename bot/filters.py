"""Custom filters for aiogram."""
from typing import Any, Callable, Union

from aiogram.filters import Filter
from aiogram.types import Message, CallbackQuery

from config import get_settings
from database import DatabaseRepository


class IsAuthorized(Filter):
    """Filter to check if user is authorized."""
    
    async def __call__(
        self,
        event: Union[Message, CallbackQuery]
    ) -> bool:
        """Check if user is authorized."""
        user_id = event.from_user.id
        
        db = DatabaseRepository()
        user = await db.get_user_by_telegram_id(user_id)
        
        return user is not None and user.is_authorized


class IsAdmin(Filter):
    """Filter to check if user is admin."""
    
    async def __call__(
        self,
        event: Union[Message, CallbackQuery]
    ) -> bool:
        """Check if user is admin."""
        user_id = event.from_user.id
        
        settings = get_settings()
        
        # Check if user ID is in admin list
        if user_id in settings.admin_ids:
            return True
        
        # Also check database
        db = DatabaseRepository()
        user = await db.get_user_by_telegram_id(user_id)
        
        return user is not None and user.is_admin


class IsOwner(Filter):
    """Filter to check if user is bot owner (from settings)."""
    
    async def __call__(
        self,
        event: Union[Message, CallbackQuery]
    ) -> bool:
        """Check if user is owner."""
        user_id = event.from_user.id
        
        settings = get_settings()
        return user_id in settings.admin_ids


class HasPendingAuthRequest(Filter):
    """Filter to check if there are pending auth requests."""
    
    async def __call__(
        self,
        event: Union[Message, CallbackQuery]
    ) -> bool:
        """Check for pending auth requests."""
        db = DatabaseRepository()
        requests = await db.get_pending_auth_requests()
        
        return len(requests) > 0


class CommandPrefix(Filter):
    """Filter to match command prefix."""
    
    def __init__(self, prefixes: Union[str, list[str]]):
        """Initialize filter."""
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        self.prefixes = [p.lower() for p in prefixes]
    
    async def __call__(
        self,
        message: Message
    ) -> bool:
        """Check message text starts with prefix."""
        if not message.text:
            return False
        
        text = message.text.lower()
        return any(text.startswith(p) for p in self.prefixes)
