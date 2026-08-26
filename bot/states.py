from aiogram.fsm.state import State, StatesGroup


class ReceiptStates(StatesGroup):
    waiting_for_receipt = State()


class AdminStates(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_promo_code_value = State()
    waiting_for_promo_max_uses = State()
    waiting_for_promo_valid_until = State()


class PromoStates(StatesGroup):
    waiting_for_promo_code = State()
