"""Database models using SQLAlchemy."""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
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
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Relationships
    auth_requests: Mapped[list["AuthRequest"]] = relationship(
        "AuthRequest", back_populates="user", cascade="all, delete-orphan"
    )


class AuthRequest(Base):
    """Authorization request model."""
    __tablename__ = "auth_requests"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, approved, rejected
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    processed_by_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="auth_requests")


class PCStatus(Base):
    """PC status tracking model."""
    __tablename__ = "pc_status"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    hostname: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_check: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_wake_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DotaMatch(Base):
    """Dota 2 match history model."""
    __tablename__ = "dota_matches"
    
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
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
