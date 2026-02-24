"""Application settings using Pydantic."""
from functools import lru_cache
from pathlib import Path
from typing import List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Get the project root directory (where .env file is located)
PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Bot Configuration
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    admin_ids: List[int] = Field(default=[], alias="ADMIN_IDS")
    
    @field_validator("admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: Union[str, int, List[int]]) -> List[int]:
        """Parse admin IDs from various formats."""
        if isinstance(v, list):
            return v
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            # Handle comma-separated string
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return []
    
    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///bot.db",
        alias="DATABASE_URL"
    )
    
    # Wake-on-LAN Configuration
    pc_mac_address: str = Field(default="", alias="PC_MAC_ADDRESS")
    pc_ip_address: str = Field(default="192.168.1.100", alias="PC_IP_ADDRESS")
    pc_broadcast_address: str = Field(
        default="192.168.1.255",
        alias="PC_BROADCAST_ADDRESS"
    )
    
    # Windows PC Management
    pc_username: str = Field(default="Administrator", alias="PC_USERNAME")
    pc_password: str = Field(default="", alias="PC_PASSWORD")
    pc_domain: str = Field(default="WORKGROUP", alias="PC_DOMAIN")
    
    # Dota 2 / Steam
    dota2_steam_api_key: str = Field(default="", alias="DOTA2_STEAM_API_KEY")
    dota2_account_id: str = Field(default="", alias="DOTA2_ACCOUNT_ID")
    
    # Notification Settings
    notification_interval: int = Field(default=300, alias="NOTIFICATION_INTERVAL")
    notify_on_pc_status: bool = Field(default=True, alias="NOTIFY_ON_PC_STATUS")
    notify_on_dota_game: bool = Field(default=True, alias="NOTIFY_ON_DOTA_GAME")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="bot.log", alias="LOG_FILE")
    log_rotation: str = Field(default="10MB", alias="LOG_ROTATION")
    log_retention: int = Field(default=7, alias="LOG_RETENTION")
    
    # Other
    debug: bool = Field(default=False, alias="DEBUG")


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
