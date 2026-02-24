"""Database repository for CRUD operations."""
from datetime import datetime
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import selectinload

from config import get_settings
from database.models import Base, User, AuthRequest, PCStatus, DotaMatch, LogEntry


class DatabaseRepository:
    """Async database repository."""
    
    def __init__(self, database_url: Optional[str] = None):
        """Initialize database connection."""
        settings = get_settings()
        self.database_url = database_url or settings.database_url
        
        self.engine = create_async_engine(
            self.database_url,
            echo=settings.debug,
            future=True,
        )
        
        self.async_session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    
    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def get_session(self) -> AsyncSession:
        """Get async database session."""
        async with self.async_session_maker() as session:
            yield session
    
    # User methods
    async def create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """Create a new user."""
        async with self.async_session_maker() as session:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
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
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
    
    async def get_all_authorized_users(self) -> List[User]:
        """Get all authorized users."""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.is_authorized == True)
            )
            return list(result.scalars().all())
    
    async def update_user(self, user: User) -> User:
        """Update user."""
        async with self.async_session_maker() as session:
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    
    # Auth request methods
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
            
            if request:
                request.status = status
                request.processed_at = datetime.utcnow()
                request.processed_by_id = processed_by_id
                await session.commit()
                await session.refresh(request)
            
            return request
    
    # PC Status methods
    async def get_pc_status(self) -> Optional[PCStatus]:
        """Get PC status."""
        async with self.async_session_maker() as session:
            result = await session.execute(select(PCStatus))
            return result.scalar_one_or_none()
    
    async def update_pc_status(
        self,
        is_online: bool,
        ip_address: Optional[str] = None,
        hostname: Optional[str] = None,
    ) -> PCStatus:
        """Update PC status."""
        async with self.async_session_maker() as session:
            result = await session.execute(select(PCStatus))
            status = result.scalar_one_or_none()
            
            if not status:
                status = PCStatus()
                session.add(status)
            
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
            result = await session.execute(select(PCStatus))
            status = result.scalar_one_or_none()
            
            if not status:
                status = PCStatus()
                session.add(status)
            
            status.last_wake_attempt = datetime.utcnow()
            await session.commit()
    
    # Dota match methods
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
    
    # Log entry methods
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
    
    async def close(self) -> None:
        """Close database connection."""
        await self.engine.dispose()
