"""Logging configuration using Loguru."""
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from config import get_settings


def setup_logging(
    log_file: Optional[str] = None,
    log_level: Optional[str] = None,
    log_rotation: Optional[str] = None,
    log_retention: Optional[int] = None,
) -> None:
    """
    Configure logging for the application.
    
    Args:
        log_file: Path to log file
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_rotation: Log rotation size (e.g., "10MB")
        log_retention: Days to keep logs
    """
    settings = get_settings()
    
    log_file = log_file or settings.log_file
    log_level = log_level or settings.log_level
    log_rotation = log_rotation or settings.log_rotation
    log_retention = log_retention or settings.log_retention
    
    # Remove default handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
    )
    
    # Add file handler
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=log_level,
        rotation=log_rotation,
        retention=log_retention,
        compression="zip",
        encoding="utf-8",
    )
    
    logger.info("Logging initialized")


def get_logger(name: str = __name__):
    """
    Get a logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    return logger.bind(name=name)
