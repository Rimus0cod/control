"""Two-Factor Authentication service."""
import pyotp
from typing import Optional
import secrets

from database import DatabaseRepository
from utils import get_logger

logger = get_logger(__name__)


class TwoFactorService:
    """Service for handling 2FA operations."""
    
    def __init__(self):
        self.db = DatabaseRepository()
    
    async def generate_secret(self, telegram_id: int) -> Optional[str]:
        """Generate new 2FA secret for user."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return None
        
        # Generate random secret
        secret = pyotp.random_base32()
        user.two_factor_secret = secret
        await self.db.update_user(user)
        
        logger.info(f"Generated 2FA secret for user {telegram_id}")
        return secret
    
    async def enable_2fa(self, telegram_id: int, verification_code: str) -> bool:
        """Enable 2FA for user after verifying code."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.two_factor_secret:
            return False
        
        # Verify the code
        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(verification_code):
            logger.warning(f"Invalid 2FA code for user {telegram_id}")
            return False
        
        user.is_2fa_enabled = True
        await self.db.update_user(user)
        
        logger.info(f"Enabled 2FA for user {telegram_id}")
        return True
    
    async def disable_2fa(self, telegram_id: int, verification_code: str) -> bool:
        """Disable 2FA for user after verifying code."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.is_2fa_enabled:
            return False
        
        # Verify the code
        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(verification_code):
            logger.warning(f"Invalid 2FA code for user {telegram_id}")
            return False
        
        user.is_2fa_enabled = False
        user.two_factor_secret = None
        await self.db.update_user(user)
        
        logger.info(f"Disabled 2FA for user {telegram_id}")
        return True
    
    async def verify_code(self, telegram_id: int, code: str) -> bool:
        """Verify 2FA code."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.is_2fa_enabled or not user.two_factor_secret:
            return False
        
        totp = pyotp.TOTP(user.two_factor_secret)
        return totp.verify(code)
    
    async def get_provisioning_uri(self, telegram_id: int) -> Optional[str]:
        """Get provisioning URI for authenticator app."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.two_factor_secret:
            return None
        
        totp = pyotp.TOTP(user.two_factor_secret)
        return totp.provisioning_uri(
            name=f"telegram_id:{telegram_id}",
            issuer_name="PC Controller Bot"
        )
    
    async def is_2fa_enabled(self, telegram_id: int) -> bool:
        """Check if 2FA is enabled for user."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False
        return user.is_2fa_enabled
    
    async def reset_2fa(self, user_id: int) -> bool:
        """Reset 2FA (admin function)."""
        user = await self.db.get_user_by_id(user_id)
        if not user:
            return False
        
        user.is_2fa_enabled = False
        user.two_factor_secret = None
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.update_user(user)
        
        logger.info(f"Reset 2FA for user {user_id}")
        return True


class LoginSecurityService:
    """Service for login security (brute force protection)."""
    
    MAX_ATTEMPTS = 5
    LOCKOUT_DURATION = 300  # 5 minutes
    
    def __init__(self):
        self.db = DatabaseRepository()
    
    async def check_login_attempts(self, telegram_id: int) -> tuple[bool, Optional[str]]:
        """Check if user can attempt login."""
        from datetime import datetime, timedelta
        
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return True, None
        
        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            remaining = (user.locked_until - datetime.utcnow()).seconds
            return False, f"Account locked. Try again in {remaining} seconds."
        
        # Reset failed attempts if lockout expired
        if user.locked_until and user.locked_until <= datetime.utcnow():
            user.failed_login_attempts = 0
            user.locked_until = None
            await self.db.update_user(user)
        
        return True, None
    
    async def record_failed_attempt(self, telegram_id: int) -> None:
        """Record failed login attempt."""
        from datetime import datetime, timedelta
        
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return
        
        user.failed_login_attempts += 1
        
        if user.failed_login_attempts >= self.MAX_ATTEMPTS:
            user.locked_until = datetime.utcnow() + timedelta(seconds=self.LOCKOUT_DURATION)
            logger.warning(f"Account {telegram_id} locked due to too many failed attempts")
        
        await self.db.update_user(user)
    
    async def record_successful_login(self, telegram_id: int) -> None:
        """Record successful login."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return
        
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.update_user(user)
