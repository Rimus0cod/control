"""Two-factor authentication and login protection services."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

import pyotp

from database import DatabaseRepository
from utils import get_logger

logger = get_logger(__name__)


class TwoFactorService:
    """Service for handling 2FA lifecycle and verification."""

    CODE_DIGITS = 6
    CODE_VALID_WINDOW = 1  # tolerate +/-1 step clock drift (30s each)
    BACKUP_CODES_COUNT = 8
    BACKUP_CODE_LENGTH = 10

    def __init__(self):
        self.db = DatabaseRepository()
        self.last_error: Optional[str] = None

    @staticmethod
    def _normalize_code(code: str) -> str:
        return (code or "").strip().replace(" ", "")

    @classmethod
    def validate_code_format(cls, code: str) -> tuple[bool, Optional[str]]:
        """Validate TOTP code format before verification."""
        norm = cls._normalize_code(code)
        if not norm:
            return False, "Please provide the 2FA code."
        if not norm.isdigit():
            return False, "Invalid code format. Use only digits."
        if len(norm) != cls.CODE_DIGITS:
            return False, f"Invalid code length. Expected {cls.CODE_DIGITS} digits."
        return True, None

    async def generate_secret(self, telegram_id: int) -> Optional[str]:
        """Generate new 2FA secret for user."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            self.last_error = "User not found."
            return None

        secret = pyotp.random_base32()
        user.two_factor_secret = secret
        user.is_2fa_enabled = False
        user.two_factor_backup_codes = None
        await self.db.update_user(user)

        logger.info(f"Generated 2FA secret for user {telegram_id}")
        self.last_error = None
        return secret

    async def enable_2fa(self, telegram_id: int, verification_code: str) -> bool:
        """Enable 2FA after successful TOTP verification."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.two_factor_secret:
            self.last_error = "2FA setup is not initialized."
            return False

        is_valid, reason = self.validate_code_format(verification_code)
        if not is_valid:
            self.last_error = reason
            return False

        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(self._normalize_code(verification_code), valid_window=self.CODE_VALID_WINDOW):
            logger.warning(f"Invalid 2FA code for user {telegram_id}")
            self.last_error = "Invalid 2FA code. Check your authenticator and device time."
            return False

        user.is_2fa_enabled = True
        await self.db.update_user(user)

        logger.info(f"Enabled 2FA for user {telegram_id}")
        self.last_error = None
        return True

    async def disable_2fa(self, telegram_id: int, verification_code: str) -> bool:
        """Disable 2FA for user after code verification."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.is_2fa_enabled or not user.two_factor_secret:
            self.last_error = "2FA is not enabled."
            return False

        is_valid, reason = self.validate_code_format(verification_code)
        if not is_valid:
            self.last_error = reason
            return False

        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(self._normalize_code(verification_code), valid_window=self.CODE_VALID_WINDOW):
            logger.warning(f"Invalid 2FA disable code for user {telegram_id}")
            self.last_error = "Invalid 2FA code."
            return False

        user.is_2fa_enabled = False
        user.two_factor_secret = None
        user.two_factor_backup_codes = None
        await self.db.update_user(user)

        logger.info(f"Disabled 2FA for user {telegram_id}")
        self.last_error = None
        return True

    async def verify_code(self, telegram_id: int, code: str) -> bool:
        """Verify TOTP code (or backup code) for enabled 2FA users."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.is_2fa_enabled or not user.two_factor_secret:
            self.last_error = "2FA is not enabled."
            return False

        norm = self._normalize_code(code)
        is_valid, reason = self.validate_code_format(norm)
        if is_valid:
            totp = pyotp.TOTP(user.two_factor_secret)
            if totp.verify(norm, valid_window=self.CODE_VALID_WINDOW):
                self.last_error = None
                return True

        # Fallback to backup code (alphanumeric, one-time)
        if await self.consume_backup_code(telegram_id, norm):
            logger.warning(f"User {telegram_id} authenticated with backup code")
            self.last_error = None
            return True

        self.last_error = reason or "Invalid 2FA code."
        return False

    async def get_provisioning_uri(self, telegram_id: int) -> Optional[str]:
        """Get provisioning URI for authenticator app."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.two_factor_secret:
            return None

        totp = pyotp.TOTP(user.two_factor_secret)
        return totp.provisioning_uri(
            name=f"telegram_id:{telegram_id}",
            issuer_name="PC Controller Bot",
        )

    async def is_2fa_enabled(self, telegram_id: int) -> bool:
        """Check whether 2FA is enabled for user."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        return bool(user and user.is_2fa_enabled)

    async def reset_2fa(self, user_id: int) -> bool:
        """Reset 2FA state and brute-force counters (admin function)."""
        user = await self.db.get_user_by_id(user_id)
        if not user:
            return False

        user.is_2fa_enabled = False
        user.two_factor_secret = None
        user.two_factor_backup_codes = None
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.update_user(user)

        logger.info(f"Reset 2FA for user {user_id}")
        return True

    @staticmethod
    def _hash_backup_code(code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    @staticmethod
    def _dump_hashes(hashes: list[str]) -> str:
        return json.dumps(hashes, separators=(",", ":"))

    @staticmethod
    def _load_hashes(data: Optional[str]) -> list[str]:
        if not data:
            return []
        try:
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except json.JSONDecodeError:
            return []
        return []

    async def generate_backup_codes(self, telegram_id: int) -> list[str]:
        """Generate one-time backup codes and store only hashed values."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            self.last_error = "User not found."
            return []

        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        codes = [
            "".join(secrets.choice(alphabet) for _ in range(self.BACKUP_CODE_LENGTH))
            for _ in range(self.BACKUP_CODES_COUNT)
        ]
        code_hashes = [self._hash_backup_code(code) for code in codes]
        user.two_factor_backup_codes = self._dump_hashes(code_hashes)
        await self.db.update_user(user)

        self.last_error = None
        return codes

    async def consume_backup_code(self, telegram_id: int, code: str) -> bool:
        """Consume one backup code (single-use)."""
        norm = (code or "").strip().upper()
        if not norm:
            return False

        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return False

        code_hash = self._hash_backup_code(norm)
        hashes = self._load_hashes(user.two_factor_backup_codes)
        if code_hash not in hashes:
            return False

        hashes.remove(code_hash)
        user.two_factor_backup_codes = self._dump_hashes(hashes)
        await self.db.update_user(user)
        return True


class LoginSecurityService:
    """Service for login security with exponential lockout and pending 2FA sessions."""

    MAX_ATTEMPTS = 5
    BASE_LOCKOUT_SECONDS = 300
    MAX_LOCKOUT_SECONDS = 3600
    PENDING_2FA_TTL_SECONDS = 300

    _pending_2fa: dict[int, datetime] = {}

    def __init__(self):
        self.db = DatabaseRepository()

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    @classmethod
    def _calculate_lockout_seconds(cls, attempts: int) -> int:
        """Return lockout duration using exponential backoff after MAX_ATTEMPTS."""
        if attempts < cls.MAX_ATTEMPTS:
            return 0
        exponent = attempts - cls.MAX_ATTEMPTS
        seconds = cls.BASE_LOCKOUT_SECONDS * (2 ** exponent)
        return min(seconds, cls.MAX_LOCKOUT_SECONDS)

    async def check_login_attempts(self, telegram_id: int) -> tuple[bool, Optional[str]]:
        """Check whether user can perform a login attempt."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return True, None

        now = self._now()

        if user.locked_until and user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds())
            return False, f"Account locked. Try again in {remaining} seconds."

        # Clear stale lock flag, but keep attempt counter until successful login.
        if user.locked_until and user.locked_until <= now:
            user.locked_until = None
            await self.db.update_user(user)

        return True, None

    async def remaining_attempts(self, telegram_id: int) -> int:
        """Return attempts left before lockout starts."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return self.MAX_ATTEMPTS
        return max(0, self.MAX_ATTEMPTS - user.failed_login_attempts)

    async def record_failed_attempt(self, telegram_id: int) -> None:
        """Record failed attempt and apply lockout policy when needed."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return

        user.failed_login_attempts += 1
        lockout = self._calculate_lockout_seconds(user.failed_login_attempts)

        if lockout > 0:
            user.locked_until = self._now() + timedelta(seconds=lockout)
            logger.warning(
                f"Account {telegram_id} locked for {lockout}s "
                f"after {user.failed_login_attempts} failed attempts"
            )

        await self.db.update_user(user)

    async def record_successful_login(self, telegram_id: int) -> None:
        """Reset failed counters after successful authentication."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            return

        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.update_user(user)
        self.clear_pending_2fa(telegram_id)

    def set_pending_2fa(self, telegram_id: int) -> None:
        """Mark user as pending second factor after password verification."""
        self._pending_2fa[telegram_id] = self._now() + timedelta(seconds=self.PENDING_2FA_TTL_SECONDS)

    def has_pending_2fa(self, telegram_id: int) -> bool:
        """Check if user has an active pending 2FA challenge."""
        expires_at = self._pending_2fa.get(telegram_id)
        if not expires_at:
            return False
        if expires_at <= self._now():
            self._pending_2fa.pop(telegram_id, None)
            return False
        return True

    def clear_pending_2fa(self, telegram_id: int) -> None:
        """Clear pending 2FA challenge."""
        self._pending_2fa.pop(telegram_id, None)
