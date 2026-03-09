"""Security-focused unit tests for auth, 2FA, lockout and recovery."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from database.models import User
from services.password_recovery import PasswordRecoveryService
from services.two_factor import LoginSecurityService, TwoFactorService


class TestUserPasswordSecurity:
    """User password hashing and policy tests."""

    def test_set_password_uses_bcrypt(self) -> None:
        user = User()
        user.set_password("Str0ng!Pass")

        assert user.password_hash.startswith("$2")
        assert user.check_password("Str0ng!Pass") is True
        assert user.check_password("WrongPass123!") is False

    def test_weak_password_rejected(self) -> None:
        user = User()
        with pytest.raises(ValueError):
            user.set_password("short")

    def test_legacy_sha256_compatibility(self) -> None:
        user = User()
        user.password_hash = hashlib.sha256("Legacy123".encode("utf-8")).hexdigest()

        assert user.check_password("Legacy123") is True
        assert user.needs_rehash() is True


class TestTwoFactorService:
    """2FA helper behavior tests."""

    def test_validate_code_format(self) -> None:
        ok, reason = TwoFactorService.validate_code_format("123456")
        assert ok is True
        assert reason is None

        ok, reason = TwoFactorService.validate_code_format("12a456")
        assert ok is False
        assert "digits" in str(reason)

        ok, reason = TwoFactorService.validate_code_format("12345")
        assert ok is False
        assert "length" in str(reason)

    @pytest.mark.asyncio
    async def test_generate_backup_codes_stores_hashes(self) -> None:
        service = TwoFactorService()

        user = SimpleNamespace(two_factor_backup_codes=None)
        service.db = AsyncMock()
        service.db.get_user_by_telegram_id = AsyncMock(return_value=user)
        service.db.update_user = AsyncMock()

        codes = await service.generate_backup_codes(telegram_id=123)

        assert len(codes) == service.BACKUP_CODES_COUNT
        assert all(len(code) == service.BACKUP_CODE_LENGTH for code in codes)

        stored = json.loads(user.two_factor_backup_codes)
        assert len(stored) == service.BACKUP_CODES_COUNT
        assert all(len(item) == 64 for item in stored)


class TestLoginSecurityService:
    """Brute-force lockout behavior tests."""

    def test_exponential_lockout(self) -> None:
        assert LoginSecurityService._calculate_lockout_seconds(4) == 0
        assert LoginSecurityService._calculate_lockout_seconds(5) == 300
        assert LoginSecurityService._calculate_lockout_seconds(6) == 600
        assert LoginSecurityService._calculate_lockout_seconds(7) == 1200

    @pytest.mark.asyncio
    async def test_check_login_attempts_returns_lock_message(self) -> None:
        service = LoginSecurityService()
        locked_user = SimpleNamespace(
            locked_until=datetime.utcnow() + timedelta(seconds=120),
            failed_login_attempts=5,
        )
        service.db = AsyncMock()
        service.db.get_user_by_telegram_id = AsyncMock(return_value=locked_user)

        allowed, msg = await service.check_login_attempts(1)
        assert allowed is False
        assert "Account locked" in str(msg)


class TestPasswordRecoveryService:
    """Recovery token hardening tests."""

    def test_token_digest_has_prefix(self) -> None:
        digest = PasswordRecoveryService._token_digest("abc")
        assert digest.startswith(PasswordRecoveryService.TOKEN_PREFIX)

    @pytest.mark.asyncio
    async def test_generate_token_stores_hash_not_plaintext(self) -> None:
        service = PasswordRecoveryService()

        user = SimpleNamespace(
            recovery_token=None,
            recovery_token_expires=None,
        )
        service.db = AsyncMock()
        service.db.get_user_by_telegram_id = AsyncMock(return_value=user)
        service.db.update_user = AsyncMock()

        token = await service.generate_recovery_token(telegram_id=123)

        assert token is not None
        assert user.recovery_token != token
        assert user.recovery_token.startswith(PasswordRecoveryService.TOKEN_PREFIX)
        assert user.recovery_token_expires > datetime.utcnow()

    @pytest.mark.asyncio
    async def test_verify_token_supports_hashed_storage(self) -> None:
        service = PasswordRecoveryService()
        raw = "my-token"
        user = SimpleNamespace(
            recovery_token=PasswordRecoveryService._token_digest(raw),
            recovery_token_expires=datetime.utcnow() + timedelta(minutes=10),
        )

        service.db = AsyncMock()
        service.db.get_user_by_telegram_id = AsyncMock(return_value=user)

        assert await service.verify_token(123, raw) is True
        assert await service.verify_token(123, "wrong") is False

    @pytest.mark.asyncio
    async def test_recovery_rate_limit(self) -> None:
        service = PasswordRecoveryService()
        telegram_id = 98765

        # Ensure clean state for this test.
        service._recovery_requests.pop(telegram_id, None)

        for _ in range(service.RATE_LIMIT_REQUESTS):
            allowed, _ = await service.can_request_recovery(telegram_id)
            assert allowed is True
            service._record_recovery_request(telegram_id)

        allowed, reason = await service.can_request_recovery(telegram_id)
        assert allowed is False
        assert "Too many recovery requests" in str(reason)
