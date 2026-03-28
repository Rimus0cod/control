"""Password recovery service with secure token handling and rate limiting."""

from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Optional

from database import DatabaseRepository
from database.models import User
from utils import get_logger

logger = get_logger(__name__)


class PasswordRecoveryService:
    """Service for password recovery flows."""

    TOKEN_EXPIRY_HOURS = 1
    TOKEN_BYTES = 32
    RATE_LIMIT_REQUESTS = 3
    RATE_LIMIT_WINDOW_SECONDS = 3600
    TOKEN_PREFIX = "sha256$"

    _recovery_requests: dict[int, deque[datetime]] = defaultdict(deque)

    def __init__(self):
        self.db = DatabaseRepository()
        self.last_error: Optional[str] = None

    @staticmethod
    def _now() -> datetime:
        return datetime.utcnow()

    @classmethod
    def _token_digest(cls, token: str) -> str:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"{cls.TOKEN_PREFIX}{digest}"

    @classmethod
    def _is_within_rate_limit(cls, telegram_id: int) -> bool:
        now = cls._now()
        bucket = cls._recovery_requests[telegram_id]
        while bucket and (now - bucket[0]).total_seconds() > cls.RATE_LIMIT_WINDOW_SECONDS:
            bucket.popleft()
        return len(bucket) < cls.RATE_LIMIT_REQUESTS

    @classmethod
    def _record_recovery_request(cls, telegram_id: int) -> None:
        cls._recovery_requests[telegram_id].append(cls._now())

    async def can_request_recovery(self, telegram_id: int) -> tuple[bool, Optional[str]]:
        """Check if user can request another recovery token."""
        if not self._is_within_rate_limit(telegram_id):
            return False, "Too many recovery requests. Try again in about 1 hour."
        return True, None

    async def generate_recovery_token(self, telegram_id: int) -> Optional[str]:
        """Generate a secure, time-limited recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            self.last_error = "User not found."
            return None

        can_request, reason = await self.can_request_recovery(telegram_id)
        if not can_request:
            self.last_error = reason
            return None

        raw_token = secrets.token_urlsafe(self.TOKEN_BYTES)
        user.recovery_token = self._token_digest(raw_token)
        user.recovery_token_expires = self._now() + timedelta(hours=self.TOKEN_EXPIRY_HOURS)
        await self.db.update_user(user)

        self._record_recovery_request(telegram_id)
        self.last_error = None
        logger.info(f"Generated password recovery token for user {telegram_id}")
        return raw_token

    @classmethod
    def _verify_user_token(cls, user: User, token: str) -> bool:
        """Verify token hash (with backward compatibility for legacy plain token)."""
        stored = user.recovery_token or ""
        supplied = token or ""
        if not stored or not supplied:
            return False

        if stored.startswith(cls.TOKEN_PREFIX):
            return secrets.compare_digest(stored, cls._token_digest(supplied))

        # Legacy plain token compatibility.
        return secrets.compare_digest(stored, supplied)

    async def verify_token(self, telegram_id: int, token: str) -> bool:
        """Verify recovery token and expiration timestamp."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            self.last_error = "User not found."
            return False

        if not user.recovery_token or not user.recovery_token_expires:
            self.last_error = "Recovery token does not exist."
            return False

        if user.recovery_token_expires < self._now():
            self.last_error = "Recovery token expired."
            logger.warning(f"Expired recovery token for user {telegram_id}")
            return False

        if not self._verify_user_token(user, token):
            self.last_error = "Invalid recovery token."
            logger.warning(f"Invalid recovery token for user {telegram_id}")
            return False

        self.last_error = None
        return True

    async def reset_password(self, telegram_id: int, token: str, new_password: str) -> bool:
        """Reset password using one-time recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user:
            self.last_error = "User not found."
            return False

        if not await self.verify_token(telegram_id, token):
            return False

        try:
            user.set_password(new_password)
        except ValueError as exc:
            self.last_error = str(exc)
            return False

        # Invalidate token (single-use)
        user.recovery_token = None
        user.recovery_token_expires = None
        await self.db.update_user(user)

        await self.db.add_log_entry(
            action="password_reset",
            user_id=user.id,
            details="Password was reset using recovery token",
        )

        logger.info(f"Password reset for user {telegram_id}")
        self.last_error = None
        return True

    async def clear_recovery_token(self, telegram_id: int) -> None:
        """Clear recovery token for user."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if user:
            user.recovery_token = None
            user.recovery_token_expires = None
            await self.db.update_user(user)

    async def is_token_valid(self, telegram_id: int) -> bool:
        """Check whether user currently has a valid recovery token."""
        user = await self.db.get_user_by_telegram_id(telegram_id)
        if not user or not user.recovery_token or not user.recovery_token_expires:
            return False
        return user.recovery_token_expires > self._now()
