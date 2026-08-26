from __future__ import annotations

from bot.handlers.admin import create_admin_router
from bot.handlers.user import create_user_router

__all__ = ["create_admin_router", "create_user_router"]