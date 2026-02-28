"""Handlers package."""
from .authorization import router as auth_router
from .pc_control import router as pc_router
from .wol import router as wol_router
from .dota import router as dota_router
from .voice import router as voice_router
from .notifications import router as notification_router

__all__ = [
    "auth_router",
    "pc_router",
    "wol_router",
    "dota_router",
    "voice_router",
    "notification_router",
]
