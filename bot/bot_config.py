"""Bot configuration."""
from dataclasses import dataclass
from typing import Optional

from config import get_settings


@dataclass
class BotConfig:
    """Bot configuration dataclass."""
    
    token: str
    admin_ids: list[int]
    database_url: str
    pc_mac_address: str
    pc_ip_address: str
    pc_broadcast_address: str
    pc_username: str
    pc_password: str
    pc_domain: str
    dota2_steam_api_key: str
    dota2_account_id: str
    notification_interval: int
    notify_on_pc_status: bool
    notify_on_dota_game: bool
    log_level: str
    log_file: str
    debug: bool
    
    @classmethod
    def from_settings(cls) -> "BotConfig":
        """Create config from settings."""
        settings = get_settings()
        return cls(
            token=settings.bot_token,
            admin_ids=settings.admin_ids,
            database_url=settings.database_url,
            pc_mac_address=settings.pc_mac_address,
            pc_ip_address=settings.pc_ip_address,
            pc_broadcast_address=settings.pc_broadcast_address,
            pc_username=settings.pc_username,
            pc_password=settings.pc_password,
            pc_domain=settings.pc_domain,
            dota2_steam_api_key=settings.dota2_steam_api_key,
            dota2_account_id=settings.dota2_account_id,
            notification_interval=settings.notification_interval,
            notify_on_pc_status=settings.notify_on_pc_status,
            notify_on_dota_game=settings.notify_on_dota_game,
            log_level=settings.log_level,
            log_file=settings.log_file,
            debug=settings.debug,
        )
    
    @property
    def is_configured(self) -> bool:
        """Check if bot is properly configured."""
        return bool(self.token)
