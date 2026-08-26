from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards, texts


MAINTENANCE_MODE = False


class MaintenanceGateMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: set[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and user.id not in self.admin_ids and MAINTENANCE_MODE:
            state = data.get("state")
            if isinstance(state, FSMContext):
                await state.clear()

            if isinstance(event, Message):
                await event.answer(texts.MAINTENANCE_NOTICE, reply_markup=keyboards.maintenance_keyboard())
                return

            if isinstance(event, CallbackQuery):
                if event.message is not None:
                    try:
                        await event.message.edit_text(texts.MAINTENANCE_NOTICE, reply_markup=keyboards.maintenance_keyboard())
                    except TelegramBadRequest:
                        await event.message.answer(texts.MAINTENANCE_NOTICE, reply_markup=keyboards.maintenance_keyboard())
                    await event.answer()
                else:
                    await event.answer(texts.MAINTENANCE_NOTICE, show_alert=True)
                return

        return await handler(event, data)
