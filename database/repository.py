"""Database repository for CRUD operations."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar, List, Optional

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import selectinload

from config import get_settings
from database.models import (
    AuthRequest,
    Base,
    DotaMatch,
    LogEntry,
    PCStatus,
    User,
    UserProfile,
)


class DatabaseRepository:
    """Async database repository."""

    _engine_cache: ClassVar[dict[str, AsyncEngine]] = {}
    _session_maker_cache: ClassVar[dict[str, async_sessionmaker[AsyncSession]]] = {}
    _PROFILE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "pc_mac_address",
            "pc_ip_address",
            "pc_broadcast_address",
            "pc_username",
            "pc_password",
            "pc_domain",
            "dota2_steam_api_key",
            "dota2_account_id",
        }
    )

    def __init__(self, database_url: Optional[str] = None):
        """Initialize database connection."""
        settings = get_settings()
        self.database_url = database_url or settings.database_url

        if self.database_url not in self._engine_cache:
            engine = create_async_engine(
                self.database_url,
                echo=settings.debug,
                future=True,
                pool_pre_ping=True,
            )
            session_maker = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            self._engine_cache[self.database_url] = engine
            self._session_maker_cache[self.database_url] = session_maker

        self.engine = self._engine_cache[self.database_url]
        self.async_session_maker = self._session_maker_cache[self.database_url]

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._run_compat_migrations)

    @staticmethod
    def _run_compat_migrations(sync_conn) -> None:
        """
        Run lightweight compatibility migrations for existing SQLite databases.

        This keeps old installations working after model changes without requiring
        a full Alembic migration setup.
        """
        dialect = getattr(sync_conn.dialect, "name", "")
        if dialect != "sqlite":
            return

        inspector = inspect(sync_conn)
        tables = set(inspector.get_table_names())
        if "users" not in tables:
            return

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "two_factor_backup_codes" not in user_columns:
            sync_conn.execute(text("ALTER TABLE users ADD COLUMN two_factor_backup_codes TEXT"))

        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_telegram_id ON users (telegram_id)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_is_authorized ON users (is_authorized)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_locked_until ON users (locked_until)"))
        sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_log_entries_created_at ON log_entries (created_at)"))

    async def get_session(self):
        """Get async database session."""
        return self.async_session_maker()

    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> User:
        """Create new user."""
        async with self.async_session_maker() as session:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_2fa_enabled=False,
            )
            if password:
                user.set_password(password)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        async with self.async_session_maker() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()

    async def get_all_authorized_users(self) -> List[User]:
        """Get all authorized users."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.is_authorized.is_(True))
            )
            return list(result.scalars().all())

    async def update_user_password(self, user_id: int, password: str) -> bool:
        """Update user password."""
        async with self.async_session_maker() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return False
            user.set_password(password)
            await session.commit()
            return True

    async def check_user_password(self, telegram_id: int, password: str) -> bool:
        """Check user password and transparently migrate legacy password hashes."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user or not user.password_hash:
                return False

            if not user.check_password(password):
                return False

            if user.needs_rehash():
                user.set_password(password, enforce_policy=False)
                await session.commit()

            return True

    async def get_all_users(self) -> List[User]:
        """Get all users."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(User).order_by(User.created_at.desc())
            )
            return list(result.scalars().all())

    async def get_user_logs(self, user_id: int) -> List[LogEntry]:
        """Get logs for specific user."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(LogEntry)
                .where(LogEntry.user_id == user_id)
                .order_by(LogEntry.created_at.desc())
                .limit(50)
            )
            return list(result.scalars().all())

    async def get_recent_logs(self, limit: int = 50) -> List[LogEntry]:
        """Get recent logs."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(LogEntry)
                .order_by(LogEntry.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def update_user(self, user: User) -> User:
        """Update user."""
        async with self.async_session_maker() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def create_auth_request(self, user_id: int) -> AuthRequest:
        """Create authorization request."""
        async with self.async_session_maker() as session:
            request = AuthRequest(user_id=user_id, status="pending")
            session.add(request)
            await session.commit()
            await session.refresh(request)
            return request

    async def get_pending_auth_requests(self) -> List[AuthRequest]:
        """Get pending authorization requests."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(AuthRequest)
                .options(selectinload(AuthRequest.user))
                .where(AuthRequest.status == "pending")
            )
            return list(result.scalars().all())

    async def update_auth_request(
        self,
        request_id: int,
        status: str,
        processed_by_id: Optional[int] = None,
    ) -> Optional[AuthRequest]:
        """Update authorization request."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(AuthRequest).where(AuthRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return None

            request.status = status
            request.processed_at = datetime.utcnow()
            request.processed_by_id = processed_by_id
            await session.commit()
            await session.refresh(request)
            return request

    async def get_pc_status(self) -> Optional[PCStatus]:
        """Get PC status."""
        async with self.async_session_maker() as session:
            result = await session.execute(select(PCStatus))
            return result.scalar_one_or_none()

    async def _get_or_create_pc_status(self, session: AsyncSession) -> PCStatus:
        """Return existing PC status row or create one."""
        result = await session.execute(select(PCStatus))
        status = result.scalar_one_or_none()
        if status is None:
            status = PCStatus()
            session.add(status)
        return status

    async def update_pc_status(
        self,
        is_online: bool,
        ip_address: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> PCStatus:
        """Update PC status."""
        async with self.async_session_maker() as session:
            status = await self._get_or_create_pc_status(session)
            status.is_online = is_online
            status.ip_address = ip_address or status.ip_address
            status.hostname = hostname or status.hostname
            status.last_check = datetime.utcnow()
            await session.commit()
            await session.refresh(status)
            return status

    async def update_last_wake_attempt(self) -> None:
        """Update last wake attempt time."""
        async with self.async_session_maker() as session:
            status = await self._get_or_create_pc_status(session)
            status.last_wake_attempt = datetime.utcnow()
            await session.commit()

    async def add_dota_match(self, match_data: dict) -> DotaMatch:
        """Add Dota 2 match."""
        async with self.async_session_maker() as session:
            match = DotaMatch(**match_data)
            session.add(match)
            await session.commit()
            await session.refresh(match)
            return match

    async def get_last_dota_match(self) -> Optional[DotaMatch]:
        """Get last Dota 2 match."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(DotaMatch).order_by(DotaMatch.started_at.desc()).limit(1)
            )
            return result.scalar_one_or_none()

    async def get_dota_matches(self, limit: int = 10) -> List[DotaMatch]:
        """Get recent Dota 2 matches."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(DotaMatch)
                .order_by(DotaMatch.started_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def add_log_entry(
        self,
        action: str,
        user_id: Optional[int] = None,
        details: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> LogEntry:
        """Add log entry."""
        async with self.async_session_maker() as session:
            entry = LogEntry(
                user_id=user_id,
                action=action,
                details=details,
                ip_address=ip_address,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
            return entry

    async def get_log_entries(self, limit: int = 100) -> List[LogEntry]:
        """Get recent log entries."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(LogEntry)
                .order_by(LogEntry.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_user_profile(self, user_id: int) -> Optional[UserProfile]:
        """Get profile by internal user ID."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            return result.scalar_one_or_none()

    async def get_user_profile_by_telegram_id(self, telegram_id: int) -> Optional[UserProfile]:
        """Get profile by Telegram user ID (joins through users table)."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(UserProfile)
                .join(User, User.id == UserProfile.user_id)
                .where(User.telegram_id == telegram_id)
            )
            return result.scalar_one_or_none()

    async def upsert_user_profile(
        self,
        user_id: int,
        **fields,
    ) -> UserProfile:
        """
        Create or update user profile.

        Pass only the fields you want to set/update as keyword arguments.
        Unknown fields are silently ignored to avoid SQLAlchemy errors.
        """
        clean = {key: value for key, value in fields.items() if key in self._PROFILE_FIELDS}

        async with self.async_session_maker() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if profile is None:
                profile = UserProfile(user_id=user_id, **clean)
                session.add(profile)
            else:
                for key, value in clean.items():
                    setattr(profile, key, value)

            await session.commit()
            await session.refresh(profile)
            return profile

    async def delete_user_profile(self, user_id: int) -> bool:
        """Delete user profile. Returns True if deleted."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if not profile:
                return False

            await session.delete(profile)
            await session.commit()
            return True

    async def close(self) -> None:
        """Close and remove cached engine for this database URL."""
        cached_engine = self._engine_cache.pop(self.database_url, None)
        self._session_maker_cache.pop(self.database_url, None)
        if cached_engine:
            await cached_engine.dispose()
