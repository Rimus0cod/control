"""Password recovery service."""
import secrets
from datetime import datetime, timedelta
from typing import Optional

from database import DatabaseRepository
from utils import get_logger

logger = get_logger(__name__)


class PasswordRecoveryService:
    """Service for password recovery."""
    
    TOKEN_EXPIRY_HOURS = 24
    
    def __init__(self):
        self.db = DatabaseRepository()
    
    async def generate_recovery_token(self, telegram_id: int) -> Optional[str]:
        """Generate password recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return None
        
        # Generate secure token
        token = secrets.token_urlsafe(32)
        
        # Set token and expiry
        user.recovery_token = token
        user.recovery_token_expires = datetime.utcnow() + timedelta(hours=self.TOKEN_EXPIRY_HOURS)
        
        await self.db.update_user(user)
        
        logger.info(f"Generated recovery token for user {telegram_id}")
        return token
    
    async def verify_token(self, telegram_id: int, token: str) -> bool:
        """Verify recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False
        
        # Check token and expiry
        if not user.recovery_token or not user.recovery_token_expires:
            return False
        
        if user.recovery_token != token:
            logger.warning(f"Invalid recovery token for user {telegram_id}")
            return False
        
        if user.recovery_token_expires < datetime.utcnow():
            logger.warning(f"Expired recovery token for user {telegram_id}")
            return False
        
        return True
    
    async def reset_password(self, telegram_id: int, token: str, new_password: str) -> bool:
        """Reset password using recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False
        
        # Verify token
        if not await self.verify_token(telegram_id, token):
            return False
        
        # Set new password
        user.set_password(new_password)
        
        # Clear recovery token
        user.recovery_token = None
        user.recovery_token_expires = None
        
        await self.db.update_user(user)
        
        logger.info(f"Password reset for user {telegram_id}")
        
        # Log the action
        await self.db.add_log_entry(
            action="password_reset",
            user_id=user.id,
            details="Password was reset using recovery token",
        )
        
        return True
    
    async def clear_recovery_token(self, telegram_id: int) -> None:
        """Clear recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if user:
            user.recovery_token = None
            user.recovery_token_expires = None
            await self.db.update_user(user)
    
    async def is_token_valid(self, telegram_id: int) -> bool:
        """Check if user has valid recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.recovery_token or not user.recovery_token_expires:
            return False
        
        return user.recovery_token_expires > datetime.utcnow()
