"""Database models using SQLAlchemy."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Optional

import bcrypt

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class User(Base):
    """Authorized user model."""

    __tablename__ = "users"

    __table_args__ = (
        Index("ix_users_telegram_id", "telegram_id"),
        Index("ix_users_is_authorized", "is_authorized"),
        Index("ix_users_locked_until", "locked_until"),
    )

    BCRYPT_ROUNDS = 12
    _LEGACY_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    two_factor_backup_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    recovery_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    recovery_token_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Biometric verification data
    biometric_photo_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    biometric_voice_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    biometric_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    biometric_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @staticmethod
    def validate_password_strength(password: str) -> tuple[bool, Optional[str]]:
        """
        Validate password complexity.

        Requirements:
        - Minimum length 8
        - Must include characters from at least 3 groups:
          lowercase, uppercase, digits, symbols
        """
        if not password:
            return False, "Password cannot be empty."

        if len(password) < 8:
            return False, "Password must be at least 8 characters long."

        groups = 0
        groups += bool(re.search(r"[a-z]", password))
        groups += bool(re.search(r"[A-Z]", password))
        groups += bool(re.search(r"\d", password))
        groups += bool(re.search(r"[^A-Za-z0-9]", password))

        if groups < 3:
            return (
                False,
                "Password must contain at least 3 groups: lowercase, uppercase, digits, symbols.",
            )

        return True, None

    def set_password(self, password: str, enforce_policy: bool = True) -> None:
        """Hash and set password with bcrypt."""
        if enforce_policy:
            is_valid, reason = self.validate_password_strength(password)
            if not is_valid:
                raise ValueError(reason or "Invalid password.")
        elif not password:
            raise ValueError("Password cannot be empty.")

        password_bytes = password.encode("utf-8")
        salt = bcrypt.gensalt(rounds=self.BCRYPT_ROUNDS)
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode("utf-8")

    def _is_legacy_sha256_hash(self) -> bool:
        """Detect old insecure SHA-256 hashes for migration compatibility."""
        if not self.password_hash:
            return False
        return bool(self._LEGACY_SHA256_RE.fullmatch(self.password_hash))

    def check_password(self, password: str) -> bool:
        """Check password against bcrypt hash with fallback for legacy SHA-256."""
        if not self.password_hash or not password:
            return False

        # bcrypt hash
        if self.password_hash.startswith("$2"):
            try:
                return bcrypt.checkpw(
                    password.encode("utf-8"),
                    self.password_hash.encode("utf-8"),
                )
            except (ValueError, TypeError):
                return False

        # Legacy SHA-256 compatibility for old records.
        if self._is_legacy_sha256_hash():
            return hashlib.sha256(password.encode("utf-8")).hexdigest() == self.password_hash

        return False

    def needs_rehash(self) -> bool:
        """Return True when a password should be rehashed with the current bcrypt policy."""
        if not self.password_hash:
            return False

        if self._is_legacy_sha256_hash():
            return True

        if not self.password_hash.startswith("$2"):
            return True

        try:
            parts = self.password_hash.split("$")
            if len(parts) < 3:
                return True
            rounds = int(parts[2])
            return rounds < self.BCRYPT_ROUNDS
        except (ValueError, IndexError):
            return True

    # Relationships
    auth_requests: Mapped[list["AuthRequest"]] = relationship(
        "AuthRequest", back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class AuthRequest(Base):
    """Authorization request model."""

    __tablename__ = "auth_requests"

    __table_args__ = (
        Index("ix_auth_requests_status", "status"),
        Index("ix_auth_requests_requested_at", "requested_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, approved, rejected
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    processed_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="auth_requests")


class UserProfile(Base):
    """
    Per-user PC / Steam configuration.

    All fields are optional — users fill only what they need.
    If a field is NULL the bot falls back to the global .env value.
    """
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False
    )

    # Wake-on-LAN / network
    pc_mac_address: Mapped[Optional[str]] = mapped_column(String(17), nullable=True)
    pc_ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    pc_broadcast_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # PC credentials
    pc_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pc_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pc_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Dota 2 / Steam
    dota2_steam_api_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dota2_account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="profile")


class PCStatus(Base):
    """PC status tracking model."""

    __tablename__ = "pc_status"

    __table_args__ = (
        Index("ix_pc_status_last_check", "last_check"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_check: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_wake_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DotaMatch(Base):
    """Dota 2 match history model."""

    __tablename__ = "dota_matches"

    __table_args__ = (
        Index("ix_dota_matches_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    player_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    steam_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hero_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kills: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deaths: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    assists: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # seconds
    game_mode: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LogEntry(Base):
    """Activity log entry model."""

    __tablename__ = "log_entries"

    __table_args__ = (
        Index("ix_log_entries_user_id", "user_id"),
        Index("ix_log_entries_created_at", "created_at"),
        Index("ix_log_entries_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
